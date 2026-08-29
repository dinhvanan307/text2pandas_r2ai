"""Question-scoped A6 fact retrieval for grounded program synthesis."""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

from text2pandas.application.usecases.grounded_synthesis import GroundedFact
from text2pandas.domain.metrics import normalize_phrase
from text2pandas.domain.semantic import Basis, Dimension
from text2pandas.infrastructure.retrieval.fact_label import normalize_fact_label
from text2pandas.infrastructure.retrieval.grounded_query import GroundedQueryConcept
from text2pandas.infrastructure.retrieval.index import tokenize


class GroundedFactRetriever:
    """Retrieve lexical fact candidates inside high-recall document/table priors.

    Document priors are intentionally the primary boundary.  Official evidence
    shows report retrieval is much stronger than exact table retrieval, so the
    answer engine searches every execution-ready table inside those reports
    instead of assuming the scorer-facing top tables are complete.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        max_scanned: int = 30_000,
        include_recoverable_collisions: bool = True,
    ) -> None:
        if max_scanned < 1:
            raise ValueError("max_scanned must be positive")
        self.connection = connection
        self.max_scanned = max_scanned
        self.include_recoverable_collisions = include_recoverable_collisions

    def retrieve(
        self,
        question: str,
        *,
        document_ids: Sequence[str],
        table_uids: Sequence[str],
        entities: Sequence[str],
        periods: Sequence[str],
        basis: Basis,
        query_terms: Sequence[str] = (),
        query_concepts: Sequence[GroundedQueryConcept] = (),
        preferred_dimension: Dimension = Dimension.UNKNOWN,
        limit: int = 120,
    ) -> tuple[GroundedFact, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        docs = tuple(dict.fromkeys(str(value) for value in document_ids if value))
        tables = tuple(dict.fromkeys(str(value) for value in table_uids if value))
        if not docs and not tables:
            return ()
        rows = self._rows(
            docs,
            tables,
            tuple(dict.fromkeys(entities)),
            tuple(dict.fromkeys(period[:4] for period in periods if len(period) >= 4)),
            basis,
        )
        search_terms = tuple(dict.fromkeys((question, *query_terms)))
        token_sets = [set(tokenize(value)) for value in search_terms]
        normalized_terms = [normalize_phrase(value) for value in search_terms]
        concept_aliases = tuple(
            (
                concept.metric_id,
                tuple(
                    dict.fromkeys(
                        normalize_phrase(alias)
                        for alias in concept.aliases
                        if normalize_phrase(alias)
                    )
                ),
            )
            for concept in query_concepts
        )
        concept_statement_types = {
            concept.metric_id: frozenset(concept.statement_types)
            for concept in query_concepts
        }
        aliases_by_metric = dict(concept_aliases)
        table_rank = {uid: index for index, uid in enumerate(tables)}
        scored: list[GroundedFact] = []
        for row in rows:
            fact = self._fact(row)
            if fact is None:
                continue
            leaf = _metric_leaf(fact)
            leaf_tokens = set(tokenize(leaf))
            row_tokens = set(tokenize(fact.row_path))
            section_tokens = set(tokenize(fact.section_text))
            column_tokens = set(tokenize(fact.column_path))
            normalized_leaf = normalize_fact_label(leaf)
            normalized_leaf_tokens = set(tokenize(normalized_leaf))
            exact_concepts = [
                metric_id
                for metric_id, aliases in concept_aliases
                if any(normalized_leaf == alias for alias in aliases)
            ]
            contained_concepts = [
                metric_id
                for metric_id, aliases in concept_aliases
                if any(
                    normalized_leaf in alias or alias in normalized_leaf
                    for alias in aliases
                )
            ]
            structural_concepts = [
                metric_id
                for metric_id, aliases in concept_aliases
                if fact.metric_code in _METRIC_CODES.get(metric_id, frozenset())
                and max(
                    (
                        len(set(tokenize(alias)) & normalized_leaf_tokens)
                        for alias in aliases
                    ),
                    default=0,
                )
                >= 2
            ]
            exact_matching_terms = [
                term for term in normalized_terms if term and normalized_leaf == term
            ]
            contained_matching_terms = [
                term
                for term in normalized_terms
                if term and (normalized_leaf in term or term in normalized_leaf)
            ]
            exact_leaf = bool(exact_matching_terms)
            retrieval_metric = (
                exact_concepts[0]
                if exact_concepts
                else (
                    structural_concepts[0]
                    if structural_concepts
                    else (
                        contained_concepts[0]
                        if contained_concepts
                        else (
                            min(exact_matching_terms, key=len)
                            if exact_matching_terms
                            else (
                                min(contained_matching_terms, key=len)
                                if contained_matching_terms
                                else None
                            )
                        )
                    )
                )
            )
            contained_leaf = bool(
                contained_matching_terms or contained_concepts or structural_concepts
            )
            exact_leaf = exact_leaf or bool(exact_concepts)
            overlaps = [
                (
                    len(tokens & row_tokens),
                    len(tokens & leaf_tokens),
                    len(tokens & section_tokens),
                    len(tokens & column_tokens),
                )
                for tokens in token_sets
            ]
            overlap, leaf_overlap, section_overlap, column_overlap = max(
                overlaps,
                key=lambda item: (item[1], item[0], item[2], item[3]),
            )
            lexical = (
                80.0 * float(exact_leaf)
                + 24.0 * float(contained_leaf and not exact_leaf)
                + 3.0 * leaf_overlap
                + 1.2 * overlap
                + 0.4 * section_overlap
                + 0.25 * column_overlap
            )
            if retrieval_metric in aliases_by_metric and normalized_leaf_tokens:
                alias_token_sets = [
                    set(tokenize(alias))
                    for alias in aliases_by_metric[retrieval_metric]
                    if tokenize(alias)
                ]
                alias_precision = max(
                    (
                        len(alias_tokens & normalized_leaf_tokens)
                        / len(normalized_leaf_tokens)
                        for alias_tokens in alias_token_sets
                    ),
                    default=0.0,
                )
                alias_coverage = max(
                    (
                        len(alias_tokens & normalized_leaf_tokens) / len(alias_tokens)
                        for alias_tokens in alias_token_sets
                    ),
                    default=0.0,
                )
                lexical += 30.0 * alias_precision + 40.0 * alias_coverage
            if not contained_leaf and leaf_overlap == 0 and overlap < 2:
                continue
            prior_index = table_rank.get(fact.table_uid)
            prior = 2.5 / (1 + prior_index) if prior_index is not None else 0.0
            document_prior = 25.0 if fact.document_id in docs else 0.0
            basis_prior = (
                25.0
                if basis is Basis.UNSPECIFIED and fact.basis is Basis.CONSOLIDATED
                else 0.0
            )
            expected_statement_types = concept_statement_types.get(
                retrieval_metric or "", frozenset()
            )
            statement_prior = (
                18.0
                if expected_statement_types
                and fact.statement_type in expected_statement_types
                else (-8.0 if expected_statement_types else 0.0)
            )
            expected_codes = _METRIC_CODES.get(retrieval_metric or "", frozenset())
            metric_code_prior = (
                60.0
                if expected_codes and fact.metric_code in expected_codes
                else (
                    -15.0
                    if expected_codes and fact.metric_code is not None
                    else 0.0
                )
            )
            normalized_row = normalize_phrase(fact.row_path)
            banking_statement_prior = 0.0
            if retrieval_metric == "total_assets":
                if "rui ro" in normalized_row:
                    banking_statement_prior -= 90.0
                if "b02/tctd" in normalized_row:
                    banking_statement_prior += 45.0
            specificity = math.log1p(len(leaf_tokens)) / 5.0
            dimension_prior = _dimension_prior(fact.dimension, preferred_dimension)
            scored.append(
                GroundedFact(
                    observation_uid=fact.observation_uid,
                    table_uid=fact.table_uid,
                    document_id=fact.document_id,
                    entity=fact.entity,
                    period=fact.period,
                    basis=fact.basis,
                    row_path=fact.row_path,
                    column_path=fact.column_path,
                    section_text=fact.section_text,
                    value=fact.value,
                    dimension=fact.dimension,
                    scale_exponent=fact.scale_exponent,
                    metric_code=fact.metric_code,
                    retrieval_metric=retrieval_metric,
                    score=(
                        lexical
                        + prior
                        + document_prior
                        + basis_prior
                        + statement_prior
                        + metric_code_prior
                        + banking_statement_prior
                        + dimension_prior
                        + specificity
                    ),
                )
            )
        scored.sort(key=lambda item: (-item.score, item.observation_uid))
        deduplicated: list[GroundedFact] = []
        seen_scope_metric: set[tuple[str, str | None, Basis, str]] = set()
        for fact in scored:
            leaf = normalize_fact_label(_metric_leaf(fact))
            key = (
                fact.entity,
                fact.period[:4] if fact.period else None,
                fact.basis,
                fact.retrieval_metric or leaf,
            )
            if key in seen_scope_metric:
                continue
            seen_scope_metric.add(key)
            deduplicated.append(fact)
        return self._diversified(deduplicated, limit)

    def _rows(
        self,
        document_ids: tuple[str, ...],
        table_uids: tuple[str, ...],
        entities: tuple[str, ...],
        periods: tuple[str, ...],
        basis: Basis,
    ) -> list[tuple[object, ...]]:
        source_clauses: list[str] = []
        parameters: list[object] = []
        if document_ids:
            placeholders = ",".join("?" for _ in document_ids)
            source_clauses.append(f"t.directory_doc_id IN ({placeholders})")
            parameters.extend(document_ids)
        if table_uids:
            placeholders = ",".join("?" for _ in table_uids)
            source_clauses.append(f"o.table_uid IN ({placeholders})")
            parameters.extend(table_uids)
        # Scorer-facing top-N references are a prior, not an answer-retrieval
        # boundary.  Multi-entity questions can require one report per entity,
        # while the public top-N may omit one of them.  Expand to the explicit
        # entities from the question, still bounded by period/basis below.
        if entities:
            entity_placeholders = ",".join("?" for _ in entities)
            entity_clause = f"o.ticker IN ({entity_placeholders})"
            parameters.extend(entities)
            if periods:
                document_years = tuple(
                    dict.fromkeys(
                        year
                        for period in periods
                        for year in (period, str(int(period) + 1))
                    )
                )
                year_placeholders = ",".join("?" for _ in document_years)
                entity_clause += f" AND CAST(t.doc_year AS TEXT) IN ({year_placeholders})"
                parameters.extend(document_years)
            source_clauses.append(f"({entity_clause})")
        readiness = "r.execution_ready = 1"
        if self.include_recoverable_collisions:
            readiness = (
                "(r.execution_ready = 1 OR o.collision_class IN "
                "('missing_column_group','missing_row_parent') OR "
                "(o.collision_class = 'missing_label_or_split' AND "
                "COALESCE(o.metric_code, row_meta.metric_code) IS NOT NULL))"
            )
        clauses = [f"({' OR '.join(source_clauses)})", readiness]
        if entities:
            placeholders = ",".join("?" for _ in entities)
            clauses.append(f"o.ticker IN ({placeholders})")
            parameters.extend(entities)
        if periods:
            placeholders = ",".join("?" for _ in periods)
            clauses.append(f"substr(o.period_end, 1, 4) IN ({placeholders})")
            parameters.extend(periods)
        if basis is not Basis.UNSPECIFIED:
            clauses.append("d.basis = ?")
            parameters.append(basis.value)
        parameters.append(self.max_scanned)
        query = f"""
            SELECT o.observation_uid, o.table_uid, t.directory_doc_id,
                   o.ticker, o.period_end, d.basis, o.row_path_text,
                   o.col_path_text, t.section_text, o.value_decimal_text,
                   o.unit_kind, o.scale_exponent
                   , COALESCE(o.metric_code, row_meta.metric_code), t.statement_type
                   , previous_row.row_path_text, o.collision_class
            FROM observations o
            JOIN observation_readiness r USING(observation_uid)
            JOIN tables t USING(table_uid)
            JOIN documents d USING(document_uid)
            JOIN rows row_meta
              ON row_meta.table_uid = o.table_uid
             AND row_meta.grid_row_idx = o.grid_row_idx
            LEFT JOIN rows previous_row
              ON previous_row.table_uid = o.table_uid
             AND previous_row.grid_row_idx = o.grid_row_idx - 1
            WHERE {' AND '.join(clauses)}
              AND o.value_decimal_text IS NOT NULL
            ORDER BY o.table_uid, o.grid_row_idx, o.grid_col_idx, o.observation_uid
            LIMIT ?
        """
        rows = list(self.connection.execute(query, tuple(parameters)))
        if rows or basis is Basis.UNSPECIFIED:
            return rows
        # Explicit scope is a strong preference but OCR metadata can be absent.
        # Retry without the basis gate and expose both scopes to the planner.
        return self._rows(
            document_ids,
            table_uids,
            entities,
            periods,
            Basis.UNSPECIFIED,
        )

    @staticmethod
    def _fact(row: tuple[object, ...]) -> GroundedFact | None:
        (
            observation_uid,
            table_uid,
            document_id,
            entity,
            period,
            basis_raw,
            row_path,
            column_path,
            section_text,
            value_raw,
            unit_kind,
            scale_raw,
            metric_code,
            statement_type,
            previous_row_path,
            collision_class,
        ) = row
        try:
            value = Decimal(str(value_raw))
        except InvalidOperation:
            return None
        if not value.is_finite():
            return None
        dimension = _dimension(
            str(unit_kind or "unknown"),
            " ".join((str(row_path or ""), str(column_path or ""))),
        )
        try:
            basis = Basis(str(basis_raw or Basis.UNSPECIFIED.value))
        except ValueError:
            basis = Basis.UNSPECIFIED
        try:
            scale = None if scale_raw is None else int(str(scale_raw))
        except ValueError:
            scale = None
        raw_row_path = str(row_path or "")
        if collision_class == "missing_row_parent" and previous_row_path:
            previous = str(previous_row_path)
            if previous and previous != raw_row_path:
                raw_row_path = f"{previous} › {raw_row_path.rsplit('›', 1)[-1].strip()}"
        effective_row_path = _effective_row_path(
            raw_row_path, None if metric_code is None else str(metric_code)
        )
        return GroundedFact(
            observation_uid=str(observation_uid),
            table_uid=str(table_uid),
            document_id=str(document_id),
            entity=str(entity or ""),
            period=None if period is None else str(period),
            basis=basis,
            row_path=effective_row_path,
            column_path=str(column_path or ""),
            section_text=str(section_text or ""),
            value=value,
            dimension=dimension,
            scale_exponent=scale,
            metric_code=None if metric_code is None else str(metric_code),
            statement_type=None if statement_type is None else str(statement_type),
            retrieval_metric=None,
        )

    @staticmethod
    def _diversified(facts: list[GroundedFact], limit: int) -> tuple[GroundedFact, ...]:
        if len(facts) <= limit:
            return tuple(facts)
        by_scope: dict[tuple[str, str | None], list[GroundedFact]] = defaultdict(list)
        for fact in facts:
            by_scope[(fact.entity, fact.period[:4] if fact.period else None)].append(fact)
        per_scope = max(8, limit // max(1, len(by_scope)))
        selected: list[GroundedFact] = []
        seen: set[str] = set()
        for scope in sorted(by_scope, key=lambda value: (value[0], value[1] or "")):
            for fact in by_scope[scope][:per_scope]:
                if fact.observation_uid not in seen:
                    selected.append(fact)
                    seen.add(fact.observation_uid)
        for fact in facts:
            if len(selected) >= limit:
                break
            if fact.observation_uid not in seen:
                selected.append(fact)
                seen.add(fact.observation_uid)
        selected.sort(key=lambda item: (-item.score, item.observation_uid))
        return tuple(selected[:limit])


def _dimension(unit_kind: str, local_text: str) -> Dimension:
    normalized = normalize_phrase(local_text)
    if "%" in local_text or any(
        token in normalized
        for token in ("ty le", "tỷ lệ", "phan tram", "phần trăm", "bien loi nhuan")
    ):
        return Dimension.PERCENT
    mapping = {
        "money": Dimension.MONEY,
        "percent": Dimension.PERCENT,
        "rate": Dimension.PERCENT,
        "ratio": Dimension.RATIO,
        "shares": Dimension.SHARES,
        "count": Dimension.COUNT,
    }
    return mapping.get(unit_kind, Dimension.UNKNOWN)


def _dimension_prior(actual: Dimension, preferred: Dimension) -> float:
    """Disambiguate same-row value/rate columns for direct-value questions.

    Notes often put a balance and its percentage in adjacent columns under the
    same row label.  Deduplicating before considering the requested answer type
    systematically selected percentage columns for money questions.  Formula
    questions pass UNKNOWN and therefore remain dimension-neutral.
    """

    if preferred is Dimension.UNKNOWN:
        return 0.0
    compatible = actual is preferred or {
        actual,
        preferred,
    } <= {Dimension.PERCENT, Dimension.PERCENT_POINT}
    if compatible:
        return 80.0
    if actual is Dimension.UNKNOWN:
        return -5.0
    return -100.0


def _metric_leaf(fact: GroundedFact) -> str:
    raw_leaf = fact.row_path.rsplit("›", 1)[-1].strip()
    normalized = normalize_fact_label(raw_leaf)
    # Financial statement labels routinely include accounting identities such
    # as "Lợi nhuận gộp (20 = 10 - 11)".  '=' therefore does not make a row
    # structural.  Fall back to the column only for genuinely code-only rows;
    # metric-code recovery is handled separately by _effective_row_path.
    if len(normalized) <= 2 and fact.column_path:
        column_leaf = fact.column_path.rsplit("›", 1)[-1].strip()
        if column_leaf:
            return column_leaf
    return raw_leaf


_METRIC_CODE_LABELS = {
    "100": "Tài sản ngắn hạn",
    "200": "Tài sản dài hạn",
    "270": "Tổng cộng tài sản",
    "300": "Nợ phải trả",
    "310": "Nợ ngắn hạn",
    "330": "Nợ dài hạn",
    "400": "Vốn chủ sở hữu",
    "410": "Vốn chủ sở hữu",
    "440": "Tổng cộng nguồn vốn",
}

_METRIC_CODES: dict[str, frozenset[str]] = {
    "net_revenue": frozenset({"10"}),
    "gross_profit": frozenset({"20"}),
    "profit_after_tax": frozenset({"60"}),
    "cash_flow_from_operations": frozenset({"20"}),
    "current_assets": frozenset({"100"}),
    "current_liabilities": frozenset({"310"}),
    "total_assets": frozenset({"270"}),
    "total_liabilities": frozenset({"300"}),
    "equity": frozenset({"400", "410"}),
}


def _effective_row_path(row_path: str, metric_code: str | None) -> str:
    label = _METRIC_CODE_LABELS.get(metric_code or "")
    if label is None:
        return row_path
    leaf = row_path.rsplit("›", 1)[-1]
    normalized = normalize_fact_label(leaf)
    if len(normalized) <= 2 or "=" in leaf:
        prefix = row_path.rsplit("›", 1)[0] if "›" in row_path else ""
        return f"{prefix} › {label}" if prefix else label
    return row_path
