from __future__ import annotations

import json
from pathlib import Path

from text2pandas.application.usecases.semantic_coverage import (
    ELIGIBLE,
    GAP,
    analyze_semantic_coverage,
)
from text2pandas.pipelines.retrieval.alias_store import load_aliases

ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "data" / "curated" / "evaluation" / "legacy" / "question_plans_1012.jsonl"
BASELINE = ROOT / "tests" / "fixtures" / "semantic_coverage_baseline.json"


def test_coverage_distinguishes_reviewed_routes_from_named_gaps() -> None:
    aliases = {"HPG": ["Tập đoàn Hòa Phát"], "VNM": ["Vinamilk"]}
    questions = [
        {"id": 1, "question": "Doanh thu HPG năm 2024 là bao nhiêu triệu đồng?"},
        {
            "id": 2,
            "question": "Biên lợi nhuận ròng HPG năm 2024 là bao nhiêu phần trăm?",
        },
        {"id": 3, "question": "Có bao nhiêu công ty HPG và VNM đạt mục tiêu năm 2024?"},
        {
            "id": 4,
            "question": "Tỷ lệ tiền mặt trên doanh thu HPG năm 2024 là bao nhiêu phần trăm?",
        },
    ]

    report = analyze_semantic_coverage(questions, aliases)

    assert [record.status for record in report.records] == [ELIGIBLE, ELIGIBLE, GAP, GAP]
    assert report.records[1].formula_id == "net_margin"
    assert report.records[2].reason == "ANSWER_REQUIRES_SINGLE_ENTITY:found=2"
    assert report.records[3].reason == "DIVIDE_REQUIRES_REVIEWED_FORMULA"
    assert report.summary()["scope"] == "semantic_route_only_no_retrieval_binding_or_accuracy"


def test_full_corpus_semantic_coverage_matches_reviewed_baseline() -> None:
    questions = [
        json.loads(line)
        for line in PLANS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    actual = analyze_semantic_coverage(questions, load_aliases("a6")).summary()
    expected = json.loads(BASELINE.read_text(encoding="utf-8"))

    assert actual == expected


def test_curated_winner_entity_does_not_hide_multi_entity_runtime_scope() -> None:
    questions = [
        {
            "id": 1,
            "question": "Trong nhóm HPG, HSG và NKG, công ty nào cao nhất năm 2024?",
            "entities": ["HSG"],
        }
    ]

    report = analyze_semantic_coverage(questions, {"HPG": [], "HSG": [], "NKG": []})

    assert report.records[0].reason == "MULTI_ENTITY_NOT_SUPPORTED:resolved=3"


def test_direct_money_average_requires_gold_compatible_entity_set() -> None:
    aliases = {"AAA": [], "BBB": [], "CCC": []}
    question = (
        "Giá trị trung bình thuế và các khoản phải nộp Nhà nước của AAA và BBB năm 2024 "
        "là bao nhiêu tỷ đồng?"
    )

    compatible = analyze_semantic_coverage(
        [{"id": 1, "question": question, "entities": ["BBB", "AAA"]}],
        aliases,
    )
    mismatch = analyze_semantic_coverage(
        [{"id": 1, "question": question, "entities": ["AAA", "BBB", "CCC"]}],
        aliases,
    )

    assert compatible.records[0].reason == "ELIGIBLE_TYPED_ENTITY_AVERAGE"
    assert mismatch.records[0].reason == "MULTI_ENTITY_NOT_SUPPORTED:expected=3"


def test_reviewed_entity_sum_requires_gold_compatible_entity_set() -> None:
    aliases = {"AAA": [], "BBB": [], "CCC": []}
    question = "Tổng chi phí tài chính của AAA và BBB năm 2024 là bao nhiêu tỷ đồng?"

    compatible = analyze_semantic_coverage(
        [{"id": 1, "question": question, "entities": ["BBB", "AAA"]}],
        aliases,
    )
    mismatch = analyze_semantic_coverage(
        [{"id": 1, "question": question, "entities": ["AAA", "BBB", "CCC"]}],
        aliases,
    )

    assert compatible.records[0].reason == "ELIGIBLE_TYPED_ENTITY_SUM"
    assert mismatch.records[0].reason == "MULTI_ENTITY_NOT_SUPPORTED:expected=3"
