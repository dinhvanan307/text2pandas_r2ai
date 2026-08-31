from __future__ import annotations

from copy import deepcopy

from text2pandas.application.usecases.independent_gold import question_sha256
from text2pandas.application.usecases.semantic_parser_review import (
    COMPOSITION_FRAME_FIELDS,
    audit_semantic_parser_review_packet,
    semantic_parser_adjudication_templates,
    semantic_parser_annotation_templates,
)


def _scope() -> list[dict[str, object]]:
    question = "Tổng tài sản VCB năm 2024 là bao nhiêu?"
    return [
        {
            "qid": 1,
            "question": question,
            "question_sha256": question_sha256(question),
            "family": "direct_lookup",
            "split": "development",
        }
    ]


def _complete(row: dict[str, object], identity_field: str, identity: str) -> None:
    row[identity_field] = identity
    row["independent_of_model_development"] = True
    row["source_evidence_reviewed"] = True
    row["structural_status"] = "OK"
    row["complexity_class"] = "direct"
    frame = row["composition_frame"]
    assert isinstance(frame, dict)
    frame["expected_ast"] = {"expression": {"type": "metric_ref", "metric_id": "total_assets"}}
    frame["output_dimension"] = "money"
    ambiguity = frame["ambiguity"]
    assert isinstance(ambiguity, dict)
    ambiguity["status"] = "NONE"


def test_templates_are_prediction_blind_and_field_complete() -> None:
    annotation = semantic_parser_annotation_templates(_scope(), annotator_slot="A")[0]
    frame = annotation["composition_frame"]

    assert isinstance(frame, dict)
    assert set(COMPOSITION_FRAME_FIELDS) == set(frame)
    assert not any(str(field).startswith("model_") for field in annotation)


def test_blank_packet_fails_closed_at_human_gate() -> None:
    scope = _scope()
    a = semantic_parser_annotation_templates(scope, annotator_slot="A")
    b = semantic_parser_annotation_templates(scope, annotator_slot="B")
    c = semantic_parser_adjudication_templates(scope)

    audit = audit_semantic_parser_review_packet(scope, a, b, c)

    assert not audit.sealable
    assert audit.annotator_a_complete == 0
    assert "ANNOTATOR_A_INCOMPLETE:1" in audit.blockers
    assert "DISTINCT_REVIEWER_IDENTITIES_REQUIRED:0:3" in audit.blockers


def test_complete_packet_requires_three_distinct_reviewers() -> None:
    scope = _scope()
    a = [deepcopy(row) for row in semantic_parser_annotation_templates(scope, annotator_slot="A")]
    b = [deepcopy(row) for row in semantic_parser_annotation_templates(scope, annotator_slot="B")]
    c = [deepcopy(row) for row in semantic_parser_adjudication_templates(scope)]
    _complete(a[0], "annotator_id", "reviewer-a")
    _complete(b[0], "annotator_id", "reviewer-b")
    _complete(c[0], "adjudicator_id", "reviewer-c")

    audit = audit_semantic_parser_review_packet(scope, a, b, c)

    assert audit.sealable
    assert audit.to_dict()["status"] == "READY_TO_SEAL"


def test_model_output_field_is_rejected_recursively() -> None:
    scope = _scope()
    a = [deepcopy(row) for row in semantic_parser_annotation_templates(scope, annotator_slot="A")]
    b = [deepcopy(row) for row in semantic_parser_annotation_templates(scope, annotator_slot="B")]
    c = [deepcopy(row) for row in semantic_parser_adjudication_templates(scope)]
    _complete(a[0], "annotator_id", "reviewer-a")
    _complete(b[0], "annotator_id", "reviewer-b")
    _complete(c[0], "adjudicator_id", "reviewer-c")
    frame = a[0]["composition_frame"]
    assert isinstance(frame, dict)
    frame["metadata"] = {"model_ast": {}}

    audit = audit_semantic_parser_review_packet(scope, a, b, c)

    assert not audit.sealable
    assert "A_MODEL_OUTPUT_LEAK:1:model_ast" in audit.blockers
