from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from text2pandas.application.usecases.independent_gold import question_sha256
from text2pandas.application.usecases.semantic_gold_v2 import (
    canonical_packet_jsonl,
    canonical_semantic_frame,
    validate_annotation_record,
)
from text2pandas.application.usecases.semantic_gold_v2_local import (
    LOCAL_PROVENANCE,
    LocalSchemaValidationError,
    build_local_synthetic_annotation,
    evaluate_local_predictions,
    export_canonical_v2_prediction,
    validate_json_schema_instance,
    validate_local_provenance,
)

ROOT = Path(__file__).resolve().parents[2]


def _selected(question: str, *, qid: int = 123) -> dict[str, object]:
    return {
        "schema_version": 2,
        "qid": qid,
        "question": question,
        "question_sha256": question_sha256(question),
        "cohort": "HEADLINE_CORE",
        "selection_digest": "d" * 64,
        "primary_stratum": None,
        "secondary_tags": [],
    }


def _contracts() -> dict[str, str]:
    return {
        "guideline_version": "semantic-gold-v2-guideline-draft-1",
        "guideline_sha256": "a" * 64,
        "metric_vocabulary_sha256": "b" * 64,
        "operation_vocabulary_sha256": "c" * 64,
    }


def _vocabulary() -> dict[str, object]:
    return {
        "concepts": [
            {
                "id": "REVENUE",
                "inclusion_examples_vi": ["doanh thu"],
            },
            {
                "id": "NET_REVENUE",
                "inclusion_examples_vi": ["doanh thu thuần"],
            },
        ]
    }


def test_local_provenance_is_exact_and_non_official() -> None:
    validate_local_provenance(LOCAL_PROVENANCE)
    changed = dict(LOCAL_PROVENANCE)
    changed["independent_review"] = True

    with pytest.raises(ValueError, match="non-independent"):
        validate_local_provenance(changed)


def test_synthetic_annotation_is_schema_valid_and_ontology_exact() -> None:
    question = "Doanh thu VNM năm 2024 là bao nhiêu tỷ đồng?"
    observed = build_local_synthetic_annotation(
        _selected(question),
        aliases={"VNM": ["Công ty Cổ phần Sữa Việt Nam"]},
        metric_vocabulary=_vocabulary(),
        contract_hashes=_contracts(),
    )
    annotation = observed.annotation

    schema = json.loads(
        (ROOT / "configs/evaluation/semantic_gold_v2_schema.json").read_text(
            encoding="utf-8"
        )
    )
    validate_json_schema_instance(annotation, schema)
    validate_annotation_record(annotation, require_complete=True)
    assert annotation["record_status"] == "RESOLVED"
    assert annotation["metrics"][0]["concept_id"] == "REVENUE"
    assert annotation["metrics"][0]["phrase"] == {
        "text": "Doanh thu",
        "start": 0,
        "end": 9,
    }
    assert annotation["attestations"]["independent_of_model_development"] is False
    assert canonical_semantic_frame(annotation)["record_status"] == "RESOLVED"

    invalid = dict(annotation)
    invalid["unknown_schema_field"] = True
    with pytest.raises(LocalSchemaValidationError, match="additional property"):
        validate_json_schema_instance(invalid, schema)


def test_maximal_metric_phrase_does_not_invent_overlapping_short_concept() -> None:
    question = "Doanh thu thuần VNM năm 2024 là bao nhiêu tỷ đồng?"
    annotation = build_local_synthetic_annotation(
        _selected(question),
        aliases={"VNM": ["Công ty Cổ phần Sữa Việt Nam"]},
        metric_vocabulary=_vocabulary(),
        contract_hashes=_contracts(),
    ).annotation

    assert [row["concept_id"] for row in annotation["metrics"]] == ["NET_REVENUE"]
    assert annotation["metrics"][0]["phrase"]["text"] == "Doanh thu thuần"


