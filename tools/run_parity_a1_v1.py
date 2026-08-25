#!/usr/bin/env python3
"""A1 · Parity ablation ↔ production theo TỪNG QID + bảng guard.

Đóng doc 140 §3.4 (Gate A1) và §2.4 (bảng guard).

Doc 140 nói rất đúng một điều: **khớp tổng không phải parity**. Hai nhánh có thể
cùng ra `8/24` mà sai ở hai câu khác nhau. Vì vậy ở đây so ba DANH SÁCH:

    dung[]      QID có numeric_exact
    sai[]       QID emit ra số nhưng sai
    abstain[]   QID không emit, kèm lý do

PASS chỉ khi cả ba danh sách trùng nhau **phần tử một**.

Cách đạt parity: không viết lại nhánh ablation cho giống production, mà cho cả
hai đi qua ĐÚNG một đoạn code — `emit()` của `emit_arith_v1` — chỉ khác tham số
`scorer` của `PipelineFlags`. Parity khi đó đúng theo cấu tạo. Nếu vẫn lệch thì
lệch ấy là thật, không phải giả tạo do hai đường ống.

Bảng guard `enforce_metric_consistency` (doc 140 §2.4) báo đủ bốn ô:

    improved       guard bật, và nhờ nó câu ĐÚNG (repair thành công)
    regressed      guard bật, và vì nó câu SAI (đáng lẽ đúng)
    abstain_dung   guard abstain, và đáp án không-guard cũng SAI
    abstain_sai    guard abstain, nhưng đáp án không-guard lại ĐÚNG

Guard không kích hoạt ở câu nào thì ghi `not_exercised` — KHÔNG suy ra PASS.

Chạy:  python3 tools/run_parity_a1_v1.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from execution.emit_arith_v1 import ARITH_INTENTS, ARITH_PIPE, emit  # noqa: E402
from execution.emit_lookup_v1 import asked_unit  # noqa: E402
from execution.score_v2 import ScoreFlags  # noqa: E402
from build_candidate_v1 import khop, registry_labels  # noqa: E402

TOL = 0.01


def chay(con, qids, gold, plans, labs, pipe, arith_flags) -> dict:
    """→ {qid: {numeric_exact, abstain, abstain_reason, answer, guard}}"""
    from execution.emit_arith_v1 import ArithFlags
    out = {}
    for q in qids:
        g, plan = gold[q], plans[q]
        fl = replace(arith_flags, pipeline=pipe)
        r = emit(con, plan, g["lop"], fl, labs)
        if r is None:
            out[q] = {"numeric_exact": False, "abstain": True,
                      "abstain_reason": "INTENT_OFF", "guard": None}
            continue
        ab = bool(r.get("abstain"))
        ne = (not ab) and khop(r.get("answer"), g["dap_an_gold"], TOL)
        out[q] = {
            "numeric_exact": ne, "abstain": ab,
            "abstain_reason": r.get("abstain_reason"),
            "answer": r.get("answer"),
            "guard": (r.get("consistency") or {}).get("reason"),
        }
    return out


def bo_ba(res: dict) -> dict:
    return {
        "dung": sorted(q for q, v in res.items() if v["numeric_exact"]),
        "sai": sorted(q for q, v in res.items()
                      if not v["numeric_exact"] and not v["abstain"]),
        "abstain": sorted(q for q, v in res.items() if v["abstain"]),
    }


def main() -> int:
    from execution.emit_arith_v1 import LADDER
    con = sqlite3.connect(
        f"file:{ROOT/'data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db'}?mode=ro&immutable=1", uri=True)
    plans = {p["qid"]: p for p in (json.loads(l) for l in
             (ROOT / "data/curated/evaluation/legacy/question_plans_1012.jsonl").open(encoding="utf-8"))}
    gold = {g["qid"]: g for g in (json.loads(l) for l in
            (ROOT / "data/curated/dev-legacy/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")}
    labs = registry_labels()
    qids = sorted(q for q, g in gold.items() if g["lop"] in ARITH_INTENTS)
    C3 = LADDER["C3"]

    # ── parity ─────────────────────────────────────────────────────────────
    prod = chay(con, qids, gold, plans, labs, ARITH_PIPE, C3)
    abl = chay(con, qids, gold, plans, labs,
               replace(ARITH_PIPE, scorer=ScoreFlags()), C3)
    bp, ba = bo_ba(prod), bo_ba(abl)
    lech = {k: {"chi_production": sorted(set(bp[k]) - set(ba[k])),
                "chi_ablation": sorted(set(ba[k]) - set(bp[k]))}
            for k in ("dung", "sai", "abstain")}
    parity = all(not v["chi_production"] and not v["chi_ablation"]
                 for v in lech.values())

    # ── bảng guard ─────────────────────────────────────────────────────────
    no_guard = chay(con, qids, gold, plans, labs,
                    replace(ARITH_PIPE, metric_consistency=False), C3)
    g_tab = {"improved": [], "regressed": [], "abstain_dung": [],
             "abstain_sai": [], "not_exercised": []}
    for q in qids:
        a, b = prod[q], no_guard[q]
        bat = a["guard"] is not None or a["abstain_reason"] == "METRIC_MISMATCH_ACROSS_SLOTS"
        if not bat:
            g_tab["not_exercised"].append(q)
        elif a["abstain"]:
            (g_tab["abstain_sai"] if b["numeric_exact"] else g_tab["abstain_dung"]).append(q)
        elif a["numeric_exact"] and not b["numeric_exact"]:
            g_tab["improved"].append(q)
        elif b["numeric_exact"] and not a["numeric_exact"]:
            g_tab["regressed"].append(q)
        else:
            g_tab["not_exercised"].append(q)

    rep = {
        "_schema": "parity_a1 v1 — doc 140 §3.4 Gate A1 + §2.4 bảng guard",
        "date": "2026-08-21",
        "dataset": "gold_dap_an_v1 · 24 câu non-lookup",
        "evaluation_mode": "TRAIN_FIT",
        "qid_set": qids,

        "GATE_A1_parity": {
            "ket_qua": "PASS" if parity else "FAIL",
            "quy_uoc": "khớp theo TỪNG QID cả ba danh sách; khớp tổng KHÔNG tính",
            "production_C3": bp | {"n_dung": len(bp["dung"])},
            "ablation_S0": ba | {"n_dung": len(ba["dung"])},
            "lech_theo_danh_sach": lech,
            "cach_dat_duoc": ("cả hai nhánh gọi CÙNG emit() của emit_arith_v1, "
                              "chỉ khác tham số PipelineFlags.scorer"),
        },

        "bang_guard_enforce_metric_consistency": {
            k: {"n": len(v), "qids": v} for k, v in g_tab.items()} | {
            "doc_the_nao": ("`not_exercised` KHÔNG phải PASS — nó nghĩa là guard "
                            "chưa từng được thử ở câu đó. `abstain_sai` là ca "
                            "guard vứt bỏ đáp án ĐÚNG."),
            "quyet_dinh": "GIỮ guard. Chưa gỡ — cần người phân xử, xem báo cáo.",
        },

        "so_lieu_khong_guard": {"n_dung": sum(v["numeric_exact"]
                                              for v in no_guard.values())},
        "per_qid": {"production": prod, "ablation_S0": abl, "no_guard": no_guard},
        "command": "python3 tools/run_parity_a1_v1.py",
    }
    (ROOT / "reports/parity_a1_v1.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"GATE A1 parity : {rep['GATE_A1_parity']['ket_qua']}")
    print(f"  production C3 dung={len(bp['dung'])} sai={len(bp['sai'])} abstain={len(bp['abstain'])}")
    print(f"  ablation   S0 dung={len(ba['dung'])} sai={len(ba['sai'])} abstain={len(ba['abstain'])}")
    for k, v in lech.items():
        if v["chi_production"] or v["chi_ablation"]:
            print(f"  ✗ {k}: chỉ prod {v['chi_production']} · chỉ abl {v['chi_ablation']}")
    print("\nbảng guard enforce_metric_consistency:")
    for k, v in g_tab.items():
        print(f"  {k:15} {len(v):2}  {v}")
    print("-> reports/parity_a1_v1.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
