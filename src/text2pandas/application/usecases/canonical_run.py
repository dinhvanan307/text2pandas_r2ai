"""Canonical question runtime over the active A6 and retrieval snapshots.

The runtime is deliberately fail-closed: retrieval may return broad candidates,
but answer generation only emits a value after every operand has an exact period,
an explicit unit contract, and positive lexical evidence from an A6 row label.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import pandas as pd

from text2pandas.application.usecases.answer import AnswerResult
from text2pandas.application.parsing import OperationKind, QuestionAnnotations
from text2pandas.application.selection import (
    MetricResolution,
    MetricSelectorPolicy,
    ReviewedMetricResolver,
    SelectorSpec,
)
from text2pandas.domain.metrics import MetricOntology
from text2pandas.domain.units.lexicon import MONEY as LEXICON_MONEY
from text2pandas.domain.units.lexicon import scan_unit
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.retrieval.index import tokenize
from text2pandas.infrastructure.semantic import (
    A6MetricMentionResolver,
    LegacyVietnameseAnnotator,
    load_metric_resolver_policy,
    load_metric_selector_policy,
)
from text2pandas.pipelines.answering import (
    DIVIDE,
    LOOKUP,
    SUBTRACT,
    CandidateCell,
    Selector,
    Unit,
    answer_question,
    classify_operation,
)
from text2pandas.pipelines.answering.adapters import requested_unit_of
from text2pandas.pipelines.answering.count_engine import answer_count_periods
from text2pandas.pipelines.answering.entity_average import answer_entity_average
from text2pandas.pipelines.answering.entity_count import answer_entity_count
from text2pandas.pipelines.answering.entity_difference import answer_entity_difference
from text2pandas.pipelines.answering.entity_sum import (
    answer_entity_sum,
    is_typed_entity_sum,
)
from text2pandas.pipelines.answering.formula_engine import answer_formula_question
from text2pandas.pipelines.answering.ir import OperandSlot
from text2pandas.pipelines.answering.metric_selector import (
    MetricAwareSelector,
    build_selector_specs,
)
from text2pandas.pipelines.answering.frame import parse_question
from text2pandas.pipelines.answering.router import route
from text2pandas.pipelines.answering.units import MONEY, PERCENT, SHARES, UNKNOWN
from text2pandas.pipelines.retrieval.alias_store import load_aliases
from text2pandas.pipelines.retrieval.metric_hint import metric_codes_hint
from text2pandas.pipelines.retrieval.query_terms import content_terms, drop_terms
from text2pandas.pipelines.retrieval.question_intent import parse_intent
from text2pandas.pipelines.retrieval.submission_adapter import RetrievalToSubmission

_PURE_NUMBER = re.compile(r"^\d+(?:[.,]\d+)?$")
_GLUED_EXPLICIT_UNIT = re.compile(
    r"(?:\d|n[ăa]m)(?:tri[ệe]u|ngh[ìi]n|t[ỷy]|vnd)\b",
    re.IGNORECASE,
)
_CATEGORY = re.compile(
    r"\b(?:ngành|lĩnh\s*vực|khu\s*vực|nhóm|đối\s*tượng|loại\s*tiền|kỳ\s*hạn)\s+"
    r"(?P<value>.+?)(?=\s+(?:của|tại|năm|cuối|đầu|trong|là|đạt|bao\s+nhiêu)\b|[?,]|$)",
    re.IGNORECASE,
)
_GENERIC = frozenset(
    {
        "bao",
        "nhieu",
        "nam",
        "cong",
        "ty",
        "gia",
        "giá",
        "tri",
        "trị",
        "me",
        "hop",
        "nhat",
        "trieu",
        "dong",
        "vnd",
        "la",
        "cua",
        "co",
        "cuoi",
        "trong",
        "tai",
    }
)
_METRIC_SELECTOR_MODES = frozenset({"off", "shadow", "guarded"})


@dataclass(slots=True)
class CanonicalPipelineReport:
    n_questions: int
    n_with_entity: int
    n_with_year: int
    n_retrieved: int
    n_answered: int
    n_abstained: int
    seconds: float
    abstain_reasons: dict[str, int]
    results: list[AnswerResult]
    metric_selector_mode: str = "off"
    metric_resolution_status: dict[str, int] = field(default_factory=dict)
    metric_differential_counts: dict[str, int] = field(default_factory=dict)


class _PipelineAnswer(Protocol):
    stage_failed: str | None
    reason: str | None
    query: str | None
    answer: float | None
    evidence: list[dict[str, str]]

    @property
    def ok(self) -> bool: ...

    def to_dict(self) -> dict[str, object]: ...


class QuestionSelector(Selector):
    """Select an A6 fact with hard semantic gates and deterministic scoring."""

    def __init__(
        self,
        question: str,
        code_hints: frozenset[str],
        drop: tuple[str, ...] = (),
        *,
        cross_entity_sum: bool = False,
        preferred_basis: str | None = None,
        preferred_table_uids: frozenset[str] = frozenset(),
    ) -> None:
        normalized_question = tokenize(question)
        self.aggregate_required = not cross_entity_sum and any(
            token in {"tong", "tổng"}
            and (index == 0 or normalized_question[index - 1] in {"co", "có", "tinh", "tính"})
            and normalized_question[index + 1 : index + 3] not in (["cong", "ty"], ["công", "ty"])
            for index, token in enumerate(normalized_question)
        )
        self.question_sequence = [
            token.lower()
            for token in content_terms(question, drop=drop, stop_mode="dau")
            if token.lower() not in _GENERIC
        ]
        self.question_tokens = set(self.question_sequence)
        self.code_hints = code_hints
        self.preferred_basis = preferred_basis
        self.preferred_table_uids = preferred_table_uids
        self.requested_period_role: str | None
        role_text = question.casefold()
        if re.search(
            r"(?:cu[ốo]i\s+(?:n[ăa]m|k[ỳy])|s[ốo]\s+(?:d[ưu]\s+)?cu[ốo]i"
            r"|31\s*/\s*12|ng[àa]y\s+31\s+th[áa]ng\s+12)",
            role_text,
        ):
            self.requested_period_role = "closing"
        elif re.search(
            r"(?:đ[ầa]u\s+n[ăa]m|s[ốo]\s+(?:d[ưu]\s+)?đ[ầa]u|01\s*/\s*01)",
            role_text,
        ):
            self.requested_period_role = "opening"
        else:
            self.requested_period_role = None
        category = _CATEGORY.search(question)
        self.category_tokens = (
            set(tokenize(category.group("value"))) - _GENERIC if category else set()
        )

    def pick(
        self,
        slot: OperandSlot,
        pool: Sequence[CandidateCell],
    ) -> CandidateCell | None:
        ranked: list[tuple[tuple[float, ...], CandidateCell]] = []
        for cell in pool:
            score = self.score_candidate(slot, cell)
            if score is not None:
                ranked.append((score, cell))
        if not ranked:
            return None
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked[0][1]

    def score_candidate(
        self,
        slot: OperandSlot,
        cell: CandidateCell,
    ) -> tuple[float, ...] | None:
        if slot.entity and cell.entity and slot.entity != cell.entity:
            return None
        if slot.basis and cell.basis and slot.basis != cell.basis:
            return None
        if slot.period and (not cell.period or cell.period[:4] != slot.period[:4]):
            return None

        row_sequence = [token for token in tokenize(cell.row_path) if token not in _GENERIC]
        leaf_sequence = [
            token
            for token in tokenize(cell.row_path.rsplit("›", 1)[-1])
            if token not in _GENERIC
        ]
        aggregate_row = (
            leaf_sequence[:1] in (["tong"], ["tổng"], ["cong"], ["cộng"])
            or leaf_sequence[:2] in (["toan", "bo"], ["toàn", "bộ"])
        )
        section_sequence = [token for token in tokenize(cell.section_text) if token not in _GENERIC]
        context_sequence = [
            token for token in tokenize(cell.table_context) if token not in _GENERIC
        ]
        row_tokens = set(row_sequence)
        section_tokens = set(section_sequence)
        context_tokens = set(context_sequence)
        if self.category_tokens and not self.category_tokens.issubset(row_tokens | section_tokens):
            return None
        overlap = len(self.question_tokens & row_tokens)
        section_overlap = len(self.question_tokens & section_tokens)
        context_overlap = len(self.question_tokens & context_tokens)
        row_run = _longest_common_run(self.question_sequence, row_sequence)
        leaf_run = _longest_common_run(self.question_sequence, leaf_sequence)
        section_run = _longest_common_run(self.question_sequence, section_sequence)
        context_run = _longest_common_run(self.question_sequence, context_sequence)
        code_hit = bool(cell.metric_code and cell.metric_code in self.code_hints)
        semantic_gate = (
            row_run >= 2
            or overlap >= 2
            or (row_run >= 1 and section_run >= 1 and context_run >= 2)
        )
        if not semantic_gate and not code_hit:
            return None
        lexical = overlap / math.sqrt(max(1, len(row_tokens)))
        semantic_score = row_run + 1.5 * section_run + 0.5 * context_run
        semantic_coverage = len(
            self.question_tokens & (row_tokens | section_tokens | context_tokens)
        ) / math.sqrt(max(1, len(self.question_tokens)))
        leaf_coverage = len(self.question_tokens & set(leaf_sequence)) / math.sqrt(
            max(1, len(set(leaf_sequence)))
        )
        if self.requested_period_role is None:
            period_role_score = 0.0
        elif cell.period_role == self.requested_period_role:
            period_role_score = 1.0
        elif self.requested_period_role == "closing" and cell.period_role == "current":
            period_role_score = 0.5
        else:
            period_role_score = 0.0
        return (
            # Retrieval is a hard preference only after the cell has passed
            # the semantic gate above.  The wider answer pool remains a
            # fail-closed fallback when shortlisted tables have no valid cell.
            1.0 if cell.table_uid in self.preferred_table_uids else 0.0,
            1.0 if code_hit else 0.0,
            1.0 if self.aggregate_required and aggregate_row else 0.0,
            float(leaf_run),
            leaf_coverage,
            -float(cell.row_path.count("›")),
            # Scope is a soft prior: it only breaks ties after the candidate
            # has matched the same leaf metric at the same structural depth.
            # This preserves standalone-only fallback while preventing minor
            # context wording from defeating BTC's consolidated default.
            1.0 if cell.basis == self.preferred_basis else 0.0,
            semantic_coverage,
            semantic_score,
            lexical,
            period_role_score,
            section_overlap / math.sqrt(max(1, len(section_tokens))),
            context_overlap / math.sqrt(max(1, len(context_tokens))),
            1.0 if not cell.is_restated else 0.0,
            -float(cell.table_rank),
            -float(cell.row_index),
        )


def _longest_common_run(left: Sequence[str], right: Sequence[str]) -> int:
    """Length of the longest contiguous token sequence shared by two texts."""

    if not left or not right:
        return 0
    previous = [0] * (len(right) + 1)
    best = 0
    for left_token in left:
        current = [0] * (len(right) + 1)
        for index, right_token in enumerate(right, 1):
            if left_token == right_token:
                current[index] = previous[index - 1] + 1
                best = max(best, current[index])
        previous = current
    return best


def _unit(kind: str, scale: int | None, currency: str | None) -> Unit:
    if kind == "money":
        return Unit(MONEY, scale, currency)
    if kind == "percent":
        return Unit(PERCENT)
    if kind == "shares":
        # A6 stores share counts as absolute counts; historical snapshots left
        # ``scale_exponent`` NULL because the field was originally money-only.
        return Unit(SHARES, scale if scale is not None else 0)
    return Unit(UNKNOWN)


def _safe_label(label: str, period: str | None) -> str:
    clean = label.strip()
    if not clean:
        return f"period:{period or '?'}"
    return f"{clean} ({period or 'period'})" if _PURE_NUMBER.match(clean) else clean


def load_candidate_cells(
    connection: sqlite3.Connection,
    table_uids: Sequence[str],
) -> tuple[list[CandidateCell], dict[str, pd.DataFrame]]:
    """Load execution-ready observations and build collision-safe dataframes."""

    if not table_uids:
        return [], {}
    rank = {uid: index for index, uid in enumerate(table_uids)}
    placeholders = ",".join("?" for _ in table_uids)
    table_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(tables)")}
    observation_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(observations)")
    }
    document_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(documents)")
    }
    has_document_basis = (
        "document_uid" in table_columns
        and "document_uid" in document_columns
        and "basis" in document_columns
    )
    document_join = (
        "JOIN documents d ON d.document_uid = t.document_uid" if has_document_basis else ""
    )
    basis_expression = "d.basis" if has_document_basis else "t.basis"
    document_expression = (
        "t.directory_doc_id" if "directory_doc_id" in table_columns else "'table:' || t.table_uid"
    )
    statement_expression = (
        "t.statement_type" if "statement_type" in table_columns else "NULL"
    )
    scale_source_expression = (
        "o.scale_source" if "scale_source" in observation_columns else "'unknown'"
    )
    rows = list(
        connection.execute(
            f"""
            SELECT o.observation_uid, o.table_uid, o.ticker, {basis_expression}, {statement_expression},
                   o.row_path_text, o.metric_label_clean, o.col_path_text,
                   o.value_source_raw, o.value_decimal_text, o.unit_kind,
                   o.currency, o.scale_exponent, {scale_source_expression},
                   o.period_end, o.period_role,
                   o.metric_code, o.is_restated, o.grid_row_idx, o.grid_col_idx,
                   t.section_text, tc.table_search_text, {document_expression}
            FROM observations o
            JOIN observation_readiness r USING(observation_uid)
            JOIN tables t USING(table_uid)
            {document_join}
            JOIN table_cards tc USING(table_uid)
            WHERE o.table_uid IN ({placeholders})
              AND r.execution_ready = 1
              AND o.value_decimal_text IS NOT NULL
            ORDER BY o.table_uid, o.grid_row_idx, o.grid_col_idx, o.observation_uid
            """,
            tuple(table_uids),
        )
    )

    # A table-wide unit printed in header columns is inherited by closing
    # columns whose own label is only a date. Infer only from unanimous,
    # explicit column-path evidence; mixed explicit scales remain unresolved.
    explicit_scales: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        table_uid, unit_kind, scale, scale_source = row[1], row[10], row[12], row[13]
        if unit_kind == "money" and scale is not None and scale_source == "column_path":
            explicit_scales[str(table_uid)].add(int(scale))
    inherited_scale = {
        table_uid: next(iter(scales))
        for table_uid, scales in explicit_scales.items()
        if len(scales) == 1
    }

    candidates: list[CandidateCell] = []
    frame_rows: dict[str, list[dict[str, object]]] = defaultdict(list)
    keys: dict[str, dict[tuple[str, str], tuple[str, int]]] = defaultdict(dict)
    for row in rows:
        (
            _observation_uid,
            table_uid,
            ticker,
            basis,
            statement_type,
            row_path,
            metric_label,
            col_path,
            value_raw,
            decimal_text,
            unit_kind,
            currency,
            scale,
            scale_source,
            period_end,
            period_role,
            metric_code,
            is_restated,
            _grid_row,
            _grid_col,
            section_text,
            table_context,
            document_id,
        ) = row
        path = (row_path or metric_label or "").strip()
        if not path:
            continue
        try:
            value = float(decimal_text)
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(value):
            continue

        detected_dimension, detected_scale, _ = scan_unit(col_path or "")
        # A row label may carry a more specific unit than the table header.
        # Typical example: a statement is generally in "Triệu đồng" while
        # the EPS row explicitly says "VND/cổ phiếu".  Row-local evidence
        # must win, otherwise 1,161 VND/share becomes 1.161 billion VND/share.
        row_dimension, row_scale, _ = scan_unit(
            " ".join(part for part in (row_path, metric_label) if part)
        )
        effective_scale = scale
        if (
            unit_kind == "money"
            and detected_dimension == LEXICON_MONEY
            and detected_scale is not None
            and detected_scale != scale
        ):
            # The legacy A6 parser missed explicit units glued to a preceding
            # token (for example ``Số cuối nămTriệu đồng``) and recorded 1e0.
            # The runtime lexicon recognizes that exact header. Correct only
            # this measured parser-boundary defect; ordinary disagreements
            # remain fail-closed.
            if _GLUED_EXPLICIT_UNIT.search(col_path or ""):
                effective_scale = detected_scale
            else:
                continue
        if (
            unit_kind == "money"
            and row_dimension == LEXICON_MONEY
            and row_scale is not None
        ):
            effective_scale = row_scale
        elif (
            unit_kind == "money"
            and scale_source != "column_path"
            and detected_dimension != LEXICON_MONEY
            and str(table_uid) in inherited_scale
        ):
            effective_scale = inherited_scale[str(table_uid)]

        csv_path = f"data/{table_uid}.csv"
        df_var = f"df{rank[table_uid] + 1}"
        column = _safe_label(col_path or "", period_end)
        base_column = column
        suffix = 0
        current = keys[csv_path]
        while (
            (path, column) in current
            and current[(path, column)][0] != str(decimal_text)
        ):
            suffix += 1
            column = f"{base_column} #{suffix}"
        if (path, column) not in current:
            row_index = len(frame_rows[csv_path])
            current[(path, column)] = (str(decimal_text), row_index)
            frame_rows[csv_path].append(
                {
                    "row_path": path,
                    "row_label": metric_label or path,
                    "col_label": column,
                    "value_raw": value_raw or "",
                    "value": value,
                }
            )
        else:
            row_index = current[(path, column)][1]
        candidates.append(
            CandidateCell(
                df_var=df_var,
                csv_path=csv_path,
                row_index=row_index,
                row_path=path,
                col_label=column,
                value_raw=value_raw or str(decimal_text),
                value=value,
                parsed_raw=value,
                storage_exponent=0,
                unit=_unit(unit_kind, effective_scale, currency),
                period=period_end,
                table_uid=table_uid,
                document_id=document_id,
                entity=ticker,
                basis=basis,
                statement_type=statement_type,
                metric_code=metric_code,
                period_role=period_role,
                is_restated=bool(is_restated),
                table_rank=rank[table_uid],
                section_text=section_text or "",
                table_context=table_context or "",
            )
        )
    frames = {path: pd.DataFrame(values) for path, values in frame_rows.items()}
    return candidates, frames


def _write_evidence_frames(
    data_dir: Path,
    evidence: Sequence[dict[str, str]],
    frames_by_path: dict[str, pd.DataFrame],
) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for item in evidence:
        csv_path = item["csv_path"]
        frame = frames_by_path[csv_path]
        target = data_dir.parent / csv_path
        if not target.exists():
            frame.to_csv(target, index=False)


def _metric_guard_eligible(
    resolution: MetricResolution,
    annotations: QuestionAnnotations,
    policy: MetricSelectorPolicy,
) -> bool:
    if (
        not resolution.resolved
        or not resolution.operation_eligible
        or resolution.confidence < policy.min_guarded_confidence
        or len(annotations.entities) != 1
    ):
        return False
    periods = len(annotations.periods)
    if annotations.operation == OperationKind.LOOKUP:
        return periods == 1
    if annotations.operation in {OperationKind.SUBTRACT, OperationKind.GROWTH}:
        return periods == 2
    if annotations.operation in {OperationKind.SUM, OperationKind.AVERAGE}:
        return periods >= 2
    return False


def _run_metric_candidate(
    question: str,
    pool: Sequence[CandidateCell],
    frames: dict[str, pd.DataFrame],
    *,
    qid: int,
    entity: str,
    requested_unit: Unit,
    requested_period_role: str | None,
    resolution: MetricResolution,
    annotations: QuestionAnnotations,
    ontology: MetricOntology,
    policy: MetricSelectorPolicy,
) -> tuple[_PipelineAnswer | None, tuple[SelectorSpec, ...]]:
    metric_id = resolution.selected_metric_id
    if metric_id is None:
        return None, ()
    frame = parse_question(
        question,
        qid=qid,
        metric_id=metric_id,
        requested_unit=requested_unit,
        resolved_entity=entity,
    )
    routed = route(frame)
    if not routed.ok or routed.ir is None:
        return None, ()
    specs_by_slot = build_selector_specs(
        resolution,
        ontology,
        annotations,
        routed.ir,
        requested_period_role=requested_period_role,
    )
    if len(specs_by_slot) != routed.ir.arity:
        return None, ()
    selector = MetricAwareSelector(
        specs_by_slot,
        ambiguity_margin=policy.ambiguity_margin,
    )
    candidate = answer_question(
        question,
        pool,
        frames,
        qid=qid,
        metric_id=metric_id,
        requested_unit=requested_unit,
        selector=selector,
        resolved_entity=entity,
        max_bind_attempts=policy.max_rebind_candidates,
    )
    ordered_specs = tuple(specs_by_slot[slot.key()] for slot in routed.ir.slots)
    return candidate, ordered_specs


def _pipeline_differential(
    legacy: _PipelineAnswer,
    candidate: _PipelineAnswer,
) -> str:
    if legacy.ok and not candidate.ok:
        return "LEGACY_ONLY"
    if candidate.ok and not legacy.ok:
        return "P0_ONLY"
    if not legacy.ok and not candidate.ok:
        return "BOTH_ABSTAIN"
    assert legacy.answer is not None and candidate.answer is not None
    if not math.isclose(legacy.answer, candidate.answer, rel_tol=1e-12, abs_tol=1e-9):
        return "BOTH_DIFFERENT_ANSWER"
    legacy_evidence = tuple(
        sorted((item["variable"], item["csv_path"]) for item in legacy.evidence)
    )
    candidate_evidence = tuple(
        sorted((item["variable"], item["csv_path"]) for item in candidate.evidence)
    )
    return (
        "BOTH_SAME_ANSWER_SAME_EVIDENCE"
        if legacy_evidence == candidate_evidence
        else "BOTH_SAME_ANSWER_DIFFERENT_EVIDENCE"
    )


def run_canonical_pipeline(
    a6_db: Path,
    retrieval_db: Path,
    questions_path: Path,
    output_dir: Path,
    *,
    question_ids: frozenset[int] | None = None,
    offset: int = 0,
    limit: int = 0,
    max_tables: int = 10,
    answer_pool_tables: int = 50,
    output_score_margin: float | None = None,
    retrieval_primary_boost: float = 0.0,
    prefer_retrieval_output_in_binding: bool = False,
    enable_direct_interest_average: bool = False,
    metric_selector_mode: str = "off",
    p0_source_build_id: str | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> CanonicalPipelineReport:
    """Run retrieval and fail-closed answer generation for a question slice."""

    if metric_selector_mode not in _METRIC_SELECTOR_MODES:
        raise ValueError(
            f"metric_selector_mode must be one of {sorted(_METRIC_SELECTOR_MODES)}"
        )
    if metric_selector_mode != "off" and not p0_source_build_id:
        raise ValueError("p0_source_build_id is required for shadow/guarded mode")
    output_dir.mkdir(parents=True, exist_ok=False)
    data_dir = output_dir / "data"
    data_dir.mkdir()
    records_path = output_dir / "records.jsonl"
    aliases = load_aliases("a6")
    retrieval = RetrievalToSubmission(
        aliases,
        max_n=max_tables,
        top_k_rerank=max(answer_pool_tables, max_tables),
        output_score_margin=output_score_margin,
        primary_boost=retrieval_primary_boost,
    )
    # Scorer-facing ranking experiments must not silently perturb answer
    # selection.  Keep the wider binding pool on the baseline ranker; the
    # candidate ranker controls only submitted table refs and the explicitly
    # enabled retrieval-core preference below.
    answer_pool_retrieval = (
        RetrievalToSubmission(
            aliases,
            max_n=max_tables,
            top_k_rerank=max(answer_pool_tables, max_tables),
        )
        if retrieval_primary_boost
        else retrieval
    )
    questions = [
        json.loads(line)
        for line in questions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if question_ids is not None:
        source_ids = {int(question["id"]) for question in questions}
        unknown_ids = sorted(question_ids - source_ids)
        if unknown_ids:
            raise ValueError(f"unknown question IDs: {unknown_ids}")
        questions = [
            question for question in questions if int(question["id"]) in question_ids
        ]
    questions = questions[offset:]
    if limit:
        questions = questions[:limit]

    ret_conn = sqlite3.connect(f"file:{retrieval_db.resolve()}?mode=ro&immutable=1", uri=True)
    a6_conn = sqlite3.connect(f"file:{a6_db.resolve()}?mode=ro&immutable=1", uri=True)
    results: list[AnswerResult] = []
    reasons: dict[str, int] = defaultdict(int)
    metric_resolution_status: dict[str, int] = defaultdict(int)
    metric_differential_counts: dict[str, int] = defaultdict(int)
    n_entity = n_year = n_retrieved = n_answered = 0
    started = time.time()
    metric_ontology: MetricOntology | None = None
    metric_annotator: LegacyVietnameseAnnotator | None = None
    metric_resolver: ReviewedMetricResolver | None = None
    metric_selector_policy: MetricSelectorPolicy | None = None
    try:
        if metric_selector_mode != "off":
            metric_ontology = load_ontology()
            metric_annotator = LegacyVietnameseAnnotator(aliases)
            source_resolver = A6MetricMentionResolver(
                a6_conn,
                source_build_id=str(p0_source_build_id),
                entity_aliases=aliases,
            )
            metric_resolver = ReviewedMetricResolver(
                metric_ontology,
                load_metric_resolver_policy(),
                source_resolver,
            )
            metric_selector_policy = load_metric_selector_policy()
        with records_path.open("x", encoding="utf-8") as handle:
            for index, question in enumerate(questions, 1):
                qid = int(question["id"])
                text = str(question["question"])
                intent = parse_intent(text, aliases)
                metric_annotations: QuestionAnnotations | None = None
                metric_resolution: MetricResolution | None = None
                metric_specs: tuple[SelectorSpec, ...] = ()
                metric_candidate: _PipelineAnswer | None = None
                metric_eligible = False
                metric_selected = False
                metric_differential = "MODE_OFF"
                if metric_resolver is not None and metric_annotator is not None:
                    metric_annotations = metric_annotator.annotate(text)
                    metric_resolution = metric_resolver.resolve(text, metric_annotations)
                    metric_resolution_status[metric_resolution.status] += 1
                    assert metric_selector_policy is not None
                    metric_eligible = _metric_guard_eligible(
                        metric_resolution,
                        metric_annotations,
                        metric_selector_policy,
                    )
                    metric_differential = (
                        "ELIGIBLE_NOT_RUN" if metric_eligible else "NOT_ELIGIBLE"
                    )
                n_entity += bool(intent.tickers)
                n_year += bool(intent.years)
                refs = retrieval.refs_for(ret_conn, qid, text)
                answer_pool_refs = (
                    answer_pool_retrieval.refs_for(ret_conn, qid, text)
                    if answer_pool_retrieval is not retrieval
                    else refs
                )
                n_retrieved += bool(refs.table_uids)

                reason: str | None = None
                pipeline_result: _PipelineAnswer | None = None
                frames_by_path: dict[str, pd.DataFrame] = {}
                evidence_uids: list[str] = []
                binding_preferred_uids: list[str] = []
                if not refs.table_uids:
                    reason = "NO_RETRIEVED_TABLE"
                elif not intent.targets:
                    reason = "ANSWER_REQUIRES_ENTITY"
                else:
                    answer_tables = answer_pool_refs.ranked_table_uids[:answer_pool_tables]
                    pool, frames_by_path = load_candidate_cells(a6_conn, answer_tables)
                    frames = {
                        cell.df_var: frames_by_path[cell.csv_path]
                        for cell in pool
                        if cell.csv_path in frames_by_path
                    }
                    requested_unit = requested_unit_of(text)
                    entity_sum_route = is_typed_entity_sum(
                        text,
                        intent.targets,
                        intent.years,
                        requested_unit,
                    )
                    operation_kind = classify_operation(text).op
                    binding_preference_allowed = (
                        prefer_retrieval_output_in_binding
                        and len(intent.targets) == 1
                        and operation_kind in {LOOKUP, SUBTRACT}
                    )
                    if binding_preference_allowed:
                        output_policy = refs.trace["output_policy"]
                        binding_core_n = (
                            int(output_policy.get("base_n", refs.n_policy))
                            if isinstance(output_policy, dict)
                            else refs.n_policy
                        )
                        binding_preferred_uids = refs.ranked_table_uids[:binding_core_n]
                    selector = QuestionSelector(
                        text,
                        metric_codes_hint(text),
                        drop=drop_terms(intent.targets, aliases),
                        cross_entity_sum=entity_sum_route,
                        preferred_basis=intent.basis,
                        preferred_table_uids=(
                            frozenset(binding_preferred_uids)
                            if binding_preference_allowed
                            else frozenset()
                        ),
                    )
                    if len(intent.targets) >= 2:
                        pipeline_result = answer_entity_count(
                            text,
                            pool,
                            frames,
                            entities=intent.targets,
                            years=intent.years,
                            basis=intent.answer_basis,
                            selector=selector,
                            mode=intent.mode,
                            qid=qid,
                        )
                        if pipeline_result is None and len(intent.targets) == 2:
                            pipeline_result = answer_entity_difference(
                                text,
                                pool,
                                frames,
                                entities=intent.targets,
                                years=intent.years,
                                basis=intent.answer_basis,
                                requested_unit=requested_unit,
                                selector=selector,
                                mode=intent.mode,
                                qid=qid,
                            )
                        if pipeline_result is None:
                            pipeline_result = answer_entity_average(
                                text,
                                pool,
                                frames,
                                entities=intent.targets,
                                years=intent.years,
                                basis=intent.answer_basis,
                                requested_unit=requested_unit,
                                selector=selector,
                                qid=qid,
                                allow_interest_expense=enable_direct_interest_average,
                            )
                        if pipeline_result is None:
                            pipeline_result = answer_entity_sum(
                                text,
                                pool,
                                frames,
                                entities=intent.targets,
                                years=intent.years,
                                basis=intent.answer_basis,
                                requested_unit=requested_unit,
                                selector=selector,
                                qid=qid,
                            )
                        if pipeline_result is None:
                            reason = "MULTI_ENTITY_OPERATION_NOT_SUPPORTED"
                    else:
                        pipeline_result = answer_count_periods(
                            text,
                            pool,
                            frames,
                            entity=intent.targets[0],
                            years=intent.years,
                            basis=intent.answer_basis,
                            selector=selector,
                            qid=qid,
                        )
                        if pipeline_result is None:
                            pipeline_result = answer_formula_question(
                                text,
                                pool,
                                frames,
                                entity=intent.targets[0],
                                years=intent.years,
                                basis=intent.answer_basis,
                                requested_unit=requested_unit,
                                qid=qid,
                            )
                        if pipeline_result is None:
                            if operation_kind == DIVIDE:
                                reason = "DIVIDE_REQUIRES_REVIEWED_FORMULA"
                            else:
                                legacy_result = answer_question(
                                    text,
                                    pool,
                                    frames,
                                    qid=qid,
                                    requested_unit=requested_unit,
                                    selector=selector,
                                    resolved_entity=intent.targets[0],
                                )
                                pipeline_result = legacy_result
                                if (
                                    metric_eligible
                                    and metric_resolution is not None
                                    and metric_annotations is not None
                                    and metric_ontology is not None
                                    and metric_selector_policy is not None
                                ):
                                    metric_candidate, metric_specs = _run_metric_candidate(
                                        text,
                                        pool,
                                        frames,
                                        qid=qid,
                                        entity=intent.targets[0],
                                        requested_unit=requested_unit,
                                        requested_period_role=selector.requested_period_role,
                                        resolution=metric_resolution,
                                        annotations=metric_annotations,
                                        ontology=metric_ontology,
                                        policy=metric_selector_policy,
                                    )
                                    if metric_candidate is None:
                                        metric_differential = "P0_ROUTE_BUILD_FAILED"
                                    else:
                                        metric_differential = _pipeline_differential(
                                            legacy_result,
                                            metric_candidate,
                                        )
                                        if metric_selector_mode == "guarded":
                                            pipeline_result = metric_candidate
                                            metric_selected = True
                    if pipeline_result is not None and not pipeline_result.ok:
                        reason = f"{pipeline_result.stage_failed}:{pipeline_result.reason}"

                if metric_selector_mode != "off":
                    metric_differential_counts[metric_differential] += 1

                if pipeline_result is not None and pipeline_result.ok:
                    evidence = pipeline_result.evidence
                    evidence_uids = [Path(item["csv_path"]).stem for item in evidence]
                    evidence_tables, evidence_docs = retrieval.submission_refs_for_uids(
                        ret_conn,
                        evidence_uids,
                    )
                    _write_evidence_frames(data_dir, evidence, frames_by_path)
                    result = AnswerResult(
                        qid=qid,
                        answer=pipeline_result.answer,
                        relevant_docs=evidence_docs,
                        relevant_tables=evidence_tables,
                        evidence=evidence,
                        pandas_query=pipeline_result.query or "",
                        confidence=0.5,
                        has_csv=True,
                        notes=[],
                    )
                    n_answered += 1
                else:
                    reason = reason or "UNKNOWN_ABSTENTION"
                    reasons[reason] += 1
                    result = AnswerResult(
                        qid=qid,
                        answer=None,
                        relevant_docs=refs.relevant_docs,
                        relevant_tables=refs.relevant_tables,
                        evidence=[],
                        pandas_query="",
                        confidence=0.0,
                        notes=[reason],
                    )
                binding_applied = pipeline_result is not None and pipeline_result.ok
                if not binding_applied:
                    binding_effect = "NOT_APPLIED"
                elif evidence_uids == refs.table_uids:
                    binding_effect = "UNCHANGED"
                elif set(evidence_uids) & set(refs.table_uids):
                    binding_effect = "PARTIAL_REPLACEMENT"
                elif evidence_uids:
                    binding_effect = "REPLACED"
                else:
                    binding_effect = "EMPTY"
                binding_trace = {
                    "status": "APPLIED" if binding_applied else "NOT_APPLIED",
                    "effect": binding_effect,
                    "retrieval_selected_table_ids": refs.table_uids,
                    "answer_pool_table_ids": answer_pool_refs.ranked_table_uids[
                        :answer_pool_tables
                    ],
                    "preferred_retrieval_core_table_ids": binding_preferred_uids,
                    "selected_evidence_table_ids": evidence_uids,
                }
                results.append(result)
                record_payload: dict[str, object] = {
                    "qid": qid,
                    "question": text,
                    "status": "OK" if result.answer is not None else "ABSTAIN",
                    "answer": result.answer,
                    "relevant_docs": result.relevant_docs,
                    "relevant_tables": result.relevant_tables,
                    "evidence": result.evidence,
                    "pandas_query": result.pandas_query,
                    "confidence": result.confidence,
                    "reason": reason,
                    "trace": pipeline_result.to_dict() if pipeline_result else None,
                    "retrieval": refs.trace,
                    "binding": binding_trace,
                    "final": {
                        "relevant_tables": result.relevant_tables,
                        "relevant_docs": result.relevant_docs,
                    },
                }
                if metric_selector_mode != "off":
                    record_payload["metric_p0"] = {
                        "mode": metric_selector_mode,
                        "eligible": metric_eligible,
                        "selected_for_output": metric_selected,
                        "differential": metric_differential,
                        "resolution": (
                            metric_resolution.to_dict() if metric_resolution else None
                        ),
                        "selector_specs": [spec.to_dict() for spec in metric_specs],
                        "candidate_trace": (
                            metric_candidate.to_dict() if metric_candidate else None
                        ),
                    }
                handle.write(
                    json.dumps(
                        record_payload,
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                if progress and index % 100 == 0:
                    progress(index, n_answered)
    finally:
        ret_conn.close()
        a6_conn.close()

    return CanonicalPipelineReport(
        n_questions=len(questions),
        n_with_entity=n_entity,
        n_with_year=n_year,
        n_retrieved=n_retrieved,
        n_answered=n_answered,
        n_abstained=len(questions) - n_answered,
        seconds=round(time.time() - started, 2),
        abstain_reasons=dict(sorted(reasons.items(), key=lambda item: (-item[1], item[0]))),
        results=results,
        metric_selector_mode=metric_selector_mode,
        metric_resolution_status=dict(sorted(metric_resolution_status.items())),
        metric_differential_counts=dict(sorted(metric_differential_counts.items())),
    )
