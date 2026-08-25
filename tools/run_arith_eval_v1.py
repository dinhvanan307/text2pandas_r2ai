#!/usr/bin/env python3
"""Đo arithmetic engine trên gold-45 + báo đủ metric review 131 §3.3 đòi.

Metric bắt buộc (review 131 §3.3):
    pool recall · operand top1/top3 · full-plan exact · duplicate rate
    ambiguity rate · downstream numeric exact · p50/p95 latency · peak cand/QID

Tách bạch hai thứ hay bị gộp:
    operand top1   — chọn ĐÚNG Ô cho từng slot
    full-plan exact — ĐÚNG MỌI slot của một câu (điều kiện cần để số học đúng)
    numeric exact  — đáp án cuối khớp gold trong tolerance

Một câu có operand top1 = 4/5 slot vẫn cho đáp án SAI. Vì vậy full-plan exact
mới là mẫu số thực tế của tầng số học, không phải top1 trung bình.

Chạy:  python3 tools/run_arith_eval_v1.py [--rung C2A|C2B|C3]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from execution.emit_arith_v1 import ARITH_INTENTS, LADDER, emit  # noqa: E402
from execution.operand_pipeline_v1 import slots_for  # noqa: E402
from build_candidate_v1 import khop, load_control, registry_labels  # noqa: E402


def mcnemar_exact(b: int, c: int) -> float:
    """p hai phía trên các cặp BẤT ĐỒNG. Không có p thì +2 và +20 trông giống nhau."""
    from math import comb
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / (2 ** n))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """CI Wilson — dùng cho tỷ lệ trên n nhỏ, nơi CI chuẩn cho cận ngoài [0,1]."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (round(max(0.0, c - h), 4), round(min(1.0, c + h), 4))

