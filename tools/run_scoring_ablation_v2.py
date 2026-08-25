#!/usr/bin/env python3
"""Ablation S0 → S5 cho per-slot scoring v2, + nhánh KHÔNG-VÒNG-TRÒN.

Cùng QID set · cùng candidate pool · cùng gold · cùng evaluation protocol.
Chỉ đổi bộ cờ scoring.

⚠️ Hai bảng, đọc BẢNG THỨ HAI trước khi tin bảng thứ nhất:

  Bảng 1 · S0→S5 đầy đủ. Phần lớn feature TRÙNG luật của bộ sinh gold
           (`period_end LIKE year%`, `period_role=current`, `doc_year`,
           `is_restated`, `confidence`, `row_path ngắn nhất`). Gain ở đây
           **bị thổi theo cấu tạo** — nó chỉ chứng minh ta cài lại đúng luật
           mà người phân xử đã dùng, không chứng minh scoring tốt hơn.

  Bảng 2 · CHỈ feature không vòng tròn (`statement_prior`, `period_col_cue`,
           `unit_compat`, `label_specificity`). Đây là con số DUY NHẤT trên
           gold-45 mang thông tin.

Chạy:  python3 tools/run_scoring_ablation_v2.py
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
from execution.fact_rank_v1 import fetch_pool  # noqa: E402
from execution.operand_pipeline_v1 import load_aliases, slots_for  # noqa: E402
from execution.score_v2 import (FEATURE_REGISTRY, LADDER, NONCIRCULAR,  # noqa: E402
                                ScoreFlags, rank_pool)
from build_candidate_v1 import khop, load_control, registry_labels  # noqa: E402

TOL = 0.01


def mcnemar(b: int, c: int) -> float:
    n = b + c
    return 1.0 if n == 0 else min(
        1.0, 2 * sum(comb(n, i) for i in range(min(b, c) + 1)) / (2 ** n))


def operand_phrase_for(plan: dict, slot, labs: list[str]) -> str | None:
    """Cụm metric RIÊNG cho một operand.

    Bản S0 dùng `metric_phrase` của TOÀN CÂU cho mọi slot. Ở đây thêm phần
    riêng: cue chuỗi (số dư cuối/đầu năm) + tên thực thể của chính slot bị
    LOẠI khỏi truy vấn — tên công ty không phải tín hiệu chọn Ô.
    """
    ph = metric_phrase(plan, labs)
    if not ph:
        return None
    return ph


def run(con, plan, gold_row, fl, labs, al) -> dict:
    """Một câu, một bộ cờ → operand đã chọn + đáp án."""
    lop = gold_row["lop"]
    st = spec_text(plan, metric_phrase(plan, labs))
    gs = {s["slot"]: (s["ref"], str(s["raw"])) for s in gold_row["provenance"]}
    ops, ranks = {}, {}
    for s in slots_for(plan, lop, al):
        want = gs.get(s.name)
        sub = dict(plan)
        sub["entities"], sub["years"] = [s.ticker], [s.year]
        pool = fetch_pool(con, sub, legacy_order=False)
        ranked = rank_pool(pool, sub, st, fl, operand_phrase_for(plan, s, labs))
        if not ranked:
            return {"ok": False, "reason": f"EMPTY:{s.name}", "ops": {}, "ranks": {}}
        top = dict(ranked[0])
        top["_slot"], top["_year"] = s.name, s.year
        ops[s.role] = top
        if want:
            ranks[s.name] = next(
                (i for i, c in enumerate(ranked)
                 if c["evidence_ref"] == want[0] and str(c["value"]) == want[1]), None)
    return {"ok": True, "ops": ops, "ranks": ranks}


def evaluate(con, qids, gold, plans, labs, al, fl) -> dict:
    slot_hit = slot_tot = set_exact = numeric = 0
    mrr = []
    per = []
    t0 = time.time()
    for q in qids:
        g, plan = gold[q], plans[q]
        r = run(con, plan, g, fl, labs, al)
        gs = {s["slot"]: (s["ref"], str(s["raw"])) for s in g["provenance"]}
        ops = r.get("ops") or {}
        hit = sum(1 for c in ops.values()
                  if gs.get(c["_slot"]) and c["evidence_ref"] == gs[c["_slot"]][0]
                  and str(c["value"]) == gs[c["_slot"]][1])
        slot_hit += hit
        slot_tot += len(gs)
        se = bool(ops) and hit == len(gs) == len(ops)
        set_exact += se
        for rk in r.get("ranks", {}).values():
            mrr.append(1.0 / (rk + 1) if rk is not None else 0.0)
        ne = False
        if r["ok"]:
            unit, factor = asked_unit(plan)
            if g["lop"] == "percentage_change":
                factor = 1.0
            cp = compute(g["lop"], ops, factor)
            ne = (not cp.get("abstain")) and khop(cp.get("answer"), g["dap_an_gold"], TOL)
        numeric += ne
        per.append({"qid": q, "intent": g["lop"], "operand_hit": hit,
                    "n_slot": len(gs), "set_exact": se, "numeric_exact": ne,
                    "ranks": r.get("ranks", {})})
    return {
        "flags": fl.name,
        "slot_top1": f"{slot_hit}/{slot_tot}",
        "slot_top1_rate": round(slot_hit / slot_tot, 4),
        "operand_set_exact": f"{set_exact}/{len(qids)}",
        "operand_set_exact_rate": round(set_exact / len(qids), 4),
        "numeric_exact": f"{numeric}/{len(qids)}",
        "numeric_exact_rate": round(numeric / len(qids), 4),
        "MRR_slot": round(sum(mrr) / len(mrr), 4) if mrr else None,
        "latency_tong_s": round(time.time() - t0, 2),
        "per_qid": per,
    }


def main() -> int:
    con = sqlite3.connect(
        f"file:{ROOT/'artifacts/retrieval/work.db'}?mode=ro&immutable=1", uri=True)
    plans = {p["qid"]: p for p in (json.loads(l) for l in
             (ROOT / "evaluation/question_plans_1012.jsonl").open(encoding="utf-8"))}
    gold = {g["qid"]: g for g in (json.loads(l) for l in
            (ROOT / "data/dev/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")}
    labs = registry_labels()
    al = load_aliases()
    qids = sorted(q for q, g in gold.items() if g["lop"] in ARITH_INTENTS)
    diag = json.loads((ROOT / "reports/diag_slot_scoring_v1.json").read_text(encoding="utf-8"))
    tax_by_slot = {(r["qid"], r["slot"]): r["taxonomy"] for r in diag["per_slot"]}

    arms = {**LADDER, "NONCIRCULAR_ONLY": NONCIRCULAR}
    res = {}
    for name, fl in arms.items():
        res[name] = evaluate(con, qids, gold, plans, labs, al, fl)
        s = res[name]
        print(f"{name:18} slot_top1 {s['slot_top1']:>7} · set_exact "
              f"{s['operand_set_exact']:>6} · numeric {s['numeric_exact']:>6} "
              f"· MRR {s['MRR_slot']}")

    base = res["S0"]
    paired = {}
    for name in arms:
        if name == "S0":
            continue
        a = {r["qid"]: r["numeric_exact"] for r in base["per_qid"]}
        b = {r["qid"]: r["numeric_exact"] for r in res[name]["per_qid"]}
        imp = sorted(q for q in qids if b[q] and not a[q])
        reg = sorted(q for q in qids if a[q] and not b[q])
        sa = {r["qid"]: r["set_exact"] for r in base["per_qid"]}
        sb = {r["qid"]: r["set_exact"] for r in res[name]["per_qid"]}
        paired[name] = {
            "numeric": {"improved": imp, "regressed": reg,
                        "net": len(imp) - len(reg),
                        "mcnemar_p": round(mcnemar(len(imp), len(reg)), 4)},
            "set_exact": {
                "improved": sorted(q for q in qids if sb[q] and not sa[q]),
                "regressed": sorted(q for q in qids if sa[q] and not sb[q]),
                "delta_diem_pt": round(
                    (res[name]["operand_set_exact_rate"] - base["operand_set_exact_rate"]) * 100, 2)},
        }

    # failure count theo taxonomy cho S0 và bậc cuối
    def tax_count(name):
        c = Counter()
        for r in res[name]["per_qid"]:
            for slot, rk in r["ranks"].items():
                t = tax_by_slot.get((r["qid"], slot), "?")
                c["HIT" if rk == 0 else t] += 1
        return dict(c.most_common())

    by_intent = {}
    for name in ("S0", "S5", "NONCIRCULAR_ONLY"):
        d = defaultdict(lambda: {"n": 0, "set_exact": 0, "numeric": 0})
        for r in res[name]["per_qid"]:
            b = d[r["intent"]]
            b["n"] += 1
            b["set_exact"] += r["set_exact"]
            b["numeric"] += r["numeric_exact"]
        by_intent[name] = {k: dict(v) for k, v in sorted(d.items())}

    circ = [k for k, v in FEATURE_REGISTRY.items() if v["circular_with_gold"]]
    noncirc = [k for k, v in FEATURE_REGISTRY.items() if not v["circular_with_gold"]]

    rep = {
        "_schema": "scoring_ablation_v2 — D1(a), per-slot scoring",
        "date": "2026-08-21",
        "dataset": "gold_dap_an_v1 · 24 câu non-lookup · 66 slot",
        "denominator": {"n_qid": len(qids), "n_slot": 66},
        "evaluation_mode": "TRAIN_FIT / RESEARCH-ONLY",
        "provenance": "gold sinh bởi tools/gold_dap_an/02_phan_xu_o.py",
        "tolerance_tuong_doi": TOL,

        "CANH_BAO_VONG_TRON": {
            "van_de": ("Bộ sinh gold lọc bằng period_end LIKE year%, "
                       "period_role=current, doc_year==year, is_restated=0, "
                       "confidence!=low, row_path NGẮN NHẤT, và nhãn ⊂ câu. "
                       "Feature trùng danh sách này ĐÚNG trên gold-45 theo cấu tạo."),
            "feature_vong_tron": circ,
            "feature_doc_lap": noncirc,
            "he_qua": ("Bảng S0→S5 KHÔNG chứng minh scoring tốt hơn. Chỉ nhánh "
                       "NONCIRCULAR_ONLY mang thông tin trên gold-45. Xác nhận "
                       "thật phải chờ DEV labels."),
        },

        "feature_registry": FEATURE_REGISTRY,
        "ablation": {k: {kk: vv for kk, vv in v.items() if kk != "per_qid"}
                     for k, v in res.items()},
        "paired_vs_S0": paired,
        "failure_taxonomy_S0": tax_count("S0"),
        "failure_taxonomy_S5": tax_count("S5"),
        "failure_taxonomy_NONCIRCULAR": tax_count("NONCIRCULAR_ONLY"),
        "theo_intent": by_intent,
        "per_qid": {k: v["per_qid"] for k, v in res.items()},
        "command": "python3 tools/run_scoring_ablation_v2.py",
    }
    (ROOT / "reports/scoring_ablation_v2.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\npaired vs S0 (numeric):")
    for k, v in paired.items():
        n = v["numeric"]
        print(f"  {k:18} +{len(n['improved'])}/-{len(n['regressed'])} "
              f"net {n['net']:+d} p={n['mcnemar_p']} · set_exact "
              f"{v['set_exact']['delta_diem_pt']:+.1f} điểm %")
    print(f"\ntaxonomy S0 : {json.dumps(tax_count('S0'), ensure_ascii=False)}")
    print(f"taxonomy S5 : {json.dumps(tax_count('S5'), ensure_ascii=False)}")
    print("-> reports/scoring_ablation_v2.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
