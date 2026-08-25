#!/usr/bin/env python3
"""Scan pandas_query of a submission for numeric scaling factors, via Python AST.

Emits ONE record per QID. Distinguishes:
  - literal occurrences (any numeric literal >= 1000 appearing anywhere)
  - direct top-level divisions  (expr / LIT)
  - direct top-level multiplications (expr * LIT)
  - nested divisions (inside a call / subscript)
No QID whitelist. Deterministic ordering.
"""
from __future__ import annotations
import ast, json, sys, argparse
from pathlib import Path

SCALE_LITERALS = {1e2: 2, 1e3: 3, 1e6: 6, 1e9: 9, 1e12: 12, 100: 2, 1000: 3,
                  1_000_000: 6, 1_000_000_000: 9, 1_000_000_000_000: 12}


def _num(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        v = _num(node.operand)
        return None if v is None else -v
    return None


def scan_one(query: str) -> dict:
    out = {
        "parse_ok": True,
        "parse_error": None,
        "literals": [],            # every numeric literal >= 100
        "div_factors": [],         # divisor literals of any BinOp Div
        "mul_factors": [],         # multiplier literals of any BinOp Mult
        "n_div_nodes": 0,
        "n_mul_nodes": 0,
    }
    try:
        tree = ast.parse(query, mode="eval")
    except SyntaxError as e:  # pragma: no cover - defensive
        out["parse_ok"] = False
        out["parse_error"] = str(e)
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            if abs(float(node.value)) >= 100:
                out["literals"].append(float(node.value))
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Div):
                out["n_div_nodes"] += 1
                v = _num(node.right)
                if v is not None:
                    out["div_factors"].append(v)
            elif isinstance(node.op, ast.Mult):
                out["n_mul_nodes"] += 1
                v = _num(node.right)
                if v is None:
                    v = _num(node.left)
                if v is not None:
                    out["mul_factors"].append(v)
    return out


def net_factor(rec: dict):
    """Net multiplicative constant applied by the query, or None if not derivable."""
    if not rec["parse_ok"]:
        return None
    f = 1.0
    for d in rec["div_factors"]:
        if d == 0:
            return None
        f /= d
    for m in rec["mul_factors"]:
        f *= m
    return f


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--submission", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--summary", required=True)
    a = p.parse_args()
    recs = json.loads(Path(a.submission).read_text(encoding="utf-8"))
    rows = []
    for r in recs:
        q = r.get("pandas_query") or ""
        s = scan_one(q)
        s["qid"] = r["id"]
        s["net_query_factor"] = net_factor(s)
        rows.append(s)
    rows.sort(key=lambda x: x["qid"])
    with open(a.out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    def cnt(pred):
        return sum(1 for r in rows if pred(r))

    summary = {
        "n_records": len(rows),
        "n_parse_ok": cnt(lambda r: r["parse_ok"]),
        "distinct_qid_with_literal_1e6": cnt(lambda r: any(x == 1_000_000 for x in r["literals"])),
        "occurrences_literal_1e6": sum(r["literals"].count(1_000_000.0) for r in rows),
        "distinct_qid_div_by_1e6": cnt(lambda r: any(x == 1_000_000 for x in r["div_factors"])),
        "occurrences_div_by_1e6": sum(r["div_factors"].count(1_000_000.0) for r in rows),
        "distinct_qid_any_div_literal": cnt(lambda r: bool(r["div_factors"])),
        "distinct_qid_any_mul_literal": cnt(lambda r: bool(r["mul_factors"])),
        "net_factor_histogram": {},
    }
    hist = {}
    for r in rows:
        k = repr(r["net_query_factor"])
        hist[k] = hist.get(k, 0) + 1
    summary["net_factor_histogram"] = dict(sorted(hist.items(), key=lambda kv: -kv[1]))
    Path(a.summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
