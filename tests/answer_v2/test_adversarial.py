#!/usr/bin/env python3
"""Adversarial — mỗi ca nhắm một cách hệ thống có thể HỎNG NGẦM.

Ca "im lặng sai" nguy hiểm hơn ca crash. Phần lớn test dưới đây khẳng định hệ
thống **từ chối** thay vì đoán.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/answer_v2"))
sys.path.insert(0, str(ROOT / "tools"))

import formula_registry as FR   # noqa: E402
import ir_v1                    # noqa: E402
import metric_ontology as MO    # noqa: E402
import operand_binder as OB     # noqa: E402
import pandas_renderer as PR    # noqa: E402
import router_v1 as RT          # noqa: E402
import verifier as VF           # noqa: E402

SPECS, FORMULAS = MO.load(), FR.load()
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _moitruong import chay_chung, in_ket_qua  # noqa: E402
CA = []


def ca(ten):
    def deco(f):
        CA.append((ten, f))
        return f
    return deco


class _Op:
    def __init__(self, ref, basis, year, ent="T"):
        self.evidence_ref, self.basis, self.period_end = ref, basis, f"{year}-12-31"

        class K:
            entity = ent
            period_year = year
        self.key = K()


@ca("alias con · 'Nợ phải trả người bán ngắn hạn' KHÔNG được nhận là total_liabilities")
def _():
    """Đây là lỗi tệ nhất có thể xảy ra với D/E: khớp tiền tố nuốt dòng con,
    tỷ số nhỏ đi hàng chục lần mà không có dấu hiệu nào."""
    assert MO.nhan_dien(SPECS, "Nợ phải trả người bán ngắn hạn") is None
    assert MO.nhan_dien(SPECS, "Nợ phải trả") == "total_liabilities"


@ca("alias con · 'Lợi nhuận sau thuế chưa phân phối' ≠ profit_after_tax")
def _():
    assert MO.nhan_dien(SPECS, "Lợi nhuận sau thuế chưa phân phối") is None
    assert MO.nhan_dien(SPECS, "Lợi nhuận sau thuế thu nhập doanh nghiệp") == "profit_after_tax"


@ca("scope · trộn consolidated với separate ⇒ SCOPE_MISMATCH")
def _():
    ops = {"total_liabilities": _Op("A_2024_consolidated|line:1", "consolidated", 2024),
           "equity": _Op("A_2024_separate|line:2", "separate", 2024)}
    assert "SCOPE_MISMATCH" in OB.kiem_rang_buoc(ops, True, True)


@ca("kỳ · hai lá khác năm ⇒ PERIOD_MISMATCH")
def _():
    ops = {"a": _Op("X|1", "consolidated", 2023), "b": _Op("X|2", "consolidated", 2024)}
    assert "PERIOD_MISMATCH" in OB.kiem_rang_buoc(ops, True, True)


@ca("entity · hai lá khác công ty ⇒ ENTITY_MISMATCH")
def _():
    ops = {"a": _Op("X|1", "consolidated", 2024, "AAA"),
           "b": _Op("X|2", "consolidated", 2024, "BBB")}
    assert "ENTITY_MISMATCH" in OB.kiem_rang_buoc(ops, True, True)


@ca("literal lạ · Literal không nguồn ⇒ LITERAL_UNSOURCED ở render")
def _():
    plan = ir_v1.Plan(qid=1, route="R2", formula_id="f", variant_id="v",
                      output_kind="ratio", output_unit="times",
                      nodes={"k": {"id": "k", "node": "Literal", "value": 7.0,
                                   "kind": "scalar"},
                             "r": {"id": "r", "node": "Return", "child": "k"}},
                      root_id="r")
    try:
        PR.render(plan, {})
    except PR.RenderError as e:
        assert e.code == "LITERAL_UNSOURCED"
        return
    raise AssertionError("phải chặn literal không nguồn")


@ca("sorted() bị chặn · CAM bắt mọi token ngoài _safe_env")
def _():
    for t in ("sorted(x)", "list(x)", "any(x)", "all(x)", "import os",
              "x.__class__", "lambda x: x", "eval('1')"):
        assert PR.CAM.search(t), f"không chặn: {t}"


@ca("router · câu HAI TẦNG không được đi R2 dù khớp alias")
def _():
    q = ("Trong giai đoạn 2016-2020, vào năm KBC có tỷ số D/E cao nhất, "
         "hệ số khả năng thanh toán lãi vay là bao nhiêu lần?")
    r, sp, ly = RT.route(q, {"entities": ["KBC"], "years": [2016, 2020]}, FORMULAS)
    assert r == "R0" and ly == "HAI_TANG_CHUA_HO_TRO"


@ca("router · câu ĐIỀU KIỆN không được đi R2")
def _():
    q = ("Trong nhóm HPG, HSG, MSR và NKG, xét các công ty có hệ số thanh toán "
         "nhanh năm 2022 thấp hơn trung vị của nhóm...")
    r, _sp, ly = RT.route(q, {"entities": ["HPG"], "years": [2022]}, FORMULAS)
    assert r == "R0" and ly == "DIEU_KIEN_CHUA_HO_TRO"


@ca("router · khớp alias nhưng THIẾU entity ⇒ R0, không bịa công ty")
def _():
    r, _sp, ly = RT.route("Biên lợi nhuận gộp năm 2024 là bao nhiêu %?",
                          {"entities": [], "years": [2024]}, FORMULAS)
    assert r == "R0" and ly == "THIEU_ENTITY"


@ca("semantic · năm nào trả tiền ⇒ chặn; trả năm ⇒ qua")
def _():
    q = "Trong các năm 2015, 2020, năm nào có tổng nợ cao nhất?"
    assert VF.semantic(q, 8e11) == ["TYPE_CONTRACT_VIOLATION"]
    assert VF.semantic(q, 2020) == []


@ca("dynamic · CSV thiếu ⇒ CSV_MISSING, không ném")
def _():
    errs = VF.dynamic("float(df1['value'].values[0])",
                      [{"variable": "df1", "csv_path": "data/khong_co.csv"}],
                      1.0, data_dir=Path("/tmp/khong_ton_tai/data"))
    assert errs == ["CSV_MISSING"]


def chay():
    """Ủy quyền cho runner chung — ca thiếu DB thành SKIP, không thành PASS."""
    return chay_chung(CA)


if __name__ == "__main__":
    x, n, d = chay()
    raise SystemExit(in_ket_qua(Path(__file__).stem, x, n, d))
