#!/usr/bin/env python3
"""Ablation v3 · workstream B (row_path) — singleton / bundle / leave-one-out.

Đóng doc 140 §3.5. Ba khác biệt so với ablation v2:

  1. **Chạy ĐÚNG đường ống production.** v2 gọi thẳng fetch_pool → rank_pool và
     bỏ qua dedupe + ambiguity_gate + enforce_metric_consistency, nên số của nó
     không so được với C3. v3 đi qua `emit()` như production, chỉ đổi tham số
     `PipelineFlags.scorer`. Gate A1 đã PASS với cách này.
  2. **Luật giữ feature mềm hơn nhưng chặt hơn.** v2 dùng "singleton net ≥ +2".
     Doc 140 bác đúng: luật ấy giết feature có tương tác. Luật mới:
         giữ nếu  singleton net ≥ +2  HOẶC  bỏ khỏi bundle làm bundle giảm ≥ 2
  3. **Báo cả bốn cấp metric**, không gộp: slot_top1_exact · operand_set_exact ·
     numeric_exact · abstain. Doc 140 §3.8 nói đúng rằng slot_top1 KHÔNG kéo
     theo set_exact như một hệ quả toán học — nên phải báo riêng.

Chạy:  python3 tools/run_scoring_ablation_v3.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import replace
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from execution.emit_arith_v1 import ARITH_INTENTS, ARITH_PIPE, LADDER  # noqa: E402
from execution.row_feats_v1 import REGISTRY as ROW_REG  # noqa: E402
from execution.score_v2 import LADDER as SL, NONCIRCULAR, ScoreFlags  # noqa: E402
from build_candidate_v1 import registry_labels  # noqa: E402
from run_a2_a3_sweep_v1 import mot_lan  # noqa: E402

ROW_FEATS = tuple(ROW_REG)
NONCIRC_ROW = tuple(k for k, v in ROW_REG.items() if not v["circular_with_gold"])


def mcnemar(b: int, c: int) -> float:
    n = b + c
    return 1.0 if n == 0 else min(
        1.0, 2 * sum(comb(n, i) for i in range(min(b, c) + 1)) / (2 ** n))


def paired(a: dict, b: dict, qids, khoa="numeric_exact") -> dict:
    imp = sorted(q for q in qids if b["per_qid"].get(q, {}).get(khoa)
                 and not a["per_qid"].get(q, {}).get(khoa))
    reg = sorted(q for q in qids if a["per_qid"].get(q, {}).get(khoa)
                 and not b["per_qid"].get(q, {}).get(khoa))
    return {"improved": imp, "regressed": reg, "net": len(imp) - len(reg),
            "mcnemar_p": round(mcnemar(len(imp), len(reg)), 4)}


def main() -> int:
    con = sqlite3.connect(
        f"file:{ROOT/'data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db'}?mode=ro&immutable=1", uri=True)
    plans = {p["qid"]: p for p in (json.loads(l) for l in
             (ROOT / "evaluation/question_plans_1012.jsonl").open(encoding="utf-8"))}
    gold = {g["qid"]: g for g in (json.loads(l) for l in
            (ROOT / "data/curated/dev-legacy/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")}
    labs = registry_labels()
    qids = sorted(q for q, g in gold.items() if g["lop"] in ARITH_INTENTS)
    C3 = LADDER["C3"]
    S5 = SL["S5"]

    def run(sfl: ScoreFlags) -> dict:
        return mot_lan(con, qids, gold, plans, labs,
                       replace(ARITH_PIPE, scorer=sfl), C3)

    arms: dict[str, ScoreFlags] = {"S0": ScoreFlags(), "S5_baseline": S5}
    for f in ROW_FEATS:                       # singleton
        arms[f"SGL_{f}"] = replace(S5, **{f: True})
    arms["BUNDLE_all4"] = replace(S5, **{f: True for f in ROW_FEATS})
    arms["BUNDLE_noncirc"] = replace(S5, **{f: True for f in NONCIRC_ROW})
    for f in ROW_FEATS:                       # leave-one-out khỏi bundle đầy đủ
        arms[f"LOO_bo_{f}"] = replace(S5, **{g: (g != f) for g in ROW_FEATS})
    # NONCIRC_base là mốc đối chiếu ĐÚNG cho Gate C. Bản đầu chỉ có
    # `NONCIRCULAR_ONLY` (đã kèm 3 feature row) nên so C với nó là so lệch mốc.
    arms["NONCIRC_base"] = NONCIRCULAR
    arms["NONCIRCULAR_ONLY"] = replace(NONCIRCULAR, **{f: True for f in NONCIRC_ROW})

    # B-2 · TÁCH thay vì CỘNG THÊM. Xem ghi chú trong score_v2.score_cell:
    # row_path vốn ĐÃ nằm trong idf_overlap (ghép nhãn + row_path), nên mọi
    # feature row_* cộng lên trên đều là cộng đôi. Nhánh dưới tách hai nguồn ra.
    arms["SPLIT_only"] = replace(S5, split_label_row=True)
    for f in ROW_FEATS:
        arms[f"SPLIT+{f}"] = replace(S5, split_label_row=True, **{f: True})
    arms["SPLIT+noncirc3"] = replace(S5, split_label_row=True,
                                     **{f: True for f in NONCIRC_ROW})
    arms["SPLIT+all4"] = replace(S5, split_label_row=True,
                                 **{f: True for f in ROW_FEATS})

    # C · parser kỳ. Ưu tiên C được nâng lên sau reports/diag_weight_scale_v1:
    # `col_year` (+0,6) tạo 12/33 khoảng cách điểm — chiều QUYẾT ĐỊNH thứ hạng
    # là CỘT, không phải DÒNG. Doc 138 xếp B trước C là lỗi phương pháp.
    arms["C_period_parse"] = replace(S5, period_parse=True)
    arms["C_period_parse_noncirc"] = replace(NONCIRCULAR, period_parse=True)
    arms["C+SPLIT"] = replace(S5, period_parse=True, split_label_row=True)

    res = {k: run(v) for k, v in arms.items()}
    base = res["S5_baseline"]
    bundle = res["BUNDLE_all4"]

    # ── luật giữ feature (doc 140 §3.5) ────────────────────────────────────
    quyet_dinh = {}
    for f in ROW_FEATS:
        sgl = paired(base, res[f"SGL_{f}"], qids)
        loo = paired(res[f"LOO_bo_{f}"], bundle, qids)   # bundle − LOO = đóng góp
        giu = sgl["net"] >= 2 or loo["net"] >= 2
        quyet_dinh[f] = {
            "singleton": sgl, "leave_one_out_dong_gop": loo,
            "circular_with_gold": ROW_REG[f]["circular_with_gold"],
            "GIU": giu,
            "ly_do": ("singleton net ≥ +2" if sgl["net"] >= 2 else
                      "LOO cho thấy bundle giảm ≥ 2 khi bỏ" if loo["net"] >= 2 else
                      "không đạt cả hai điều kiện ⇒ GỠ")}

    def gon(d):
        return {k: v for k, v in d.items() if k != "per_qid"}

    gate_b = {
        "slot_top1_delta": None, "PASS": None,
        "quy_uoc": "slot_top1_exact ≥ +6/66 vs S5 · numeric_exact không giảm · P0 xanh",
    }
    b_hit = int(bundle["slot_top1_exact"].split("/")[0])
    s_hit = int(base["slot_top1_exact"].split("/")[0])
    b_num = int(bundle["numeric_exact"].split("/")[0])
    s_num = int(base["numeric_exact"].split("/")[0])
    gate_b["slot_top1_delta"] = b_hit - s_hit
    gate_b["numeric_delta"] = b_num - s_num
    gate_b["PASS"] = (b_hit - s_hit) >= 6 and b_num >= s_num

    rep = {
        "_schema": "scoring_ablation_v3 — workstream B, doc 140 §3.5",
        "date": "2026-08-21",
        "dataset": "gold_dap_an_v1 · 24 câu non-lookup · 66 slot",
        "evaluation_mode": "TRAIN_FIT / RESEARCH-ONLY",
        "duong_ong": "emit() của emit_arith_v1 — CÙNG production (Gate A1 PASS)",
        "prereg": "docs/PREREGISTRATION_D1A.md §3 Gate B",
        "feature_registry_row": {k: {kk: vv for kk, vv in v.items() if kk != "ham"}
                                 for k, v in ROW_REG.items()},
        "ablation": {k: gon(v) for k, v in res.items()},
        "paired_vs_S5": {k: paired(base, v, qids) for k, v in res.items()
                         if k != "S5_baseline"},
        "quyet_dinh_giu_feature": quyet_dinh,
        "GATE_B": gate_b,
        "GATE_C": {
            "quy_uoc": "nhánh NONCIRCULAR tăng ≥ +4/66 VÀ overall không regression",
            "NONCIRC_base": None, "NONCIRC_plus_period_parse": None,
            "S5_base": None, "S5_plus_period_parse": None},
        "canh_bao_vong_tron": {
            "feature_vong_tron": [k for k, v in ROW_REG.items()
                                  if v["circular_with_gold"]],
            "y_nghia": ("row_depth_prior trùng luật 7 của bộ sinh gold (row_path "
                        "NGẮN NHẤT) ⇒ gain của nó trên gold-45 KHÔNG chứng minh "
                        "gì. Đọc BUNDLE_noncirc thay vì BUNDLE_all4."),
        },
        "per_qid": {k: v["per_qid"] for k, v in res.items()},
        "command": "python3 tools/run_scoring_ablation_v3.py",
    }
    rep["GATE_C"] |= {
        "NONCIRC_base": res["NONCIRC_base"]["slot_top1_exact"],
        "NONCIRC_plus_period_parse": res["C_period_parse_noncirc"]["slot_top1_exact"],
        "S5_base": base["slot_top1_exact"],
        "S5_plus_period_parse": res["C_period_parse"]["slot_top1_exact"],
        "delta_noncirc": int(res["C_period_parse_noncirc"]["slot_top1_exact"].split("/")[0])
                         - int(res["NONCIRC_base"]["slot_top1_exact"].split("/")[0]),
    }
    rep["GATE_C"]["PASS"] = rep["GATE_C"]["delta_noncirc"] >= 4
    (ROOT / "reports/scoring_ablation_v3.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{'nhánh':26} {'slot_top1':>10} {'set_exact':>10} {'numeric':>8} {'abst':>5}")
    for k, v in res.items():
        print(f"{k:26} {v['slot_top1_exact']:>10} {v['operand_set_exact']:>10} "
              f"{v['numeric_exact']:>8} {v['n_abstain']:>5}")
    print("\nquyết định giữ feature:")
    for f, d in quyet_dinh.items():
        print(f"  {f:24} sgl net {d['singleton']['net']:+d} · LOO net "
              f"{d['leave_one_out_dong_gop']['net']:+d} · circular "
              f"{str(d['circular_with_gold']):5} → {'GIỮ' if d['GIU'] else 'GỠ'}")
    nb = int(res["NONCIRC_base"]["slot_top1_exact"].split("/")[0])
    nc = int(res["C_period_parse_noncirc"]["slot_top1_exact"].split("/")[0])
    print(f"\nGATE C (nhánh NONCIRCULAR): {nb}/66 → {nc}/66 · delta {nc-nb:+d} "
          f"(cần ≥ +4) → {'PASS' if nc-nb >= 4 else 'FAIL'}")
    print(f"GATE B: slot_top1 delta {gate_b['slot_top1_delta']:+d} "
          f"(cần ≥ +6) · numeric delta {gate_b['numeric_delta']:+d} "
          f"(cần ≥ 0) → {'PASS' if gate_b['PASS'] else 'FAIL'}")
    print("-> reports/scoring_ablation_v3.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
