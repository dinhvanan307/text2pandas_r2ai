"""Deterministic diagnostic review backlog for Semantic V3 failure cohorts."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ReviewBacklog:
    records: tuple[dict[str, Any], ...]
    source_reason_counts: dict[str, int]
    selected_reason_counts: dict[str, int]
    priority_records: int
    filler_records: int


def build_failure_review_backlog(
    records: Sequence[Mapping[str, object]],
    *,
    target_count: int,
    priority_reasons: tuple[str, ...],
    seed: str,
) -> ReviewBacklog:
    """Select every priority failure, then deterministic filler abstentions.

    This cohort is explicitly diagnostic because selection reads model failure
    output. It must never be registered as independent promotion gold.
    """

    if target_count < 1:
        raise ValueError("target_count must be positive")
    if not priority_reasons:
        raise ValueError("at least one priority reason is required")
    seen: set[int] = set()
    abstentions: list[Mapping[str, object]] = []
    for record in records:
        qid = _qid(record)
        if qid in seen:
            raise ValueError(f"duplicate source qid: {qid}")
        seen.add(qid)
        if str(record.get("status") or "") == "ABSTAIN":
            abstentions.append(record)
    if target_count > len(abstentions):
        raise ValueError(
            f"target_count exceeds abstentions: {target_count}>{len(abstentions)}"
        )

    priority_set = set(priority_reasons)
    priority = [
        record
        for record in abstentions
        if str(record.get("reason") or "UNKNOWN") in priority_set
    ]
    if len(priority) > target_count:
        raise ValueError(
            f"priority cohort exceeds target_count: {len(priority)}>{target_count}"
        )
    filler = [record for record in abstentions if record not in priority]
    priority.sort(key=lambda row: (str(row.get("reason") or ""), _qid(row)))
    filler.sort(key=lambda row: _selection_key(row, seed))
    selected = priority + filler[: target_count - len(priority)]
    output = tuple(
        _review_record(
            record,
            selection_role=("PRIORITY" if index < len(priority) else "FILLER"),
        )
        for index, record in enumerate(selected)
    )
    return ReviewBacklog(
        records=output,
        source_reason_counts=dict(
            sorted(Counter(str(row.get("reason") or "UNKNOWN") for row in abstentions).items())
        ),
        selected_reason_counts=dict(
            sorted(Counter(str(row["failure_reason"]) for row in output).items())
        ),
        priority_records=len(priority),
        filler_records=len(output) - len(priority),
    )


def _review_record(
    record: Mapping[str, object], *, selection_role: str
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "qid": _qid(record),
        "question": str(record.get("question") or ""),
        "selection_role": selection_role,
        "failure_reason": str(record.get("reason") or "UNKNOWN"),
        "stage_failed": record.get("stage_failed"),
        "binding_margin": record.get("binding_margin"),
        "ast": record.get("ast"),
        "evidence": record.get("evidence") or [],
        "relevant_tables": record.get("relevant_tables") or [],
        "model_outputs_included": True,
        "promotion_eligible": False,
        "review": {
            "reviewer_id": None,
            "source_evidence_reviewed": None,
            "failure_class_correct": None,
            "expected_status": None,
            "corrected_answer": None,
            "corrected_ast": None,
            "ordered_observation_uids": None,
            "notes": None,
        },
    }


def _selection_key(record: Mapping[str, object], seed: str) -> tuple[str, int]:
    qid = _qid(record)
    reason = str(record.get("reason") or "UNKNOWN")
    digest = hashlib.sha256(f"{seed}\0{qid}\0{reason}".encode()).hexdigest()
    return digest, qid


def _qid(record: Mapping[str, object]) -> int:
    value = record.get("qid")
    if isinstance(value, bool):
        raise TypeError("qid must be an integer")
    try:
        qid = int(str(value))
    except (TypeError, ValueError) as error:
        raise TypeError("qid must be an integer") from error
    if qid < 1:
        raise ValueError("qid must be positive")
    return qid
