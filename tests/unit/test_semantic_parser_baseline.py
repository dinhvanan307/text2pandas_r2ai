from __future__ import annotations

from text2pandas.application.parsing import SemanticParser
from text2pandas.application.usecases.semantic_parser_baseline import (
    build_semantic_parser_record,
    summarize_semantic_parser_records,
)
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.semantic import LegacyVietnameseAnnotator


def _parser() -> SemanticParser:
    return SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator({"VCB": "VCB", "BID": "BID"}),
    )


def test_parser_baseline_record_is_prediction_only_and_profiles_direct_ast() -> None:
    record = build_semantic_parser_record(
        _parser(),
        "Tổng tài sản VCB năm 2024 là bao nhiêu tỷ đồng?",
        qid=1,
    )

    assert record["measurement_scope"] == "PREDICTED_STRUCTURE_ONLY_NOT_GOLD"
    assert record["primary_status"] == "OK"
    assert record["any_candidate_ok"] is True
    candidate = record["candidates"][0]
    assert candidate["predicted_ast_profile"]["complexity"] == "direct"


def test_parser_baseline_profiles_nested_filter_average_as_compositional() -> None:
    record = build_semantic_parser_record(
        _parser(),
        "Trong nhóm VCB và BID, xét các ngân hàng có lợi nhuận sau thuế lớn hơn "
        "0 tỷ đồng, tổng tài sản bình quân là bao nhiêu tỷ đồng?",
        qid=2,
    )

    ok_candidates = [value for value in record["candidates"] if value["status"] == "OK"]
    assert ok_candidates
    profile = ok_candidates[0]["predicted_ast_profile"]
    assert profile["complexity"] == "compositional"
    assert {"aggregated", "filtered", "predicate"} <= set(profile["layers"])


def test_parser_baseline_summary_does_not_claim_correctness() -> None:
    records = [
        build_semantic_parser_record(
            _parser(),
            "Tổng tài sản VCB năm 2024 là bao nhiêu tỷ đồng?",
            qid=1,
        )
    ]

    summary = summarize_semantic_parser_records(records)

    assert summary["records"] == 1
    assert summary["any_candidate_ok"] == 1
    assert summary["correctness"] == "NOT_MEASURED"
