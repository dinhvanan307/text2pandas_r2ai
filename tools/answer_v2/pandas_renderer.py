#!/usr/bin/env python3
"""Renderer IR → biểu thức pandas MỘT DÒNG, chạy được trong `_safe_env`.

WHITELIST KHÔNG PHẢI DO TÔI CHỌN — nó đã bị code chốt cứng.
`tools/replay_submission_v1.py::_safe_env` cấp đúng:

    pd, np, float, int, abs, round, min, max, sum, len, str,  __builtins__ = {}

Nghĩa là **không có** `sorted`, `list`, `dict`, `any`, `all`, `zip`, `map`,
`filter`. Doc 144 §12.2 để ngỏ ("nếu AST policy cho phép") — nhưng policy đã tồn
tại và không mơ hồ. Renderer chỉ được phát trong tập trên.

⚠️ `_safe_env` là môi trường replay **local**. Môi trường chấm của BTC là
`UNKNOWN` (bản chụp B không nói). Nên renderer nằm trong **giao** của `_safe_env`
và pandas/numpy phổ thông: chỉ boolean mask + `['value'].values[0]` + số học.

Đồng thời tính GIÁ TRỊ bằng Python thuần trên cùng cây IR, để bất biến
`answer == eval(pandas_query)` được kiểm bằng **hai đường độc lập** chứ không
phải bằng cách gán `answer = eval(query)`.
"""
from __future__ import annotations

import re

import ir_v1

# Ký tự được phép trong biểu thức cuối. Dùng để chặn ở tầng ký tự, sau khi đã
# chặn ở tầng AST — hai lớp rẻ hơn một lớp.
#
# `__` KHÔNG được đặt trong nhóm có `\b` hai đầu: trong `x.__class__`, sau `__`
# là `c` — không có ranh giới từ — nên `\b__\b` trượt. Dunder phải bị chặn ở
# BẤT KỲ vị trí nào, nên nó là một nhánh riêng không có `\b`.
CAM = re.compile(r"__|\b(import|exec|eval|open|lambda|sorted|list|dict|any|all|"
                 r"zip|map|filter|getattr|setattr|globals|locals|compile|input)\b")


class RenderError(Exception):
    def __init__(self, code: str, detail: str = ""):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def _q(s: str) -> str:
    """Escape cho literal chuỗi trong biểu thức pandas."""
    return (s or "").replace("\\", "\\\\").replace("'", "\\'")


def _cell(bind: dict) -> str:
    v = bind["variable"]
    return (f"{v}[({v}['row_path'] == '{_q(bind['row_path'])}') & "
            f"({v}['col_label'] == '{_q(bind['col_label'])}')]['value'].values[0]")


def render(plan: ir_v1.Plan, bind: dict[str, dict]) -> tuple[str, float]:
    """→ (pandas_query, giá trị tính độc lập). Ném `RenderError` khi không dựng được."""

    def walk(nid: str) -> tuple[str, float]:
        n = plan.node(nid)
        k = n["node"]
        if k == "FactRef":
            b = bind.get(n["metric_id"])
            if b is None:
                raise RenderError("EVIDENCE_VAR_MISSING", n["metric_id"])
            return f"float({_cell(b)})", float(b["value_vnd"])
        if k == "Literal":
            if n.get("source") not in ir_v1.LITERAL_SOURCES:
                raise RenderError("LITERAL_UNSOURCED", str(n.get("value")))
            val = float(n["value"])
            # `repr` cho float giữ đủ chữ số để eval ra ĐÚNG cùng bit.
            return repr(val), val
        if k == "Abs":
            e, v = walk(n["child"])
            return f"abs({e})", abs(v)
        if k == "Return":
            return walk(n["child"])
        if k in ("Add", "Subtract", "Multiply"):
            le, lv = walk(n["left"])
            re_, rv = walk(n["right"])
            op = {"Add": "+", "Subtract": "-", "Multiply": "*"}[k]
            val = {"Add": lv + rv, "Subtract": lv - rv, "Multiply": lv * rv}[k]
            return f"({le} {op} {re_})", val
        if k == "Divide":
            ne, nv = walk(n["num"])
            de, dv = walk(n["den"])
            if dv == 0:
                # Không phát `x / 0`: chấm sẽ ra ZeroDivisionError hoặc inf.
                # `unresolved` là chính sách đã khai trong FormulaSpec.
                raise RenderError("ZERO_DENOMINATOR", n["id"])
            return f"({ne} / {de})", nv / dv
        raise RenderError("AST_FORBIDDEN_NODE", k)

    expr, val = walk(plan.root_id)
    query = f"float({expr})"
    if CAM.search(query):
        raise RenderError("AST_FORBIDDEN_NODE", "token cấm trong biểu thức")
    return query, float(val)


def doi_don_vi(query: str, val: float, unit_exponent: int | None) -> tuple[str, float]:
    """Đổi sang đơn vị câu hỏi NGAY TRONG biểu thức — giữ bất biến answer==eval.

    Chỉ áp cho đại lượng TIỀN. Ratio/percentage không có đơn vị tiền nên
    `unit_exponent` phải là None hoặc 0; gọi nhầm ở đó là lỗi logic phía trên,
    không phải ở đây.
    """
    if not unit_exponent:
        return query, val
    d = 10 ** int(unit_exponent)
    return f"({query} / {d})", val / d
