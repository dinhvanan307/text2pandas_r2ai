#!/usr/bin/env python3
"""IR v1 — 8 node, đủ cho route R2 `DERIVED_FORMULA`.

VÌ SAO 8 CHỨ KHÔNG 20 (doc 145 §P1-6)
Doc 144 §6.2 liệt 20 node. `ArgMax/ArgMin/SelectAt` chỉ dùng ở R3;
`Filter/Compare/And/Or/Median` chỉ ở R4; `ScenarioOverride` chỉ ở R5;
`PercentChange/CAGR` là đường tắt của `Divide/Subtract/**`. Xây cả 20 rồi mới có
candidate đầu tiên là tiêu quỹ thời gian vào phần chưa dùng.

DIMENSION ALGEBRA — đây là thứ bắt lỗi công thức, không phải kiểu Python.
    money ± money    → money
    money / money    → ratio
    ratio × scalar   → ratio            (nhân 1 hằng ≠ 100)
    ratio × 100      → percentage       (quy ước duy nhất đổi ratio→percentage)
    abs(x)           → dimension của x
    money ± ratio    → INVALID
Nhờ luật cuối, một công thức viết nhầm `L / E * 100` khi output khai `ratio` sẽ
đỏ ở validator chứ không lặng lẽ trả số gấp 100 lần.

`Literal` BẮT BUỘC có `source ∈ {question_literal, formula_constant}` — đây là
cơ chế chống ảo giác số: không hằng số nào được xuất hiện mà không truy được
nguồn. `Divide` BẮT BUỘC có `zero_policy`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 8 node của wave 1. Thêm node = sửa DUY NHẤT bảng này + `dimension_of` + renderer.
NODE_ARITY: dict[str, tuple[str, ...]] = {
    "FactRef": (),
    "Literal": (),
    "Add": ("left", "right"),
    "Subtract": ("left", "right"),
    "Multiply": ("left", "right"),
    "Divide": ("num", "den"),
    "Abs": ("child",),
    "Return": ("child",),
}

DIMENSIONS = ("money", "ratio", "percentage", "scalar", "count", "year")
LITERAL_SOURCES = ("question_literal", "formula_constant")
ZERO_POLICIES = ("unresolved", "zero", "nan")


class IRError(Exception):
    """Lỗi IR có mã — mọi mã đều xuất hiện trong `verifier_report.json`."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass
class Plan:
    """Một chương trình IR đã phẳng hoá: `nodes` là dict id → node."""

    qid: int
    route: str
    formula_id: str
    variant_id: str
    output_kind: str
    output_unit: str
    nodes: dict[str, dict]
    root_id: str
    meta: dict = field(default_factory=dict)

    def node(self, nid: str) -> dict:
        n = self.nodes.get(nid)
        if n is None:
            raise IRError("NODE_NOT_FOUND", nid)
        return n


# ── xây plan từ expression lồng nhau của formulas_v1.yaml ──────────────────

def from_expression(expr: dict, *, qid: int, formula_id: str, variant_id: str,
                    output_kind: str, output_unit: str,
                    fact_binding: dict[str, dict]) -> Plan:
    """`expr` (cây lồng) + ràng buộc lá → `Plan` phẳng có `Return` ở gốc.

    `fact_binding[metric_id]` cung cấp entity/period/scope cho từng `FactRef`.
    Tách như vậy để **một** định nghĩa formula dùng lại được cho mọi
    (công ty, năm) mà không phải nhân bản YAML.
    """
    nodes: dict[str, dict] = {}
    seq = [0]

    def add(n: dict) -> str:
        seq[0] += 1
        nid = f"n{seq[0]}"
        n = dict(n)
        n["id"] = nid
        nodes[nid] = n
        return nid

    def walk(e: dict) -> str:
        if not isinstance(e, dict) or "node" not in e:
            raise IRError("MALFORMED_EXPRESSION", repr(e)[:80])
        kind = e["node"]
        if kind not in NODE_ARITY:
            raise IRError("AST_FORBIDDEN_NODE", kind)
        if kind == "FactRef":
            mid = e["metric_id"]
            b = fact_binding.get(mid)
            if b is None:
                raise IRError("FACTREF_UNBOUND", mid)
            return add({"node": "FactRef", "metric_id": mid, **b})
        if kind == "Literal":
            return add({"node": "Literal", "value": float(e["value"]),
                        "kind": e.get("kind", "scalar"),
                        "source": e.get("source"), "span": e.get("span")})
        # Giữ MỌI khoá không phải slot con — `zero_policy` của `Divide` nằm ở
        # đây. Bản đầu chỉ copy slot con và đánh rơi nó, làm 7/10 câu R2 đỏ
        # `DIVIDE_NO_ZERO_POLICY` dù YAML đã khai đúng. Lỗi kiểu "mất thuộc tính
        # khi chuyển dạng" không lộ ra ở test đơn vị của từng hàm — chỉ lộ khi
        # chạy đường đầy đủ.
        out = {k: v for k, v in e.items() if k not in NODE_ARITY[kind]}
        out["node"] = kind
        for slot in NODE_ARITY[kind]:
            if slot not in e:
                raise IRError("INVALID_ARITY", f"{kind} thiếu '{slot}'")
            out[slot] = walk(e[slot])
        return add(out)

    root_child = walk(expr)
    root = add({"node": "Return", "child": root_child})
    return Plan(qid=qid, route="DERIVED_FORMULA", formula_id=formula_id,
                variant_id=variant_id, output_kind=output_kind,
                output_unit=output_unit, nodes=nodes, root_id=root)


