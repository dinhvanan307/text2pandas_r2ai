#!/usr/bin/env python3
"""Formula reference tests — 11 formula × 8 ca = 88. Gate G1 đòi 100%.

Tám ca cho MỖI formula (doc 145 §9):
    3 normal · zero denominator · negative denominator · missing operand ·
    unit mismatch · explicit-question override

Test chạy trên IR THẬT: dựng plan bằng `from_expression`, validate, render bằng
`pandas_renderer`, rồi so giá trị renderer tính với giá trị mong đợi tính tay.
Không mock IR — mock ở đây sẽ bỏ lọt đúng lớp lỗi vừa bắt được thật
(`zero_policy` bị đánh rơi khi phẳng hoá).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/answer_v2"))

import formula_registry as FR   # noqa: E402
import ir_v1                    # noqa: E402
import metric_ontology as MO    # noqa: E402
import pandas_renderer as PR    # noqa: E402

SPECS = MO.load()
FORMULAS = FR.load()

# Giá trị lá cho các ca thường. Đơn vị VND, như CSV a6_*.
NORMAL = [
    {"total_liabilities": 300.0, "equity": 150.0, "total_assets": 500.0,
     "current_assets": 200.0, "current_liabilities": 100.0, "inventory": 50.0,
     "gross_profit": 40.0, "net_revenue": 200.0, "profit_after_tax": 20.0,
     "selling_expense": 10.0, "admin_expense": 5.0, "cogs": 120.0},
    {"total_liabilities": 900.0, "equity": 300.0, "total_assets": 1200.0,
     "current_assets": 600.0, "current_liabilities": 400.0, "inventory": 100.0,
     "gross_profit": 150.0, "net_revenue": 1000.0, "profit_after_tax": -50.0,
     "selling_expense": -30.0, "admin_expense": 20.0, "cogs": -700.0},
    {"total_liabilities": 1.0, "equity": 4.0, "total_assets": 5.0,
     "current_assets": 3.0, "current_liabilities": 3.0, "inventory": 0.0,
     "gross_profit": 0.0, "net_revenue": 7.0, "profit_after_tax": 7.0,
     "selling_expense": 1.0, "admin_expense": 1.0, "cogs": 0.0},
]

MONG_DOI = {
    "debt_to_equity": lambda v: v["total_liabilities"] / v["equity"],
    "debt_to_assets": lambda v: v["total_liabilities"] / v["total_assets"] * 100.0,
    "current_ratio": lambda v: v["current_assets"] / v["current_liabilities"],
    "quick_ratio": lambda v: (v["current_assets"] - v["inventory"]) / v["current_liabilities"],
    "gross_margin": lambda v: v["gross_profit"] / v["net_revenue"] * 100.0,
    "net_margin": lambda v: v["profit_after_tax"] / v["net_revenue"] * 100.0,
    "inventory_to_assets": lambda v: v["inventory"] / v["total_assets"] * 100.0,
    "sga_intensity": lambda v: (abs(v["selling_expense"]) + abs(v["admin_expense"]))
                               / v["net_revenue"] * 100.0,
    "admin_expense_intensity": lambda v: abs(v["admin_expense"])
                                         / v["net_revenue"] * 100.0,
    "selling_expense_intensity": lambda v: abs(v["selling_expense"])
                                           / v["net_revenue"] * 100.0,
    "cogs_intensity": lambda v: abs(v["cogs"]) / v["net_revenue"] * 100.0,
}

# Lá nằm ở MẪU SỐ của từng formula — dùng cho ca zero/negative denominator.
MAU = {
    "debt_to_equity": "equity", "debt_to_assets": "total_assets",
    "current_ratio": "current_liabilities", "quick_ratio": "current_liabilities",
    "gross_margin": "net_revenue", "net_margin": "net_revenue",
    "inventory_to_assets": "total_assets", "sga_intensity": "net_revenue",
    "admin_expense_intensity": "net_revenue",
    "selling_expense_intensity": "net_revenue", "cogs_intensity": "net_revenue",
}

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _moitruong import chay_chung, in_ket_qua  # noqa: E402
CA = []


def ca(ten):
    def deco(f):
        CA.append((ten, f))
        return f
    return deco


def _dung(fid: str, vals: dict, bo_lá: str | None = None):
    """→ (plan, bind, errs). `bo_lá` mô phỏng thiếu operand."""
    sp = FORMULAS[fid]
    binding, bind = {}, {}
    for mid in sp.leaves:
        if mid == bo_lá:
            continue
        binding[mid] = {"entity": "TST", "period": {"year": 2024},
                        "scope": "consolidated_preferred"}
        bind[mid] = {"variable": "df1", "row_path": f"rp_{mid}",
                     "col_label": "2024VND", "csv_path": "data/x.csv",
                     "value_vnd": vals[mid]}
    expr = FR.with_zero_policy(sp.expression, sp.zero_policy)
    plan = ir_v1.from_expression(
        expr, qid=1, formula_id=fid, variant_id=sp.variant_id,
        output_kind=sp.output_kind, output_unit=sp.output_unit,
        fact_binding=binding)
    vk = {m: SPECS[m].value_kind for m in sp.leaves}
    return plan, bind, ir_v1.validate(plan, vk)


for _fid in FORMULAS:
    for _i in range(3):
        @ca(f"{_fid} · normal {_i + 1}")
        def _(fid=_fid, i=_i):
            vals = NORMAL[i]
            plan, bind, errs = _dung(fid, vals)
            assert not errs, f"IR không hợp lệ: {errs}"
            q, v = PR.render(plan, bind)
            mong = MONG_DOI[fid](vals)
            assert abs(v - mong) < 1e-9, f"{v} != {mong}"
            assert q.startswith("float(") and "df1[" in q

    @ca(f"{_fid} · zero denominator ⇒ ZERO_DENOMINATOR, KHÔNG phát x/0")
    def _(fid=_fid):
        vals = dict(NORMAL[0])
        vals[MAU[fid]] = 0.0
        plan, bind, errs = _dung(fid, vals)
        assert not errs
        try:
            PR.render(plan, bind)
        except PR.RenderError as e:
            assert e.code == "ZERO_DENOMINATOR"
            return
        raise AssertionError("phải ném ZERO_DENOMINATOR")

    @ca(f"{_fid} · negative denominator ⇒ VẪN tính, giữ dấu")
    def _(fid=_fid):
        """Mẫu âm (vốn chủ âm, doanh thu âm) là dữ liệu THẬT, không phải lỗi.
        Trả kết quả âm là đúng; chặn ở đây sẽ mất câu một cách vô cớ."""
        vals = dict(NORMAL[0])
        vals[MAU[fid]] = -abs(vals[MAU[fid]]) or -100.0
        plan, bind, errs = _dung(fid, vals)
        assert not errs
        q, v = PR.render(plan, bind)
        assert abs(v - MONG_DOI[fid](vals)) < 1e-9

    @ca(f"{_fid} · missing operand ⇒ FACTREF_UNBOUND")
    def _(fid=_fid):
        thieu = FORMULAS[fid].leaves[0]
        try:
            _dung(fid, NORMAL[0], bo_lá=thieu)
        except ir_v1.IRError as e:
            assert e.code == "FACTREF_UNBOUND"
            return
        raise AssertionError("phải ném FACTREF_UNBOUND")

    @ca(f"{_fid} · unit mismatch ⇒ tỉ số BẤT BIẾN khi đổi thang")
    def _(fid=_fid):
        """Mọi formula wave 1 là ratio/percentage ⇒ nhân mọi lá cùng một hệ số
        KHÔNG được đổi kết quả. Nếu đổi thì có lá bị quy đổi đơn vị nhầm."""
        a = NORMAL[0]
        b = {k: v * 1000.0 for k, v in a.items()}
        _, bind_a, _ = _dung(fid, a)
        pa, _, _ = _dung(fid, a)
        pb, bind_b, _ = _dung(fid, b)
        _, va = PR.render(pa, bind_a)
        _, vb = PR.render(pb, bind_b)
        assert abs(va - vb) < 1e-9, f"{va} != {vb} — không bất biến thang"

    @ca(f"{_fid} · explicit-question override ⇒ output_kind khai sai bị BẮT")
    def _(fid=_fid):
        """Nếu ai đó sửa YAML cho `output.kind` lệch với công thức thật,
        validator phải đỏ `DIMENSION_MISMATCH` chứ không im lặng trả sai thang."""
        sp = FORMULAS[fid]
        sai = "percentage" if sp.output_kind == "ratio" else "ratio"
        binding = {m: {"entity": "T", "period": {"year": 2024}, "scope": "s"}
                   for m in sp.leaves}
        plan = ir_v1.from_expression(
            FR.with_zero_policy(sp.expression, sp.zero_policy), qid=1,
            formula_id=fid, variant_id="x", output_kind=sai,
            output_unit="?", fact_binding=binding)
        errs = ir_v1.validate(plan, {m: SPECS[m].value_kind for m in sp.leaves})
        assert "DIMENSION_MISMATCH" in errs


def chay():
    """Ủy quyền cho runner chung — ca thiếu DB thành SKIP, không thành PASS."""
    return chay_chung(CA)


if __name__ == "__main__":
    x, n, d = chay()
    raise SystemExit(in_ket_qua(Path(__file__).stem, x, n, d))