def test_unmatched_metric_is_unresolved_instead_of_invented() -> None:
    question = "Giá trị thương hiệu VNM năm 2024 là bao nhiêu tỷ đồng?"
    annotation = build_local_synthetic_annotation(
        _selected(question),
        aliases={"VNM": ["Công ty Cổ phần Sữa Việt Nam"]},
        metric_vocabulary=_vocabulary(),
        contract_hashes=_contracts(),
    ).annotation

    assert annotation["record_status"] == "UNRESOLVED"
    assert annotation["field_status"]["metrics"] == "UNRESOLVED"
    assert annotation["metrics"] == []


def test_same_span_claimed_by_two_concepts_is_unresolved() -> None:
    question = "Doanh thu VNM năm 2024 là bao nhiêu tỷ đồng?"
    vocabulary = {
        "concepts": [
            {"id": "REVENUE", "inclusion_examples_vi": ["doanh thu"]},
            {"id": "CONFLICTING_REVENUE", "inclusion_examples_vi": ["doanh thu"]},
        ]
    }
    annotation = build_local_synthetic_annotation(
        _selected(question),
        aliases={"VNM": ["Công ty Cổ phần Sữa Việt Nam"]},
        metric_vocabulary=vocabulary,
        contract_hashes=_contracts(),
    ).annotation

    assert annotation["record_status"] == "UNRESOLVED"
    assert annotation["field_status"]["metrics"] == "UNRESOLVED"
    assert annotation["metrics"] == []


def test_prediction_export_does_not_promote_ontology_or_vas_hint_to_concept() -> None:
    question = "Doanh thu thuần VNM năm 2024 là bao nhiêu tỷ đồng?"
    prediction = export_canonical_v2_prediction(
        _selected(question),
        aliases={"VNM": ["Công ty Cổ phần Sữa Việt Nam"]},
        metric_vocabulary=_vocabulary(),
        contract_hashes=_contracts(),
        implementation_fingerprint="f" * 64,
    )

    assert prediction["semantic"]["metrics"] == []
    assert prediction["semantic"]["field_status"]["metrics"] == "UNRESOLVED"
    assert "metrics" in prediction["missing_fields"]
    assert prediction["vas_metric_code_hints"] == ["10"]


def test_evaluator_counts_missing_metric_output_wrong_and_taxonomizes_it() -> None:
    question = "Doanh thu VNM năm 2024 là bao nhiêu tỷ đồng?"
    selected = _selected(question)
    annotation = build_local_synthetic_annotation(
        selected,
        aliases={"VNM": ["Công ty Cổ phần Sữa Việt Nam"]},
        metric_vocabulary=_vocabulary(),
        contract_hashes=_contracts(),
    ).annotation
    prediction = export_canonical_v2_prediction(
        selected,
        aliases={"VNM": ["Công ty Cổ phần Sữa Việt Nam"]},
        metric_vocabulary=_vocabulary(),
        contract_hashes=_contracts(),
        implementation_fingerprint="f" * 64,
    )

    metrics, failures = evaluate_local_predictions([annotation], [prediction])
    rows = {
        row["metric"]: row
        for row in metrics["views"]["HEADLINE_CORE"]["metrics"]
    }
    assert rows["Entity Reference Accuracy"]["accuracy"] == 1.0
    assert rows["Metric Concept Accuracy"]["accuracy"] == 0.0
    assert rows["Full Semantic Frame Exact"]["accuracy"] == 0.0
    assert failures[0]["primary_failure"] == "MISSING_OUTPUT"
    assert failures[0]["boundary"] == "PARSER"


def test_generation_is_byte_deterministic() -> None:
    vocabulary = yaml.safe_load(
        (ROOT / "configs/evaluation/semantic_metric_concepts_v1.yaml").read_text(
            encoding="utf-8"
        )
    )
    selected = _selected("Doanh thu VNM năm 2024 là bao nhiêu tỷ đồng?")
    kwargs = {
        "aliases": {"VNM": ["Công ty Cổ phần Sữa Việt Nam"]},
        "metric_vocabulary": vocabulary,
        "contract_hashes": _contracts(),
    }
    first = build_local_synthetic_annotation(selected, **kwargs).annotation
    second = build_local_synthetic_annotation(selected, **kwargs).annotation

    assert canonical_packet_jsonl([first]) == canonical_packet_jsonl([second])
