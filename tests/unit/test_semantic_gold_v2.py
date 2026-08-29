from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from text2pandas.application.usecases.independent_gold import question_sha256
from text2pandas.application.usecases.semantic_gold_v2 import (
    BASIS_VALUES,
    FIELD_STATUSES,
    OPERAND_ROLES,
    OPERATIONS,
    OUTPUT_SHAPES,
    RECORD_STATUSES,
    UNIT_DIMENSIONS,
    annotation_templates,
    assert_full_frame_matches_components,
    build_contamination_ledger,
    canonical_packet_jsonl,
    canonical_semantic_frame,
    reject_prediction_fields,
    select_semantic_questions,
    validate_annotation_record,
    validate_reviewer_governance,
)

ROOT = Path(__file__).resolve().parents[2]


def _sampling() -> dict[str, object]:
    return {
        "headline_core": {"records": 4, "seed": "core"},
        "diagnostic_supplement": {
            "records": 3,
            "seed": "diagnostic",
            "strata": [
                {"id": "COUNT", "quota": 1, "patterns_any": ["co bao nhieu"]},
                {"id": "DIVIDE", "quota": 1, "patterns_any": ["chia cho"]},
                {"id": "BASIS", "quota": 1, "patterns_any": ["cong ty me"]},
            ],
        },
        "reserve": {"records": 2, "seed": "reserve"},
    }


def _questions() -> list[dict[str, object]]:
    texts = [
        "Có bao nhiêu công ty lãi năm 2024?",
        "Lợi nhuận chia cho doanh thu năm 2024?",
        "Doanh thu công ty mẹ AAA năm 2024?",
        "Doanh thu BBB năm 2024?",
        "Tài sản CCC năm 2024?",
        "Nợ phải trả DDD năm 2024?",
        "Vốn chủ sở hữu EEE năm 2024?",
        "Lợi nhuận FFF năm 2024?",
        "Tiền GGG năm 2024?",
        "Hàng tồn kho HHH năm 2024?",
        "Chi phí III năm 2024?",
        "Doanh thu JJJ năm 2024?",
        "Có bao nhiêu doanh nghiệp lãi năm 2023?",
        "Có bao nhiêu công ty lỗ năm 2022?",
        "Tài sản chia cho nợ phải trả năm 2024?",
        "Vốn chủ sở hữu chia cho tài sản năm 2023?",
        "Lợi nhuận công ty mẹ KKK năm 2024?",
        "Tài sản công ty mẹ LLL năm 2023?",
    ]
    return [{"id": index, "question": text} for index, text in enumerate(texts, 1)]


def _contract_bindings() -> dict[str, str]:
    return {
        "guideline_version": "semantic-gold-v2-guideline-draft-1",
        "guideline_sha256": "a" * 64,
        "metric_vocabulary_sha256": "b" * 64,
        "operation_vocabulary_sha256": "c" * 64,
    }


def _attestation() -> dict[str, object]:
    return {
        "independent_of_model_development": True,
        "blind_to_model_outputs": True,
        "source_evidence_reviewed": True,
        **_contract_bindings(),
    }


def _span(question: str, text: str) -> dict[str, object]:
    start = question.index(text)
    return {"text": text, "start": start, "end": start + len(text)}


