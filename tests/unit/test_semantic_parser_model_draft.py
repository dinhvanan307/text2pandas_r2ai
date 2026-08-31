from __future__ import annotations

from text2pandas.application.usecases.semantic_parser_model_draft import (
    MODEL_DRAFT_STATUS,
    build_user_review_queue,
    compile_model_draft,
    generation_failure_draft,
    summarize_model_drafts,
)


def _scope() -> dict[str, object]:
    return {
        "qid": 1,
        "question": "Tổng tài sản VCB năm 2024 là bao nhiêu tỷ đồng?",
        "question_sha256": "question-sha",
        "family": "direct_lookup",
        "split": "development",
    }


def _frame() -> dict[str, object]:
    return {
        "entity_domain": ["VCB"],
        "period_domain": ["2024"],
        "basis": "unspecified",
        "metric_mentions": [
            {
                "mention_text": "Tổng tài sản",
                "metric_id": "total_assets",
                "semantic_role": "projection",
                "reported_or_derived": "reported",
            }
        ],
        "predicate_clauses": [],
        "logical_connectors": [],
        "temporal_transforms": [],
        "projection": {"metric_id": "total_assets"},
        "aggregate": None,
        "rank": None,
        "operation_order": ["lookup"],
        "expected_ast": {
            "expression": {
                "type": "metric_ref",
                "metric_id": "total_assets",
                "entities": ["VCB"],
                "periods": ["2024"],
                "basis": "unspecified",
                "expected_unit": {
                    "dimension": "money",
                    "scale_exponent": None,
                    "currency": None,
                },
            },
            "output": {
                "result_kind": "scalar",
                "rounding_digits": None,
                "unit": {
                    "dimension": "money",
                    "scale_exponent": 9,
                    "currency": "VND",
                },
            },
        },
        "output_dimension": "money",
        "ambiguity": {"status": "NONE", "notes": None},
    }


def test_compile_model_draft_is_reviewable_but_not_gold() -> None:
    draft = compile_model_draft(
        _scope(),
        {
            "structural_status": "OK",
            "complexity_class": "direct",
            "composition_frame": _frame(),
            "notes": None,
        },
        {"model_id": "test-model", "attempt_count": 1},
    )

    assert draft["review_status"] == MODEL_DRAFT_STATUS
    assert draft["independent_human_gold"] is False
    assert draft["composition_frame"]["metric_mentions"][0]["start"] == 0
    assert draft["composition_frame"]["expected_ast"]["schema_version"] == 3


def test_compile_model_draft_infers_complexity_from_validated_ast() -> None:
    draft = compile_model_draft(
        _scope(),
        {
            "structural_status": "OK",
            "complexity_class": "compositional",
            "composition_frame": _frame(),
            "notes": None,
        },
        {"model_id": "test-model"},
    )

    assert draft["complexity_class"] == "direct"
    assert draft["compiler_adjustments"] == ["INFER_COMPLEXITY_FROM_AST:compositional->direct"]


def test_compile_model_draft_aligns_unaccented_metric_mention() -> None:
    frame = _frame()
    frame["metric_mentions"][0]["mention_text"] = "tong tai san"

    draft = compile_model_draft(
        _scope(),
        {
            "structural_status": "OK",
            "complexity_class": "direct",
            "composition_frame": frame,
            "notes": None,
        },
        {"model_id": "test-model"},
    )

    mention = draft["composition_frame"]["metric_mentions"][0]
    assert mention["mention_text"] == "Tổng tài sản"
    assert mention["start"] == 0


def test_compile_model_draft_rejects_unused_metric_mentions() -> None:
    frame = _frame()
    frame["metric_mentions"].append(
        {
            "mention_text": "năm 2024",
            "metric_id": "reported_unused",
            "semantic_role": "qualifier",
            "reported_or_derived": "reported",
        }
    )

    try:
        compile_model_draft(
            _scope(),
            {
                "structural_status": "OK",
                "complexity_class": "direct",
                "composition_frame": frame,
                "notes": None,
            },
            {"model_id": "test-model"},
        )
    except ValueError as error:
        assert "not referenced" in str(error)
    else:
        raise AssertionError("unused metric mention must fail closed")


def test_generation_failure_remains_unresolved_silver() -> None:
    draft = generation_failure_draft(_scope(), {"model_id": "test-model"}, "bad JSON")
    queue = build_user_review_queue([draft])
    summary = summarize_model_drafts([draft])

    assert draft["structural_status"] == "UNRESOLVED"
    assert draft["composition_frame"]["expected_ast"] is None
    assert queue[0]["review_decision"] is None
    assert summary["correctness"] == "NOT_MEASURED"
    assert summary["independent_gold"] is False
