from __future__ import annotations

from text2pandas.application.usecases.independent_gold_audit import (
    audit_independent_gold_packet,
)


def _gold() -> dict[str, object]:
    return {
        "answer": {"status": "OK", "value": 1},
        "semantic_parser": {"status": "OK", "ast": {"expression": {}}},
        "evidence_binding": {
            "status": "OK",
            "ordered_operands": [{"observation_uid": "obs-1"}],
        },
    }


def _annotation(qid: int, identity: str, field: str) -> dict[str, object]:
    return {
        "qid": qid,
        field: identity,
        "independent_of_model_development": True,
        "source_evidence_reviewed": True,
        **_gold(),
    }


def test_audit_reports_empty_templates_as_blocked() -> None:
    selection = [{"qid": 1}, {"qid": 2}]
    empty_a = [{"qid": 1}, {"qid": 2}]
    empty_b = [{"qid": 1}, {"qid": 2}]
    empty_c = [
        {"qid": 1, "reviewed_disagreement_fields": []},
        {"qid": 2, "reviewed_disagreement_fields": []},
    ]

    audit = audit_independent_gold_packet(selection, empty_a, empty_b, empty_c)

    assert not audit.sealable
    assert audit.annotator_a_complete == 0
    assert "ANNOTATOR_A_INCOMPLETE:2" in audit.blockers
    assert "DISTINCT_REVIEWER_IDENTITIES_REQUIRED:0:3" in audit.blockers


def test_audit_accepts_complete_distinct_reviews() -> None:
    selection = [{"qid": 1}]
    a = [_annotation(1, "reviewer-a", "annotator_id")]
    b = [_annotation(1, "reviewer-b", "annotator_id")]
    c = [
        {
            **_annotation(1, "reviewer-c", "adjudicator_id"),
            "reviewed_disagreement_fields": [],
        }
    ]

    audit = audit_independent_gold_packet(selection, a, b, c)

    assert audit.sealable
    assert audit.to_dict()["status"] == "READY_TO_SEAL"
