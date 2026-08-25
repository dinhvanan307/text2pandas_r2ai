#!/usr/bin/env python3
"""Formula registry wave 1 — 8 formula SAFE.

Parser tối giản cho `configs/answer_v2/formulas_v1.yaml` (không cần PyYAML).
Đọc tới khoá `needs_domain_confirmation:` thì dừng — mọi thứ sau đó **cố ý**
không được nạp, vì nạp một formula chưa phân xử vào registry deterministic tạo
sai số CÓ HỆ THỐNG trên cả lớp câu.

`expression` giữ nguyên dạng cây lồng; `ir_v1.from_expression` phẳng hoá nó cùng
với ràng buộc lá (entity/period/scope) do binder cung cấp.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from metric_ontology import chuan

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "configs/answer_v2/formulas_v1.yaml"


@dataclass(frozen=True)
class FormulaSpec:
    formula_id: str
    variant_id: str
    aliases: tuple[str, ...]
    leaves: tuple[str, ...]
    period_semantics: str
    same_entity: bool
    same_period: bool
    output_kind: str
    output_unit: str
    zero_policy: str
    expression: dict


def _scalar(v: str):
    v = v.strip().strip('"').strip("'")
    if v in ("true", "True"):
        return True
    if v in ("false", "False"):
        return False
    try:
        return float(v) if "." in v else int(v)
    except ValueError:
        return v


def _inline_map(raw: str) -> dict:
    """`{kind: ratio, unit: times}` → dict. Chỉ hỗ trợ map một tầng, đủ dùng."""
    out = {}
    for part in raw.strip()[1:-1].split(","):
        if ":" in part:
            k, _, v = part.partition(":")
            out[k.strip()] = _scalar(v)
    return out


def _parse_expr(lines: list[tuple[int, str]], i: int) -> tuple[dict, int]:
    """Đọc một khối `expression` thụt lề thành cây dict. Trả (cây, dòng kế)."""
    base = lines[i][0]
    node: dict = {}
    while i < len(lines):
        ind, s = lines[i]
        if ind < base:
            break
        if ind > base:                       # con của khoá vừa đọc, đã xử lý
            i += 1
            continue
        k, _, v = s.partition(":")
        k, v = k.strip(), v.strip()
        if v.startswith("{"):
            node[k] = _inline_map(v)
            i += 1
        elif v == "":
            child, i = _parse_expr(lines, i + 1)
            node[k] = child
        else:
            node[k] = _scalar(v)
            i += 1
    return node, i


def load(path: Path = CFG) -> dict[str, FormulaSpec]:
    raw = path.read_text(encoding="utf-8")
    raw = raw.split("\nneeds_domain_confirmation:")[0]     # dừng đúng chỗ
    lines = [(len(l) - len(l.lstrip()), l.strip())
             for l in raw.splitlines()
             if l.strip() and not l.strip().startswith("#")]

    out: dict[str, FormulaSpec] = {}
    cur: dict = {}
    i = 0
    in_f = False
    while i < len(lines):
        ind, s = lines[i]
        if s.startswith("formulas:"):
            in_f = True
            i += 1
            continue
        if not in_f:
            i += 1
            continue
        if s.startswith("- formula_id:"):
            if cur.get("formula_id"):
                out[cur["formula_id"]] = _build(cur)
            cur = {"formula_id": s.split(":", 1)[1].strip()}
            i += 1
            continue
        if s.startswith("expression:"):
            expr, i = _parse_expr(lines, i + 1)
            cur["expression"] = expr
            continue
        if ":" in s:
            k, _, v = s.partition(":")
            k, v = k.strip(), v.strip()
            if v.startswith("["):
                inner = v[1:-1].strip()
                cur[k] = ([x.strip().strip('"').strip("'")
                           for x in inner.split(",") if x.strip()] if inner else [])
            elif v.startswith("{"):
                cur[k] = _inline_map(v)
            elif v == "":
                cur[k] = []
                i += 1
                while i < len(lines) and lines[i][1].startswith("- "):
                    cur[k].append(lines[i][1][2:].strip().strip('"').strip("'"))
                    i += 1
                continue
            else:
                cur[k] = _scalar(v)
        i += 1
    if cur.get("formula_id"):
        out[cur["formula_id"]] = _build(cur)
    return out


def _build(d: dict) -> FormulaSpec:
    o = d.get("output") or {}
    return FormulaSpec(
        formula_id=d["formula_id"],
        variant_id=str(d.get("variant_id", "default")),
        aliases=tuple(chuan(a) for a in d.get("aliases", [])),
        leaves=tuple(d.get("leaves", [])),
        period_semantics=str(d.get("period_semantics", "point_in_time")),
        same_entity=bool(d.get("same_entity", True)),
        same_period=bool(d.get("same_period", True)),
        output_kind=str(o.get("kind", "ratio")),
        output_unit=str(o.get("unit", "times")),
        zero_policy=str(d.get("zero_policy", "unresolved")),
        expression=d.get("expression") or {},
    )


def with_zero_policy(expr: dict, policy: str) -> dict:
    """Gắn `zero_policy` vào MỌI `Divide` trong cây.

    Đặt ở đây thay vì bắt YAML lặp lại từng node: luật 5 của validator đòi mọi
    `Divide` có policy, và quên một chỗ trong YAML là lỗi im lặng.
    """
    if not isinstance(expr, dict):
        return expr
    out = {k: with_zero_policy(v, policy) if isinstance(v, dict) else v
           for k, v in expr.items()}
    if out.get("node") == "Divide":
        out["zero_policy"] = policy
    return out


def tim_theo_cau_hoi(specs: dict[str, FormulaSpec], question: str) -> FormulaSpec | None:
    """Khớp alias formula trong câu hỏi. Alias DÀI NHẤT thắng.

    Alias dài cụ thể hơn: `"ty so thanh toan nhanh"` phải thắng
    `"thanh toan"` nếu sau này có alias ngắn như vậy.
    """
    q = chuan(question)
    tot, best = None, 0
    for sp in specs.values():
        for a in sp.aliases:
            if a and a in q and len(a) > best:
                best, tot = len(a), sp
    return tot
