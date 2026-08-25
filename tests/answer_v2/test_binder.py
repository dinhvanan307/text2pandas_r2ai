#!/usr/bin/env python3
"""Binder — `OperandKey` và ràng buộc theo formula.

Trọng tâm: chứng minh binder **không** dùng lại giả định một-metric của
`operand_pipeline_v1.enforce_metric_consistency`, và ràng buộc mới đúng là thứ
công thức tài chính cần (cùng entity/kỳ/phạm vi, KHÁC metric).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/answer_v2"))
sys.path.insert(0, str(ROOT / "tools"))

import metric_ontology as MO   # noqa: E402
import operand_binder as OB    # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _moitruong import chay_chung, in_ket_qua, work_db  # noqa: E402

SPECS = MO.load()
CA = []


def ca(ten):
    def deco(f):
        CA.append((ten, f))
        return f
    return deco


class Op:
    def __init__(self, ent="T", year=2024, basis="consolidated", pe=None):
        self.basis = basis
        self.period_end = pe if pe is not None else f"{year}-12-31"

        class K:
            entity = ent
            period_year = year
        self.key = K()


@ca("OperandKey · hai metric khác nhau cùng công ty/năm là HAI khoá")
def _():
    """Chính là điều `SlotKey(ticker, year, role)` KHÔNG làm được (doc 143 §1.1a)."""
    a = OB.OperandKey("total_liabilities", "HPG", 2024)
    b = OB.OperandKey("equity", "HPG", 2024)
    assert a != b and a.name != b.name
    assert len({a, b}) == 2


@ca("ràng buộc · cùng entity/kỳ/scope, KHÁC metric ⇒ HỢP LỆ")
def _():
    ops = {"total_liabilities": Op(), "equity": Op()}
    assert OB.kiem_rang_buoc(ops, True, True) == []


@ca("ràng buộc · rỗng ⇒ NO_OPERANDS")
def _():
    assert OB.kiem_rang_buoc({}, True, True) == ["NO_OPERANDS"]


@ca("ràng buộc · period_end lệch năm ⇒ PERIOD_END_MISMATCH")
def _():
    ops = {"a": Op(pe="2024-12-31"), "b": Op(pe="2023-12-31")}
    errs = OB.kiem_rang_buoc(ops, True, True)
    assert "PERIOD_END_MISMATCH" in errs


@ca("_basis_cua · suy phạm vi từ evidence_ref")
def _():
    assert OB._basis_cua("AAA_financial_statements_2015_consolidated|line:1") == "consolidated"
    assert OB._basis_cua("AAA_financial_statements_2015_separate|line:1") == "separate"
    assert OB._basis_cua("khong_ro|line:1") == "unknown"


@ca("_diem · ô ĐÚNG kỳ hơn hẳn ô SAI kỳ (phạt, không chỉ bỏ thưởng)")
def _():
    sp = SPECS["total_liabilities"]
    dung = {"period_end": "2024-12-31", "col_path": "31/12/2024",
            "statement_type": "balance_sheet", "evidence_ref": "X_consolidated|line:1",
            "is_restated": 0, "confidence": "high", "ready": 1, "row_path": "Nợ phải trả"}
    sai = dict(dung, period_end="2019-12-31", col_path="31/12/2019")
    a = OB._diem(dung, sp, 2024, "consolidated_preferred")
    b = OB._diem(sai, sp, 2024, "consolidated_preferred")
    assert a - b >= 5.0, f"khoảng cách quá nhỏ: {a} vs {b}"


@ca("_diem · row_path NÔNG hơn được ưu tiên")
def _():
    sp = SPECS["total_liabilities"]
    base = {"period_end": "2024-12-31", "col_path": "", "statement_type": "balance_sheet",
            "evidence_ref": "X_consolidated|line:1", "is_restated": 0,
            "confidence": "high", "ready": 1}
    nong = OB._diem({**base, "row_path": "Nợ phải trả"}, sp, 2024, "consolidated_preferred")
    sau = OB._diem({**base, "row_path": "A › B › Nợ phải trả"}, sp, 2024,
                   "consolidated_preferred")
    assert nong > sau


@ca("bind_leaf · metric không có trong ontology ⇒ UNKNOWN_METRIC")
def _():
    con = sqlite3.connect(f"file:{work_db()}?mode=ro&immutable=1", uri=True)
    op, err = OB.bind_leaf(con, {"entities": ["AAA"], "years": [2015], "question": "x"},
                           OB.OperandKey("khong_ton_tai", "AAA", 2015), SPECS)
    assert op is None and err == "UNKNOWN_METRIC"


@ca("bind_leaf · công ty không có dữ liệu ⇒ EMPTY_POOL, không ném")
def _():
    con = sqlite3.connect(f"file:{work_db()}?mode=ro&immutable=1", uri=True)
    op, err = OB.bind_leaf(con, {"entities": ["ZZZZ"], "years": [1900], "question": "x"},
                           OB.OperandKey("equity", "ZZZZ", 1900), SPECS)
    assert op is None and err in ("EMPTY_POOL", "METRIC_NOT_IN_POOL")


def chay():
    """Ủy quyền cho runner chung — ca thiếu DB thành SKIP, không thành PASS."""
    return chay_chung(CA)


if __name__ == "__main__":
    x, n, d = chay()
    raise SystemExit(in_ket_qua(Path(__file__).stem, x, n, d))