def _resolved_lookup_record() -> dict[str, object]:
    question = "Doanh thu VNM năm 2024 là bao nhiêu tỷ đồng?"
    return {
        "schema_version": 2,
        "qid": 123,
        "question": question,
        "question_sha256": question_sha256(question),
        "cohort": "HEADLINE_CORE",
        "selection_digest": "d" * 64,
        "primary_stratum": None,
        "secondary_tags": [],
        "reviewer_slot": "A",
        "reviewer_id": "reviewer-a",
        "attestations": _attestation(),
        "record_status": "RESOLVED",
        "entities": [
            {
                "entity_ref": "e1",
                "mention": _span(question, "VNM"),
                "canonical_ref": "VNM",
                "resolution_status": "RESOLVED",
                "semantic_role": "REPORTING_ENTITY",
            }
        ],
        "metrics": [
            {
                "metric_ref": "m1",
                "phrase": _span(question, "Doanh thu"),
                "concept_id": "REVENUE",
                "concept_status": "RESOLVED",
                "reported_or_derived": "REPORTED",
                "definition_version": "semantic-metric-concepts-v1",
                "variant": None,
            }
        ],
        "periods": [
            {
                "period_ref": "p1",
                "year": 2024,
                "quarter": None,
                "point": "PERIOD",
                "role": "VALUE",
                "explicit": True,
            }
        ],
        "basis": {"value": "UNSPECIFIED", "explicit": False},
        "unit": {
            "dimension": "MONEY",
            "scale_exponent": 9,
            "currency": "VND",
            "explicit": True,
        },
        "operation_tree": {"node": "LOOKUP", "operands": ["o1"], "children": []},
        "output": {"shape": "SCALAR"},
        "operands": [
            {
                "operand_ref": "o1",
                "role": "VALUE",
                "metric_ref": "m1",
                "entity_ref": "e1",
                "period_ref": "p1",
                "basis": None,
                "unit": None,
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
            {
                "csv_path": None,
                "row_path": None,
                "col_label": None,
                "status": "NOT_LOCATED",
            }
        ],
        "ambiguity_alternatives": [],
        "adjudication": None,
        "notes": None,
    }


def _resolved_ratio_record() -> dict[str, object]:
    question = "Lợi nhuận chia cho doanh thu năm 2024?"
    record = _resolved_lookup_record()
    record.update(
        {
            "question": question,
            "question_sha256": question_sha256(question),
            "entities": [],
            "metrics": [
                {
                    "metric_ref": "m1",
                    "phrase": _span(question, "Lợi nhuận"),
                    "concept_id": "PROFIT_AFTER_TAX",
                    "concept_status": "RESOLVED",
                    "reported_or_derived": "REPORTED",
                    "definition_version": "semantic-metric-concepts-v1",
                    "variant": None,
                },
                {
                    "metric_ref": "m2",
                    "phrase": _span(question, "doanh thu"),
                    "concept_id": "REVENUE",
                    "concept_status": "RESOLVED",
                    "reported_or_derived": "REPORTED",
                    "definition_version": "semantic-metric-concepts-v1",
                    "variant": None,
                },
            ],
            "unit": {
                "dimension": "RATIO",
                "scale_exponent": None,
                "currency": None,
                "explicit": False,
            },
            "operation_tree": {
                "node": "DIVIDE",
                "operands": ["o1", "o2"],
                "children": [],
            },
            "operands": [
                {
                    "operand_ref": "o1",
                    "role": "NUMERATOR",
                    "metric_ref": "m1",
                    "entity_ref": None,
                    "period_ref": "p1",
                    "basis": None,
                    "unit": None,
                },
                {
                    "operand_ref": "o2",
                    "role": "DENOMINATOR",
                    "metric_ref": "m2",
                    "entity_ref": None,
                    "period_ref": "p1",
                    "basis": None,
                    "unit": None,
                },
            ],
        }
    )
    return record


def _assert_top_level_schema(record: dict[str, object]) -> None:
    schema: dict[str, object] = json.loads(
        (ROOT / "configs/evaluation/semantic_gold_v2_schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    required = set(schema["required"])
    properties = set(schema["properties"])
    assert required <= set(record)
    assert set(record) <= properties


def test_selection_is_deterministic_disjoint_and_prediction_blind() -> None:
    first = select_semantic_questions(
        _questions(), contaminated_qids=frozenset({12}), sampling=_sampling()
    )
    second = select_semantic_questions(
        _questions(), contaminated_qids=frozenset({12}), sampling=_sampling()
    )

    assert canonical_packet_jsonl(first.core) == canonical_packet_jsonl(second.core)
    assert canonical_packet_jsonl(first.diagnostic) == canonical_packet_jsonl(
        second.diagnostic
    )
    assert len(first.core) == 4
    assert len(first.diagnostic) == 3
    assert len(first.reserve) == 2
    qids = [int(row["qid"]) for row in (*first.core, *first.diagnostic, *first.reserve)]
    assert len(qids) == len(set(qids))
    assert 12 not in qids
    assert first.coverage["selection_uses_predictions"] is False
    assert first.coverage["model_outputs_included"] is False
    for row in (*first.core, *first.diagnostic, *first.reserve):
        reject_prediction_fields(row, "selection")


def test_contamination_ledger_keeps_source_and_reason_per_qid() -> None:
    ledger = build_contamination_ledger(
        {
            "a.jsonl": [{"qid": 2}, {"qid": 1}],
            "b.jsonl": [
                {"id": 2, "source": "test.py", "reason": "regression"},
                {"question_id": 3},
            ],
        },
        {"a.jsonl": "gold", "b.jsonl": "labels"},
    )

    assert ledger == (
        {"qid": 1, "source": "a.jsonl", "reason": "gold"},
        {"qid": 2, "source": "a.jsonl", "reason": "gold"},
        {"qid": 2, "source": "test.py", "reason": "regression"},
        {"qid": 3, "source": "b.jsonl", "reason": "labels"},
    )


def test_contamination_ledger_requires_reason_for_every_source() -> None:
    with pytest.raises(ValueError, match="exactly one reason"):
        build_contamination_ledger({"a.jsonl": [{"qid": 1}]}, {})


def test_templates_are_blank_and_bound_to_contracts() -> None:
    selected = select_semantic_questions(
        _questions(), contaminated_qids=frozenset({12}), sampling=_sampling()
    ).active

    rows = annotation_templates(
        selected, reviewer_slot="A", contract_hashes=_contract_bindings()
    )

    assert len(rows) == 7
    assert all(row["reviewer_id"] is None for row in rows)
    assert all(row["record_status"] is None for row in rows)
    assert all(row["metrics"] == [] for row in rows)
    assert all(row["attestations"]["guideline_sha256"] == "a" * 64 for row in rows)
    _assert_top_level_schema(rows[0])


@pytest.mark.parametrize(
    "field",
    [
        "answer",
        "model_ast",
        "predicted_answer",
        "retrieval_score",
        "selector_output",
        "v3_ast",
    ],
)
def test_prediction_fields_are_rejected_recursively(field: str) -> None:
    value = {"semantic": {field: {"value": 1}}}

    with pytest.raises(ValueError, match="prediction field leaked"):
        reject_prediction_fields(value, "bad")


def test_template_contract_bindings_must_be_exact() -> None:
    selected = select_semantic_questions(
        _questions(), contaminated_qids=frozenset({12}), sampling=_sampling()
    ).active
    incomplete = dict(_contract_bindings())
    incomplete.pop("guideline_version")

    with pytest.raises(ValueError, match="contract hashes"):
        annotation_templates(selected, reviewer_slot="A", contract_hashes=incomplete)


def test_resolved_record_passes_schema_relations_and_canonicalization() -> None:
    record = _resolved_lookup_record()

    _assert_top_level_schema(record)
    validate_annotation_record(record, require_complete=True)
    first = canonical_semantic_frame(record)
    second = canonical_semantic_frame(deepcopy(record))

    assert first == second
    assert "reviewer_id" not in first
    assert "source_evidence" not in first["components"]


@pytest.mark.parametrize("status", ["OK", "NOT_APPLICABLE", "resolved"])
def test_invalid_record_status_is_rejected(status: str) -> None:
    record = _resolved_lookup_record()
    record["record_status"] = status

    with pytest.raises(ValueError, match="invalid record status"):
        validate_annotation_record(record)


@pytest.mark.parametrize(
    ("start", "end", "text", "match"),
    [
        (-1, 3, "VNM", "non-negative"),
        (10, -1, "VNM", "non-negative"),
        (10, 9, "VNM", "greater than start"),
        (10, 999, "VNM", "exceeds question length"),
        (10, 13, "AAA", "does not match"),
    ],
)
def test_invalid_spans_are_rejected(
    start: int, end: int, text: str, match: str
) -> None:
    record = _resolved_lookup_record()
    record["entities"][0]["mention"] = {"text": text, "start": start, "end": end}

    with pytest.raises((TypeError, ValueError), match=match):
        validate_annotation_record(record)


def test_unstable_span_order_is_rejected() -> None:
    record = _resolved_ratio_record()
    record["metrics"] = list(reversed(record["metrics"]))

    with pytest.raises(ValueError, match="unstable metric span ordering"):
        validate_annotation_record(record)


def test_invalid_operation_is_rejected() -> None:
    record = _resolved_lookup_record()
    record["operation_tree"]["node"] = "MULTIPLY"

    with pytest.raises(ValueError, match="invalid operation"):
        validate_annotation_record(record)


def test_invalid_operand_reference_is_rejected() -> None:
    record = _resolved_lookup_record()
    record["operands"][0]["metric_ref"] = "m999"

    with pytest.raises(ValueError, match="invalid operand metric reference"):
        validate_annotation_record(record)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("basis", {"value": "CONSOLIDATED", "explicit": False}, "implicit basis"),
        (
            "unit",
            {
                "dimension": "PERCENT",
                "scale_exponent": 9,
                "currency": None,
                "explicit": True,
            },
            "non-money unit",
        ),
        ("output", {"shape": "RATIO"}, "invalid output shape"),
    ],
)
def test_invalid_basis_unit_and_output_are_rejected(
    field: str, value: object, match: str
) -> None:
    record = _resolved_lookup_record()
    record[field] = value

    with pytest.raises(ValueError, match=match):
        validate_annotation_record(record)


@pytest.mark.parametrize(
    "reviewers",
    [
        {"A": "same", "B": "same", "C": "c"},
        {"A": "same", "B": "b", "C": "same"},
        {"A": "a", "B": "same", "C": "same"},
    ],
)
def test_reviewer_roles_must_be_pairwise_distinct(
    reviewers: dict[str, str],
) -> None:
    attestations = {slot: _attestation() for slot in ("A", "B", "C")}

    with pytest.raises(ValueError, match="must be distinct"):
        validate_reviewer_governance(reviewers, attestations)


def test_missing_reviewer_attestation_is_rejected() -> None:
    attestations = {slot: _attestation() for slot in ("A", "B", "C")}
    attestations["B"].pop("blind_to_model_outputs")

    with pytest.raises(ValueError, match="missing attestations"):
        validate_reviewer_governance(
            {"A": "a", "B": "b", "C": "c"}, attestations
        )


def test_mismatched_reviewer_vocabulary_checksum_is_rejected() -> None:
    attestations = {slot: _attestation() for slot in ("A", "B", "C")}
    attestations["C"]["metric_vocabulary_sha256"] = "f" * 64

    with pytest.raises(ValueError, match="contract bindings differ"):
        validate_reviewer_governance(
            {"A": "a", "B": "b", "C": "c"}, attestations
        )


def test_unassigned_reviewer_roster_is_rejected() -> None:
    attestations = {slot: _attestation() for slot in ("A", "B", "C")}

    with pytest.raises(ValueError, match="not assigned"):
        validate_reviewer_governance(
            {"A": "UNASSIGNED", "B": "b", "C": "c"}, attestations
        )


def test_canonical_frame_preserves_operand_order() -> None:
    record = _resolved_ratio_record()
    original = canonical_semantic_frame(record)
    reordered = deepcopy(record)
    reordered["operands"] = list(reversed(reordered["operands"]))

    with pytest.raises(ValueError, match="full-frame/component mismatch"):
        assert_full_frame_matches_components(reordered, original)


def test_extra_operand_is_rejected() -> None:
    record = _resolved_lookup_record()
    extra = deepcopy(record["operands"][0])
    extra["operand_ref"] = "o2"
    record["operands"].append(extra)

    with pytest.raises(ValueError, match="operation tree/operand mismatch"):
        validate_annotation_record(record)


def test_missing_applicable_component_is_rejected() -> None:
    record = _resolved_lookup_record()
    del record["output"]

    with pytest.raises(ValueError, match="missing applicable semantic component"):
        canonical_semantic_frame(record)


def test_not_applicable_component_is_excluded_from_full_frame() -> None:
    record = _resolved_lookup_record()
    record["periods"] = []
    record["operands"][0]["period_ref"] = None
    record["field_status"]["periods"] = "NOT_APPLICABLE"

    frame = canonical_semantic_frame(record)

    assert "periods" not in frame["components"]
    assert "periods" not in frame["field_status"]


def test_manual_full_frame_is_forbidden_and_mismatch_is_rejected() -> None:
    record = _resolved_lookup_record()
    supplied = canonical_semantic_frame(record)
    supplied["components"]["output"] = {"shape": "ENTITY"}

    with pytest.raises(ValueError, match="full-frame/component mismatch"):
        assert_full_frame_matches_components(record, supplied)

    record["full_frame"] = supplied
    with pytest.raises(ValueError, match="must not supply"):
        validate_annotation_record(record)


def test_metric_vocabulary_has_reviewable_definitions_and_examples() -> None:
    vocabulary = yaml.safe_load(
        (ROOT / "configs/evaluation/semantic_metric_concepts_v1.yaml").read_text(
            encoding="utf-8"
        )
    )
    concepts = vocabulary["concepts"]
    assert concepts
    assert len({concept["id"] for concept in concepts}) == len(concepts)
    for concept in concepts:
        assert concept["definition_vi"].strip()
        assert concept["inclusion_examples_vi"]
        assert concept["exclusion_examples_vi"]
        authority_text = f"{concept['id']} {concept['definition_vi']}".casefold()
        assert not any(
            forbidden in authority_text
            for forbidden in ("silver row", "table id", "observation uid", "vas code")
        )


def test_operation_vocabulary_schema_and_validator_constants_agree() -> None:
    vocabulary = yaml.safe_load(
        (ROOT / "configs/evaluation/semantic_operation_vocabulary_v1.yaml").read_text(
            encoding="utf-8"
        )
    )
    schema = json.loads(
        (ROOT / "configs/evaluation/semantic_gold_v2_schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert set(vocabulary["record_statuses"]) == RECORD_STATUSES
    assert set(vocabulary["field_statuses"]) == FIELD_STATUSES
    assert set(vocabulary["bases"]) == BASIS_VALUES
    assert set(vocabulary["unit_dimensions"]) == UNIT_DIMENSIONS
    assert set(vocabulary["output_shapes"]) == OUTPUT_SHAPES
    assert set(vocabulary["operations"]) == OPERATIONS
    assert set(vocabulary["operand_roles"]) == OPERAND_ROLES
    assert set(schema["$defs"]["operation_tree"]["properties"]["node"]["enum"]) == OPERATIONS
    assert set(schema["$defs"]["operand"]["properties"]["role"]["enum"]) == OPERAND_ROLES


def test_selection_changes_when_question_text_changes() -> None:
    original = select_semantic_questions(
        _questions(), contaminated_qids=frozenset({12}), sampling=_sampling()
    )
    changed_questions = deepcopy(_questions())
    changed_questions[0]["question"] = "Có bao nhiêu doanh nghiệp lãi năm 2024?"
    changed = select_semantic_questions(
        changed_questions, contaminated_qids=frozenset({12}), sampling=_sampling()
    )

    original_by_qid = {
        int(row["qid"]): str(row["selection_digest"])
        for row in (*original.core, *original.diagnostic, *original.reserve)
    }
    changed_by_qid = {
        int(row["qid"]): str(row["selection_digest"])
        for row in (*changed.core, *changed.diagnostic, *changed.reserve)
    }
    if 1 in original_by_qid and 1 in changed_by_qid:
        assert original_by_qid[1] != changed_by_qid[1]
