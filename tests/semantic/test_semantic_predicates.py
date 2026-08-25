#!/usr/bin/env python3
"""Test cho semantic predicates + contract — Pha 8/9 directive 165.

Chín fixture bắt buộc, mỗi fixture là một **negative test có chủ đích**: nếu
predicate bị viết hỏng theo đúng kiểu mà review 165 mô tả thì test phải ĐỎ.
Ví dụ `test_unit_sai_nhung_ty_le_khong_phai_luy_thua_10` sẽ xanh với bản v2 cũ
(vì bản đó suy unit từ `pred/gold`) — đó chính là lý do nó tồn tại.

Chạy:  python3 -m pytest tests/semantic/ -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import pytest                                                    # noqa: E402

from semantic import predicates as P                             # noqa: E402
from semantic.contract import danh_gia, du_dieu_kien_whitelist    # noqa: E402

Q_MOT_O = ("float(df1[(df1['row_path'] == 'A') & "
           "(df1['col_label'] == 'Số cuối nămTriệu đồng')]['value'].values[0]) / 1000000")
Q_HAI_O = ("float(df1[(df1['row_path'] == 'A') & (df1['col_label'] == 'C1')]"
           "['value'].values[0]) / float(df1[(df1['row_path'] == 'B') & "
           "(df1['col_label'] == 'C2')]['value'].values[0])")


def op(role, row, col):
    return {"role": role, "row_path": row, "col_path": col}


# ── 1 · ca đúng ─────────────────────────────────────────────────────────────
def test_1_ca_dung_moi_chieu_pass():
    v = {c: P.Verdict(P.PASS) for c in
         ("entity", "metric", "period", "basis", "operation", "operands",
          "unit", "computation", "evidence")}
    r = danh_gia(v, answer_exact=True)
    assert r.semantic_correctness == "PROVEN_CORRECT"
    assert du_dieu_kien_whitelist(r)[0] is True


# ── 2 · metric mismatch ─────────────────────────────────────────────────────
def test_2_metric_mismatch_thanh_proven_incorrect():
    v = {"metric": P.Verdict(P.FAIL, "chọn dòng rollforward dự phòng")}
    v.update({c: P.Verdict(P.PASS) for c in
              ("entity", "period", "basis", "operation", "operands", "unit",
               "computation", "evidence")})
    r = danh_gia(v, answer_exact=False)
    assert r.semantic_correctness == "PROVEN_INCORRECT"
    assert r.primary_failure == "METRIC_MISMATCH"


# ── 3 · year/period mismatch ────────────────────────────────────────────────
def test_3_period_mismatch():
    r = P.period_match(["2017-01-01"], ["2016-12-31"])
    assert r.status == P.FAIL
    assert P.period_match(["2024-12-31"], ["2024-12-31"]).status == P.PASS


# ── 4 · basis mismatch ──────────────────────────────────────────────────────
def test_4_basis_mismatch():
    assert P.basis_match("separate",
                         ["KLB_financial_statements_2018_consolidated"]).status == P.FAIL
    assert P.basis_match("separate",
                         ["KLB_financial_statements_2018_separate"]).status == P.PASS
    # basis gold không rõ ⇒ KHÔNG được đoán
    assert P.basis_match("unknown", ["X_separate"]).status == P.NOT_MEASURABLE


# ── 5 · operation mismatch (F7) ─────────────────────────────────────────────
def test_5_operation_so_that_khong_phai_dem_operand():
    assert P.operation_match("count", "lookup").status == P.FAIL
    assert P.operation_match("lookup", "lookup").status == P.PASS
    # `multi` KHÔNG phải operation ⇒ không được trả True/False
    assert P.operation_match("multi", "lookup").status == P.NOT_MEASURABLE


def test_5b_operand_count_giong_nhau_nhung_operation_khac():
    """Ca mà bản v2 cũ sẽ báo PASS: cùng 1 toán hạng, khác phép toán."""
    sels, _ = P.tach_selection(Q_MOT_O)
    assert P.operand_binding([op("value", "A", "Số cuối nămTriệu đồng")],
                             sels).status == P.PASS
    assert P.operation_match("count", "lookup").status == P.FAIL


# ── 6 · operand mismatch, role-aware (F10) ──────────────────────────────────
def test_6_operand_dao_tu_mau_phai_FAIL():
    sels, st = P.tach_selection(Q_HAI_O)
    assert st == "OK" and len(sels) == 2
    dung = [op("numerator", "A", "C1"), op("denominator", "B", "C2")]
    dao = [op("numerator", "B", "C2"), op("denominator", "A", "C1")]
    assert P.operand_binding(dung, sels).status == P.PASS
    assert P.operand_binding(dao, sels).status == P.FAIL


def test_6b_khong_duoc_nhan_cheo_row_va_col():
    """Bản cũ gom row/col thành hai set rồi nhân chéo ⇒ ghép nhầm A×C2."""
    sels, _ = P.tach_selection(Q_HAI_O)
    cap = {(s.row_path, s.col_path) for s in sels}
    assert cap == {("A", "C1"), ("B", "C2")}
    assert ("A", "C2") not in cap


# ── 7 · unit mismatch KHÔNG suy từ pred/gold (F8) ───────────────────────────
def test_7_unit_tinh_tu_nguon():
    # nguồn triệu đồng, hỏi triệu đồng ⇒ hệ số 1, nhưng query chia 1e6 ⇒ FAIL
    r = P.unit_contract("Số cuối nămTriệu đồng", "bao nhiêu triệu đồng?", Q_MOT_O)
    assert r.status == P.FAIL
    assert r.evidence["expected_factor"] == 1
    # nguồn triệu đồng, hỏi tỷ đồng ⇒ hệ số 1e-3
    r2 = P.unit_contract("Triệu đồng", "bao nhiêu tỷ đồng?",
                         "float(x['value'].values[0]) / 1000")
    assert r2.status == P.PASS


def test_7b_unit_sai_nhung_ty_le_khong_phai_luy_thua_10():
    """Đúng lỗi F8: pred/gold = 3,7 (không phải 10^k) nên bản cũ báo U1=PASS."""
    pred, gold = 3.7, 1.0
    assert not any(abs(pred / gold - 10 ** e) < 1e-9
                   for e in (-12, -9, -6, -3, -2, 2, 3, 6, 9, 12))
    r = P.unit_contract("Triệu đồng", "bao nhiêu triệu đồng?", Q_MOT_O)
    assert r.status == P.FAIL          # kiểm từ NGUỒN vẫn bắt được


# ── 8 · evidence insufficient (F9) ──────────────────────────────────────────
def test_8_evidence_tach_ba_muc():
    ev = [{"variable": "df1", "csv_path": "data/a.csv"}]
    assert P.evidence_files_present(ev, ["data/a.csv"]).status == P.PASS
    assert P.evidence_files_present(ev, []).status == P.FAIL
    sels, _ = P.tach_selection(Q_HAI_O)
    # file có mặt nhưng query dùng biến khác ⇒ E1 phải FAIL
    assert P.query_variable_resolves(
        sels, [{"variable": "df2", "csv_path": "data/a.csv"}]).status == P.FAIL
    # file có mặt nhưng KHÔNG phủ toán hạng gold ⇒ E3 phải FAIL
    assert P.gold_operands_covered(
        [op("a", "KHAC", "KHAC")], sels).status == P.FAIL


# ── 9 · gold uncertain KHÔNG được thành INCORRECT ───────────────────────────
def test_9_gold_uncertain_giu_nguyen_uncertain():
    v = {c: P.Verdict(P.PASS) for c in
         ("entity", "metric", "period", "basis", "operands", "unit",
          "computation", "evidence")}
    v["operation"] = P.Verdict(P.NOT_MEASURABLE, "gold ghi 'multi'")
    r = danh_gia(v, answer_exact=None)
    assert r.semantic_correctness == "UNCERTAIN"
    assert r.primary_failure == "GOLD_UNCERTAIN"
    assert du_dieu_kien_whitelist(r)[0] is False


# ── phụ · SPURIOUS_CORRECT và parser số ─────────────────────────────────────
def test_spurious_correct_duoc_gan_co():
    v = {c: P.Verdict(P.PASS) for c in
         ("entity", "period", "basis", "operation", "operands", "unit",
          "computation", "evidence")}
    v["metric"] = P.Verdict(P.FAIL, "sai chỉ tiêu")
    r = danh_gia(v, answer_exact=True)
    assert r.semantic_correctness == "PROVEN_INCORRECT"
    assert "SPURIOUS_CORRECT" in r.flags


@pytest.mark.parametrize("raw,val,st", [
    ("1.484.894", 1484894.0, "OK"),
    ("(652.429)", -652429.0, "OK"),
    ("-12.345", -12345.0, "OK"),
    ("100,00", 100.0, "OK"),
    ("-", None, "MISSING_TOKEN"),
    ("", None, "MISSING_TOKEN"),
])
def test_parser_giu_dau_am_ngoac_thap_phan(raw, val, st):
    v, s = P.parse_so(raw)
    assert s == st and v == val


def test_verdict_khong_co_gia_tri_chan_ly():
    """Chặn lỗi `if verdict:` — nguồn của nhiều false-green."""
    with pytest.raises(TypeError):
        bool(P.Verdict(P.FAIL))
