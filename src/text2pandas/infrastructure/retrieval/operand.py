"""SQLite A6 adapter for operand-aware observation retrieval."""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from text2pandas.application.planning import OperandRequest
from text2pandas.application.retrieval import CandidateBatch, ObservationCandidate
from text2pandas.domain.metrics import MetricOntology, normalize_phrase
from text2pandas.domain.semantic import (
    Basis,
    Dimension,
    MetricBindingHint,
    PeriodSemantics,
    UnitSpec,
)

from .fact_label import fact_label_segments, normalize_fact_label

FACT_RETRIEVAL_POLICY_VERSION = "fact-retrieval-v2"


@dataclass(frozen=True, slots=True)
class _MetricMatch:
    quality: int
    alias_length: int
    method: str
    features: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _MetricPattern:
    raw_aliases: tuple[str, ...]
    aliases: tuple[str, ...]
    raw_forbidden_prefixes: tuple[str, ...]
    forbidden_prefixes: tuple[str, ...]
    raw_forbidden_contains: tuple[str, ...]
    forbidden_contains: tuple[str, ...]


class SqliteOperandRetriever:
    """Retrieve observations for one canonical metric and one semantic scope."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        ontology: MetricOntology,
        *,
        top_k: int = 20,
        hard_allowed_table_uids: tuple[str, ...] = (),
        table_rank_priors: tuple[str, ...] = (),
        source_build_id: str | None = None,
    ):
        if top_k < 1:
            raise ValueError("top_k must be positive")
        self.connection = connection
        self.ontology = ontology
        self.top_k = top_k
        self.hard_allowed_table_uids = hard_allowed_table_uids
        self.table_rank = {uid: index for index, uid in enumerate(table_rank_priors)}
        self.source_build_id = source_build_id
        self._metric_patterns = {
            metric_id: _MetricPattern(
                tuple(dict.fromkeys(normalize_phrase(alias) for alias in metric.aliases)),
                tuple(dict.fromkeys(normalize_fact_label(alias) for alias in metric.aliases)),
                tuple(normalize_phrase(value) for value in metric.forbidden_prefixes),
                tuple(normalize_fact_label(value) for value in metric.forbidden_prefixes),
                tuple(normalize_phrase(value) for value in metric.forbidden_contains),
                tuple(normalize_fact_label(value) for value in metric.forbidden_contains),
            )
            for metric_id, metric in ontology.metrics.items()
        }
        observation_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(observations)")
        }
        self._row_uid_expression = "o.row_uid" if "row_uid" in observation_columns else "NULL"
        self._metric_code_expression = (
            "o.metric_code" if "metric_code" in observation_columns else "NULL"
        )

    def set_table_rank_priors(self, table_uids: tuple[str, ...]) -> None:
        """Replace question-scoped soft table priors without leaking prior state."""
        self.table_rank = {
            uid: index for index, uid in enumerate(dict.fromkeys(table_uids))
        }

    def retrieve(self, request: OperandRequest) -> CandidateBatch:
        metric = self.ontology.metrics.get(request.metric_id)
        source_binding = request.source_binding
        if source_binding is not None:
            rejection = self._source_binding_rejection(request, source_binding)
            if rejection is not None:
                return CandidateBatch(
                    request.request_id,
                    (),
                    {
                        "reason": "SOURCE_BINDING_HINT_REJECTED",
                        "detail": rejection,
                        "metric_id": request.metric_id,
                    },
                )
            pattern = _MetricPattern(
                tuple(dict.fromkeys(normalize_phrase(value) for value in source_binding.labels)),
                tuple(
                    dict.fromkeys(normalize_fact_label(value) for value in source_binding.labels)
                ),
                (),
                (),
                (),
                (),
            )
            section_aliases = source_binding.labels
        elif metric is not None:
            pattern = self._metric_patterns[request.metric_id]
            section_aliases = metric.aliases
        else:
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
        if self.hard_allowed_table_uids:
            placeholders = ",".join("?" for _ in self.hard_allowed_table_uids)
            clauses.append(f"o.table_uid IN ({placeholders})")
            parameters.extend(self.hard_allowed_table_uids)
        rows = self.connection.execute(
            f"""
            SELECT o.observation_uid, {self._row_uid_expression},
                   {self._metric_code_expression}, o.table_uid, t.directory_doc_id,
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
        match_methods: Counter[str] = Counter()
        for row in rows:
            scanned += 1
            candidate = self._candidate(
                request,
                row,
                pattern=pattern,
                section_aliases=section_aliases,
                source_binding=source_binding,
            )
            if isinstance(candidate, str):
                if candidate == "metric":
                    rejected_metric += 1
                else:
                    rejected_unit += 1
                continue
            candidates.append(candidate)
            match_methods[candidate.match_method or "unknown"] += 1
        candidates.sort(key=lambda value: (-value.score, value.observation_uid))
        selected = tuple(candidates[: self.top_k])
        failure_reason = None
        if not candidates:
            if scanned == 0:
                failure_reason = "SCOPE_EMPTY"
            elif rejected_metric == scanned:
                failure_reason = "METRIC_REJECT_ALL"
            elif rejected_unit == scanned:
                failure_reason = "UNIT_REJECT_ALL"
            else:
                failure_reason = "CANDIDATE_EMPTY"
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
                "candidate_observation_uids": [
                    candidate.observation_uid for candidate in selected
                ],
                "candidate_table_uids": list(
                    dict.fromkeys(candidate.table_uid for candidate in selected)
                ),
                "truncated_at": self.top_k,
                "reason": failure_reason,
                "match_methods": dict(sorted(match_methods.items())),
                "retrieval_policy": FACT_RETRIEVAL_POLICY_VERSION,
                "hard_table_filter": bool(self.hard_allowed_table_uids),
                "table_prior_count": len(self.table_rank),
                **({"source_binding": True} if source_binding is not None else {}),
            },
        )

    def _source_binding_rejection(
        self, request: OperandRequest, binding: MetricBindingHint
    ) -> str | None:
        if request.metric_id != binding.source_metric_id:
            return "METRIC_ID_MISMATCH"
        if not binding.labels:
            return "LABELS_EMPTY"
        if self.source_build_id is None:
            return "ACTIVE_SOURCE_BUILD_UNAVAILABLE"
        if binding.source_build_id != self.source_build_id:
            return "SOURCE_BUILD_MISMATCH"
        return None

    def _candidate(
        self,
        request: OperandRequest,
        row: tuple[object, ...],
        *,
        pattern: _MetricPattern,
        section_aliases: tuple[str, ...],
        source_binding: MetricBindingHint | None,
    ) -> ObservationCandidate | str:
        (
            observation_uid,
            row_uid,
            source_metric_code,
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
        label = str(row_path or metric_label or "")
        if source_binding is not None:
            allowed_paths = {fact_label_segments(value) for value in source_binding.row_paths}
            if allowed_paths and fact_label_segments(str(row_path or "")) not in allowed_paths:
                return "metric"
            if source_binding.metric_codes and (
                source_metric_code is None
                or str(source_metric_code) not in source_binding.metric_codes
            ):
                return "metric"
            if request.statement_types and str(statement_type or "") not in request.statement_types:
                return "metric"
        match = _metric_match(
            pattern,
            str(row_path or ""),
            str(metric_label or ""),
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
        context = " ".join((str(row_path or ""), str(column_path or ""), str(section_text or "")))
        normalized_context = normalize_phrase(context)
        if any(
            not _contains_phrase(normalized_context, phrase)
            for phrase in request.required_context_phrases
        ):
            return "metric"
        direct, alias_length = match.quality, match.alias_length
        # Exact leaves get a bounded tie-break, not a dominating bonus. Notes
        # may contain an exact label for a different concept while the correct
        # consolidated operand is a qualified prefix under a stronger section.
        metric_score = {4: 22.25, 3: 22.0, 2: 20.0, 1: 10.0}[direct]
        score = metric_score + alias_length / 100.0
        reasons = [
            {
                4: "metric:exact",
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
        section_score = _section_score(section_aliases, str(section_text or ""))
        score += section_score
        if section_score:
            reasons.append("section")
        qualifier_score = _qualifier_score(
            request.qualifiers,
            context,
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
            row_uid=None if row_uid is None else str(row_uid),
            source_metric_code=(
                None if source_metric_code in (None, "") else str(source_metric_code)
            ),
            matched_metric_id=request.metric_id,
            match_method=match.method,
            match_features=match.features,
        )


def _metric_match(
    pattern: _MetricPattern,
    row_path: str,
    metric_label: str,
) -> _MetricMatch | None:
    # Preserve legacy exact-match precedence. Fact normalization deliberately
    # broadens recall; it must not make an enumerated/formula-normalized label
    # tie with a source label that was already an exact canonical match.
    raw_leaf = normalize_phrase((row_path or metric_label).rsplit("›", 1)[-1])
    if any(_prefix(raw_leaf, forbidden) for forbidden in pattern.raw_forbidden_prefixes):
        return None
    if any(forbidden and forbidden in raw_leaf for forbidden in pattern.raw_forbidden_contains):
        return None
    raw_exact = [alias for alias in pattern.raw_aliases if raw_leaf == alias]
    if raw_exact:
        return _MetricMatch(
            4,
            max(map(len, raw_exact)),
            "row_leaf_raw_exact",
            ("row_leaf", "source_normalized", "legacy_exact_precedence"),
        )

    segments = fact_label_segments(row_path)
    leaf = segments[-1] if segments else normalize_fact_label(metric_label)
    normalized_metric_label = normalize_fact_label(metric_label)
    surfaces = [("row_leaf", leaf)]
    if normalized_metric_label and normalized_metric_label != leaf:
        surfaces.append(("metric_label", normalized_metric_label))
    for _surface_name, surface in surfaces:
        if any(_prefix(surface, forbidden) for forbidden in pattern.forbidden_prefixes):
            return None
        if any(forbidden and forbidden in surface for forbidden in pattern.forbidden_contains):
            return None

    for surface_name, surface in surfaces:
        exact = [alias for alias in pattern.aliases if surface == alias]
        if exact:
            return _MetricMatch(
                3,
                max(map(len, exact)),
                f"{surface_name}_exact",
                (surface_name, "fact_normalized"),
            )
    for surface_name, surface in surfaces:
        direct = [alias for alias in pattern.aliases if _prefix(surface, alias)]
        if direct:
            return _MetricMatch(
                2,
                max(map(len, direct)),
                f"{surface_name}_prefix",
                (surface_name, "fact_normalized"),
            )
    for aggregate_prefix in ("tong cong ", "tong ", "cong "):
        for surface_name, surface in surfaces:
            if not surface.startswith(aggregate_prefix):
                continue
            stripped = surface.removeprefix(aggregate_prefix)
            if any(_prefix(stripped, forbidden) for forbidden in pattern.forbidden_prefixes):
                return None
            matches = [alias for alias in pattern.aliases if _prefix(stripped, alias)]
            if matches:
                return _MetricMatch(
                    1,
                    max(map(len, matches)),
                    f"{surface_name}_aggregate_prefix",
                    (surface_name, "aggregate_prefix", "fact_normalized"),
                )

    # Full hierarchy is evidence only when the leaf is an explicitly generic
    # total. This rescues paths such as ``Tài sản ngắn hạn › Tổng cộng`` without
    # treating every descendant under ``Tài sản ngắn hạn`` as the parent total.
    if len(segments) >= 2 and leaf in {"tong", "tong cong", "cong", "total"}:
        parent = segments[-2]
        matches = [alias for alias in pattern.aliases if parent == alias]
        if matches:
            return _MetricMatch(
                1,
                max(map(len, matches)),
                "row_hierarchy_parent",
                ("row_hierarchy", "generic_total_leaf", "fact_normalized"),
            )
    return None


def _prefix(value: str, prefix: str) -> bool:
    return value == prefix or value.startswith(prefix + " ")


def _contains_phrase(context: str, phrase: str) -> bool:
    normalized_phrase = normalize_phrase(phrase)
    return bool(normalized_phrase) and f" {normalized_phrase} " in f" {context} "


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
