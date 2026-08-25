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
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pandas as pd

from text2pandas.application.usecases.answer import AnswerResult
from text2pandas.domain.units.lexicon import MONEY as LEXICON_MONEY, scan_unit
from text2pandas.infrastructure.retrieval.index import tokenize
from text2pandas.pipelines.answering import (
    DIVIDE,
    CandidateCell,
    Selector,
    Unit,
    answer_question,
    classify_operation,
)
from text2pandas.pipelines.answering.adapters import requested_unit_of
from text2pandas.pipelines.answering.ir import OperandSlot
from text2pandas.pipelines.answering.units import MONEY, PERCENT, SHARES, UNKNOWN
from text2pandas.pipelines.retrieval.alias_store import load_aliases
from text2pandas.pipelines.retrieval.metric_hint import metric_codes_hint
from text2pandas.pipelines.retrieval.question_intent import parse_intent
from text2pandas.pipelines.retrieval.query_terms import content_terms, drop_terms
from text2pandas.pipelines.retrieval.submission_adapter import RetrievalToSubmission

_PURE_NUMBER = re.compile(r"^\d+(?:[.,]\d+)?$")
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


class QuestionSelector(Selector):
    """Select an A6 fact with hard semantic gates and deterministic scoring."""

    def __init__(
        self,
        question: str,
        code_hints: frozenset[str],
        drop: tuple[str, ...] = (),
    ) -> None:
        self.question_sequence = [
            token.lower()
            for token in content_terms(question, drop=drop, stop_mode="dau")
            if token.lower() not in _GENERIC
        ]
        self.question_tokens = set(self.question_sequence)
        self.code_hints = code_hints
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
        section_sequence = [
            token for token in tokenize(cell.section_text) if token not in _GENERIC
        ]
        context_sequence = [
            token for token in tokenize(cell.table_context) if token not in _GENERIC
        ]
        row_tokens = set(row_sequence)
        section_tokens = set(section_sequence)
        context_tokens = set(context_sequence)
        if self.category_tokens and not self.category_tokens.issubset(
            row_tokens | section_tokens
        ):
            return None
        overlap = len(self.question_tokens & row_tokens)
        section_overlap = len(self.question_tokens & section_tokens)
        context_overlap = len(self.question_tokens & context_tokens)
        row_run = _longest_common_run(self.question_sequence, row_sequence)
        section_run = _longest_common_run(self.question_sequence, section_sequence)
        context_run = _longest_common_run(self.question_sequence, context_sequence)
        code_hit = bool(cell.metric_code and cell.metric_code in self.code_hints)
        semantic_gate = row_run >= 2 or (
            row_run >= 1 and section_run >= 1 and context_run >= 2
        )
        if not semantic_gate and not code_hit:
            return None
        lexical = overlap / math.sqrt(max(1, len(row_tokens)))
        semantic_score = row_run + 1.5 * section_run + 0.5 * context_run
        semantic_coverage = len(
            self.question_tokens & (row_tokens | section_tokens | context_tokens)
        ) / math.sqrt(max(1, len(self.question_tokens)))
        return (
            1.0 if code_hit else 0.0,
            semantic_coverage,
            semantic_score,
            lexical,
            section_overlap / math.sqrt(max(1, len(section_tokens))),
            context_overlap / math.sqrt(max(1, len(context_tokens))),
            1.0 if not cell.is_restated else 0.0,
            -float(cell.row_path.count("›")),
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
        return Unit(SHARES)
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
    rows = connection.execute(
        f"""
        SELECT o.observation_uid, o.table_uid, o.ticker, t.basis,
               o.row_path_text, o.metric_label_clean, o.col_path_text,
               o.value_source_raw, o.value_decimal_text, o.unit_kind,
               o.currency, o.scale_exponent, o.period_end, o.period_role,
               o.metric_code, o.is_restated, o.grid_row_idx, o.grid_col_idx,
               t.section_text, tc.table_search_text
        FROM observations o
        JOIN observation_readiness r USING(observation_uid)
        JOIN tables t USING(table_uid)
        JOIN table_cards tc USING(table_uid)
        WHERE o.table_uid IN ({placeholders})
          AND r.execution_ready = 1
          AND o.value_decimal_text IS NOT NULL
        ORDER BY o.table_uid, o.grid_row_idx, o.grid_col_idx, o.observation_uid
        """,
        tuple(table_uids),
    )

    candidates: list[CandidateCell] = []
    frame_rows: dict[str, list[dict[str, object]]] = defaultdict(list)
    keys: dict[str, dict[tuple[str, str], str]] = defaultdict(dict)
    for row in rows:
        (
            _observation_uid,
            table_uid,
            ticker,
            basis,
            row_path,
            metric_label,
            col_path,
            value_raw,
            decimal_text,
            unit_kind,
            currency,
            scale,
            period_end,
            period_role,
            metric_code,
            is_restated,
            _grid_row,
            _grid_col,
            section_text,
            table_context,
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
        if (
            unit_kind == "money"
            and detected_dimension == LEXICON_MONEY
            and detected_scale is not None
            and detected_scale != scale
        ):
            # Two independent A6 fields disagree. Choosing either side here
            # would recreate the measured 10^3/10^6 family, so this fact is not
            # eligible for answer generation until adjudicated upstream.
            continue

        csv_path = f"data/{table_uid}.csv"
        df_var = f"df{rank[table_uid] + 1}"
        column = _safe_label(col_path or "", period_end)
        base_column = column
        suffix = 0
        current = keys[csv_path]
        while (path, column) in current and current[(path, column)] != str(decimal_text):
            suffix += 1
            column = f"{base_column} #{suffix}"
        if (path, column) not in current:
            current[(path, column)] = str(decimal_text)
            frame_rows[csv_path].append(
                {
                    "row_path": path,
                    "row_label": metric_label or path,
                    "col_label": column,
                    "value_raw": value_raw or "",
                    "value": value,
                }
            )
        candidates.append(
            CandidateCell(
                df_var=df_var,
                csv_path=csv_path,
                row_index=len(frame_rows[csv_path]) - 1,
                row_path=path,
                col_label=column,
                value_raw=value_raw or str(decimal_text),
                value=value,
                parsed_raw=value,
                storage_exponent=0,
                unit=_unit(unit_kind, scale, currency),
                period=period_end,
                table_uid=table_uid,
                entity=ticker,
                basis=basis,
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


def run_canonical_pipeline(
    a6_db: Path,
    retrieval_db: Path,
    questions_path: Path,
    output_dir: Path,
    *,
    offset: int = 0,
    limit: int = 0,
    max_tables: int = 10,
    answer_pool_tables: int = 30,
    progress=None,
) -> CanonicalPipelineReport:
    """Run retrieval and fail-closed answer generation for a question slice."""

    output_dir.mkdir(parents=True, exist_ok=False)
    data_dir = output_dir / "data"
    data_dir.mkdir()
    records_path = output_dir / "records.jsonl"
    aliases = load_aliases("a6")
    retrieval = RetrievalToSubmission(
        aliases,
        max_n=max_tables,
        top_k_rerank=max(answer_pool_tables, max_tables),
    )
    questions = [
        json.loads(line)
        for line in questions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    questions = questions[offset:]
    if limit:
        questions = questions[:limit]

    ret_conn = sqlite3.connect(f"file:{retrieval_db.resolve()}?mode=ro&immutable=1", uri=True)
    a6_conn = sqlite3.connect(f"file:{a6_db.resolve()}?mode=ro&immutable=1", uri=True)
    results: list[AnswerResult] = []
    reasons: dict[str, int] = defaultdict(int)
    n_entity = n_year = n_retrieved = n_answered = 0
    started = time.time()
    try:
        with records_path.open("x", encoding="utf-8") as handle:
            for index, question in enumerate(questions, 1):
                qid = int(question["id"])
                text = str(question["question"])
                intent = parse_intent(text, aliases)
                n_entity += bool(intent.tickers)
                n_year += bool(intent.years)
                refs = retrieval.refs_for(ret_conn, qid, text)
                n_retrieved += bool(refs.table_uids)

                reason: str | None = None
                pipeline_result = None
                frames_by_path: dict[str, pd.DataFrame] = {}
                if len(intent.targets) != 1:
                    reason = "ANSWER_REQUIRES_SINGLE_ENTITY"
                elif classify_operation(text).op == DIVIDE:
                    reason = "DIVIDE_REQUIRES_PER_OPERAND_METRICS"
                elif not refs.table_uids:
                    reason = "NO_RETRIEVED_TABLE"
                else:
                    answer_tables = refs.ranked_table_uids[:answer_pool_tables]
                    pool, frames_by_path = load_candidate_cells(a6_conn, answer_tables)
                    frames = {
                        cell.df_var: frames_by_path[cell.csv_path]
                        for cell in pool
                        if cell.csv_path in frames_by_path
                    }
                    pipeline_result = answer_question(
                        text,
                        pool,
                        frames,
                        qid=qid,
                        requested_unit=requested_unit_of(text),
                        selector=QuestionSelector(
                            text,
                            metric_codes_hint(text),
                            drop=drop_terms(intent.targets, aliases),
                        ),
                    )
                    if not pipeline_result.ok:
                        reason = f"{pipeline_result.stage_failed}:{pipeline_result.reason}"

                if pipeline_result is not None and pipeline_result.ok:
                    evidence = pipeline_result.evidence
                    _write_evidence_frames(data_dir, evidence, frames_by_path)
                    result = AnswerResult(
                        qid=qid,
                        answer=pipeline_result.answer,
                        relevant_docs=refs.relevant_docs,
                        relevant_tables=refs.relevant_tables,
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
                results.append(result)
                handle.write(
                    json.dumps(
                        {
                            "qid": qid,
                            "status": "OK" if result.answer is not None else "ABSTAIN",
                            "answer": result.answer,
                            "relevant_docs": result.relevant_docs,
                            "relevant_tables": result.relevant_tables,
                            "evidence": result.evidence,
                            "pandas_query": result.pandas_query,
                            "confidence": result.confidence,
                            "reason": reason,
                            "trace": pipeline_result.to_dict() if pipeline_result else None,
                        },
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
    )
