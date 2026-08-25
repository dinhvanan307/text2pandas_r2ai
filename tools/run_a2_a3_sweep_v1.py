#!/usr/bin/env python3
"""A2 · quét N lattice  +  A3 · điểm sàn cho ô không chấm được  +  A4 · tách metric.

Đóng doc 140 §3.4. Ba việc, một đường ống, một báo cáo.

⚠️ A2 — ĐIỀU KHÔNG ĐƯỢC LÀM Ở ĐÂY
Doc 138 bản đầu viết: "chọn N nhỏ nhất đạt gold_trong_lattice ≥ 62/66; tiêu chí
này không nhìn điểm cuối". Doc 140 bác đúng: **vẫn là chọn hyperparameter bằng
gold label trên TRAIN_FIT**. Không nhìn `numeric_exact` không làm hết selection
bias — `gold_trong_lattice` cũng là hàm của gold.

Vì vậy tệp này chỉ **lập curve**. Nó KHÔNG chốt `N_final`. Việc chốt phải làm
trên DEV, sau khi có nhãn. Bất kỳ ai đọc bảng dưới rồi sửa hằng số trong code là
đang vi phạm chính điều vừa viết.

Doc 138 cũng viết "chi phí chỉ là latency, không phải chất lượng". Câu đó đã bỏ:
mở rộng N không giảm raw recall, nhưng **tăng distractor**, đổi ambiguity/margin,
và có thể giảm precision đầu cuối. Bảng dưới đo cả bốn thứ để thấy điều đó.

Chạy:  python3 tools/run_a2_a3_sweep_v1.py
"""
from __future__ import annotations

import json
import sqlite3
import statistics as st
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from execution.emit_arith_v1 import (ARITH_INTENTS, ARITH_PIPE, LADDER,  # noqa: E402
                                     emit)
from execution.fact_rank_v1 import fetch_pool  # noqa: E402
from execution.emit_lookup_v1 import metric_phrase, spec_text  # noqa: E402
from execution.operand_pipeline_v1 import load_aliases, slots_for  # noqa: E402
from execution.score_v2 import LADDER as SLADDER, ScoreFlags, rank_pool  # noqa: E402
from build_candidate_v1 import khop, registry_labels  # noqa: E402

TOL = 0.01
N_QUET = (5, 8, 10, 16, 32, 64)


def mot_lan(con, qids, gold, plans, labs, pipe, arith) -> dict:
    """Một cấu hình → mọi metric của doc 140 §3.4, đo trên CÙNG đường ống."""
    dung = sai = ab = 0
    set_exact = slot_hit = slot_tot = 0
    margins, n_distinct, lat = [], [], []
    ly_do: dict[str, int] = {}
    per = {}
    for q in qids:
        g, plan = gold[q], plans[q]
        gs = {s["slot"]: (s["ref"], str(s["raw"])) for s in g["provenance"]}
        t0 = time.perf_counter()
        r = emit(con, plan, g["lop"], replace(arith, pipeline=pipe), labs)
        lat.append((time.perf_counter() - t0) * 1000)
        if r is None:
            continue
        absta = bool(r.get("abstain"))
        ne = (not absta) and khop(r.get("answer"), g["dap_an_gold"], TOL)
        dung += ne
        ab += absta
        sai += (not absta) and (not ne)
        if absta:
            k = r.get("abstain_reason") or "?"
            ly_do[k] = ly_do.get(k, 0) + 1
        hit = 0
        ps = r.get("per_slot") or {}
        for v in ps.values():
            want = gs.get(v["slot"])
            if not want:
                continue
            slot_tot += 1
            p = v.get("pick") or {}
            if p.get("evidence_ref") == want[0] and str(p.get("value")) == want[1]:
                hit += 1
            gt = v.get("gate") or {}
            if gt.get("margin") is not None:
                margins.append(gt["margin"])
            if gt.get("n_distinct_values") is not None:
                n_distinct.append(gt["n_distinct_values"])
        slot_hit += hit
        se = bool(gs) and hit == len(gs) and not absta
        set_exact += se
        per[q] = {"numeric_exact": ne, "abstain": absta,
                  "abstain_reason": r.get("abstain_reason"), "operand_hit": hit,
                  "n_gold_slot": len(gs), "set_exact": se}
    n = len(qids)
    return {
        # A4 — hai metric BÁO SONG SONG, không thay thế nhau
        "operand_set_exact": f"{set_exact}/{n}",
        "numeric_exact": f"{dung}/{n}",
        "slot_top1_exact": f"{slot_hit}/{slot_tot}" if slot_tot else "0/0",
        "n_sai": sai, "n_abstain": ab,
        "abstain_rate": round(ab / n, 4),
        "abstain_theo_ly_do": ly_do,
        "ambiguity_margin_p50": round(st.median(margins), 4) if margins else None,
        "n_distinct_trung_binh": round(sum(n_distinct) / len(n_distinct), 2)
                                 if n_distinct else None,
        "latency_ms_p50": round(st.median(lat), 1) if lat else None,
        "latency_ms_p95": round(sorted(lat)[int(len(lat) * 0.95) - 1], 1)
                          if len(lat) >= 2 else None,
        "per_qid": per,
    }


