#!/usr/bin/env python3
"""O6 · Reference evaluator ĐỘC LẬP — CẤM import emitter.

VÌ SAO TỆP NÀY TỒN TẠI
----------------------
Nếu bộ chấm và bộ sinh dùng chung một hàm, thì "khớp" chỉ chứng minh hàm ấy
nhất quán với chính nó. Đó là lỗi R16, và dự án đã dính đúng nó một lần: luật
đơn vị `raw × 10^scale / hệ_số` được tuyên bố "khớp 21/21" trong khi bộ SINH
gold dùng chính công thức đó — tautology, zero thông tin.

O6 cài lại số học **từ đầu**, đọc operand từ gold provenance, và dùng để tách
hai loại lỗi mà số tổng gộp làm một:

    lỗi CHỌN Ô      emitter lấy operand khác gold  → O6 và emitter khác nhau
                                                     vì đầu vào khác nhau
    lỗi SỐ HỌC      emitter lấy ĐÚNG operand gold nhưng ra số khác O6
                                                   → lỗi công thức/đơn vị/dấu

Chỉ loại thứ hai là lỗi của tầng arithmetic. Không tách thì mọi cải tiến ranking
đều bị ghi nhầm thành "arithmetic tốt lên".

RÀNG BUỘC TỰ KIỂM: `--self-check` quét AST của chính tệp này và FAIL nếu thấy
bất kỳ import nào từ `execution.emit_*`. Ràng buộc bằng lời không phải ràng buộc.

Chạy:
    python3 tools/reference_eval_v1.py --self-check
    python3 tools/reference_eval_v1.py            # chấm gold + đối chiếu emitter
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Bảng đơn vị VIẾT LẠI TỪ ĐẦU. Cố ý KHÔNG import từ emit_lookup_v1 — nếu bảng
# ở đó sai thì bộ chấm phải phát hiện, không được sai theo.
UNIT_DIVISOR = {
    "dong": 1.0, "nghin": 1e3, "trieu": 1e6, "ty": 1e9,
    "tram_ty": 1e11, "nghin_ty": 1e12,
}


def _operands(g: dict) -> list[tuple[str, float]]:
    """(slot, giá trị quy về ĐỒNG) theo provenance gold, giữ thứ tự khai báo."""
    return [(s["slot"], float(s["raw"]) * (10 ** int(s.get("scale_exponent") or 0)))
            for s in g["provenance"]]


def reference_answer(g: dict) -> dict:
    """Tính đáp án tham chiếu từ operand gold + công thức gold.

    Không đọc work.db, không gọi ranker, không import emitter.
    """
    lop = g["lop"]
    ops = _operands(g)
    unit = g.get("don_vi_hoi")
    div = UNIT_DIVISOR.get(unit)

    if lop == "argmax_year":
        years = [int(s.split("/")[1]) for s, _ in ops]
        vals = [v for _, v in ops]
        top = max(vals)
        if vals.count(top) > 1:
            return {"ok": False, "reason": "ARGMAX_TIE"}
        return {"ok": True, "value": float(years[vals.index(top)]), "unit": "year"}

    if lop == "percentage_change":
        if len(ops) != 2:
            return {"ok": False, "reason": f"PCT_NEEDS_2_OPS_GOT_{len(ops)}"}
        a, b = ops[0][1], ops[1][1]
        if a == 0:
            return {"ok": False, "reason": "ZERO_DENOMINATOR"}
        return {"ok": True, "value": (b - a) / abs(a) * 100.0, "unit": "percent"}

    if div is None:
        return {"ok": False, "reason": f"UNIT_UNKNOWN:{unit}"}

    if lop == "difference":
        if len(ops) != 2:
            return {"ok": False, "reason": f"DIFF_NEEDS_2_OPS_GOT_{len(ops)}"}
        a, b = ops[0][1], ops[1][1]
        # HAI CHIỀU đều được báo. Gold-45 KHÔNG nhất quán chiều trừ ở lớp
        # cross-entity (4/5 là "vế sau − vế trước", qid 740 ngược lại), nên bộ
        # chấm không được chọn hộ một chiều rồi gọi là đúng.
        return {"ok": True, "value": (b - a) / div, "value_reversed": (a - b) / div,
                "unit": unit, "sign_ambiguous": True}

    if lop == "sum":
        return {"ok": True, "value": sum(v for _, v in ops) / div, "unit": unit}
    if lop == "average":
        return {"ok": True, "value": sum(v for _, v in ops) / len(ops) / div,
                "unit": unit}
    if lop == "lookup":
        if len(ops) != 1:
            return {"ok": False, "reason": f"LOOKUP_NEEDS_1_OP_GOT_{len(ops)}"}
        return {"ok": True, "value": ops[0][1] / div, "unit": unit}
    return {"ok": False, "reason": f"LOP_KHONG_HO_TRO:{lop}"}


def close(a, b, tol: float = 1e-6) -> bool:
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if a != a or b != b:
        return False
    return abs(a) <= tol if b == 0 else abs(a - b) / abs(b) <= tol


def self_check() -> int:
    """FAIL nếu tệp này import bất cứ thứ gì từ tầng emitter."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    bad = []
    for n in ast.walk(tree):
        mods = []
        if isinstance(n, ast.Import):
            mods = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            mods = [n.module or ""]
        for m in mods:
            if "emit" in m or "operand_pipeline" in m or "fact_rank" in m:
                bad.append(m)
    if bad:
        print(f"✗ O6 IMPORT TỪ TẦNG EMITTER: {bad} — vi phạm ràng buộc độc lập",
              file=sys.stderr)
        return 1
    print("✓ self-check: O6 không import emitter/pipeline/ranker")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-check", action="store_true")
    ap.add_argument("--traces", default="evaluation/arith_traces_v1.jsonl")
    ap.add_argument("--rung", default="C3")
    a = ap.parse_args()
    if a.self_check:
        return self_check()
    if self_check() != 0:
        return 1

    gold = {g["qid"]: g for g in (json.loads(l) for l in
            (ROOT / "data/dev/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")}

    # ── phần 1: O6 tự chấm GOLD (bắt gold tự mâu thuẫn) ────────────────────
    g_ok = g_bad = g_skip = 0
    gold_conflicts = []
    for q, g in sorted(gold.items()):
        r = reference_answer(g)
        if not r["ok"]:
            g_skip += 1
            gold_conflicts.append({"qid": q, "lop": g["lop"], "reason": r["reason"]})
            continue
        hit = close(r["value"], g["dap_an_gold"])
        rev = r.get("value_reversed") is not None and close(r["value_reversed"],
                                                           g["dap_an_gold"])
        if hit or rev:
            g_ok += 1
            if r.get("sign_ambiguous") and not hit and rev:
                gold_conflicts.append({"qid": q, "lop": g["lop"],
                                       "reason": "SIGN_CONVENTION_REVERSED",
                                       "o6": r["value"], "gold": g["dap_an_gold"]})
        else:
            g_bad += 1
            gold_conflicts.append({"qid": q, "lop": g["lop"], "reason": "O6_KHAC_GOLD",
                                   "o6": r["value"], "gold": g["dap_an_gold"]})

    # ── phần 2: tách lỗi CHỌN Ô khỏi lỗi SỐ HỌC của emitter ────────────────
    tp = ROOT / a.traces
    split = {"n": 0, "operand_dung_va_so_hoc_dung": 0, "operand_dung_nhung_so_hoc_sai": 0,
             "operand_sai": 0, "abstain": 0}
    arith_defects = []
    if tp.is_file():
        for line in tp.open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("rung") != a.rung or not r.get("enabled"):
                continue
            split["n"] += 1
            if r.get("abstain"):
                split["abstain"] += 1
                continue
            g = gold[r["qid"]]
            if r["operand_top1"] == r["n_slot_gold"] and r["n_slot_emitted"] == r["n_slot_gold"]:
                ref = reference_answer(g)
                same = ref["ok"] and (close(r["answer"], ref["value"], 1e-6) or
                                      (ref.get("value_reversed") is not None and
                                       close(r["answer"], ref["value_reversed"], 1e-6)))
                if same:
                    split["operand_dung_va_so_hoc_dung"] += 1
                else:
                    split["operand_dung_nhung_so_hoc_sai"] += 1
                    arith_defects.append({"qid": r["qid"], "lop": g["lop"],
                                          "emitter": r["answer"],
                                          "o6": ref.get("value"),
                                          "expr": r.get("expr")})
            else:
                split["operand_sai"] += 1

    rep = {
        "_schema": "reference_eval (O6) v1 — bộ chấm độc lập, cấm import emitter",
        "date": "2026-08-21",
        "independence_self_check": "PASS",
        "dataset": "gold_dap_an_v1 (45 câu)",
        "evaluation_mode": "TRAIN_FIT / REGRESSION-ONLY",
        "phan_1_O6_cham_GOLD": {
            "khop": g_ok, "khac": g_bad, "khong_tinh_duoc": g_skip,
            "y_nghia": ("O6 cài lại số học từ đầu. Ô 'khác' là chỗ GOLD tự mâu "
                        "thuẫn hoặc quy ước chưa khai — không phải lỗi emitter."),
            "xung_dot": gold_conflicts,
        },
        "phan_2_tach_loi_emitter": split | {
            "y_nghia": ("`operand_dung_nhung_so_hoc_sai` là lỗi DUY NHẤT thuộc "
                        "tầng arithmetic. Các ô còn lại là lỗi chọn ô/ranking."),
            "defects": arith_defects,
        },
        "command": "python3 tools/reference_eval_v1.py",
    }
    (ROOT / "reports/reference_eval_v1.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nO6 chấm GOLD: khớp {g_ok} · khác {g_bad} · không tính được {g_skip}")
    for c in gold_conflicts[:8]:
        print("   ", json.dumps(c, ensure_ascii=False))
    print(f"\nTách lỗi emitter ({a.rung}): {json.dumps(split, ensure_ascii=False)}")
    for d in arith_defects[:5]:
        print("   ", json.dumps(d, ensure_ascii=False))
    print("-> reports/reference_eval_v1.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