TOL = 0.01


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rung", default=None, choices=sorted(LADDER))
    a = ap.parse_args()
    rungs = [a.rung] if a.rung else list(LADDER)

    con = sqlite3.connect(
        f"file:{ROOT/'artifacts/retrieval/work.db'}?mode=ro&immutable=1", uri=True)
    plans = {p["qid"]: p for p in (json.loads(l) for l in
             (ROOT / "evaluation/question_plans_1012.jsonl").open(encoding="utf-8"))}
    gold = {g["qid"]: g for g in (json.loads(l) for l in
            (ROOT / "data/dev/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")}
    labs = registry_labels()

    # Tập đo: các câu gold có intent số học. `lop` của gold là nhãn người phân
    # xử — dùng nó làm intent để KHÔNG lẫn lỗi phân loại intent vào lỗi số học.
    targets = [q for q, g in sorted(gold.items()) if g["lop"] in ARITH_INTENTS]
    print(f"câu arithmetic trong gold-45: {len(targets)}")

    out_rows: list[dict] = []
    summary = {}
    for rung in rungs:
        fl = LADDER[rung]
        rows = []
        lat = []
        for q in targets:
            g, plan = gold[q], plans[q]
            intent = g["lop"]
            t0 = time.time()
            try:
                res = emit(con, plan, intent, fl, labs)
            except Exception as e:
                res = {"abstain": True, "abstain_reason": f"EXCEPTION:{type(e).__name__}:{e}",
                       "intent": intent}
            if res is None:
                # `emit` trả None khi cờ intent TẮT — đó là hành vi đúng, không
                # phải lỗi. Chuẩn hoá thành abstain có lý do để bảng đếm được.
                res = {"abstain": True, "abstain_reason": "INTENT_FLAG_OFF",
                       "intent": intent}
            dt = time.time() - t0
            if fl.enabled(intent):
                lat.append(dt)

            # ── operand-level: so slot đã chọn với provenance gold ──────────
            gold_slots = {s["slot"]: (s["ref"], str(s["raw"])) for s in g["provenance"]}
            per = (res or {}).get("per_slot") or {}
            n_slot_gold = len(gold_slots)
            top1 = top3 = 0
            for v in per.values():
                want = gold_slots.get(v["slot"])
                p = v.get("pick")
                if want and p and p.get("evidence_ref") == want[0] and str(p.get("value")) == want[1]:
                    top1 += 1
            full_plan = (n_slot_gold > 0 and top1 == n_slot_gold
                         and len(per) == n_slot_gold)

            ok = (not res.get("abstain")) and khop(res.get("answer"), g["dap_an_gold"], TOL)
            rows.append({
                "qid": q, "intent": intent, "enabled": fl.enabled(intent),
                "abstain": bool(res.get("abstain")),
                "abstain_reason": res.get("abstain_reason"),
                "n_slot_gold": n_slot_gold, "n_slot_emitted": len(per),
                "operand_top1": top1, "full_plan_exact": full_plan,
                "answer": res.get("answer"), "gold": g["dap_an_gold"],
                "numeric_exact": ok, "expr": res.get("expr"),
                "metrics": res.get("metrics", {}), "latency_s": round(dt, 4),
                "consistency": (res.get("consistency") or {}).get("reason"),
                "per_slot": per,
            })

        act = [r for r in rows if r["enabled"]]
        n_act = len(act)
        emitted = [r for r in act if not r["abstain"]]
        slot_tot = sum(r["n_slot_gold"] for r in act)
        slot_hit = sum(r["operand_top1"] for r in act)
        dup = sum(r["metrics"].get("n_dup_removed", 0) for r in act)
        scored = sum(r["metrics"].get("n_scored", 0) for r in act)
        lat.sort()
        summary[rung] = {
            "flags": fl.name,
            "n_target": len(targets), "n_intent_bat": n_act,
            "n_emit": len(emitted), "n_abstain": n_act - len(emitted),
            "abstain_reason": dict(Counter(r["abstain_reason"] for r in act if r["abstain"])),
            "operand_top1": f"{slot_hit}/{slot_tot}",
            "operand_top1_rate": round(slot_hit / slot_tot, 4) if slot_tot else None,
            "full_plan_exact": f"{sum(r['full_plan_exact'] for r in act)}/{n_act}",
            "numeric_exact": f"{sum(r['numeric_exact'] for r in act)}/{n_act}",
            "numeric_exact_rate": round(sum(r["numeric_exact"] for r in act) / n_act, 4) if n_act else None,
            "ambiguity_rate": round(sum(1 for r in act if str(r["abstain_reason"] or "").startswith("SLOT_")) / n_act, 4) if n_act else None,
            "duplicate_removed": dup,
            "duplicate_rate": round(dup / scored, 4) if scored else 0.0,
            "latency_s": {"p50": round(lat[len(lat) // 2], 3) if lat else None,
                          "p95": round(lat[int(len(lat) * 0.95)], 3) if lat else None},
            "theo_intent": {},
        }
        by = defaultdict(lambda: {"n": 0, "emit": 0, "exact": 0})
        for r in act:
            b = by[r["intent"]]
            b["n"] += 1
            b["emit"] += (not r["abstain"])
            b["exact"] += r["numeric_exact"]
        summary[rung]["theo_intent"] = {k: dict(v) for k, v in sorted(by.items())}
        out_rows.append({"rung": rung, "rows": rows})

        s = summary[rung]
        print(f"\n── {rung} · {fl.name}")
        print(f"   bật {s['n_intent_bat']} câu · emit {s['n_emit']} · abstain {s['n_abstain']}")
        print(f"   operand top1 {s['operand_top1']} · full-plan {s['full_plan_exact']}"
              f" · numeric exact {s['numeric_exact']}")
        print(f"   duplicate {s['duplicate_rate']:.1%} · ambiguity {s['ambiguity_rate']}"
              f" · p50 {s['latency_s']['p50']}s p95 {s['latency_s']['p95']}s")
        if s["abstain_reason"]:
            print(f"   abstain: {s['abstain_reason']}")

    # ── paired vs C0 trên CÙNG tập câu arithmetic ──────────────────────────
    sub0, _ = load_control()
    c0 = {r["id"]: r for r in sub0}
    paired = {}
    for blk in out_rows:
        rows = {r["qid"]: r for r in blk["rows"] if r["enabled"]}
        base = {q: khop(c0[q].get("answer"), gold[q]["dap_an_gold"], TOL) for q in rows}
        cand = {q: (rows[q]["numeric_exact"] if not rows[q]["abstain"] else base[q])
                for q in rows}
        imp = sorted(q for q in rows if cand[q] and not base[q])
        reg = sorted(q for q in rows if base[q] and not cand[q])
        n = len(rows)
        k = sum(cand.values())
        paired[blk["rung"]] = {
            "n_paired": n,
            "C0_dung": sum(base.values()), "candidate_dung": k,
            "net": k - sum(base.values()),
            "improved": imp, "regressed": reg,
            "discordant_table": {"b_improved": len(imp), "c_regressed": len(reg)},
            "mcnemar_p_hai_phia": round(mcnemar_exact(len(imp), len(reg)), 4),
            "wilson_ci95_acc": wilson(k, n),
            "effect_size_delta_acc": round(k / n - sum(base.values()) / n, 4) if n else None,
        }
        pr = paired[blk["rung"]]
        print(f"   paired vs C0: {pr['C0_dung']} -> {pr['candidate_dung']} "
              f"(net {pr['net']:+d}) · +{len(imp)}/-{len(reg)} · "
              f"McNemar p={pr['mcnemar_p_hai_phia']} · CI95 {pr['wilson_ci95_acc']}")

    rep = {
        "_schema": "arith_eval v1 — metric đầy đủ theo review 131 §3.3",
        "date": "2026-08-21",
        "dataset": "gold_dap_an_v1 · 24 câu non-lookup",
        "evaluation_mode": "TRAIN_FIT / REGRESSION-ONLY",
        "provenance": "gold sinh bởi tools/gold_dap_an/02_phan_xu_o.py; 45/45 row_label_exact",
        "denominator": "n_intent_bat = số câu có intent được bật cờ",
        "tolerance_tuong_doi": TOL,
        "baseline_C0_tren_cung_tap": "1/24 = 4,17%",
        "summary": summary,
        "paired_vs_C0": paired,
    }
    (ROOT / "reports/arith_eval_v1.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    with (ROOT / "evaluation/arith_traces_v1.jsonl").open("w", encoding="utf-8") as f:
        for blk in out_rows:
            for r in blk["rows"]:
                f.write(json.dumps({"rung": blk["rung"], **r}, ensure_ascii=False) + "\n")
    print("\n-> reports/arith_eval_v1.json · evaluation/arith_traces_v1.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