def recall_theo_N(con, qids, gold, plans, labs, al, sfl, Ns) -> dict:
    """gold có sống sót cắt top-M không, theo từng M. Độc lập với emit()."""
    out = {N: 0 for N in Ns}
    pool_hit = tot = 0
    for q in qids:
        g, plan = gold[q], plans[q]
        stext = spec_text(plan, metric_phrase(plan, labs))
        gs = {s["slot"]: (s["ref"], str(s["raw"])) for s in g["provenance"]}
        for s in slots_for(plan, g["lop"], al):
            want = gs.get(s.name)
            if not want:
                continue
            tot += 1
            sub = dict(plan)
            sub["entities"], sub["years"] = [s.ticker], [s.year]
            pool = fetch_pool(con, sub, legacy_order=False)
            pool_hit += any(c["evidence_ref"] == want[0] and str(c["value"]) == want[1]
                            for c in pool)
            r = rank_pool(pool, sub, stext, sfl, None)
            gi = next((i for i, c in enumerate(r)
                       if c["evidence_ref"] == want[0] and str(c["value"]) == want[1]),
                      None)
            for N in Ns:
                out[N] += gi is not None and gi < N
    return {"n_slot": tot, "pool_recall": f"{pool_hit}/{tot}",
            "lattice_recall_theo_N": {str(N): f"{v}/{tot}" for N, v in out.items()}}


