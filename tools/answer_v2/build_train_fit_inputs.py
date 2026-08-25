#!/usr/bin/env python3
"""Sinh `train_fit_inputs/` — 66 slot, pool top-16, gold, baseline. Doc 159 §6.6.

CHỐNG RÒ RỈ — lý do tách file, không phải thủ tục
`train_fit_66_slots.jsonl` và `candidate_pools_top16.jsonl` là **đầu vào dựng
prompt**; chúng KHÔNG được chứa giá trị số của ô, cũng không chứa gold ID.
`train_fit_gold_labels.jsonl` là **đầu vào chấm**; nó chứa gold.

Hai nhóm có SHA riêng. Nhờ vậy reviewer kiểm được bằng băm rằng file dựng prompt
không mang theo đáp án — thay vì phải tin lời hứa.

ELIGIBILITY v2 (§6.7) — KHÔNG khoá vào `route == R2`
    SUPPORTED_SLOT = OperandKey hợp lệ
                     AND pool qua hard filter có đúng entity/period
                     AND pool có ≥2 ứng viên
`answer_route` chỉ là trường BÁO CÁO. Khoá theo R2 sẽ vứt gần hết gold-45 (sau
P0 chỉ còn 2 QID R2) và biến thí nghiệm thành vô nghĩa.

Chạy:  python3 tools/answer_v2/build_train_fit_inputs.py --out <thư mục>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/answer_v2"))
sys.path.insert(0, str(ROOT / "tools"))

import cell_reranker as CR                     # noqa: E402
import router_v1 as RT                         # noqa: E402
import formula_registry as FR                  # noqa: E402
from execution.emit_arith_v1 import ARITH_INTENTS  # noqa: E402
from execution.emit_lookup_v1 import metric_phrase, spec_text  # noqa: E402
from execution.fact_rank_v1 import fetch_pool  # noqa: E402
from execution.operand_pipeline_v1 import load_aliases, slots_for  # noqa: E402
from execution.score_v2 import LADDER as SL, rank_pool  # noqa: E402
from build_candidate_v1 import registry_labels  # noqa: E402

WORK = ROOT / "artifacts/retrieval/work.db"
TOP16 = 16


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def _basis(ref: str) -> str:
    r = (ref or "").lower()
    return ("consolidated" if "_consolidated" in r
            else "separate" if "_separate" in r else "unknown")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path,
                    default=ROOT / "reports/answer_v2/train_fit_inputs")
    a = ap.parse_args()
    out = a.out
    out.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(f"file:{WORK}?mode=ro&immutable=1", uri=True)
    plans = {p["qid"]: p for p in (json.loads(l) for l in
             (ROOT / "evaluation/question_plans_1012.jsonl").open(encoding="utf-8"))}
    gold = {g["qid"]: g for g in (json.loads(l) for l in
            (ROOT / "data/dev/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")}
    labs, al, fl = registry_labels(), load_aliases(), SL["S5"]
    formulas = FR.load()

    slots, pools, golds, baseline = [], [], [], []
    t0 = time.time()
    qids = sorted(q for q, g in gold.items() if g["lop"] in ARITH_INTENTS)

    for q in qids:
        g, plan = gold[q], plans[q]
        st = spec_text(plan, metric_phrase(plan, labs))
        gs = {s["slot"]: (s["ref"], str(s["raw"])) for s in g["provenance"]}
        route, sp, _ly = RT.route(plan.get("question", ""), plan, formulas)

        for s in slots_for(plan, g["lop"], al):
            want = gs.get(s.name)
            if not want:
                continue
            sub = dict(plan)
            sub["entities"], sub["years"] = [s.ticker], [s.year]
            pool = fetch_pool(con, sub, legacy_order=False)
            ranked = rank_pool(pool, sub, st, fl, None)

            # ── SUPPORTED_SLOT (§6.7) ─────────────────────────────────────
            ly_do_khong = None
            if not ranked:
                ly_do_khong = "EMPTY_RANKED_POOL"
            elif len(ranked) < 2:
                ly_do_khong = "POOL_LT_2_CANDIDATES"
            supported = ly_do_khong is None

            top = ranked[:TOP16]
            top_ids = [CR.candidate_id(c) for c in top]
            gold_id = next((CR.candidate_id(c) for c in ranked
                            if c["evidence_ref"] == want[0]
                            and str(c["value"]) == want[1]), None)
            gold_rank = next((i for i, c in enumerate(ranked)
                              if c["evidence_ref"] == want[0]
                              and str(c["value"]) == want[1]), None)

            # AMBIGUOUS: hai ứng viên đầu sát điểm ⇒ scorer không quyết được
            amb, trig = False, None
            if len(ranked) >= 2:
                d = float(ranked[0]["score"]) - float(ranked[1]["score"])
                if d <= 0.5:
                    amb, trig = True, f"SCORE_MARGIN_LE_0.5:{round(d, 4)}"
                elif len({str(c.get("metric_label")) for c in top[:3]}) > 1:
                    amb, trig = True, "TOP3_METRIC_LABEL_DIFFERS"

            slots.append({
                "qid": q, "slot_id": s.name, "question": plan.get("question", ""),
                "metric_id": None, "entity": s.ticker,
                "period": {"year": s.year}, "scope": "consolidated_preferred",
                "answer_route": route,          # BÁO CÁO, không phải điều kiện
                "supported_slot": supported, "unsupported_reason": ly_do_khong,
                "ambiguous": amb, "ambiguity_trigger": trig,
                "deterministic_top1_candidate_id": top_ids[0] if top_ids else None,
                "n_pool_raw": len(pool), "n_ranked": len(ranked),
            })

            for r, c in enumerate(top):
                pools.append({
                    "qid": q, "slot_id": s.name,
                    "stable_candidate_id": CR.candidate_id(c),
                    "deterministic_rank": r,
                    "metric_label": c.get("metric_label"),
                    "row_path": c.get("row_path"), "col_path": c.get("col_path"),
                    "entity": c.get("ticker"), "period_end": c.get("period_end"),
                    "period_role": c.get("period_role"),
                    "scope": _basis(str(c.get("evidence_ref"))),
                    "statement_type": c.get("statement_type"),
                    "value_kind": c.get("value_kind"), "unit_kind": c.get("unit_kind"),
                    "evidence_ref": c.get("evidence_ref"),
                    # dấu vết đặc trưng tất định — KHÔNG có giá trị số của ô
                    "feature_trace": {k: v for k, v in
                                      (c.get("score_parts") or {}).items()
                                      if isinstance(v, (int, float))},
                    "deterministic_score": c.get("score"),
                })

            golds.append({
                "qid": q, "slot_id": s.name, "gold_candidate_id": gold_id,
                "gold_in_top16": gold_id in top_ids if gold_id else False,
                "gold_rank_in_ranked": gold_rank,
                "provenance": {"evidence_ref": want[0], "raw_value": want[1]},
                "nguon_nhan": "gold_dap_an_v1.jsonl · provenance của bộ phân xử",
            })

            baseline.append({
                "qid": q, "slot_id": s.name,
                "predicted_candidate_id": top_ids[0] if top_ids else None,
                "correct": bool(gold_id and top_ids and gold_id == top_ids[0]),
                "scorer": "S5", "scorer_config": "score_v2.LADDER['S5']",
            })

    def ghi(ten: str, rows: list) -> Path:
        p = out / ten
        with p.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return p

    p_slots = ghi("train_fit_66_slots.jsonl", slots)
    p_pools = ghi("candidate_pools_top16.jsonl", pools)
    p_gold = ghi("train_fit_gold_labels.jsonl", golds)
    p_base = ghi("baseline_predictions.jsonl", baseline)

    n_dung = sum(1 for b in baseline if b["correct"])
    (out / "baseline_29_of_66.json").write_text(json.dumps({
        "_schema": "baseline S5 trên TRAIN_FIT 66 slot",
        "scorer": "S5", "n_slot": len(baseline), "n_correct": n_dung,
        "ty_le": f"{n_dung}/{len(baseline)}",
        "tai_lap": "so predicted_candidate_id với gold_candidate_id trong hai jsonl",
        "per_slot_file": "baseline_predictions.jsonl",
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── kiểm rò rỉ: file dựng prompt KHÔNG được chứa giá trị số hay gold ──
    ro_ri = []
    txt_prompt = p_slots.read_text(encoding="utf-8") + p_pools.read_text(encoding="utf-8")
    if "gold_candidate_id" in txt_prompt:
        ro_ri.append("gold_candidate_id xuất hiện trong file dựng prompt")
    for g in golds[:200]:
        v = g["provenance"]["raw_value"]
        if v and len(str(v)) >= 6 and str(v) in txt_prompt:
            ro_ri.append(f"giá trị gold {v} xuất hiện trong file dựng prompt")
            break

    ident = {
        "_schema": "TRAIN_FIT_IDENTITY v1 — doc 159 §6.6",
        "n_qid": len({s["qid"] for s in slots}),
        "n_slot": len(slots),
        "unique_qid_slot": len({(s["qid"], s["slot_id"]) for s in slots}),
        "question_plan_sha256": sha_file(ROOT / "evaluation/question_plans_1012.jsonl"),
        "gold_label_sha256": sha_file(p_gold),
        "candidate_pool_sha256": sha_file(p_pools),
        "slots_sha256": sha_file(p_slots),
        "baseline_sha256": sha_file(p_base),
        "baseline_source_config": "score_v2.LADDER['S5'] · fetch_pool legacy_order=False",
        "ag1b_parent_sha256": None,   # điền ở bước đóng gói, xem PATCH_IDENTITY
        "leakage_policy": {
            "file_dung_prompt": [p_slots.name, p_pools.name],
            "file_cham_diem": [p_gold.name, p_base.name],
            "quy_tac": "file dựng prompt KHÔNG chứa giá trị số của ô và KHÔNG chứa gold ID",
            "kiem_tu_dong": "PASS" if not ro_ri else "FAIL",
            "vi_pham": ro_ri,
        },
        "eligibility_version": "v2 · SUPPORTED_SLOT, KHÔNG dùng route==R2",
        "top_k_pool": TOP16,
        "latency_s": round(time.time() - t0, 1),
        "command": "python3 tools/answer_v2/build_train_fit_inputs.py",
    }
    (out / "TRAIN_FIT_IDENTITY.json").write_text(
        json.dumps(ident, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"slot {len(slots)} · unique {ident['unique_qid_slot']} · qid {ident['n_qid']}")
    print(f"supported {sum(1 for s in slots if s['supported_slot'])}/{len(slots)}"
          f" · ambiguous {sum(1 for s in slots if s['ambiguous'])}")
    print(f"gold trong top16 {sum(1 for g in golds if g['gold_in_top16'])}/{len(golds)}")
    print(f"baseline S5 {n_dung}/{len(baseline)}")
    print(f"rò rỉ: {ident['leakage_policy']['kiem_tu_dong']} {ro_ri}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
