from __future__ import annotations

from text2pandas.application.usecases.semantic_parser_holdout import (
    build_replacement_holdout,
)


def _inventory() -> list[dict[str, object]]:
    return [
        {
            "qid": qid,
            "triage": {"repair_class": "complex", "risk_tier": "C"},
            "semantic": {"model_prediction": f"ignored-{qid}"},
            "source_attempt": {"status": "ignored"},
        }
        for qid in range(1, 7)
    ] + [
        {
            "qid": qid,
            "triage": {"repair_class": "average", "risk_tier": "D"},
            "semantic": {"model_prediction": f"ignored-{qid}"},
        }
        for qid in range(7, 11)
    ]


def test_replacement_holdout_is_deterministic_and_excludes_contamination() -> None:
    questions = {qid: f"Question {qid}" for qid in range(1, 11)}
    first = build_replacement_holdout(
        _inventory(),
        questions,
        {2, 8},
        family_quota={"complex": 2, "average": 1},
        seed="replacement-v1",
    )
    mutated = _inventory()
    for row in mutated:
        row["semantic"] = {"model_prediction": "changed"}
        row["answer"] = 999
    second = build_replacement_holdout(
        mutated,
        questions,
        {2, 8},
        family_quota={"complex": 2, "average": 1},
        seed="replacement-v1",
    )

    assert first.records == second.records
    assert len(first.records) == 3
    assert {int(row["qid"]) for row in first.records}.isdisjoint({2, 8})
    assert {str(row["split"]) for row in first.records} == {"replacement_holdout"}


def test_replacement_holdout_fails_when_quota_is_unavailable() -> None:
    questions = {qid: f"Question {qid}" for qid in range(1, 11)}

    try:
        build_replacement_holdout(
            _inventory(),
            questions,
            set(),
            family_quota={"average": 5},
            seed="replacement-v1",
        )
    except ValueError as error:
        assert "insufficient holdout candidates" in str(error)
    else:
        raise AssertionError("unavailable quota must fail closed")
