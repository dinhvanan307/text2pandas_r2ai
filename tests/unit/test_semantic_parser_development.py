from __future__ import annotations

from text2pandas.application.usecases.semantic_parser_development import (
    build_development_records,
    summarize_development_records,
)


def _scope() -> list[dict[str, object]]:
    return [
        {
            "qid": 1,
            "question": "Q1?",
            "question_sha256": "q1",
            "family": "direct_lookup",
            "split": "development",
        },
        {
            "qid": 2,
            "question": "Q2?",
            "question_sha256": "q2",
            "family": "direct_lookup",
            "split": "holdout",
        },
    ]


def _review() -> list[dict[str, object]]:
    return [
        {"qid": 1, "decision": "ACCEPT", "semantic_structure": "lookup"},
        {"qid": 2, "decision": "CORRECT", "semantic_structure": "ratio"},
    ]


def _prediction(status: str, *, ast: dict[str, object] | None) -> dict[str, object]:
    candidate = {
        "status": status,
        "reason": None if ast else "METRIC_UNRESOLVED",
        "ast": ast,
        "predicted_ast_profile": None,
    }
    return {
        "qid": 1,
        "question": "Q1?",
        "annotations": {
            "entities": ["AAA"],
            "periods": ["2024"],
            "basis": "unspecified",
        },
        "candidates": [candidate],
    }


def test_development_checkpoint_keeps_prediction_separate_from_gold() -> None:
    ast = {
        "schema_version": 3,
        "qid": 1,
        "question": "Q1?",
        "expression": {
            "type": "metric_ref",
            "metric_id": "total_assets",
            "entities": ["AAA"],
            "periods": ["2024"],
            "basis": "unspecified",
            "statement_types": [],
            "expected_unit": None,
            "period_semantics": "unknown",
            "qualifiers": [],
            "required_context_phrases": [],
        },
        "output": {
            "result_kind": "scalar",
            "unit": {"dimension": "money", "scale_exponent": 9, "currency": None},
            "rounding_digits": None,
        },
        "diagnostics": [],
    }
    records = build_development_records(
        _scope(),
        _review(),
        [_prediction("ABSTAIN", ast=None)],
        [_prediction("OK", ast=ast)],
    )

    assert len(records) == 1
    assert records[0]["correctness"] == "NOT_MEASURED"
    assert records[0]["promotion_eligible"] is False
    candidate = records[0]["candidate"]
    assert candidate["ast_state"] == "FULL_QUESTION_AST_CANDIDATE"
    assert candidate["composition_frame_candidate"]["expected_ast"] == ast
    summary = summarize_development_records(records)
    assert summary["full_question_ast_candidates"] == 1
    assert summary["independent_gold"] is False
