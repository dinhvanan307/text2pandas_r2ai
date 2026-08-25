"""Semantic gold: artifact integrity + the parser fixes it drove.

The gold set is `data/curated/gold/semantic_gold.jsonl`, produced by TWO INDEPENDENT
MODEL PASSES with disjoint context. That is deliberately NOT called a human
blinded recheck: two runs of one model share a prior, so their agreement bounds
reliability from above and is not evidence of correctness. Every test here
respects that -- fields the two passes disagreed on are never used as a target.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "measure_v4"))

import pytest  # noqa: E402

GOLD_DIR = ROOT / "data" / "gold"
GOLD = GOLD_DIR / "semantic_gold.jsonl"

from text2pandas.answer_pipeline.frame import (  # noqa: E402
    DEFAULT_BASIS, classify_operation, extract_basis, extract_entities,
    extract_entity, extract_periods, resolve_basis,
)

pytestmark = pytest.mark.skipif(not GOLD.exists(), reason="semantic gold not built")


def load(name):
    p = GOLD_DIR / name
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


# ------------------------------------------------------- artifact integrity
def test_gold_has_forty_unique_cases():
    g = load("semantic_gold.jsonl")
    assert len(g) == 40
    assert len({r["qid"] for r in g}) == 40


def test_every_record_declares_its_status():
    for r in load("semantic_gold.jsonl"):
        assert r["annotation_status"] in {"RESOLVED", "AMBIGUOUS", "UNRESOLVED"}


def test_non_resolved_records_carry_a_reason():
    for r in load("semantic_gold.jsonl"):
        if r["annotation_status"] != "RESOLVED":
            has_note = bool((r.get("annotator_notes") or "").strip())
            has_disagreement = bool(r["agreement"]["fields_disagreed"])
            assert has_note or has_disagreement, r["qid"]


def test_method_is_labelled_honestly():
    """The artifact must never claim a human blinded recheck."""
    for r in load("semantic_gold.jsonl"):
        a = r["agreement"]
        assert a["method"] == "two_independent_model_passes_disjoint_context"
        assert a["NOT"] == "human_blinded_recheck"
    cov = json.loads((GOLD_DIR / "field_coverage.json").read_text(encoding="utf-8"))
    assert "NOT a human blinded recheck" in cov["method_caveat"]


def test_disagreed_fields_are_not_offered_as_gold():
    """A field the two passes disagreed on must be excluded from scoring."""
    for r in load("semantic_gold.jsonl"):
        usable = set(r["gold_usable_fields"])
        disagreed = set(r["agreement"]["fields_disagreed"])
        assert not (usable & disagreed), r["qid"]


def test_no_gold_field_was_copied_from_a_prediction():
    """Structural guard: gold records must not carry prediction-shaped keys."""
    banned = {"parser_operation", "parser_basis", "parser_unit", "answer",
              "pandas_query", "evidence", "parent_answer"}
    for r in load("semantic_gold.jsonl"):
        assert not (banned & set(r)), (r["qid"], banned & set(r))


def test_numerator_and_denominator_never_share_a_metric():
    for r in load("semantic_gold.jsonl"):
        by_role = {}
        for o in r.get("operand_specs") or []:
            by_role.setdefault(o.get("role"), []).append(o.get("metric_id"))
        num, den = by_role.get("numerator"), by_role.get("denominator")
        if num and den and num[0] and den[0]:
            assert num[0] != den[0], r["qid"]


def test_coverage_matrix_hits_every_required_category():
    m = json.loads((GOLD_DIR / "coverage_matrix.json").read_text(encoding="utf-8"))
    for name, c in m["categories"].items():
        assert len(c["selected"]) >= c["required"], name


def test_disagreement_log_matches_the_gold_records():
    logged = {(d["qid"], d["field"]) for d in load("disagreement_log.jsonl")
              if d["field"] != "__presence__"}
    declared = {(r["qid"], f) for r in load("semantic_gold.jsonl")
                for f in r["agreement"]["fields_disagreed"]}
    assert logged == declared


# ---------------------------------------- parser fixes measured against gold
def test_year_ranges_expand():
    """REGRESSION: 'giai đoạn 2021-2024' names four years. Gold-measured:
    period exact-match 0.862 -> 0.966."""
    assert set(extract_periods("Trong giai đoạn 2021-2024, doanh thu ...")) == \
        {"2021", "2022", "2023", "2024"}
    assert set(extract_periods("Trong giai đoạn 2021–2022 ...")) == {"2021", "2022"}


def test_year_range_is_not_expanded_absurdly():
    assert extract_periods("từ 1990-2050") == ("1990", "2050")


def test_basis_has_an_explicit_unmarked_default():
    """REGRESSION: a question that says nothing means consolidated, and the
    parser must report that it DEFAULTED rather than read it."""
    assert resolve_basis("Doanh thu năm 2023 của HPG?") == (DEFAULT_BASIS, False)
    assert resolve_basis("Doanh thu công ty mẹ HPG 2023?") == ("separate", True)
    assert resolve_basis("Doanh thu hợp nhất HPG 2023?") == ("consolidated", True)
    assert extract_basis("Doanh thu năm 2023?") is None, "raw reader must stay honest"


def test_multi_entity_extraction():
    """REGRESSION: a four-company comparison has four entities, not one.
    Gold-measured: entity-set exact match 0.425 -> 0.950."""
    assert extract_entities("Trong nhóm HPG, HSG và NKG năm 2024") == ("HPG", "HSG", "NKG")
    assert extract_entity("Trong nhóm HPG, HSG và NKG năm 2024") == "HPG"


def test_entity_stopwords_are_not_tickers():
    for noise in ("Ngân hàng TMCP Nam Á", "CTCP Chứng khoán FPT có ROE",
                  "doanh thu tính bằng VND", "chỉ số EPS và ROA"):
        assert "TMCP" not in extract_entities(noise)
        assert "CTCP" not in extract_entities(noise)
        assert "VND" not in extract_entities(noise)
        assert "ROE" not in extract_entities(noise)


@pytest.mark.parametrize("q,expected", [
    # a superlative marks the OUTER operation; an inner change word does not
    ("Năm nào có mức tăng doanh thu cao nhất?", "EXTREMUM"),
    ("Năm nào có tỷ lệ nợ xấu thấp nhất?", "EXTREMUM"),
    # cardinality questions
    ("Có bao nhiêu công ty đạt lợi nhuận dương năm 2024?", "COUNT"),
    ("Số lượng doanh nghiệp có ROE trên 15% là bao nhiêu?", "COUNT"),
    # "Tổng cộng X" is the NAME of a reported line, not an instruction to add
    ("Tổng cộng tài sản cuối năm 2025 là bao nhiêu?", "LOOKUP"),
    ("Giá trị lợi thế thương mại (tổng cộng) là bao nhiêu?", "LOOKUP"),
    # a real enumeration is a SUM
    ("Tổng doanh thu năm 2021 và năm 2022 là bao nhiêu?", "SUM"),
    # earlier regressions must hold
    ("Chênh lệch tỷ lệ nợ xấu 2023 so với 2022 là bao nhiêu điểm phần trăm?", "SUBTRACT"),
    ("Tỷ lệ nợ xấu trên tổng dư nợ năm 2023 là bao nhiêu %?", "DIVIDE"),
    ("Tăng trưởng doanh thu 2023 so với 2022 là bao nhiêu %?", "GROWTH"),
])
def test_operation_precedence_after_gold_fixes(q, expected):
    """Gold-measured: operation family (lenient) 0.450 -> 0.825."""
    assert classify_operation(q).op == expected


def test_count_is_declared_unsupported_not_silently_routed():
    """COUNT is detected but has no IR yet -- it must abstain loudly."""
    from text2pandas.answer_pipeline.frame import SUPPORTED
    assert classify_operation("Có bao nhiêu công ty lãi năm 2024?").op == "COUNT"
    assert "COUNT" not in SUPPORTED


def test_parser_scores_are_reproducible():
    """The recorded scores must match a live recomputation of the same rule."""
    summary = json.loads((GOLD_DIR / "parser_vs_gold_summary.json").read_text(encoding="utf-8"))
    per_qid = {r["qid"]: r for r in load("parser_vs_gold_per_qid.jsonl")}
    gold = {r["qid"]: r for r in load("semantic_gold.jsonl")}
    live = sum(1 for q, r in per_qid.items()
               if "basis" in set(gold[q]["gold_usable_fields"])
               and resolve_basis_ok(q, gold))
    assert live == summary["metrics"]["basis"]["correct"]


def resolve_basis_ok(qid, gold):
    ws = {json.loads(l)["qid"]: json.loads(l)["question"]
          for l in (GOLD_DIR / "annotation_worksheet.jsonl").read_text(
              encoding="utf-8").splitlines() if l.strip()}
    return resolve_basis(ws[qid])[0] == gold[qid]["basis"]
