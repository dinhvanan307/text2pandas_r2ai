from __future__ import annotations

import pytest

from text2pandas.application.usecases.semantic_parser_user_review import (
    SemanticParserUserReviewError,
    apply_user_review,
)


def _queue() -> list[dict[str, object]]:
    return [
        {"qid": 1, "model_draft": {"structural_status": "OK"}},
        {"qid": 2, "model_draft": {"structural_status": "UNRESOLVED"}},
    ]


def _review() -> dict[str, object]:
    return {
        "kind": "text2pandas.semantic_parser_wave6_user_review_input",
        "review_id": "review-v1",
        "reviewer_id": "user-review",
        "reviewer_scope": "SINGLE_USER_SEMANTIC_REVIEW_NOT_INDEPENDENT_GOLD",
        "independent_human_gold": False,
        "source_evidence_default": False,
        "records": [
            {
                "qid": 1,
                "decision": "ACCEPT",
                "semantic_structure": "lookup metric",
                "primary_issue": "draft is correct",
            },
            {
                "qid": 2,
                "decision": "CORRECT",
                "semantic_structure": "ratio then average",
                "primary_issue": "missing composition",
            },
        ],
    }


def test_apply_user_review_preserves_governance() -> None:
    reviewed, summary = apply_user_review(_queue(), _review())

    assert len(reviewed) == 2
    assert reviewed[0]["review_decision"] == "ACCEPT"
    assert reviewed[1]["review_decision"] == "CORRECT"
    assert reviewed[1]["corrected_annotation"] is None
    assert reviewed[1]["source_evidence_reviewed"] is False
    assert summary["model_status_decision_cross_tab"] == {
        "OK:ACCEPT": 1,
        "UNRESOLVED:CORRECT": 1,
    }
    assert summary["independent_human_gold"] is False
    assert summary["ready_for_runtime"] is False
    assert summary["accepted_model_drafts"] == 1
    assert summary["accepted_proposals_without_model_ast"] == 0
    assert summary["corrections_requiring_full_annotation"] == 1


def test_apply_user_review_rejects_incomplete_qid_set() -> None:
    review = _review()
    records = review["records"]
    assert isinstance(records, list)
    records.pop()

    with pytest.raises(SemanticParserUserReviewError, match="QID mismatch"):
        apply_user_review(_queue(), review)


def test_apply_user_review_rejects_gold_claim() -> None:
    review = _review()
    review["independent_human_gold"] = True

    with pytest.raises(SemanticParserUserReviewError, match="must not claim independent gold"):
        apply_user_review(_queue(), review)
