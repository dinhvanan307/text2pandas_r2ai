from __future__ import annotations

from copy import deepcopy

import pytest

from text2pandas.application.usecases.independent_gold import (
    adjudication_templates,
    annotation_templates,
    select_blinded_questions,
    validate_and_merge_release,
)


def _completed():
    selected = select_blinded_questions(
        ({"id": 1, "question": "Câu một?"}, {"id": 2, "question": "Câu hai?"}),
        seed="sealed",
        count=2,
    )
    a = [dict(row) for row in annotation_templates(selected, annotator_slot="A")]
    b = [dict(row) for row in annotation_templates(selected, annotator_slot="B")]
    c = [dict(row) for row in adjudication_templates(selected)]
    answer = {"status": "OK", "value": "1", "unit": {"dimension": "count"}}
    semantic = {"status": "OK", "ast": {"schema_version": 3}}
    evidence = {
        "status": "OK",
        "ordered_operands": [{"observation_uid": "obs-1", "role": "value"}],
    }
    for rows, reviewer_field, reviewer in (
        (a, "annotator_id", "reviewer-a"),
        (b, "annotator_id", "reviewer-b"),
        (c, "adjudicator_id", "reviewer-c"),
    ):
        for row in rows:
            row[reviewer_field] = reviewer
            row["independent_of_model_development"] = True
            row["source_evidence_reviewed"] = True
            row["answer"] = deepcopy(answer)
            row["semantic_parser"] = deepcopy(semantic)
            row["evidence_binding"] = deepcopy(evidence)
    return selected, a, b, c


def test_blinded_selection_is_deterministic_and_contains_no_prediction() -> None:
    selected, a, b, c = _completed()

    assert [row["qid"] for row in selected] == [row["qid"] for row in select_blinded_questions(
        ({"id": 1, "question": "Câu một?"}, {"id": 2, "question": "Câu hai?"}),
        seed="sealed",
        count=2,
    )]
    assert "model_answer" not in a[0]
    assert "model_answer" not in b[0]
    assert "model_answer" not in c[0]


def test_dual_review_and_distinct_adjudication_can_be_sealed() -> None:
    selected, a, b, c = _completed()

    result = validate_and_merge_release(
        a, b, c, expected_qids=[int(row["qid"]) for row in selected]
    )

    assert len(result.records) == 2
    assert result.disagreements == 0
    assert result.records[0]["provenance"]["annotators"] == ["reviewer-a", "reviewer-b"]


def test_same_reviewer_cannot_fill_independent_roles() -> None:
    selected, a, b, c = _completed()
    b[0]["annotator_id"] = "reviewer-a"

    with pytest.raises(ValueError, match="identities must be distinct"):
        validate_and_merge_release(a, b, c, expected_qids=[int(row["qid"]) for row in selected])


def test_disagreement_must_be_explicitly_adjudicated() -> None:
    selected, a, b, c = _completed()
    b[0]["answer"] = {"status": "OK", "value": "2", "unit": {"dimension": "count"}}

    with pytest.raises(ValueError, match="unreviewed disagreement"):
        validate_and_merge_release(a, b, c, expected_qids=[int(row["qid"]) for row in selected])


def test_model_output_leak_is_rejected() -> None:
    selected, a, b, c = _completed()
    a[0]["model_answer"] = "1"

    with pytest.raises(ValueError, match="model output leaked"):
        validate_and_merge_release(a, b, c, expected_qids=[int(row["qid"]) for row in selected])
