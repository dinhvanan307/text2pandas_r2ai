#!/usr/bin/env python3
"""Renderer + whitelist. `_safe_env` của replay là SSOT — test khoá điều đó lại.

Test quan trọng nhất ở đây là `safe_env_la_SSOT`: nếu ai đó đổi
`tools/replay_submission_v1.py::_safe_env` mà không đổi `verifier.safe_env`,
renderer sẽ sinh biểu thức chạy được ở local nhưng **hỏng khi chấm**. Không có
test này thì lệch đó chỉ lộ ra sau khi mất một lượt nộp.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/answer_v2"))
sys.path.insert(0, str(ROOT / "tools"))

import formula_registry as FR   # noqa: E402
import ir_v1                    # noqa: E402
import metric_ontology as MO    # noqa: E402
import pandas_renderer as PR    # noqa: E402
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


def _plan_bind(fid="debt_to_equity", vals=None, var2=False):
    sp = FORMULAS[fid]
    vals = vals or {"total_liabilities": 300.0, "equity": 150.0}
    binding = {m: {"entity": "T", "period": {"year": 2024}, "scope": "s"}
               for m in sp.leaves}
    bind = {}
    for i, m in enumerate(sp.leaves):
        bind[m] = {"variable": f"df{i + 1}" if var2 else "df1",
                   "row_path": f"rp_{m}", "col_label": "2024VND",
                   "csv_path": "data/x.csv", "value_vnd": vals[m]}
    plan = ir_v1.from_expression(
        FR.with_zero_policy(sp.expression, sp.zero_policy), qid=1,
        formula_id=fid, variant_id="v", output_kind=sp.output_kind,
        output_unit=sp.output_unit, fact_binding=binding)
    return plan, bind


def _df(bind, vals):
    """Dựng DataFrame khớp đúng khoá renderer dùng."""
    out = {}
    for m, b in bind.items():
        rows = out.setdefault(b["variable"], [])
        rows.append({"row_path": b["row_path"], "row_label": m,
                     "col_label": b["col_label"], "value_raw": "",
                     "value": vals[m]})
    return {v: pd.DataFrame(r) for v, r in out.items()}


@ca("SSOT · verifier.safe_env khớp replay_submission_v1._safe_env")
def _():
    src = (ROOT / "tools/replay_submission_v1.py").read_text(encoding="utf-8")
    m = re.search(r"def _safe_env.*?return env", src, re.S)
    assert m, "không tìm thấy _safe_env trong replay_submission_v1"
    ten_replay = set(re.findall(r'"(\w+)":', m.group(0)))
    ten_verifier = set(VF.safe_env({}).keys()) - {"__builtins__"}
    ten_replay.discard("__builtins__")
    assert ten_replay == ten_verifier, (
        f"lệch whitelist — replay {sorted(ten_replay)} vs "
        f"verifier {sorted(ten_verifier)}")


@ca("render · một df, biểu thức chạy đúng trong safe_env")
def _():
    vals = {"total_liabilities": 300.0, "equity": 150.0}
    plan, bind = _plan_bind(vals=vals)
    q, v = PR.render(plan, bind)
    got = eval(q, VF.safe_env(_df(bind, vals)))     # noqa: S307
    assert abs(got - v) < 1e-9 and abs(v - 2.0) < 1e-9


@ca("render · HAI df, biểu thức vẫn là một expression và chạy đúng")
def _():
    vals = {"total_liabilities": 900.0, "equity": 300.0}
    plan, bind = _plan_bind(vals=vals, var2=True)
    q, v = PR.render(plan, bind)
    assert "df1[" in q and "df2[" in q
    got = eval(q, VF.safe_env(_df(bind, vals)))     # noqa: S307
    assert abs(got - 3.0) < 1e-9 and abs(got - v) < 1e-9


@ca("render · escape nháy đơn trong nhãn không làm vỡ biểu thức")
def _():
    vals = {"total_liabilities": 10.0, "equity": 5.0}
    plan, bind = _plan_bind(vals=vals)
    bind["equity"]["col_label"] = "2024VND › LU'U CHUYÊN TIÊN"
    q, v = PR.render(plan, bind)
    got = eval(q, VF.safe_env(_df(bind, vals)))     # noqa: S307
    assert abs(got - 2.0) < 1e-9


@ca("render · literal dùng repr ⇒ eval ra ĐÚNG cùng bit")
def _():
    plan, bind = _plan_bind("gross_margin",
                            {"gross_profit": 1.0, "net_revenue": 3.0})
    q, v = PR.render(plan, bind)
    got = eval(q, VF.safe_env(_df(bind, {"gross_profit": 1.0, "net_revenue": 3.0})))
    assert got == v, "lệch bit giữa render và eval"


@ca("render · biểu thức KHÔNG chứa token cấm")
def _():
    for fid in FORMULAS:
        sp = FORMULAS[fid]
        vals = {m: float(i + 2) for i, m in enumerate(sp.leaves)}
        plan, bind = _plan_bind(fid, vals)
        q, _v = PR.render(plan, bind)
        assert not PR.CAM.search(q), f"{fid}: {q[:60]}"


@ca("static verifier · biến dùng mà thiếu evidence ⇒ EVIDENCE_VAR_MISSING")
def _():
    plan, bind = _plan_bind(var2=True)
    q, _ = PR.render(plan, bind)
    errs = VF.static(plan, q, [{"variable": "df1", "csv_path": "data/x.csv"}], bind)
    assert "EVIDENCE_VAR_MISSING" in errs


@ca("static verifier · evidence thừa ⇒ EVIDENCE_UNUSED")
def _():
    plan, bind = _plan_bind()
    q, _ = PR.render(plan, bind)
    ev = [{"variable": "df1", "csv_path": "data/x.csv"},
          {"variable": "df9", "csv_path": "data/y.csv"}]
    assert "EVIDENCE_UNUSED" in VF.static(plan, q, ev, bind)


@ca("semantic verifier · hỏi 'bao nhiêu lần' trả tiền ⇒ TYPE_CONTRACT_VIOLATION")
def _():
    q = "Tỷ số D/E của KBC năm 2020 là bao nhiêu lần?"
    assert VF.semantic(q, 5344660910.0) == ["TYPE_CONTRACT_VIOLATION"]
    assert VF.semantic(q, 2.31) == []


def chay():
    """Ủy quyền cho runner chung — ca thiếu DB thành SKIP, không thành PASS."""
    return chay_chung(CA)


if __name__ == "__main__":
    x, n, d = chay()
    raise SystemExit(in_ket_qua(Path(__file__).stem, x, n, d))
