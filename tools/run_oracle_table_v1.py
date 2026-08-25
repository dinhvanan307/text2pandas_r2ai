#!/usr/bin/env python3
"""Bảng oracle O0/O2/O4/O6 + tách 5 tầng đúng — đóng P0-3 và P0-4 của doc 134.

DOC 134 P0-3: *"Từ 3/3 conditional cases không thể suy ra arithmetic pass rate
≈100%"*. Đúng. Doc 133 §0 dùng `arithmetic_pass_rate ≈ 100%` trong forecast dựa
trên 3 câu mà resolver TÌNH CỜ chọn đúng operand. Đó là mẫu tự chọn.

DOC 134 P0-4: *"chưa phải số oracle marginal gain"*. Cũng đúng. Quan sát 20
operand miss gợi ý resolver là bottleneck nhưng chưa phải bảng O0→O2→O4→O6.

Tệp này chạy CẢ HAI, trên **đủ 24 câu non-lookup**, không chỉ 3 câu may mắn.

ĐỊNH NGHĨA (theo doc 132, giữ nguyên — không viết lại)

    O0  production end-to-end
    O2  gold evidence scope + production resolver/emitter
        (pool bị giới hạn về đúng evidence_ref của gold, resolver vẫn tự chọn ô)
    O4  gold operands + production operation/emitter
        (bỏ hẳn khâu chọn ô; đo riêng tầng số học của PRODUCTION)
    O6  gold operands + gold operation + reference evaluator độc lập

Năm tầng tách theo yêu cầu P0-3:

    formula_reference_correctness              O6 vs gold
    emitter_coverage                           có dựng được plan không
    emitter_execution_rate                     code chạy không ném lỗi
    emitter_numeric_exact_given_gold_operands  = O4  ← số P0-3 đòi
    end_to_end_numeric_exact                   = O0

Chạy:  python3 tools/run_oracle_table_v1.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import traceback
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from execution.emit_arith_v1 import ARITH_INTENTS, LADDER, compute, emit  # noqa: E402
from execution.emit_lookup_v1 import asked_unit  # noqa: E402
from execution.operand_pipeline_v1 import (PipelineFlags, candidates_for_slot,  # noqa: E402
                                           load_aliases, slots_for)
from execution.emit_lookup_v1 import metric_phrase, spec_text  # noqa: E402
from build_candidate_v1 import khop, load_control, registry_labels  # noqa: E402
from reference_eval_v1 import reference_answer, close  # noqa: E402

TOL = 0.01


def gold_ops(g: dict) -> dict[str, dict]:
    """Operand GOLD dựng thành cell giả — dùng cho O4/O6.

    `observation_uid = None` là CỐ Ý: gold provenance không mang uid, nên
    `effective_scale` sẽ dùng `scale_exponent` của gold. Override UNIT_SCALE
    không áp ở đây — đúng, vì gold đã là giá trị đã phân xử.
    """
    lop = g["lop"]
    prov = g["provenance"]
    cells = [{"value": str(s["raw"]), "scale_exponent": int(s.get("scale_exponent") or 0),
              "observation_uid": None, "metric_label": s.get("nhan"),
              "col_path": s.get("col"), "_year": int(s["slot"].split("/")[1]),
              "_slot": s["slot"]} for s in prov]
    if lop in ("percentage_change", "difference"):
        if len(cells) != 2:
            return {}
        return {"old": cells[0], "new": cells[1]}
    return {f"x{i}": c for i, c in enumerate(cells)}


def main() -> int:
    con = sqlite3.connect(
        f"file:{ROOT/'data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db'}?mode=ro&immutable=1", uri=True)
    plans = {p["qid"]: p for p in (json.loads(l) for l in
             (ROOT / "data/curated/evaluation/legacy/question_plans_1012.jsonl").open(encoding="utf-8"))}
    gold = {g["qid"]: g for g in (json.loads(l) for l in
            (ROOT / "data/curated/dev-legacy/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")}
    labs = registry_labels()
    sub0, _ = load_control()
    c0 = {r["id"]: r for r in sub0}
    fl = LADDER["C3"]

    targets = [q for q, g in sorted(gold.items()) if g["lop"] in ARITH_INTENTS]
    rows = []

    for q in targets:
        g, plan = gold[q], plans[q]
        lop = g["lop"]
        rec = {"qid": q, "intent": lop, "n_slot_gold": len(g["provenance"])}

        # ── O0 · production end-to-end ─────────────────────────────────────
        try:
            r0 = emit(con, plan, lop, fl, labs) or {"abstain": True}
        except Exception:
            r0 = {"abstain": True, "abstain_reason": "EXCEPTION"}
        rec["O0_exact"] = (not r0.get("abstain")) and khop(r0.get("answer"),
                                                           g["dap_an_gold"], TOL)
        rec["O0_abstain_reason"] = r0.get("abstain_reason")

        # ── O2 · gold evidence scope + production resolver ─────────────────
        # Giới hạn pool về đúng các evidence_ref của gold, resolver VẪN tự chọn
        # ô trong đó. Nếu O2 >> O0 thì lỗi nằm ở SCOPE (retrieval/pool), nếu
        # O2 ≈ O0 thì lỗi nằm ở CHỌN Ô trong scope đã đúng.
        refs = {s["ref"] for s in g["provenance"]}
        slots = slots_for(plan, lop, load_aliases())
        o2_ok = None
        if slots:
            phrase = metric_phrase(plan, labs)
            st = spec_text(plan, phrase)
            ops2, missing = {}, False
            for s in slots:
                short, _ = candidates_for_slot(con, plan, s, fl.pipeline,
                                               scoring_text=st)
                inscope = [c for c in short if c["evidence_ref"] in refs]
                if not inscope:
                    # mở rộng: lấy sâu hơn trong cùng scope
                    deep, _ = candidates_for_slot(
                        con, plan, s, PipelineFlags(depth=300, shortlist_m=300),
                        scoring_text=st)
                    inscope = [c for c in deep if c["evidence_ref"] in refs]
                if not inscope:
                    missing = True
                    break
                cc = dict(inscope[0])
                cc["_year"] = s.year
                ops2[s.role] = cc
            if not missing:
                unit, factor = asked_unit(plan)
                if lop == "percentage_change":
                    factor = 1.0
                r2 = compute(lop, ops2, factor)
                o2_ok = (not r2.get("abstain")) and khop(r2.get("answer"),
                                                         g["dap_an_gold"], TOL)
            else:
                o2_ok = False
        rec["O2_exact"] = bool(o2_ok)

        # ── O4 · gold operands + production emitter ────────────────────────
        ops = gold_ops(g)
        rec["emitter_coverage"] = bool(ops)
        if not ops:
            rec["O4_exact"] = False
            rec["emitter_execution_ok"] = False
            rec["O4_reason"] = "KHONG_DUNG_DUOC_OPS_TU_GOLD"
        else:
            unit, factor = asked_unit(plan)
            if lop == "percentage_change":
                factor = 1.0
            try:
                r4 = compute(lop, ops, factor)
                rec["emitter_execution_ok"] = True
            except Exception as e:
                r4 = {"abstain": True, "abstain_reason": f"EXC:{type(e).__name__}"}
                rec["emitter_execution_ok"] = False
                rec["trace"] = traceback.format_exc()[-300:]
            rec["O4_exact"] = (not r4.get("abstain")) and khop(r4.get("answer"),
                                                               g["dap_an_gold"], TOL)
            rec["O4_answer"] = r4.get("answer")
            rec["O4_reason"] = r4.get("abstain_reason")
            rec["unit_factor"] = factor
            rec["unit_name"] = unit

        # ── O6 · gold operands + gold operation + evaluator độc lập ────────
        r6 = reference_answer(g)
        hit = r6["ok"] and close(r6["value"], g["dap_an_gold"])
        rev = (r6.get("value_reversed") is not None
               and close(r6["value_reversed"], g["dap_an_gold"]))
        rec["O6_exact"] = bool(hit or rev)
        rec["O6_can_reverse"] = bool(rev and not hit)
        rec["C0_exact"] = khop(c0[q].get("answer"), g["dap_an_gold"], TOL)
        rows.append(rec)

    n = len(rows)
    def cnt(k):
        return sum(bool(r.get(k)) for r in rows)

    o0, o2, o4, o6 = cnt("O0_exact"), cnt("O2_exact"), cnt("O4_exact"), cnt("O6_exact")
    by_intent = defaultdict(lambda: {"n": 0, "O0": 0, "O2": 0, "O4": 0, "O6": 0})
    for r in rows:
        b = by_intent[r["intent"]]
        b["n"] += 1
        for k in ("O0", "O2", "O4", "O6"):
            b[k] += bool(r.get(f"{k}_exact"))

    o4_fail = [{"qid": r["qid"], "intent": r["intent"], "reason": r.get("O4_reason"),
                "o4_answer": r.get("O4_answer"), "gold": gold[r["qid"]]["dap_an_gold"]}
               for r in rows if not r.get("O4_exact")]

    rep = {
        "_schema": "oracle_table v1 — đóng P0-3 và P0-4 của doc 134",
        "date": "2026-08-21",
        "dataset": "gold_dap_an_v1 · 24 câu non-lookup",
        "denominator": n,
        "evaluation_mode": "TRAIN_FIT / REGRESSION-ONLY",
        "provenance": "gold sinh bởi tools/gold_dap_an/02_phan_xu_o.py; 45/45 row_label_exact",
        "tolerance_tuong_doi": TOL,
        "qid_list": [r["qid"] for r in rows],

        "dinh_nghia": {
            "O0": "production end-to-end (C3)",
            "O2": "gold evidence scope + production resolver/emitter",
            "O4": "gold operands + production operation/emitter",
            "O6": "gold operands + gold operation + reference evaluator độc lập",
        },
        "bang_oracle": {
            "C0_baseline": {"correct": cnt("C0_exact"), "n": n},
            "O0": {"correct": o0, "n": n, "rate": round(o0 / n, 4)},
            "O2": {"correct": o2, "n": n, "rate": round(o2 / n, 4),
                   "delta_vs_O0": o2 - o0},
            "O4": {"correct": o4, "n": n, "rate": round(o4 / n, 4),
                   "delta_vs_O2": o4 - o2},
            "O6": {"correct": o6, "n": n, "rate": round(o6 / n, 4),
                   "delta_vs_O4": o6 - o4},
        },
        "marginal_gain": {
            "O2_minus_O0": o2 - o0,
            "O4_minus_O2": o4 - o2,
            "O6_minus_O4": o6 - o4,
            "dominant": max([("O2-O0", o2 - o0), ("O4-O2", o4 - o2),
                             ("O6-O4", o6 - o4)], key=lambda x: x[1])[0],
        },

        "nam_tang_P0_3": {
            "formula_reference_correctness": f"{o6}/{n}",
            "emitter_coverage": f"{cnt('emitter_coverage')}/{n}",
            "emitter_execution_rate": f"{cnt('emitter_execution_ok')}/{n}",
            "emitter_numeric_exact_given_gold_operands": f"{o4}/{n}",
            "end_to_end_numeric_exact": f"{o0}/{n}",
            "GHI_CHU": ("Doc 133 dùng `arithmetic_pass_rate ≈ 100%` suy từ 3 câu "
                        "mà resolver tình cờ chọn đúng — mẫu TỰ CHỌN. Số đúng để "
                        "dùng trong forecast là `emitter_numeric_exact_given_gold_"
                        f"operands = {o4}/{n} = {o4/n:.1%}`, đo trên ĐỦ {n} câu."),
        },
        "theo_intent": {k: dict(v) for k, v in sorted(by_intent.items())},
        "O4_that_bai": o4_fail,
        "per_qid": rows,
        "command": "python3 tools/run_oracle_table_v1.py",
    }
    (ROOT / "reports/oracle_table_v1.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"n = {n} câu non-lookup · tolerance {TOL}\n")
    print(f"{'Oracle':6} {'Correct/n':>10} {'rate':>8} {'delta':>7}")
    print(f"{'C0':6} {cnt('C0_exact'):>7}/{n:<3} {cnt('C0_exact')/n:>7.1%} {'—':>7}")
    print(f"{'O0':6} {o0:>7}/{n:<3} {o0/n:>7.1%} {'—':>7}")
    print(f"{'O2':6} {o2:>7}/{n:<3} {o2/n:>7.1%} {o2-o0:>+7d}")
    print(f"{'O4':6} {o4:>7}/{n:<3} {o4/n:>7.1%} {o4-o2:>+7d}")
    print(f"{'O6':6} {o6:>7}/{n:<3} {o6/n:>7.1%} {o6-o4:>+7d}")
    print(f"\ndominant marginal gain: {rep['marginal_gain']['dominant']}")
    print(f"\nNăm tầng (P0-3): {json.dumps(rep['nam_tang_P0_3'], ensure_ascii=False, indent=1)}")
    if o4_fail:
        print(f"\nO4 thất bại ({len(o4_fail)}):")
        for f in o4_fail[:8]:
            print("   ", json.dumps(f, ensure_ascii=False))
    print("\n-> reports/oracle_table_v1.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
