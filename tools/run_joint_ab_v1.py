#!/usr/bin/env python3
"""A/B joint search vs independent top-1 — Gate 2 của doc 134.

MỘT THỨ ĐỔI DUY NHẤT giữa hai nhánh: cách chọn BỘ operand.
Cùng lattice, cùng scoring_text, cùng emitter, cùng tolerance, cùng QID set.

Metric chính (Plan 133 §3, doc 134 §4.1):
    all_operands_pool_recall   gold có nằm trong lattice không
    operand_set_exact          ĐÚNG MỌI slot (không phải trung bình slot-recall)
    full_plan_exact            = operand_set_exact ở đây
    numeric_exact              đáp án cuối
    answer_query_consistency   emitter chạy được và ra số hữu hạn

Gate 2 (doc 134 §6): operand-set exact tăng >= 10 điểm % HOẶC numeric net rõ dương.

Chạy:  python3 tools/run_joint_ab_v1.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from execution.emit_arith_v1 import ARITH_INTENTS, compute  # noqa: E402
from execution.emit_lookup_v1 import asked_unit, metric_phrase, spec_text  # noqa: E402
from execution.joint_search_v1 import JointFlags, search  # noqa: E402
from execution.operand_pipeline_v1 import load_aliases  # noqa: E402
from build_candidate_v1 import khop, load_control, registry_labels  # noqa: E402

TOL = 0.01
ARMS = {
    "A_independent_top1": JointFlags(enabled=False),
    "B_joint_search": JointFlags(enabled=True),
}


def mcnemar(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(comb(n, i) for i in range(min(b, c) + 1)) / (2 ** n))


def main() -> int:
    con = sqlite3.connect(
        f"file:{ROOT/'data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db'}?mode=ro&immutable=1", uri=True)
    plans = {p["qid"]: p for p in (json.loads(l) for l in
             (ROOT / "evaluation/question_plans_1012.jsonl").open(encoding="utf-8"))}
    gold = {g["qid"]: g for g in (json.loads(l) for l in
            (ROOT / "data/curated/dev-legacy/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")}
    labs = registry_labels()
    al = load_aliases()
    sub0, _ = load_control()
    c0 = {r["id"]: r for r in sub0}

    qids = sorted(q for q, g in gold.items() if g["lop"] in ARITH_INTENTS)
    results: dict[str, dict[int, dict]] = {a: {} for a in ARMS}

    for arm, fl in ARMS.items():
        for q in qids:
            g, plan = gold[q], plans[q]
            lop = g["lop"]
            phrase = metric_phrase(plan, labs)
            st = spec_text(plan, phrase)
            t0 = time.time()
            try:
                r = search(con, plan, lop, fl, st, al)
            except Exception as e:
                r = {"ok": False, "reason": f"EXC:{type(e).__name__}:{e}", "ops": {}}
            dt = time.time() - t0

            gs = {s["slot"]: (s["ref"], str(s["raw"])) for s in g["provenance"]}
            ops = r.get("ops") or {}
            hit = sum(1 for c in ops.values()
                      if gs.get(c.get("_slot")) and c["evidence_ref"] == gs[c["_slot"]][0]
                      and str(c["value"]) == gs[c["_slot"]][1])
            set_exact = bool(ops) and hit == len(gs) and len(ops) == len(gs)

            ans, exact, reason = None, False, r.get("reason")
            if r.get("ok"):
                unit, factor = asked_unit(plan)
                if lop == "percentage_change":
                    factor = 1.0
                comp = compute(lop, ops, factor)
                if not comp.get("abstain"):
                    ans = comp["answer"]
                    exact = khop(ans, g["dap_an_gold"], TOL)
                else:
                    reason = comp.get("abstain_reason")

            results[arm][q] = {
                "qid": q, "intent": lop, "ok": bool(r.get("ok")), "reason": reason,
                "n_slot_gold": len(gs), "operand_hit": hit,
                "operand_set_exact": set_exact, "answer": ans,
                "gold": g["dap_an_gold"], "numeric_exact": exact,
                "rejected_by": r.get("rejected_by"),
                "lattice_sizes": r.get("lattice_sizes"),
                "latency_s": round(dt, 4),
                "picked": {k: {"uid": v.get("observation_uid"),
                               "ref": v.get("evidence_ref"),
                               "label": v.get("metric_label"),
                               "value": v.get("value")} for k, v in ops.items()},
            }

    # ── pool recall THẬT của lattice ───────────────────────────────────────
    # Bản đầu tính từ ô ĐÃ CHỌN rồi gọi là "pool recall" — sai tên và sai số:
    # nó đo resolver chứ không đo lattice. Ở đây dựng lại lattice và hỏi đúng
    # một câu: gold có NẰM TRONG đó không.
    from execution.joint_search_v1 import semantic_collapse
    from execution.operand_pipeline_v1 import PipelineFlags as _PF, candidates_for_slot as _cfs, slots_for as _sf
    fl_b = ARMS["B_joint_search"]
    pipe = _PF(depth=fl_b.lattice_depth, shortlist_m=fl_b.lattice_depth)
    pool_slot_hit = pool_slot_tot = 0
    pool_set_ok = 0
    for q in qids:
        g, plan = gold[q], plans[q]
        gs = {s["slot"]: (s["ref"], str(s["raw"])) for s in g["provenance"]}
        st = spec_text(plan, metric_phrase(plan, labs))
        hits = 0
        for s in _sf(plan, g["lop"], al):
            want = gs.get(s.name)
            if not want:
                continue
            pool_slot_tot += 1
            cands, _ = _cfs(con, plan, s, pipe, scoring_text=st)
            lat = semantic_collapse(cands, fl_b.top_m)
            if any(c["evidence_ref"] == want[0] and str(c["value"]) == want[1]
                   for c in lat):
                pool_slot_hit += 1
                hits += 1
        if gs and hits == len(gs):
            pool_set_ok += 1
    pool_hit = pool_set_ok

    summary = {}
    for arm in ARMS:
        rs = [results[arm][q] for q in qids]
        n = len(rs)
        se = sum(r["operand_set_exact"] for r in rs)
        ne = sum(r["numeric_exact"] for r in rs)
        slot_tot = sum(r["n_slot_gold"] for r in rs)
        slot_hit = sum(r["operand_hit"] for r in rs)
        lat = sorted(r["latency_s"] for r in rs)
        summary[arm] = {
            "flags": ARMS[arm].name,
            "n": n,
            "operand_slot_recall": f"{slot_hit}/{slot_tot}",
            "operand_set_exact": f"{se}/{n}",
            "operand_set_exact_rate": round(se / n, 4),
            "numeric_exact": f"{ne}/{n}",
            "numeric_exact_rate": round(ne / n, 4),
            "answer_query_consistency": f"{sum(1 for r in rs if r['answer'] is not None)}/{n}",
            "khong_dung_duoc_bo": dict(Counter(r["reason"] for r in rs if not r["ok"])),
            "latency_s": {"p50": lat[n // 2], "p95": lat[int(n * 0.95)]},
            "theo_intent": {},
        }
        by = defaultdict(lambda: {"n": 0, "set_exact": 0, "numeric": 0})
        for r in rs:
            b = by[r["intent"]]
            b["n"] += 1
            b["set_exact"] += r["operand_set_exact"]
            b["numeric"] += r["numeric_exact"]
        summary[arm]["theo_intent"] = {k: dict(v) for k, v in sorted(by.items())}

    A, B = summary["A_independent_top1"], summary["B_joint_search"]
    se_delta = B["operand_set_exact_rate"] - A["operand_set_exact_rate"]
    a_ok = {q: results["A_independent_top1"][q]["numeric_exact"] for q in qids}
    b_ok = {q: results["B_joint_search"][q]["numeric_exact"] for q in qids}
    imp = sorted(q for q in qids if b_ok[q] and not a_ok[q])
    reg = sorted(q for q in qids if a_ok[q] and not b_ok[q])

    gate_pass = (se_delta >= 0.10) or (len(imp) - len(reg) > 0 and
                                       mcnemar(len(imp), len(reg)) <= 0.05)
    rep = {
        "_schema": "joint_ab v1 — Gate 2 doc 134",
        "date": "2026-08-21",
        "dataset": "gold_dap_an_v1 · 24 câu non-lookup",
        "denominator": len(qids), "qids": qids,
        "evaluation_mode": "TRAIN_FIT / REGRESSION-ONLY",
        "thay_doi_duy_nhat": "cách chọn BỘ operand (independent top-1 ↔ joint beam)",
        "all_operands_pool_recall": {
            "slot_level": f"{pool_slot_hit}/{pool_slot_tot}",
            "slot_rate": round(pool_slot_hit / pool_slot_tot, 4) if pool_slot_tot else None,
            "set_level_MOI_slot_trong_lattice": f"{pool_set_ok}/{len(qids)}",
            "y_nghia": ("TRẦN của joint search. Joint search không thể chọn ô "
                        "không có trong lattice — set_level là chặn trên tuyệt đối "
                        "của operand_set_exact."),
        },
        "summary": summary,
        "paired_B_vs_A": {
            "improved": imp, "regressed": reg,
            "discordant_table": {"b": len(imp), "c": len(reg)},
            "net": len(imp) - len(reg),
            "mcnemar_p_hai_phia": round(mcnemar(len(imp), len(reg)), 4),
        },
        "operand_set_exact_delta_diem_phan_tram": round(se_delta * 100, 2),
        "GATE_2": {
            "dieu_kien": "operand_set_exact tăng >=10 điểm % HOẶC numeric net dương có p<=0,05",
            "ket_qua": "PASS" if gate_pass else "FAIL",
        },
        "per_qid": {a: [results[a][q] for q in qids] for a in ARMS},
        "command": "python3 tools/run_joint_ab_v1.py",
    }
    (ROOT / "reports/joint_ab_v1.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"n = {len(qids)} · lattice pool recall: slot {pool_slot_hit}/{pool_slot_tot}"
          f" · SET (mọi slot) {pool_set_ok}/{len(qids)}  ← TRẦN của joint search\n")
    print(f"{'nhánh':22} {'slot recall':>12} {'set_exact':>10} {'numeric':>9} {'p95':>7}")
    for a in ARMS:
        s = summary[a]
        print(f"{a:22} {s['operand_slot_recall']:>12} {s['operand_set_exact']:>10} "
              f"{s['numeric_exact']:>9} {s['latency_s']['p95']:>7.2f}s")
    print(f"\noperand_set_exact delta: {se_delta*100:+.1f} điểm %")
    print(f"numeric paired B vs A: +{len(imp)}/-{len(reg)} net {len(imp)-len(reg):+d} "
          f"· McNemar p={rep['paired_B_vs_A']['mcnemar_p_hai_phia']}")
    print(f"improved: {imp}\nregressed: {reg}")
    print(f"\nGATE_2: {rep['GATE_2']['ket_qua']}")
    rj = Counter()
    for r in rep["per_qid"]["B_joint_search"]:
        for k, v in (r.get("rejected_by") or {}).items():
            rj[k] += v
    print(f"ràng buộc cứng loại: {dict(rj)}")
    print(f"không dựng được bộ: A={A['khong_dung_duoc_bo']} B={B['khong_dung_duoc_bo']}")
    print("-> reports/joint_ab_v1.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
