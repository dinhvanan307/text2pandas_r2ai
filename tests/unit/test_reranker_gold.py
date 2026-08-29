from __future__ import annotations

import pytest

from text2pandas.application.usecases.reranker_gold import (
    reranker_review_templates,
    seal_reranker_gold,
)


def _completed(row: dict[str, object], identity: str, field: str) -> dict[str, object]:
    return {
        **row,
        field: identity,
        "independent_of_model_development": True,
        "source_evidence_reviewed": True,
        "gold_table_uids": ["table-1"],
    }


def test_reranker_review_templates_seal_with_distinct_reviewers() -> None:
    questions = [{"id": 2, "question": "Question two"}]
    a = _completed(
        dict(reranker_review_templates(questions, reviewer_slot="A")[0]),
        "reviewer-a",
        "annotator_id",
    )
    b = _completed(
        dict(reranker_review_templates(questions, reviewer_slot="B")[0]),
        "reviewer-b",
        "annotator_id",
    )
    c = _completed(
        dict(reranker_review_templates(questions, reviewer_slot="C")[0]),
        "reviewer-c",
        "adjudicator_id",
    )

    release = seal_reranker_gold([a], [b], [c], expected_qids=[2])

    assert release.disagreement_records == 0
    assert release.records[0]["gold_table_uids"] == ["table-1"]
    assert release.records[0]["annotators"] == ["reviewer-a", "reviewer-b"]


def test_reranker_sealer_requires_explicit_disagreement_review() -> None:
    questions = [{"id": 2, "question": "Question two"}]
    a = _completed(
        dict(reranker_review_templates(questions, reviewer_slot="A")[0]),
        "reviewer-a",
        "annotator_id",
    )
    b = {
        **_completed(
            dict(reranker_review_templates(questions, reviewer_slot="B")[0]),
            "reviewer-b",
            "annotator_id",
        ),
        "gold_table_uids": ["table-2"],
    }
    c = _completed(
        dict(reranker_review_templates(questions, reviewer_slot="C")[0]),
        "reviewer-c",
        "adjudicator_id",
    )

    with pytest.raises(ValueError, match="unreviewed evidence disagreement"):
        seal_reranker_gold([a], [b], [c], expected_qids=[2])


def test_reranker_sealer_rejects_question_not_in_sealed_packet() -> None:
    questions = [{"id": 2, "question": "Question two"}]
    rows = {
        slot: _completed(
            dict(reranker_review_templates(questions, reviewer_slot=slot)[0]),
            f"reviewer-{slot.lower()}",
            "adjudicator_id" if slot == "C" else "annotator_id",
        )
        for slot in ("A", "B", "C")
    }

    with pytest.raises(ValueError, match="sealed packet"):
        seal_reranker_gold(
            [rows["A"]],
            [rows["B"]],
            [rows["C"]],
            expected_qids=[2],
            expected_question_sha256={2: "different"},
        )


def test_reranker_sealer_requires_stable_reviewer_identity() -> None:
    questions = [
        {"id": 2, "question": "Question two"},
        {"id": 3, "question": "Question three"},
    ]
    pass_a = [
        _completed(dict(row), f"reviewer-a-{index}", "annotator_id")
        for index, row in enumerate(
            reranker_review_templates(questions, reviewer_slot="A"), start=1
        )
    ]
    pass_b = [
        _completed(dict(row), "reviewer-b", "annotator_id")
        for row in reranker_review_templates(questions, reviewer_slot="B")
    ]
    pass_c = [
        _completed(dict(row), "reviewer-c", "adjudicator_id")
        for row in reranker_review_templates(questions, reviewer_slot="C")
    ]

    with pytest.raises(ValueError, match="stable for slot A"):
        seal_reranker_gold(pass_a, pass_b, pass_c, expected_qids=[2, 3])
