from __future__ import annotations

import pytest

from text2pandas.application.usecases.review_backlog import build_failure_review_backlog


def _record(qid: int, reason: str, *, status: str = "ABSTAIN") -> dict[str, object]:
    return {
        "qid": qid,
        "question": f"Question {qid}",
        "status": status,
        "reason": reason,
        "ast": {"expression": {"type": "metric_ref"}},
        "evidence": [],
    }


def test_review_backlog_keeps_all_priority_and_fills_deterministically() -> None:
    rows = [
        _record(1, "BINDING_TIE"),
        _record(2, "OTHER"),
        _record(3, "REPORTED"),
        _record(4, "OTHER"),
        _record(5, "IGNORED", status="OK"),
    ]

    first = build_failure_review_backlog(
        rows,
        target_count=3,
        priority_reasons=("BINDING_TIE", "REPORTED"),
        seed="fixture",
    )
    second = build_failure_review_backlog(
        list(reversed(rows)),
        target_count=3,
        priority_reasons=("BINDING_TIE", "REPORTED"),
        seed="fixture",
    )

    assert first.records == second.records
    assert {row["qid"] for row in first.records[:2]} == {1, 3}
    assert first.priority_records == 2
    assert first.filler_records == 1
    assert all(row["promotion_eligible"] is False for row in first.records)
    assert all(row["model_outputs_included"] is True for row in first.records)


def test_review_backlog_rejects_target_smaller_than_priority_cohort() -> None:
    with pytest.raises(ValueError, match="priority cohort exceeds"):
        build_failure_review_backlog(
            [_record(1, "BINDING_TIE"), _record(2, "BINDING_TIE")],
            target_count=1,
            priority_reasons=("BINDING_TIE",),
            seed="fixture",
        )
