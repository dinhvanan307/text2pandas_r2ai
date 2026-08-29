from __future__ import annotations

from copy import deepcopy

import pytest

from text2pandas.application.usecases.semantic_gold_v2 import (
    annotation_templates,
    build_contamination_ledger,
    canonical_packet_jsonl,
    reject_prediction_fields,
    select_semantic_questions,
)


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
    ]
    return [{"id": index, "question": text} for index, text in enumerate(texts, 1)]


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
    for row in (*first.core, *first.diagnostic, *first.reserve):
        reject_prediction_fields(row, "selection")


def test_contamination_ledger_keeps_all_sources_per_qid() -> None:
    ledger = build_contamination_ledger(
        {
            "a.jsonl": [{"qid": 2}, {"qid": 1}],
            "b.jsonl": [{"id": 2}, {"question_id": 3}],
        }
    )

    assert ledger == (
        {"qid": 1, "sources": ["a.jsonl"]},
        {"qid": 2, "sources": ["a.jsonl", "b.jsonl"]},
        {"qid": 3, "sources": ["b.jsonl"]},
    )


def test_templates_are_blank_and_bound_to_contract_hashes() -> None:
    selected = select_semantic_questions(
        _questions(), contaminated_qids=frozenset({12}), sampling=_sampling()
    ).active
    hashes = {
        "guideline_sha256": "a" * 64,
        "metric_vocabulary_sha256": "b" * 64,
        "operation_vocabulary_sha256": "c" * 64,
    }

    rows = annotation_templates(selected, reviewer_slot="A", contract_hashes=hashes)

    assert len(rows) == 7
    assert all(row["reviewer_id"] is None for row in rows)
    assert all(row["record_status"] is None for row in rows)
    assert all(row["metrics"] == [] for row in rows)
    assert all(row["attestations"]["guideline_sha256"] == "a" * 64 for row in rows)


def test_prediction_field_is_rejected_recursively() -> None:
    value = {"semantic": {"model_ast": {"node": "Lookup"}}}

    with pytest.raises(ValueError, match="prediction field leaked"):
        reject_prediction_fields(value, "bad")


def test_template_contract_hashes_must_be_exact() -> None:
    selected = select_semantic_questions(
        _questions(), contaminated_qids=frozenset({12}), sampling=_sampling()
    ).active
    incomplete = {
        "guideline_sha256": "a" * 64,
        "metric_vocabulary_sha256": "b" * 64,
    }

    with pytest.raises(ValueError, match="contract hashes"):
        annotation_templates(selected, reviewer_slot="A", contract_hashes=incomplete)


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
