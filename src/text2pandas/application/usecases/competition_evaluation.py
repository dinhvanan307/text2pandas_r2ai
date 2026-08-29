"""Pure scorer for the competition's ten leaderboard metrics.

The organiser keeps test gold private.  This module therefore implements the
published metric semantics without claiming that any local gold is official.
Adapters decide which governed gold release and submission artifact to load.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RetrievalGold:
    qid: int
    relevant_tables: frozenset[str]
    relevant_docs: frozenset[str]


@dataclass(frozen=True, slots=True)
class AnswerGold:
    qid: int
    answer: float


@dataclass(frozen=True, slots=True)
class Prediction:
    qid: int
    relevant_tables: tuple[str, ...]
    relevant_docs: tuple[str, ...]
    answer: float | None


@dataclass(frozen=True, slots=True)
class ReplayResult:
    qid: int
    status: str
    value: float | None


@dataclass(frozen=True, slots=True)
class RankedCaseScore:
    qid: int
    precision: float
    recall: float
    f2: float
    mrr5: float


def normalize_doc_ref(value: object) -> str:
    return str(value or "").strip().removesuffix("_extracted")


def normalize_table_ref(value: object) -> str:
    raw = str(value or "").strip()
    doc, separator, locator = raw.rpartition("|")
    if not separator or not doc or not locator:
        raise ValueError(f"invalid table reference: {raw!r}")
    doc = normalize_doc_ref(doc)
    locator = locator.removeprefix("line:")
    try:
        line = int(locator)
    except ValueError as error:
        raise ValueError(f"invalid table locator: {raw!r}") from error
    if line < 1:
        raise ValueError(f"table locator must be 1-based: {raw!r}")
    return f"{doc}|{line}"


def score_ranked_case(
    qid: int,
    predicted: tuple[str, ...],
    gold: frozenset[str],
) -> RankedCaseScore:
    if not gold:
        raise ValueError(f"retrieval gold must be non-empty: {qid}")
    hits = len(set(predicted) & gold)
    precision = hits / len(predicted) if predicted else 0.0
    recall = len(set(predicted) & gold) / len(gold)
    denominator = 4 * precision + recall
    f2 = 5 * precision * recall / denominator if denominator else 0.0
    first = next((rank for rank, value in enumerate(predicted, 1) if value in gold), None)
    mrr5 = 1.0 / first if first is not None and first <= 5 else 0.0
    return RankedCaseScore(qid, precision, recall, f2, mrr5)


def score_competition(
    predictions: list[Prediction],
    retrieval_gold: list[RetrievalGold],
    answer_gold: list[AnswerGold],
    replay: list[ReplayResult],
    *,
    tolerance: float = 0.005,
) -> dict[str, Any]:
    """Score one prediction set using the published macro-per-query rules."""

    if not 0 <= tolerance < 1:
        raise ValueError("tolerance must be in [0, 1)")
    by_qid = _unique(predictions, "prediction")
    replay_by_qid = _unique(replay, "replay")
    retrieval_ids = [row.qid for row in retrieval_gold]
    answer_ids = [row.qid for row in answer_gold]
    if len(set(retrieval_ids)) != len(retrieval_ids):
        raise ValueError("duplicate retrieval gold qid")
    if len(set(answer_ids)) != len(answer_ids):
        raise ValueError("duplicate answer gold qid")

    table_cases: list[RankedCaseScore] = []
    doc_cases: list[RankedCaseScore] = []
    retrieval_details: list[dict[str, Any]] = []
    for retrieval_case in sorted(retrieval_gold, key=lambda row: row.qid):
        prediction = by_qid.get(
            retrieval_case.qid, Prediction(retrieval_case.qid, (), (), None)
        )
        table = score_ranked_case(
            retrieval_case.qid,
            prediction.relevant_tables,
            retrieval_case.relevant_tables,
        )
        docs = score_ranked_case(
            retrieval_case.qid, prediction.relevant_docs, retrieval_case.relevant_docs
        )
        table_cases.append(table)
        doc_cases.append(docs)
        retrieval_details.append(
            {
                "qid": retrieval_case.qid,
                "tables": _case_dict(table),
                "docs": _case_dict(docs),
                "predicted_tables": list(prediction.relevant_tables),
                "gold_tables": sorted(retrieval_case.relevant_tables),
            }
        )

    answer_correct = 0
    execution_correct = 0
    answer_details: list[dict[str, Any]] = []
    for answer_case in sorted(answer_gold, key=lambda row: row.qid):
        prediction = by_qid.get(
            answer_case.qid, Prediction(answer_case.qid, (), (), None)
        )
        replay_result = replay_by_qid.get(
            answer_case.qid, ReplayResult(answer_case.qid, "NOT_REPLAYED", None)
        )
        answer_match = _close(prediction.answer, answer_case.answer, tolerance)
        execution_match = (
            replay_result.status == "OK"
            and _close(replay_result.value, answer_case.answer, tolerance)
        )
        answer_correct += answer_match
        execution_correct += execution_match
        answer_details.append(
            {
                "qid": answer_case.qid,
                "gold": answer_case.answer,
                "predicted": prediction.answer,
                "replayed": replay_result.value,
                "replay_status": replay_result.status,
                "answer_correct": answer_match,
                "execution_correct": execution_match,
            }
        )

    metrics = {
        "execution_accuracy": _ratio(execution_correct, len(answer_gold)),
        "tables_f2_macro": _mean(row.f2 for row in table_cases),
        "docs_f2_macro": _mean(row.f2 for row in doc_cases),
        "tables_precision": _mean(row.precision for row in table_cases),
        "tables_recall": _mean(row.recall for row in table_cases),
        "tables_mrr_at_5": _mean(row.mrr5 for row in table_cases),
        "docs_precision": _mean(row.precision for row in doc_cases),
        "docs_recall": _mean(row.recall for row in doc_cases),
        "docs_mrr_at_5": _mean(row.mrr5 for row in doc_cases),
        "answer_accuracy": _ratio(answer_correct, len(answer_gold)),
    }
    return {
        "metrics": metrics,
        "denominators": {
            "retrieval_gold": len(retrieval_gold),
            "answer_gold": len(answer_gold),
            "submission_records": len(predictions),
        },
        "counts": {
            "answer_correct": answer_correct,
            "execution_correct": execution_correct,
        },
        "cases": {"retrieval": retrieval_details, "answer": answer_details},
    }


def compare_scores(
    candidate: dict[str, Any], baseline: dict[str, Any]
) -> dict[str, Any]:
    candidate_metrics = candidate["metrics"]
    baseline_metrics = baseline["metrics"]
    deltas = {
        key: float(candidate_metrics[key]) - float(baseline_metrics[key])
        for key in candidate_metrics
    }
    answer_changes = _case_changes(
        candidate["cases"]["answer"], baseline["cases"]["answer"], "answer_correct"
    )
    execution_changes = _case_changes(
        candidate["cases"]["answer"], baseline["cases"]["answer"], "execution_correct"
    )
    return {
        "metric_deltas": deltas,
        "all_ten_metrics_non_regressing": all(delta >= -1e-12 for delta in deltas.values()),
        "answer_changes": answer_changes,
        "execution_changes": execution_changes,
    }


def _case_changes(
    candidate: list[dict[str, Any]], baseline: list[dict[str, Any]], field: str
) -> dict[str, list[int]]:
    left = {int(row["qid"]): bool(row[field]) for row in candidate}
    right = {int(row["qid"]): bool(row[field]) for row in baseline}
    qids = sorted(set(left) | set(right))
    return {
        "improved_qids": [qid for qid in qids if left.get(qid) and not right.get(qid)],
        "regressed_qids": [qid for qid in qids if right.get(qid) and not left.get(qid)],
    }


def _unique(rows: list[Any], label: str) -> dict[int, Any]:
    output: dict[int, Any] = {}
    for row in rows:
        if row.qid in output:
            raise ValueError(f"duplicate {label} qid: {row.qid}")
        output[row.qid] = row
    return output


def _close(actual: float | None, expected: float, tolerance: float) -> bool:
    return (
        actual is not None
        and math.isfinite(actual)
        and abs(actual - expected) <= tolerance * max(1.0, abs(expected))
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _mean(values: Any) -> float | None:
    materialized = list(values)
    return sum(materialized) / len(materialized) if materialized else None


def _case_dict(value: RankedCaseScore) -> dict[str, float]:
    return {
        "precision": value.precision,
        "recall": value.recall,
        "f2": value.f2,
        "mrr_at_5": value.mrr5,
    }
