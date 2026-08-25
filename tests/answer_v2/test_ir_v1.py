#!/usr/bin/env python3
"""IR v1 — 7 luật validate, mỗi luật MỘT test, + dimension algebra.

Gate G1 đòi cả 7 luật PASS. Test viết theo kiểu "dựng plan CỐ Ý sai một luật
duy nhất rồi khẳng định đúng mã lỗi đó xuất hiện" — nếu một luật bị xoá khỏi
validator, đúng một test đỏ và biết ngay luật nào.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/answer_v2"))

import ir_v1  # noqa: E402

VK = {"a": "money", "b": "money", "p": "percentage"}
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _moitruong import chay_chung, in_ket_qua  # noqa: E402
CA = []


def ca(ten):
    def deco(f):
        CA.append((ten, f))
        return f
    return deco


def P(nodes: dict, root: str, kind="ratio") -> ir_v1.Plan:
    return ir_v1.Plan(qid=1, route="DERIVED_FORMULA", formula_id="f",
                      variant_id="v", output_kind=kind, output_unit="times",
                      nodes=nodes, root_id=root)


def _fact(mid):
    return {"node": "FactRef", "metric_id": mid, "entity": "T",
            "period": {"year": 2024}, "scope": "s"}


def _chia(num="l1", den="l2", policy="unresolved"):
    n = {"node": "Divide", "num": num, "den": den}
    if policy is not None:
        n["zero_policy"] = policy
    return n


def _ok_nodes():
    return {"l1": _fact("a") | {"id": "l1"}, "l2": _fact("b") | {"id": "l2"},
            "d1": _chia() | {"id": "d1"},
            "r": {"id": "r", "node": "Return", "child": "d1"}}


# ── luật 1 ─────────────────────────────────────────────────────────────────
@ca("luật 1 · root không tồn tại ⇒ MISSING_OUTPUT")
def _():
    assert ir_v1.validate(P(_ok_nodes(), "khong_co"), VK) == ["MISSING_OUTPUT"]


@ca("luật 1b · root không phải Return ⇒ MISSING_OUTPUT")
def _():
    assert "MISSING_OUTPUT" in ir_v1.validate(P(_ok_nodes(), "d1"), VK)


# ── luật 2 ─────────────────────────────────────────────────────────────────
@ca("luật 2 · chu trình ⇒ CYCLIC_PLAN")
def _():
    n = _ok_nodes()
    n["l1"] = {"id": "l1", "node": "Abs", "child": "d1"}      # d1 → l1 → d1
    assert "CYCLIC_PLAN" in ir_v1.validate(P(n, "r"), VK)


# ── luật 3 ─────────────────────────────────────────────────────────────────
@ca("luật 3 · node ngoài whitelist ⇒ AST_FORBIDDEN_NODE")
def _():
    n = _ok_nodes()
    n["x"] = {"id": "x", "node": "ArgMax", "child": "l1"}     # R3, chưa có ở v1
    n["r"]["child"] = "x"
    assert "AST_FORBIDDEN_NODE" in ir_v1.validate(P(n, "r"), VK)


# ── luật 4 ─────────────────────────────────────────────────────────────────
@ca("luật 4 · thiếu slot con ⇒ INVALID_ARITY")
def _():
    n = _ok_nodes()
    del n["d1"]["den"]
    assert "INVALID_ARITY" in ir_v1.validate(P(n, "r"), VK)


@ca("luật 4b · slot trỏ node không tồn tại ⇒ INVALID_ARITY")
def _():
    n = _ok_nodes()
    n["d1"]["den"] = "ma"
    assert "INVALID_ARITY" in ir_v1.validate(P(n, "r"), VK)


# ── luật 5 ─────────────────────────────────────────────────────────────────
@ca("luật 5 · Divide thiếu zero_policy ⇒ DIVIDE_NO_ZERO_POLICY")
def _():
    n = _ok_nodes()
    del n["d1"]["zero_policy"]
    assert "DIVIDE_NO_ZERO_POLICY" in ir_v1.validate(P(n, "r"), VK)


@ca("luật 5b · zero_policy lạ ⇒ vẫn đỏ")
def _():
    n = _ok_nodes()
    n["d1"]["zero_policy"] = "cu_chia_di"
    assert "DIVIDE_NO_ZERO_POLICY" in ir_v1.validate(P(n, "r"), VK)


# ── luật 6 ─────────────────────────────────────────────────────────────────
@ca("luật 6 · Literal không có source ⇒ LITERAL_UNSOURCED")
def _():
    n = _ok_nodes()
    n["k"] = {"id": "k", "node": "Literal", "value": 100.0, "kind": "scalar"}
    n["m"] = {"id": "m", "node": "Multiply", "left": "d1", "right": "k"}
    n["r"]["child"] = "m"
    assert "LITERAL_UNSOURCED" in ir_v1.validate(P(n, "r", "percentage"), VK)


@ca("luật 6b · source hợp lệ ⇒ không đỏ")
def _():
    n = _ok_nodes()
    n["k"] = {"id": "k", "node": "Literal", "value": 100.0, "kind": "scalar",
              "source": "formula_constant"}
    n["m"] = {"id": "m", "node": "Multiply", "left": "d1", "right": "k"}
    n["r"]["child"] = "m"
    assert ir_v1.validate(P(n, "r", "percentage"), VK) == []


# ── luật 7 ─────────────────────────────────────────────────────────────────
@ca("luật 7 · dimension(root) ≠ output.kind ⇒ DIMENSION_MISMATCH")
def _():
    assert "DIMENSION_MISMATCH" in ir_v1.validate(P(_ok_nodes(), "r", "money"), VK)


# ── dimension algebra ──────────────────────────────────────────────────────
@ca("dim · money / money = ratio")
def _():
    assert ir_v1.validate(P(_ok_nodes(), "r", "ratio"), VK) == []


@ca("dim · money + money = money; money + ratio = INVALID")
def _():
    n = {"l1": _fact("a") | {"id": "l1"}, "l2": _fact("b") | {"id": "l2"},
         "s": {"id": "s", "node": "Add", "left": "l1", "right": "l2"},
         "r": {"id": "r", "node": "Return", "child": "s"}}
    assert ir_v1.validate(P(n, "r", "money"), VK) == []
    n["l2"] = _fact("p") | {"id": "l2"}                # percentage
    assert "DIMENSION_MISMATCH" in ir_v1.validate(P(n, "r", "money"), VK)


@ca("dim · ratio × 100 = percentage, ratio × 2 vẫn = ratio")
def _():
    for hs, mong in ((100.0, "percentage"), (2.0, "ratio")):
        n = _ok_nodes()
        n["k"] = {"id": "k", "node": "Literal", "value": hs, "kind": "scalar",
                  "source": "formula_constant"}
        n["m"] = {"id": "m", "node": "Multiply", "left": "d1", "right": "k"}
        n["r"]["child"] = "m"
        assert ir_v1.validate(P(n, "r", mong), VK) == [], f"hệ số {hs}"


@ca("dim · Abs giữ nguyên dimension")
def _():
    n = {"l1": _fact("a") | {"id": "l1"},
         "b": {"id": "b", "node": "Abs", "child": "l1"},
         "r": {"id": "r", "node": "Return", "child": "b"}}
    assert ir_v1.validate(P(n, "r", "money"), VK) == []


@ca("leaves/literals trả đúng và ổn định thứ tự")
def _():
    n = _ok_nodes()
    assert [x["metric_id"] for x in ir_v1.leaves(P(n, "r"))] == ["a", "b"]
    assert ir_v1.literals(P(n, "r")) == []


def chay():
    """Ủy quyền cho runner chung — ca thiếu DB thành SKIP, không thành PASS."""
    return chay_chung(CA)


if __name__ == "__main__":
    x, n, d = chay()
    raise SystemExit(in_ket_qua(Path(__file__).stem, x, n, d))
