#!/usr/bin/env python3
"""Đo A/B cell reranker trên 66 slot có gold — bộ đo DUY NHẤT có gold thật.

Nhánh A  `S5`            scorer tất định tốt nhất (doc 141) — parent
Nhánh B  `S5 + rerank`   LLM chọn lại top-1 trong top-K của A

Cùng câu hỏi · cùng pool · cùng gold · cùng cách chấm. Chỉ đổi bước chọn top-1.
Đây là điều kiện để quy delta về đúng LLM chứ không phải thứ khác.

CHẠY KHÔNG CẦN MODEL
Không có endpoint ⇒ mọi slot `fallback` ⇒ nhánh B **bằng đúng** nhánh A, và
report ghi `exercised: false`. Đó là kết quả hợp lệ, không phải lỗi: nó chứng
minh đường lui tất định hoạt động.

Bật model:
    export ANSWER_V2_LLM_ENDPOINT=http://localhost:8000
    python3 tools/answer_v2/run_rerank_eval.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/answer_v2"))
sys.path.insert(0, str(ROOT / "tools"))

import cell_reranker as CR              # noqa: E402
import llm_client as LC                 # noqa: E402
from execution.emit_arith_v1 import ARITH_INTENTS  # noqa: E402
from execution.emit_lookup_v1 import metric_phrase, spec_text  # noqa: E402
from execution.fact_rank_v1 import fetch_pool  # noqa: E402
from execution.operand_pipeline_v1 import load_aliases, slots_for  # noqa: E402
from execution.score_v2 import LADDER as SL, rank_pool  # noqa: E402
from build_candidate_v1 import registry_labels  # noqa: E402

WORK = ROOT / "data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db"
REP = ROOT / "reports/answer_v2"


def mcnemar(b: int, c: int) -> float:
    n = b + c
    return 1.0 if n == 0 else min(
        1.0, 2 * sum(comb(n, i) for i in range(min(b, c) + 1)) / (2 ** n))


def main() -> int:
    REP.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{WORK}?mode=ro&immutable=1", uri=True)
    plans = {p["qid"]: p for p in (json.loads(l) for l in
             (ROOT / "data/curated/evaluation/legacy/question_plans_1012.jsonl").open(encoding="utf-8"))}
    gold = {g["qid"]: g for g in (json.loads(l) for l in
            (ROOT / "data/curated/dev-legacy/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")}
    labs, al, fl = registry_labels(), load_aliases(), SL["S5"]

    client = LC.tu_config()
    client.identity.prompt_template_hash = CR.prompt_hash()
    stats = CR.RerankStats()

    qids = sorted(q for q, g in gold.items() if g["lop"] in ARITH_INTENTS)
    stats2 = CR.RerankStats()
    per_slot, t0 = [], time.time()
    A = B = B2 = tong = 0
    n_cap = n_dong_y = 0

    for q in qids:
        g, plan = gold[q], plans[q]
        st = spec_text(plan, metric_phrase(plan, labs))
        gs = {s["slot"]: (s["ref"], str(s["raw"])) for s in g["provenance"]}
        for s in slots_for(plan, g["lop"], al):
            want = gs.get(s.name)
            if not want:
                continue
            sub = dict(plan)
            sub["entities"], sub["years"] = [s.ticker], [s.year]
            ranked = rank_pool(fetch_pool(con, sub, legacy_order=False),
                               sub, st, fl, None)
            if not ranked:
                continue
            tong += 1

            def trung(c):
                return (c["evidence_ref"] == want[0]
                        and str(c["value"]) == want[1])

            a_ok = trung(ranked[0])
            A += a_ok

            # HAI cách trình bày, CÙNG một slot. Khác nhau duy nhất ở THỨ TỰ
            # ứng viên trong prompt — nội dung y hệt. Nếu model chọn cùng một Ô
            # ở cả hai thì nó chọn theo NỘI DUNG; nếu chọn khác thì nó đang bị
            # vị trí dẫn dắt, và mọi delta đo được đều không quy cho "hiểu đúng".
            khoa = f"{q}/{s.name}"
            b1 = CR.rerank(plan.get("question", ""), ranked, client, stats,
                           trinh_bay="s5", seed_text=khoa)
            b2 = CR.rerank(plan.get("question", ""), ranked, client, stats2,
                           trinh_bay="hoan_vi", seed_text=khoa)
            b_ok, b2_ok = trung(b1[0]), trung(b2[0])
            B += b_ok
            B2 += b2_ok
            dong_y = b1[0] is b2[0]
            n_cap += 1
            n_dong_y += dong_y

            if a_ok != b_ok or b1[0] is not ranked[0] or not dong_y:
                per_slot.append({
                    "qid": q, "slot": s.name, "A_dung": a_ok, "B_dung": b_ok,
                    "B_hoanvi_dung": b2_ok, "hai_cach_dong_y": dong_y,
                    "A_top1": (ranked[0].get("metric_label") or "")[:70],
                    "B_top1": (b1[0].get("metric_label") or "")[:70],
                    "B_hoanvi_top1": (b2[0].get("metric_label") or "")[:70],
                    "gold_rank_trong_A": next(
                        (i for i, c in enumerate(ranked) if trung(c)), None)})

    exercised = stats.n_llm_chon > 0
    imp = [r for r in per_slot if r["B_dung"] and not r["A_dung"]]
    reg = [r for r in per_slot if r["A_dung"] and not r["B_dung"]]

    rep = {
        "_schema": "rerank_eval v1 — A/B cell reranker trên gold-45",
        "date": "2026-08-22",
        "dataset": "gold_dap_an_v1 · 24 câu non-lookup · 66 slot có gold operand",
        "evaluation_mode": "TRAIN_FIT",
        "exercised": exercised,
        "ghi_chu_khi_khong_exercised": (
            "Không có endpoint LLM ⇒ mọi slot fallback ⇒ B == A. Đây là kết quả "
            "HỢP LỆ: nó chứng minh đường lui tất định hoạt động, không phải lỗi."),
        "nhanh_A_S5": f"{A}/{tong}",
        "nhanh_B_S5_rerank": f"{B}/{tong}",
        "nhanh_B2_rerank_hoan_vi": f"{B2}/{tong}",
        "delta": B - A,
        "delta_hoan_vi": B2 - A,

        # ── THIÊN VỊ VỊ TRÍ — đọc TRƯỚC khi tin `delta` ────────────────────
        "thien_vi_vi_tri": {
            "n_cap_do": n_cap,
            "n_hai_cach_chon_CUNG_o": n_dong_y,
            "ty_le_dong_y": round(n_dong_y / n_cap, 4) if n_cap else None,
            "phan_bo_vi_tri_chon_thu_tu_S5": dict(sorted(stats.vi_tri_chon.items())),
            "phan_bo_vi_tri_chon_hoan_vi": dict(sorted(stats2.vi_tri_chon.items())),
            "doc_the_nao": (
                "ty_le_dong_y THẤP ⇒ model chọn theo VỊ TRÍ, không theo nội dung "
                "⇒ mọi delta vô nghĩa. `phan_bo_vi_tri_chon` dồn vào 0 ở nhánh "
                "thứ-tự-S5 nhưng KHÔNG dồn vào 0 ở nhánh hoán vị cũng là dấu "
                "hiệu thiên vị vị trí đầu."),
            "nguong_G_LLM_6": 0.80,
            # ⚠️ KHI KHÔNG exercised, hai nhánh đều fallback về đúng thứ tự S5
            # nên chúng trùng nhau 100% MỘT CÁCH TẦM THƯỜNG. Trả PASS ở đó là
            # dấu XANH SAI — nguy hiểm hơn dấu đỏ sai, vì nó làm người đọc tin
            # rằng đã kiểm thiên vị vị trí trong khi chưa kiểm gì cả.
            "G_LLM_6": ("NOT_MEASURED" if not exercised else
                        ("PASS" if n_cap and n_dong_y / n_cap >= 0.80 else "FAIL")),
        },
        "improved": imp, "regressed": reg,
        "mcnemar_p": round(mcnemar(len(imp), len(reg)), 4),
        "rerank_stats": {
            "n_slot": stats.n_slot, "n_goi": stats.n_goi,
            "n_llm_chon": stats.n_llm_chon, "n_fallback": stats.n_fallback,
            "n_chi_so_ngoai_khoang": stats.n_ngoai_khoang,
            "n_doi_top1": stats.n_doi_top1,
            "ly_do_fallback": stats.ly_do_fallback},
        "llm": client.stats(),
        "K": CR.K_MAC_DINH,
        "prompt_template_hash": CR.prompt_hash(),
        "che_so": "giá trị ô KHÔNG vào prompt — model chọn theo nhãn/kỳ/phạm vi",
        "latency_s": round(time.time() - t0, 1),
        "per_slot_thay_doi": per_slot,
        "command": "python3 tools/answer_v2/run_rerank_eval.py",
    }
    (REP / "rerank_eval.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"exercised: {exercised}")
    print(f"  A  S5              {A}/{tong}")
    print(f"  B  rerank (S5 order) {B}/{tong}   delta {B - A:+d}")
    print(f"  B2 rerank (hoán vị)  {B2}/{tong}   delta {B2 - A:+d}")
    tv = rep["thien_vi_vi_tri"]
    print(f"  thiên vị vị trí: hai cách chọn CÙNG ô {tv['n_hai_cach_chon_CUNG_o']}"
          f"/{tv['n_cap_do']} = {tv['ty_le_dong_y']} "
          f"(cần ≥0,80) → G-LLM-6 {tv['G_LLM_6']}")
    print(f"  vị trí chọn (S5 order): {tv['phan_bo_vi_tri_chon_thu_tu_S5']}")
    print(f"  vị trí chọn (hoán vị) : {tv['phan_bo_vi_tri_chon_hoan_vi']}")
    print(f"  improved {len(imp)} · regressed {len(reg)} · p={rep['mcnemar_p']}")
    print(f"  rerank: gọi {stats.n_goi} · LLM chọn {stats.n_llm_chon} · "
          f"fallback {stats.n_fallback} · đổi top1 {stats.n_doi_top1}")
    print(f"  lý do fallback: {json.dumps(stats.ly_do_fallback, ensure_ascii=False)}")
    print(f"  llm: {json.dumps(client.stats()['identity'], ensure_ascii=False)}")
    print(f"-> {REP}/rerank_eval.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
