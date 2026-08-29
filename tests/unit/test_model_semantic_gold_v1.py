from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from text2pandas.application.usecases.model_semantic_gold_v1 import (
    ModelGoldValidationError,
    canonical_json_bytes,
    canonicalize_record,
    compile_model_response,
    evaluate_canonical_predictions,
    generation_failure_record,
    json_schema_errors,
    reject_forbidden_fields,
    validate_model_gold_record,
)

ROOT = Path(__file__).resolve().parents[2]


def _selection() -> dict[str, object]:
    question = "Tổng tài sản của STB là bao nhiêu triệu đồng vào cuối năm 2016?"
    return {
        "qid": 44,
        "question": question,
        "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
        "cohort": "DIAGNOSTIC_SUPPLEMENT",
        "selection_digest": "1" * 64,
        "primary_stratum": "UNIT_SCALE_SENSITIVE",
        "secondary_tags": ["UNIT_SCALE_SENSITIVE"],
    }


def _unit() -> dict[str, object]:
    return {
        "dimension": "MONEY",
        "scale_exponent": 6,
        "currency": "VND",
        "explicit": True,
    }


def _response() -> dict[str, object]:
    return {
        "entities": [
            {
                "entity_ref": "e1",
                "mention_text": "STB",
                "canonical_ref": "STB",
                "resolution_status": "RESOLVED",
                "entity_type": "COMPANY",
                "semantic_role": "REPORTING_ENTITY",
            }
        ],
        "metrics": [
            {
                "metric_ref": "m1",
                "phrase_text": "Tổng tài sản",
                "concept_id": "TOTAL_ASSETS",
                "concept_status": "RESOLVED",
                "reported_or_derived": "REPORTED",
                "definition_version": "semantic-metric-concepts-model-v1",
                "variant": None,
            }
        ],
        "periods": [
            {
                "period_ref": "p1",
                "mention_text": "2016",
                "year": 2016,
                "quarter": None,
                "date": None,
                "point": "CLOSING",
                "role": "VALUE",
                "explicit": True,
            }
        ],
        "basis": {"value": "UNSPECIFIED", "explicit": False},
        "unit": _unit(),
        "operation_tree": {
            "node_id": "n1",
            "node": "LOOKUP",
            "inputs": [
                {"role": "VALUE", "source_kind": "OPERAND", "source_ref": "o1"}
            ],
            "children": [],
        },
        "output": {"shape": "SCALAR"},
        "operands": [
            {
                "operand_ref": "o1",
                "role": "VALUE",
                "metric_ref": "m1",
                "entity_ref": "e1",
                "period_ref": "p1",
                "basis": {"value": "UNSPECIFIED", "explicit": False},
                "unit": _unit(),
                "literal": None,
            }
        ],
        "field_status": {
            "entities": "RESOLVED",
            "metrics": "RESOLVED",
            "periods": "RESOLVED",
            "basis": "RESOLVED",
            "unit": "RESOLVED",
            "operation_tree": "RESOLVED",
            "output": "RESOLVED",
            "operands": "RESOLVED",
        },
        "source_evidence": [
            {"source_path": None, "context_label": None, "status": "NOT_APPLICABLE"}
        ],
        "ambiguity_alternatives": [],
        "notes": None,
    }


def _generation() -> dict[str, object]:
    return {
        "gold_mode": "MODEL_GOLD",
        "annotation_source": "LLM",
        "human_review": False,
        "cross_model_review": False,
        "model_id": "qwen2.5:14b",
        "model_digest": "sha256:model",
        "prompt_version": "model-semantic-gold-prompt-v1",
        "prompt_sha256": "2" * 64,
        "response_sha256": "3" * 64,
        "attempt_count": 1,
    }


def _operation_specs() -> dict[str, object]:
    path = ROOT / "configs/evaluation/semantic_operation_vocabulary_model_v1.yaml"
    return dict(yaml.safe_load(path.read_text(encoding="utf-8"))["operations"])


