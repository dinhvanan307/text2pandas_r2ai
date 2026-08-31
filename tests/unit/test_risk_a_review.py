from __future__ import annotations

from text2pandas.application.usecases.risk_a_review import (
    REQUIRED_OBSERVATION_FIELDS,
    build_risk_a_review_scope,
    risk_a_adjudication_templates,
    risk_a_annotation_templates,
)


def _inventory() -> list[dict[str, object]]:
    return [
        {
            "qid": qid,
            "triage": {"risk_tier": "A", "repair_class": "direct_lookup"},
        }
        for qid in (1, 2, 3)
    ]


def test_scope_is_deterministic_and_stratified() -> None:
    questions = {qid: f"Question {qid}" for qid in (1, 2, 3)}
    split = {"direct_lookup": (2, 1)}
    left = build_risk_a_review_scope(
        _inventory(), questions, seed="sealed", family_split=split
    )
    right = build_risk_a_review_scope(
        list(reversed(_inventory())), questions, seed="sealed", family_split=split
    )

    assert left == right
    assert left.family_counts == {"direct_lookup": 3}
    assert left.split_counts == {"development": 2, "holdout": 1}
    assert {row["qid"] for row in left.records} == {1, 2, 3}


def test_scope_rejects_family_count_drift() -> None:
    questions = {qid: f"Question {qid}" for qid in (1, 2, 3)}
    try:
        build_risk_a_review_scope(
            _inventory(), questions, seed="sealed", family_split={"direct_lookup": (1, 1)}
        )
    except ValueError as error:
        assert "family count mismatch" in str(error)
    else:
        raise AssertionError("family count drift must fail closed")


def test_review_templates_are_prediction_blind_and_role_complete() -> None:
    questions = {qid: f"Question {qid}" for qid in (1, 2, 3)}
    scope = build_risk_a_review_scope(
        _inventory(), questions, seed="sealed", family_split={"direct_lookup": (2, 1)}
    )
    annotations = risk_a_annotation_templates(scope.records, reviewer_slot="A")
    adjudications = risk_a_adjudication_templates(scope.records)

    assert len(annotations) == len(adjudications) == 3
    assert not ({"model_answer", "model_ast", "candidate_scores"} & annotations[0].keys())
    binding = annotations[0]["evidence_binding"]
    assert isinstance(binding, dict)
    assert tuple(binding["required_observation_fields"]) == REQUIRED_OBSERVATION_FIELDS
    assert adjudications[0]["reviewed_disagreement_fields"] == []
