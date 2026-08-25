#!/usr/bin/env python3
"""Trần của hướng D1(a) + cấu trúc 37 miss — nền số của doc 138.

Doc 138 nói "trần 17/24" và "row_path lệch ở 25/37 miss". Hai số ấy phải TÁI
SINH được, không nằm chết trong markdown. Tệp này sinh lại toàn bộ §1–§2 của
doc 138 từ `work.db` + gold, và ghi ra JSON kèm lệnh.

Bốn tầng mất mát, đo riêng từng tầng:

    gold ∈ pool thô        →  retrieval có tìm ra không?
    gold chấm được điểm    →  scorer có xếp hạng nổi không?
    gold sống sót top-8    →  hằng số cắt của production ăn mất bao nhiêu?
    gold ở top-1           →  scorer chọn đúng bao nhiêu?

Tách bốn tầng là điểm mấu chốt: gộp lại thì "29/66" trông như lỗi scorer, mà
thực ra 15 slot mất vì một hằng số và 4 slot mất vì điểm None.

Chạy:  python3 tools/ceiling_analysis_v1.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from execution.emit_arith_v1 import ARITH_INTENTS  # noqa: E402
from execution.emit_lookup_v1 import metric_phrase, spec_text  # noqa: E402
from execution.fact_rank_v1 import fetch_pool  # noqa: E402
from execution.operand_pipeline_v1 import load_aliases, slots_for  # noqa: E402
from execution.score_v2 import LADDER, rank_pool  # noqa: E402
from build_candidate_v1 import registry_labels  # noqa: E402

# Cắt lattice của production. Đọc từ operand_pipeline nếu ở đó có hằng số tên
# này; nếu không thì 8 là giá trị đang chạy tại 21/08.
TOP_M = 8

DIMS = ("metric_label", "col_path", "row_path", "statement_type",
        "period_end", "period_role", "is_restated", "confidence",
        "unit_kind", "value_kind", "scale_exponent")


def main() -> int:
    con = sqlite3.connect(
        f"file:{ROOT/'data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db'}?mode=ro&immutable=1", uri=True)
    plans = {p["qid"]: p for p in (json.loads(l) for l in
             (ROOT / "evaluation/question_plans_1012.jsonl").open(encoding="utf-8"))}
    gold = {g["qid"]: g for g in (json.loads(l) for l in
            (ROOT / "data/curated/dev-legacy/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")}
    labs, al, fl = registry_labels(), load_aliases(), LADDER["S5"]

    n_slot = in_pool = scorable = in_topm = at_top1 = 0
    val_eq = rowpath_only = 0
    dim_diff = Counter()
    tax_dim = defaultdict(Counter)
    per_q, slot_plan_lech = {}, []
    rank_bucket = Counter()

    diag = json.loads((ROOT / "reports/diag_slot_scoring_v1.json").read_text(encoding="utf-8"))
    tax = {(r["qid"], r["slot"]): r["taxonomy"] for r in diag["per_slot"]}

    for q, g in sorted(gold.items()):
        if g["lop"] not in ARITH_INTENTS:
            continue
        plan = plans[q]
        st = spec_text(plan, metric_phrase(plan, labs))
        gs = {s["slot"]: (s["ref"], str(s["raw"])) for s in g["provenance"]}
        sl = slots_for(plan, g["lop"], al)

        # slot-plan mismatch: kể cả scorer hoàn hảo cũng KHÔNG ra set_exact
        if {s.name for s in sl} != set(gs):
            slot_plan_lech.append({
                "qid": q, "intent": g["lop"], "n_plan": len(sl), "n_gold": len(gs),
                "thua_trong_plan": sorted({s.name for s in sl} - set(gs)),
                "thieu_trong_plan": sorted(set(gs) - {s.name for s in sl})})

        ranks = []
        for s in sl:
            want = gs.get(s.name)
            if not want:
                continue
            sub = dict(plan)
            sub["entities"], sub["years"] = [s.ticker], [s.year]
            pool = fetch_pool(con, sub, legacy_order=False)
            ranked = rank_pool(pool, sub, st, fl, metric_phrase(plan, labs))
            n_slot += 1
            in_pool += any(c["evidence_ref"] == want[0] and str(c["value"]) == want[1]
                           for c in pool)
            gi = next((i for i, c in enumerate(ranked)
                       if c["evidence_ref"] == want[0] and str(c["value"]) == want[1]), None)
            scorable += gi is not None
            in_topm += gi is not None and gi < TOP_M
            at_top1 += gi == 0
            ranks.append(gi)

            # Histogram theo ĐÚNG bucket doc 140 §3.3 yêu cầu. Bản đầu chỉ có
            # 4 ô và cho phép viết "phần lớn ở hạng 2" mà không kèm count —
            # doc 140 bác đúng: "27 trong top-8" và "27 ở hạng 2" là HAI claim
            # khác nhau. Từ đây mọi phát ngôn phải trỏ vào ô cụ thể dưới đây.
            # `gi` là chỉ số 0-based ⇒ hạng người-đọc = gi + 1.
            h = None if gi is None else gi + 1
            rank_bucket[
                "score_None" if h is None else
                "rank_1" if h == 1 else
                "rank_2" if h == 2 else
                "rank_3_8" if h <= 8 else
                "rank_9_16" if h <= 16 else
                "rank_17_32" if h <= 32 else
                "rank_33_64" if h <= 64 else "rank_gt_64"] += 1

            if gi in (None, 0):
                continue
            top, gc = ranked[0], ranked[gi]
            t = tax.get((q, s.name), "?")
            khac = [f for f in DIMS if top.get(f) != gc.get(f)]
            for f in khac:
                dim_diff[f] += 1
                tax_dim[t][f] += 1
            if str(top["value"]) == want[1]:
                val_eq += 1
            if [f for f in khac if f in
                    ("metric_label", "col_path", "row_path", "statement_type",
                     "period_end")] == ["row_path"]:
                rowpath_only += 1

        if ranks:
            unresolved = next((d for d in slot_plan_lech if d["qid"] == q), None)
            per_q[q] = {
                "intent": g["lop"], "n_slot": len(ranks),
                "n_gold_slot": len(gs), "n_plan_slot": len(sl),
                "gold_slot_set": sorted(gs), "ranks": ranks,
                "unresolved_reason": (
                    "SLOT_PLAN_MISMATCH: plan sinh "
                    f"{len(sl)} slot, gold ghi {len(gs)} provenance"
                    if unresolved else None),
                "dat_duoc_neu_scorer_hoan_hao_trong_topM":
                    all(r is not None and r < TOP_M for r in ranks),
                "dat_duoc_neu_scorer_hoan_hao_ca_pool":
                    all(r is not None for r in ranks),
                "dung_ngay_bay_gio": all(r == 0 for r in ranks)}
            per_q[q]["ceiling_verdict"] = (
                "UNRESOLVED_KHONG_TINH_TRAN" if unresolved else
                "DAT_DUOC_TRONG_TOPM" if per_q[q]["dat_duoc_neu_scorer_hoan_hao_trong_topM"]
                else "CHI_DAT_DUOC_TREN_CA_POOL"
                if per_q[q]["dat_duoc_neu_scorer_hoan_hao_ca_pool"]
                else "KHONG_DAT_DUOC")

    lech = {d["qid"] for d in slot_plan_lech}
    cap_m = sum(v["dat_duoc_neu_scorer_hoan_hao_trong_topM"] for v in per_q.values())
    cap_p = sum(v["dat_duoc_neu_scorer_hoan_hao_ca_pool"] for v in per_q.values())
    now = sum(v["dung_ngay_bay_gio"] for v in per_q.values())
    cap_real = sum(v["dat_duoc_neu_scorer_hoan_hao_trong_topM"]
                   for q, v in per_q.items() if q not in lech)

    rep = {
        "_schema": "ceiling_analysis v1 — nền số §1–§2 doc 138",
        "date": "2026-08-21",
        "dataset": "gold_dap_an_v1 · 24 câu non-lookup",
        "scoring_arm": "S5", "top_M_lattice": TOP_M,
        "evaluation_mode": "TRAIN_FIT / RESEARCH-ONLY",

        "bon_tang_mat_mat": {
            "gold_trong_pool_tho": f"{in_pool}/{n_slot}",
            "gold_cham_duoc_diem": f"{scorable}/{n_slot}",
            f"gold_song_sot_top{TOP_M}": f"{in_topm}/{n_slot}",
            "gold_o_top1": f"{at_top1}/{n_slot}",
            "doc_the_nao": (
                "gold_trong_pool = 100% ⇒ MỌI câu sai đều sai ở tầng CHỌN, không "
                "phải tầng TÌM. Đây là bằng chứng định lượng thứ hai — độc lập với "
                "O2−O0=+1 của doc 134 — rằng đóng băng retrieval là đúng."),
        },

        "tran_o_muc_cau": {
            "hien_tai_set_exact": f"{now}/{len(per_q)}",
            f"scorer_hoan_hao_trong_top{TOP_M}": f"{cap_m}/{len(per_q)}",
            "scorer_hoan_hao_ca_pool": f"{cap_p}/{len(per_q)}",
            # Doc 140 §3.2: phải nói rõ trừ một lần hay hai, và mẫu số nào.
            # Hai qid 848/938 nằm SẴN trong 19 (ranks của chúng đều < TOP_M),
            # nên 17 = 19 − 2 là trừ ĐÚNG MỘT LẦN, không trùng.
            "TRAN_conservative_giu_mau_so_24": f"{cap_real}/{len(per_q)}",
            "TRAN_neu_loai_UNRESOLVED_khoi_mau_so":
                f"{cap_real}/{len(per_q) - len(slot_plan_lech)}",
            "hai_qid_unresolved_co_nam_trong_19_khong": {
                d["qid"]: per_q.get(d["qid"], {}).get(
                    "dat_duoc_neu_scorer_hoan_hao_trong_topM")
                for d in slot_plan_lech},
            "cach_goi_dung": ("gọi là 'conservative ceiling under current gold/slot "
                              "contract', KHÔNG gọi là 'trần thật'. Mẫu số chính "
                              "thức là 24 hay 22 phụ thuộc phân xử 848/938 — chưa có."),
            "canh_bao": "trần đạt được khi scoring HOÀN HẢO. Không dùng làm mục tiêu.",
        },

        "phan_bo_hang_cua_gold": dict(rank_bucket.most_common()),

        "chieu_lech_giua_top1_va_gold": {
            "tong_theo_truong": dict(dim_diff.most_common()),
            "theo_taxonomy": {k: dict(v.most_common()) for k, v in sorted(tax_dim.items())},
            "doc_the_nao": (
                "row_path lệch nhiều nhất VÀ không hề có trong scorer — đó là lý do "
                "workstream B đứng trước C và D."),
        },

        "miss_vo_hai": {
            "gia_tri_trung_nhau": val_eq,
            "y_nghia": ("numeric_exact vẫn đúng, chỉ provenance khác ô. "
                        "operand_set_exact phạt, numeric_exact thì không — báo cả hai."),
        },
        "miss_chi_khac_row_path": rowpath_only,

        "slot_plan_lech": {
            "n": len(slot_plan_lech), "chi_tiet": slot_plan_lech,
            "y_nghia": ("scorer hoàn hảo cũng KHÔNG ra set_exact cho các câu này. "
                        "Cần người phân xử: gold thiếu provenance, hay gán nhầm intent?"),
        },

        "per_qid": per_q,
        "command": "python3 tools/ceiling_analysis_v1.py",
    }
    (ROOT / "reports/ceiling_analysis_v1.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    # doc 140 §3.2 đòi trace QID-level riêng, một dòng một câu
    with (ROOT / "reports/ceiling_by_qid.jsonl").open("w", encoding="utf-8") as f:
        for q, v in sorted(per_q.items()):
            f.write(json.dumps({"qid": q} | v, ensure_ascii=False) + "\n")

    b = rep["bon_tang_mat_mat"]
    print("bốn tầng mất mát (slot):")
    for k in ("gold_trong_pool_tho", "gold_cham_duoc_diem",
              f"gold_song_sot_top{TOP_M}", "gold_o_top1"):
        print(f"   {k:26} {b[k]}")
    t = rep["tran_o_muc_cau"]
    print("\ntrần ở mức câu (operand_set_exact):")
    for k, v in t.items():
        if k != "canh_bao":
            print(f"   {k:34} {v}")
    print(f"\nphân bố hạng của gold: {json.dumps(dict(rank_bucket), ensure_ascii=False)}")
    print(f"chiều lệch: {json.dumps(dict(dim_diff.most_common(5)), ensure_ascii=False)}")
    print(f"miss chỉ khác row_path: {rowpath_only} · miss giá trị trùng: {val_eq}")
    print(f"slot-plan lệch: {[d['qid'] for d in slot_plan_lech]}")
    print("-> reports/ceiling_analysis_v1.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