def _concept_ids() -> frozenset[str]:
    path = ROOT / "configs/evaluation/semantic_metric_concepts_v1.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return frozenset(str(item["id"]) for item in raw["concepts"])


def _record() -> dict[str, object]:
    return compile_model_response(_selection(), _response(), _generation())


def test_model_response_schema_accepts_valid_draft() -> None:
    schema_path = ROOT / "configs/evaluation/model_semantic_gold_response_v1_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert json_schema_errors(_response(), schema) == []


def test_compile_derives_exact_spans_and_record_status() -> None:
    record = _record()
    assert record["record_status"] == "RESOLVED"
    assert record["status_reason"] is None
    assert record["entities"][0]["mention"] == {"text": "STB", "start": 17, "end": 20}
    assert record["metrics"][0]["phrase"] == {
        "text": "Tổng tài sản",
        "start": 0,
        "end": 12,
    }


def test_semantic_validator_accepts_closed_lookup() -> None:
    validate_model_gold_record(
        _record(),
        _selection(),
        metric_concept_ids=_concept_ids(),
        operation_specs=_operation_specs(),
    )


def test_forbidden_prediction_field_fails_closed_at_any_depth() -> None:
    with pytest.raises(ModelGoldValidationError, match="parser_prediction"):
        reject_forbidden_fields(
            {"safe": [{"parser_prediction": {"node": "LOOKUP"}}]},
            location="response",
        )


def test_directional_operation_arity_and_roles_are_enforced() -> None:
    record = _record()
    tree = record["operation_tree"]
    assert isinstance(tree, dict)
    tree["node"] = "SUBTRACT"
    with pytest.raises(ModelGoldValidationError, match="roles must be"):
        validate_model_gold_record(
            record,
            _selection(),
            metric_concept_ids=_concept_ids(),
            operation_specs=_operation_specs(),
        )


def test_question_cannot_hide_operation_as_not_applicable() -> None:
    record = _record()
    record["operation_tree"] = None
    record["output"] = None
    record["field_status"]["operation_tree"] = "NOT_APPLICABLE"
    record["field_status"]["output"] = "NOT_APPLICABLE"
    with pytest.raises(ModelGoldValidationError, match="cannot be NOT_APPLICABLE"):
        validate_model_gold_record(
            record,
            _selection(),
            metric_concept_ids=_concept_ids(),
            operation_specs=_operation_specs(),
        )


def test_other_reported_metric_requires_stable_variant() -> None:
    record = _record()
    record["metrics"][0]["concept_id"] = "OTHER_REPORTED_METRIC"
    with pytest.raises(ModelGoldValidationError, match="requires variant"):
        validate_model_gold_record(
            record,
            _selection(),
            metric_concept_ids=_concept_ids(),
            operation_specs=_operation_specs(),
        )


def test_canonicalization_is_byte_identical_and_removes_provenance() -> None:
    first = canonicalize_record(_record())
    second = canonicalize_record(copy.deepcopy(_record()))
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert "generation" not in first
    assert "source_evidence" not in first
    assert "notes" not in first


def test_generation_failure_preserves_qid_as_explicit_unresolved() -> None:
    record = generation_failure_record(_selection(), _generation(), "invalid JSON")
    assert record["qid"] == 44
    assert record["record_status"] == "UNRESOLVED"
    assert record["status_reason"] == "GENERATION_FAILURE"
    validate_model_gold_record(
        record,
        _selection(),
        metric_concept_ids=_concept_ids(),
        operation_specs=_operation_specs(),
    )


def test_all_fourteen_evaluator_metrics_accept_gold_self_replay() -> None:
    frame = canonicalize_record(_record())
    result = evaluate_canonical_predictions([frame], [copy.deepcopy(frame)])
    assert len(result.metrics) == 14
    assert not result.missing_prediction_qids
    assert not result.extra_prediction_qids
    assert all(metric.accuracy == 1.0 for metric in result.metrics.values())