def main() -> int:
    con = sqlite3.connect(
        f"file:{ROOT/'data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db'}?mode=ro&immutable=1", uri=True)
    plans = {p["qid"]: p for p in (json.loads(l) for l in
             (ROOT / "evaluation/question_plans_1012.jsonl").open(encoding="utf-8"))}
    gold = {g["qid"]: g for g in (json.loads(l) for l in
            (ROOT / "data/curated/dev-legacy/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")}
    labs, al = registry_labels(), load_aliases()
    qids = sorted(q for q, g in gold.items() if g["lop"] in ARITH_INTENTS)
    C3 = LADDER["C3"]

    # ── A2 ─────────────────────────────────────────────────────────────────
    quet = {}
    for N in N_QUET:
        quet[str(N)] = {k: v for k, v in mot_lan(
            con, qids, gold, plans, labs,
            replace(ARITH_PIPE, shortlist_m=N, scorer=ScoreFlags()), C3).items()
            if k != "per_qid"}
    rc_s0 = recall_theo_N(con, qids, gold, plans, labs, al, ScoreFlags(), N_QUET)
    rc_s5 = recall_theo_N(con, qids, gold, plans, labs, al, SLADDER["S5"], N_QUET)

    # ── A3 ─────────────────────────────────────────────────────────────────
    tat = mot_lan(con, qids, gold, plans, labs,
                  replace(ARITH_PIPE, scorer=ScoreFlags()), C3)
    bat = mot_lan(con, qids, gold, plans, labs,
                  replace(ARITH_PIPE, scorer=ScoreFlags(), score_floor=True), C3)
    bat2 = mot_lan(con, qids, gold, plans, labs,
                   replace(ARITH_PIPE, scorer=ScoreFlags(), score_floor=True), C3)
    tat_det = json.dumps(tat["per_qid"], sort_keys=True)
    det_ok = json.dumps(bat["per_qid"], sort_keys=True) == json.dumps(
        bat2["per_qid"], sort_keys=True)

    # đếm bao nhiêu ô cùng điểm sàn — doc 140 hỏi thẳng câu này
    cung_san = []
    for q in qids:
        g, plan = gold[q], plans[q]
        stext = spec_text(plan, metric_phrase(plan, labs))
        for s in slots_for(plan, g["lop"], al):
            sub = dict(plan)
            sub["entities"], sub["years"] = [s.ticker], [s.year]
            r = rank_pool(fetch_pool(con, sub, legacy_order=False), sub, stext,
                          ScoreFlags(), None, floor=True)
            n = sum(1 for c in r if "_floor_rank" in c)
            if n:
                cung_san.append({"qid": q, "slot": s.name, "n_o_cung_diem_san": n,
                                 "n_pool": len(r)})

    reg = [q for q in qids if tat["per_qid"].get(q, {}).get("numeric_exact")
           and not bat["per_qid"].get(q, {}).get("numeric_exact")]
    imp = [q for q in qids if bat["per_qid"].get(q, {}).get("numeric_exact")
           and not tat["per_qid"].get(q, {}).get("numeric_exact")]

    rep = {
        "_schema": "a2_a3_sweep v1 — doc 140 §3.4",
        "date": "2026-08-21", "dataset": "gold_dap_an_v1 · 24 câu non-lookup",
        "evaluation_mode": "TRAIN_FIT / RESEARCH-ONLY",

        "A2_quet_N": {
            "N_final": None,
            "TAI_SAO_None": ("Chốt N bằng gold trên TRAIN_FIT là selection bias — "
                             "doc 140 §3.4. Bảng dưới CHỈ là curve nghiên cứu. "
                             "N_final phải chốt trên DEV sau khi có nhãn."),
            "N_dang_chay_trong_production": ARITH_PIPE.shortlist_m,
            "recall_S0": rc_s0, "recall_S5": rc_s5,
            "bang": quet,
            "quan_sat": ("mở rộng N KHÔNG giảm raw recall nhưng đổi ambiguity/"
                         "margin/latency — xem cột n_distinct_trung_binh và "
                         "latency_ms_p95. Câu 'chi phí chỉ là latency' đã bỏ."),
        },

        "A3_diem_san": {
            "tat": {k: v for k, v in tat.items() if k != "per_qid"},
            "bat": {k: v for k, v in bat.items() if k != "per_qid"},
            "paired": {"improved": imp, "regressed": reg,
                       "net": len(imp) - len(reg)},
            "determinism_2_lan_giong_nhau": det_ok,
            "tie_break": "sort theo observation_uid trong nhóm cùng điểm sàn",
            "o_cung_diem_san": cung_san,
            "canh_bao_doc140": ("nếu nhiều ô cùng điểm sàn thì 'cho cạnh tranh' "
                                "KHÔNG tự tạo tín hiệu chọn đúng — nó chỉ biến "
                                "'chắc chắn sai' thành 'gần như chắc chắn sai'."),
        },

        "A4_tach_metric": {
            "quy_uoc": "operand_set_exact và numeric_exact báo SONG SONG",
            "operand_set_exact": tat["operand_set_exact"],
            "numeric_exact": tat["numeric_exact"],
            "slot_top1_exact": tat["slot_top1_exact"],
            "vi_sao_khac_nhau": ("numeric_exact có thể ĐÚNG khi operand sai — 3/37 "
                                 "miss có giá trị trùng gold ở ô khác. Gộp hai "
                                 "metric làm mất đúng thông tin đó."),
        },
        "command": "python3 tools/run_a2_a3_sweep_v1.py",
    }
    (ROOT / "reports/a2_a3_sweep_v1.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print("A2 · quét N (shortlist_m)")
    print(f"{'N':>3} {'set_exact':>10} {'numeric':>8} {'slot_top1':>10} "
          f"{'abst':>5} {'n_dist':>7} {'p50ms':>7} {'p95ms':>7}")
    for N, v in quet.items():
        print(f"{N:>3} {v['operand_set_exact']:>10} {v['numeric_exact']:>8} "
              f"{v['slot_top1_exact']:>10} {v['n_abstain']:>5} "
              f"{str(v['n_distinct_trung_binh']):>7} "
              f"{str(v['latency_ms_p50']):>7} {str(v['latency_ms_p95']):>7}")
    print(f"\npool recall {rc_s0['pool_recall']} · lattice S0 "
          f"{rc_s0['lattice_recall_theo_N']} \n                     · lattice S5 "
          f"{rc_s5['lattice_recall_theo_N']}")
    print(f"\nA3 · điểm sàn: numeric {tat['numeric_exact']} → {bat['numeric_exact']}"
          f" · improved {imp} · regressed {reg} · determinism {det_ok}")
    print(f"     slot có ô điểm sàn: {len(cung_san)} · "
          f"{[(c['slot'], c['n_o_cung_diem_san']) for c in cung_san[:6]]}")
    print("-> reports/a2_a3_sweep_v1.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
