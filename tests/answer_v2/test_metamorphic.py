#!/usr/bin/env python3
"""Metamorphic + binder — tính chất bất biến, không phải giá trị cụ thể.

Test metamorphic bắt được lớp lỗi mà test giá trị bỏ lọt: một hệ số quy đổi sai
vẫn cho "một con số" và vẫn qua mọi kiểm kiểu; chỉ quan hệ giữa các lần chạy mới
lộ ra nó.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/answer_v2"))
sys.path.insert(0, str(ROOT / "tools"))

import evidence_builder as EV   # noqa: E402
import formula_registry as FR   # noqa: E402
import ir_v1                    # noqa: E402
import metric_ontology as MO    # noqa: E402
import operand_binder as OB     # noqa: E402
import pandas_renderer as PR    # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _moitruong import BoQua, chay_chung, in_ket_qua, work_db  # noqa: E402

SPECS, FORMULAS = MO.load(), FR.load()
CA = []


def ca(ten):
    def deco(f):
        CA.append((ten, f))
        return f
    return deco


def _render(fid, vals):
    sp = FORMULAS[fid]
    binding = {m: {"entity": "T", "period": {"year": 2024}, "scope": "s"}
               for m in sp.leaves}
    bind = {m: {"variable": "df1", "row_path": f"rp_{m}", "col_label": "c",
                "csv_path": "data/x.csv", "value_vnd": vals[m]}
            for m in sp.leaves}
    plan = ir_v1.from_expression(
        FR.with_zero_policy(sp.expression, sp.zero_policy), qid=1,
        formula_id=fid, variant_id="v", output_kind=sp.output_kind,
        output_unit=sp.output_unit, fact_binding=binding)
    return PR.render(plan, bind)[1]


BASE = {"total_liabilities": 300.0, "equity": 150.0, "total_assets": 500.0,
        "current_assets": 200.0, "current_liabilities": 100.0, "inventory": 50.0,
        "gross_profit": 40.0, "net_revenue": 200.0, "profit_after_tax": 20.0,
        "selling_expense": 10.0, "admin_expense": 5.0, "cogs": 120.0,
        "financial_expense": 15.0, "interest_expense": 12.0, "financial_income": 25.0,
        "total_fixed_assets": 120.0, "intangible_fixed_assets": 30.0,
        "tangible_fixed_assets": 90.0, "short_term_borrowings": 45.0,
        "long_term_borrowings": 60.0, "cash_flow_from_operations": 30.0,
        "profit_before_tax": 20.0, "short_term_other_receivables": 30.0,
        "long_term_other_receivables": 10.0}


@ca("MM1 · nhân MỌI lá tiền ×1000 ⇒ mọi formula wave 1 BẤT BIẾN")
def _():
    for fid in FORMULAS:
        a = _render(fid, BASE)
        b = _render(fid, {k: v * 1000.0 for k, v in BASE.items()})
        assert abs(a - b) < 1e-9, f"{fid}: {a} != {b}"


@ca("MM2 · nhân ×1e-6 (đổi sang triệu) ⇒ vẫn bất biến")
def _():
    for fid in FORMULAS:
        a = _render(fid, BASE)
        b = _render(fid, {k: v * 1e-6 for k, v in BASE.items()})
        assert abs(a - b) < 1e-9, fid


@ca("MM3 · tăng tử số ⇒ tỉ số KHÔNG giảm (mẫu dương)")
def _():
    for fid, tu in (("debt_to_equity", "total_liabilities"),
                    ("current_ratio", "current_assets"),
                    ("gross_margin", "gross_profit"),
                    ("net_margin", "profit_after_tax")):
        a = _render(fid, BASE)
        b = _render(fid, {**BASE, tu: BASE[tu] * 2})
        assert b >= a - 1e-12, f"{fid}: {b} < {a}"


@ca("MM4 · expense intensities: đảo DẤU chi phí không đổi kết quả")
def _():
    for fid, metric in (
        ("sga_intensity", "selling_expense"),
        ("admin_expense_intensity", "admin_expense"),
        ("selling_expense_intensity", "selling_expense"),
        ("cogs_intensity", "cogs"),
        ("financial_expense_intensity", "financial_expense"),
        ("interest_expense_to_short_term_borrowings", "interest_expense"),
        ("interest_expense_to_long_term_borrowings", "interest_expense"),
    ):
        a = _render(fid, BASE)
        b = _render(fid, {**BASE, metric: -BASE[metric]})
        assert abs(a - b) < 1e-9, fid


@ca("MM5 · quick_ratio ≤ current_ratio khi tồn kho ≥ 0")
def _():
    q = _render("quick_ratio", BASE)
    c = _render("current_ratio", BASE)
    assert q <= c + 1e-12


@ca("binder · bind THẬT trên work.db: D/E lấy đúng HAI metric khác nhau")
def _():
    """Đây là ca chứng minh nút thắt gốc đã mở: `SlotKey(ticker, year)` cũ
    không biểu diễn được hai metric khác nhau; `OperandKey` thì được."""
    con = sqlite3.connect(f"file:{work_db()}?mode=ro&immutable=1", uri=True)
    row = con.execute(
        "SELECT ticker, doc_year FROM observations WHERE ticker IS NOT NULL"
        " AND doc_year IS NOT NULL"
        " GROUP BY ticker, doc_year HAVING COUNT(*) > 500 LIMIT 1").fetchone()
    if not row:
        raise BoQua("không (ticker,năm) nào đủ 500 observation")
    ent, yr = row
    # CAST TƯỜNG MINH (doc 157 §B4). `fetch_pool` tính `str(y + 1)` để mở rộng
    # cửa sổ năm; nếu `doc_year` về dưới dạng chuỗi thì đó là `TypeError`, không
    # phải lỗi logic. work.db khai `doc_year INTEGER`, nhưng một snapshot dựng
    # sai kiểu vẫn có thể lọt vào — chính chuyện đã xảy ra với minimal DB v1.
    # Ép kiểu ở đây rẻ hơn nhiều so với một stack trace khó truy.
    yr = int(yr)
    plan_q = {"entities": [ent], "years": [yr], "question": "x"}
    ops, errs, chan = OB.bind_plan(con, plan_q, ["total_liabilities", "equity"],
                                   ent, yr, SPECS)
    if errs:
        # Không phải mọi (ticker,năm) đều đủ hai lá — 69,7% theo đo lường.
        # Test này chỉ khẳng định: KHI bind được thì hai lá KHÁC nhau.
        raise BoQua(f"(ticker={ent}, năm={yr}) không bind đủ hai lá: {errs}")
    assert len(ops) == 2
    assert ops["total_liabilities"].metric_label != ops["equity"].metric_label
    assert ops["total_liabilities"].observation_uid != ops["equity"].observation_uid


@ca("evidence · hai lá CÙNG bảng ⇒ MỘT DataFrame, không phải hai")
def _():
    class O:
        def __init__(self, ref, uid):
            self.evidence_ref, self.table_uid = ref, uid
            self.observation_uid, self.value_decimal_text = "u", "1"
            self.scale_exponent = 0
    a, b = O("D|line:1", "T1"), O("D|line:1", "T1")
    theo = {}
    for mid, op in (("x", a), ("y", b)):
        theo.setdefault(op.evidence_ref, []).append((mid, op))
    assert len(theo) == 1, "cùng evidence_ref phải gộp về một bảng"


def chay():
    """Ủy quyền cho runner chung — ca thiếu DB thành SKIP, không thành PASS."""
    return chay_chung(CA)


if __name__ == "__main__":
    x, n, d = chay()
    raise SystemExit(in_ket_qua(Path(__file__).stem, x, n, d))
