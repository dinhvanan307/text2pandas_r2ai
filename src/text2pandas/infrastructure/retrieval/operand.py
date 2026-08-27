"""SQLite A6 adapter for operand-aware observation retrieval."""

from __future__ import annotations

import re
import sqlite3
from decimal import Decimal, InvalidOperation

from text2pandas.application.planning import OperandRequest
from text2pandas.application.retrieval import CandidateBatch, ObservationCandidate
from text2pandas.domain.metrics import MetricOntology, normalize_phrase
from text2pandas.domain.semantic import Basis, Dimension, PeriodSemantics, UnitSpec


class SqliteOperandRetriever:
    """Retrieve observations for one canonical metric and one semantic scope."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        ontology: MetricOntology,
        *,
        top_k: int = 20,
        allowed_table_uids: tuple[str, ...] = (),
    ):
        if top_k < 1:
            raise ValueError("top_k must be positive")
        self.connection = connection
        self.ontology = ontology
        self.top_k = top_k
        self.allowed_table_uids = allowed_table_uids
        self.table_rank = {uid: index for index, uid in enumerate(allowed_table_uids)}

    def retrieve(self, request: OperandRequest) -> CandidateBatch:
        metric = self.ontology.metrics.get(request.metric_id)
        if metric is None:
            return CandidateBatch(
                request.request_id,
                (),
                {"reason": "UNKNOWN_METRIC", "metric_id": request.metric_id},
            )
        clauses = ["r.execution_ready = 1", "o.value_decimal_text IS NOT NULL"]
        parameters: list[object] = []
        if request.entity:
            clauses.append("o.ticker = ?")
            parameters.append(request.entity)
        if request.period:
            if len(request.period) == 4:
                clauses.append("substr(o.period_end, 1, 4) = ?")
            else:
                clauses.append("o.period_end = ?")
            parameters.append(request.period)
        if request.basis != Basis.UNSPECIFIED:
            clauses.append("d.basis = ?")
            parameters.append(request.basis.value)
        if self.allowed_table_uids:
            placeholders = ",".join("?" for _ in self.allowed_table_uids)
            clauses.append(f"o.table_uid IN ({placeholders})")
            parameters.extend(self.allowed_table_uids)
        rows = self.connection.execute(
            f"""
            SELECT o.observation_uid, o.table_uid, t.directory_doc_id,
                   o.ticker, d.basis, o.statement_type,
                   o.row_path_text, o.metric_label_clean, o.col_path_text,
                   o.period_end, o.period_role, o.value_decimal_text,
                   o.value_source_raw, o.unit_kind, o.currency, o.scale_exponent,
                   o.is_restated, o.grid_row_idx, o.grid_col_idx, t.section_text
            FROM observations o
            JOIN observation_readiness r USING(observation_uid)
            JOIN tables t USING(table_uid)
            JOIN documents d USING(document_uid)
            WHERE {" AND ".join(clauses)}
            ORDER BY o.observation_uid
            """,
            tuple(parameters),
        )
        candidates: list[ObservationCandidate] = []
        scanned = 0
        rejected_metric = 0
        rejected_unit = 0
        for row in rows:
            scanned += 1
            candidate = self._candidate(request, row)
            if isinstance(candidate, str):
                if candidate == "metric":
                    rejected_metric += 1
                else:
                    rejected_unit += 1
                continue
            candidates.append(candidate)
        candidates.sort(key=lambda value: (-value.score, value.observation_uid))
        selected = tuple(candidates[: self.top_k])
        return CandidateBatch(
            request.request_id,
            selected,
            {
                "metric_id": request.metric_id,
                "entity": request.entity,
                "period": request.period,
                "scanned": scanned,
                "metric_rejected": rejected_metric,
                "unit_rejected": rejected_unit,
                "matched": len(candidates),
                "returned": len(selected),
                "truncated_at": self.top_k,
            },
        )

    def _candidate(
        self, request: OperandRequest, row: tuple[object, ...]
    ) -> ObservationCandidate | str:
        (
            observation_uid,
            table_uid,
            document_id,
            entity,
            basis_raw,
            statement_type,
            row_path,
            metric_label,
            column_path,
            period,
            period_role,
            decimal_text,
            value_raw,
            unit_kind,
            currency,
            scale,
            is_restated,
            grid_row,
            grid_column,
            section_text,
        ) = row
        metric = self.ontology.metrics[request.metric_id]
        label = str(row_path or metric_label or "")
        match = _metric_match(
            metric.aliases, metric.forbidden_prefixes, metric.forbidden_contains, label
        )
        if match is None:
            return "metric"
        unit = _unit(str(unit_kind or "unknown"), scale, currency)
        if not _dimension_compatible(request.expected_unit.dimension, unit.dimension):
            return "unit"
        try:
            value = Decimal(str(decimal_text))
        except InvalidOperation:
            return "unit"
        direct, alias_length = match
        # Exact leaves get a bounded tie-break, not a dominating bonus. Notes
        # may contain an exact label for a different concept while the correct
        # consolidated operand is a qualified prefix under a stronger section.
        metric_score = {3: 22.0, 2: 20.0, 1: 10.0}[direct]
        score = metric_score + alias_length / 100.0
        reasons = [
            {
                3: "metric:exact",
                2: "metric:prefix",
                1: "metric:aggregate_prefix",
            }[direct]
        ]
        if statement_type and str(statement_type) in request.statement_types:
            score += 3.0
            reasons.append("statement")
        period_score = _period_role_score(
            request.period_semantics, str(period_role or ""), str(column_path or "")
        )
        score += period_score
        if period_score:
            reasons.append("period_role")
        basis = _basis(str(basis_raw or ""))
        if request.basis == Basis.UNSPECIFIED and basis == request.preferred_basis:
            score += 1.0
            reasons.append("preferred_basis")
        section_score = _section_score(metric.aliases, str(section_text or ""))
        score += section_score
        if section_score:
            reasons.append("section")
        qualifier_score = _qualifier_score(
            request.qualifiers,
            " ".join((str(row_path or ""), str(column_path or ""), str(section_text or ""))),
        )
        score += qualifier_score
        if qualifier_score:
            reasons.append("qualifier")
        document_period_score = _document_period_score(
            request.period, str(document_id), str(period_role or "")
        )
        score += document_period_score
        if document_period_score:
            reasons.append("document_period")
        if bool(is_restated):
            score -= 0.5
            reasons.append("restated_penalty")
        if self.table_rank:
            rank = self.table_rank.get(str(table_uid))
            if rank is not None:
                score += max(0.0, 1.0 - rank / max(1, len(self.table_rank)))
                reasons.append("upstream_table_rank")
        return ObservationCandidate(
            observation_uid=str(observation_uid),
            table_uid=str(table_uid),
            document_id=str(document_id),
            entity=str(entity),
            basis=basis,
            statement_type=None if statement_type is None else str(statement_type),
            metric_id=request.metric_id,
            row_path=label,
            column_path=str(column_path or ""),
            period=None if period is None else str(period),
            period_role=None if period_role is None else str(period_role),
            value=value,
            value_raw=str(value_raw or decimal_text),
            unit=unit,
            is_restated=bool(is_restated),
            score=score,
            score_reasons=tuple(reasons),
            grid_row=int(str(grid_row)),
            grid_column=int(str(grid_column)),
        )


def _metric_match(
    aliases: tuple[str, ...],
    forbidden_prefixes: tuple[str, ...],
    forbidden_contains: tuple[str, ...],
    label: str,
) -> tuple[int, int] | None:
    normalized = normalize_phrase(label.rsplit("›", 1)[-1])
    if not normalized:
        return None
    if any(_prefix(normalized, forbidden) for forbidden in forbidden_prefixes):
        return None
    if any(forbidden in normalized for forbidden in forbidden_contains):
        return None
    exact = [alias for alias in aliases if normalized == alias]
    if exact:
        return 3, max(map(len, exact))
    direct = [alias for alias in aliases if _prefix(normalized, alias)]
    if direct:
        return 2, max(map(len, direct))
    for aggregate_prefix in ("tong cong ", "tong ", "cong "):
        if not normalized.startswith(aggregate_prefix):
            continue
        stripped = normalized.removeprefix(aggregate_prefix)
        if any(_prefix(stripped, forbidden) for forbidden in forbidden_prefixes):
            return None
        matches = [alias for alias in aliases if _prefix(stripped, alias)]
        if matches:
            return 1, max(map(len, matches))
    return None


def _prefix(value: str, prefix: str) -> bool:
    return value == prefix or value.startswith(prefix + " ")


def _period_role_score(semantics: PeriodSemantics, role: str, column: str) -> float:
    normalized = normalize_phrase(column)
    if semantics == PeriodSemantics.POINT_IN_TIME:
        if role == "closing" or any(
            value in normalized for value in ("cuoi nam", "31 12", "tai ngay")
        ):
            return 3.0
        if role in ("opening", "prior"):
            return 2.0
        return 0.0 if role == "current" else 1.0
    if semantics == PeriodSemantics.FLOW:
        if role == "current":
            return 3.0
        if role == "prior":
            return 2.0
    return 0.0


def _section_score(aliases: tuple[str, ...], section: str) -> float:
    tokens = set(normalize_phrase(section).split())
    if not tokens:
        return 0.0
    return 2.0 * max(
        (len(tokens.intersection(alias.split())) / max(1, len(alias.split())) for alias in aliases),
        default=0.0,
    )


def _qualifier_score(qualifiers: tuple[str, ...], context: str) -> float:
    if not qualifiers:
        return 0.0
    context_tokens = set(normalize_phrase(context).split())
    overlap = context_tokens.intersection(qualifiers)
    return min(4.0, 0.5 * len(overlap))


def _document_period_score(period: str | None, document_id: str, role: str) -> float:
    if period is None or len(period) < 4:
        return 0.0
    requested_year = int(period[:4])
    years = re.findall(r"(?:19|20)\d{2}", document_id)
    if not years:
        return 0.0
    document_year = int(years[-1])
    if document_year == requested_year:
        return 2.0
    if document_year == requested_year + 1 and role in {"prior", "opening"}:
        return 0.5
    return 0.0


def _unit(kind: str, scale: object, currency: object) -> UnitSpec:
    dimension = {
        "money": Dimension.MONEY,
        "percent": Dimension.PERCENT,
        "rate": Dimension.RATIO,
        "shares": Dimension.SHARES,
    }.get(kind, Dimension.UNKNOWN)
    exponent = (
        int(str(scale))
        if scale is not None and dimension in (Dimension.MONEY, Dimension.SHARES)
        else None
    )
    currency_value = (
        str(currency) if currency is not None and dimension == Dimension.MONEY else None
    )
    return UnitSpec(dimension, exponent, currency_value)


def _basis(value: str) -> Basis:
    try:
        return Basis(value)
    except ValueError:
        return Basis.UNSPECIFIED


def _dimension_compatible(expected: Dimension, actual: Dimension) -> bool:
    if expected == Dimension.UNKNOWN:
        return actual != Dimension.UNKNOWN
    return expected == actual or {expected, actual} == {Dimension.PERCENT, Dimension.RATIO}