# ── dimension algebra ──────────────────────────────────────────────────────

def dimension_of(plan: Plan, nid: str, value_kind_of: dict[str, str],
                 _seen: frozenset = frozenset()) -> str:
    """Suy dimension của một node. Phát hiện chu trình luôn tại đây."""
    if nid in _seen:
        raise IRError("CYCLIC_PLAN", nid)
    seen = _seen | {nid}
    n = plan.node(nid)
    k = n["node"]

    # Slot thiếu phải thành MÃ LỖI, không phải KeyError thô. Một plan méo (ví
    # dụ do planner LLM ở AG3 sinh ra) mà làm sập runner thì cả câu mất, thay vì
    # rơi êm về R0. Kiểm ở đây vì `dimension_of` là nơi đầu tiên chạm vào slot.
    for slot in NODE_ARITY.get(k, ()):
        if not n.get(slot):
            raise IRError("INVALID_ARITY", f"{k} thiếu '{slot}'")

    if k == "FactRef":
        return value_kind_of.get(n["metric_id"], "money")
    if k == "Literal":
        return n.get("kind") or "scalar"
    if k == "Abs":
        return dimension_of(plan, n["child"], value_kind_of, seen)
    if k == "Return":
        return dimension_of(plan, n["child"], value_kind_of, seen)

    if k in ("Add", "Subtract"):
        a = dimension_of(plan, n["left"], value_kind_of, seen)
        b = dimension_of(plan, n["right"], value_kind_of, seen)
        if a != b:
            raise IRError("DIMENSION_MISMATCH", f"{k}: {a} vs {b}")
        return a
    if k == "Divide":
        a = dimension_of(plan, n["num"], value_kind_of, seen)
        b = dimension_of(plan, n["den"], value_kind_of, seen)
        if a == b:
            return "ratio"
        if b == "scalar":
            return a
        raise IRError("DIMENSION_MISMATCH", f"Divide: {a} / {b}")
    if k == "Multiply":
        a = dimension_of(plan, n["left"], value_kind_of, seen)
        b = dimension_of(plan, n["right"], value_kind_of, seen)
        lit = None
        for side in ("left", "right"):
            m = plan.node(n[side])
            if m["node"] == "Literal":
                lit = float(m["value"])
        # Quy ước DUY NHẤT biến ratio thành percentage. Nhân hằng khác giữ ratio.
        if {a, b} == {"ratio", "scalar"} and lit == 100.0:
            return "percentage"
        if b == "scalar":
            return a
        if a == "scalar":
            return b
        raise IRError("DIMENSION_MISMATCH", f"Multiply: {a} × {b}")
    raise IRError("AST_FORBIDDEN_NODE", k)


# ── validator · 7 luật, mỗi luật một test ──────────────────────────────────

def validate(plan: Plan, value_kind_of: dict[str, str]) -> list[str]:
    """→ danh sách mã lỗi. Rỗng = hợp lệ. KHÔNG ném — để báo cáo gom được."""
    errs: list[str] = []

    # 1 · root tồn tại và là Return
    root = plan.nodes.get(plan.root_id)
    if root is None:
        return ["MISSING_OUTPUT"]
    if root["node"] != "Return":
        errs.append("MISSING_OUTPUT")

    # 3 · node thuộc whitelist · 4 · arity đúng
    for nid, n in plan.nodes.items():
        k = n.get("node")
        if k not in NODE_ARITY:
            errs.append("AST_FORBIDDEN_NODE")
            continue
        for slot in NODE_ARITY[k]:
            child = n.get(slot)
            if not child or child not in plan.nodes:
                errs.append("INVALID_ARITY")

        # 5 · Divide bắt buộc có zero_policy hợp lệ
        if k == "Divide" and n.get("zero_policy") not in ZERO_POLICIES:
            errs.append("DIVIDE_NO_ZERO_POLICY")

        # 6 · Literal phải truy được nguồn
        if k == "Literal" and n.get("source") not in LITERAL_SOURCES:
            errs.append("LITERAL_UNSOURCED")

    # 2 · acyclic + 7 · dimension(root) == output.kind
    try:
        dim = dimension_of(plan, plan.root_id, value_kind_of)
        if dim != plan.output_kind:
            errs.append("DIMENSION_MISMATCH")
    except IRError as e:
        errs.append(e.code)

    # giữ thứ tự xuất hiện, bỏ trùng — báo cáo đọc dễ hơn
    ra, thay = [], set()
    for c in errs:
        if c not in thay:
            thay.add(c)
            ra.append(c)
    return ra


def leaves(plan: Plan) -> list[dict]:
    """Mọi `FactRef`, theo thứ tự id ổn định — dùng cho binder và evidence."""
    return [n for _, n in sorted(plan.nodes.items())
            if n["node"] == "FactRef"]


def literals(plan: Plan) -> list[dict]:
    return [n for _, n in sorted(plan.nodes.items()) if n["node"] == "Literal"]
