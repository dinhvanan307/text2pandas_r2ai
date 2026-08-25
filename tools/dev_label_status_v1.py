#!/usr/bin/env python3
"""Trạng thái nhãn DEV + phân bố theo intent — review 131 §5 "DEV Wave-1".

Review 131: "37 FAST+MED được chọn theo complexity chưa chắc có đủ
percentage/difference/sum. Trước khi dùng làm gate C2 phải báo distribution."
Và: "intent chỉ có 1–2 case thì không được dùng net của intent đó để promotion".

Tệp này biến hai câu ấy thành một cổng chạy được: nó nói CHÍNH XÁC intent nào
đủ điều kiện làm promotion gate và intent nào phải mang nhãn EXPERIMENTAL,
theo ngưỡng đã khoá trong `configs/execution/promotion_rule_v1.yaml`
(`min_evaluable_cases_per_intent: 5`).

Chạy:  python3 tools/dev_label_status_v1.py
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLD_DIR = ROOT / "data/curated/dev-legacy/execution_gold"
MIN_PER_INTENT = 5          # khoá trong promotion_rule_v1.yaml

INTENTS = ("lookup", "percentage_change", "difference", "sum",
           "argmax_year", "average", "ratio", "max_min", "count",
           "multi_entity_aggregate")

REQUIRED_FIELDS = ("dap_an_gold", "don_vi_dap_an", "intent_gold", "operands",
                   "cong_thuc", "basis_gold", "trang_thai")


def main() -> int:
    sel = json.loads((GOLD_DIR / "dev60_selection.json").read_text(encoding="utf-8"))
    plans = {p["qid"]: p for p in (json.loads(l) for l in
             (ROOT / "data/curated/evaluation/legacy/question_plans_1012.jsonl").open(encoding="utf-8"))}

    lab_f = GOLD_DIR / "dev60_labels.jsonl"
    labels = ([json.loads(l) for l in lab_f.open(encoding="utf-8") if l.strip()]
              if lab_f.is_file() else [])
    done = [r for r in labels if r.get("dap_an_gold") is not None]

    dist_all = Counter(plans[q]["intent_v1"] for q in sel["qids"] if q in plans)
    batch = [r["qid"] for r in labels]
    dist_batch = Counter(plans[q]["intent_v1"] for q in batch if q in plans)
    dist_done = Counter(r.get("intent_gold") or plans.get(r["qid"], {}).get("intent_v1")
                        for r in done)

    incomplete = []
    for r in done:
        miss = [f for f in REQUIRED_FIELDS if r.get(f) in (None, "", [])]
        if r.get("trang_thai") == "GOLD_UNCERTAIN":
            miss = [m for m in miss if m == "dap_an_gold"]
        if miss:
            incomplete.append({"qid": r["qid"], "thieu": miss})

    readiness = {}
    for it in INTENTS:
        n_done = dist_done.get(it, 0)
        n_plan = dist_all.get(it, 0)
        readiness[it] = {
            "n_da_gan": n_done,
            "n_du_kien_trong_DEV60": n_plan,
            "trang_thai": ("PROMOTION_GATE_ELIGIBLE" if n_done >= MIN_PER_INTENT
                           else "EXPERIMENTAL" if n_done > 0
                           else "KHONG_CO_NHAN"),
        }

    overlap = sorted(set(sel["qids"]) & set(sel.get("excluded_gold45", [])))

    rep = {
        "_schema": "dev_label_status v1 — review 131 §5",
        "date": "2026-08-21",
        "nguong_da_khoa": {"min_evaluable_cases_per_intent": MIN_PER_INTENT,
                           "nguon": "configs/execution/promotion_rule_v1.yaml"},
        "dev60": {"n_qid": len(sel["qids"]), "seed": sel.get("seed")},
        "batch_dau": {"n_phieu": len(labels), "n_da_gan": len(done),
                      "n_pilot": sum(1 for r in labels if r.get("_la_pilot"))},
        "phan_bo_intent_v1_toan_DEV60": dict(dist_all.most_common()),
        "phan_bo_intent_v1_batch_dau": dict(dist_batch.most_common()),
        "phan_bo_intent_DA_GAN": dict(dist_done.most_common()),
        "readiness_theo_intent": readiness,
        "phieu_thieu_truong": incomplete,
        "overlap_voi_gold45": overlap,
        "overlap_hop_le": overlap == [],
        "VERDICT": ("DEV_READY" if len(done) >= 35 and not incomplete
                    else "DEV_CHUA_SAN_SANG"),
        "chan_gi": ([] if len(done) >= 35 else
                    [f"mới có {len(done)} nhãn, cần >=35 cho Wave-1 "
                     "(Definition of Done review 131 §10)"]),
        "canh_bao_anchoring": (
            "Dossier DEV có kèm top candidates để gán nhanh. Rủi ro: người gán "
            "xác nhận nhầm candidate đầu. Mỗi phiếu BẮT BUỘC ghi evidence_ref, "
            "raw value, unit, scale, period, basis, formula, operand role; và "
            "được phép GOLD_UNCERTAIN thay vì ép chọn."),
    }
    (ROOT / "reports/dev_label_status_v1.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"DEV-60: {rep['dev60']['n_qid']} QID · batch đầu {len(labels)} phiếu "
          f"· đã gán {len(done)}")
    print(f"overlap với gold-45: {overlap or 'không có'} "
          f"({'HỢP LỆ' if not overlap else 'VI PHẠM'})")
    print("\nphân bố intent_v1 toàn DEV-60:")
    for k, v in dist_all.most_common():
        print(f"   {k:24} {v}")
    print("\nphân bố intent_v1 trong BATCH ĐẦU (20 phiếu):")
    for k, v in dist_batch.most_common():
        print(f"   {k:24} {v}")
    print("\nreadiness (>=5 nhãn mới được làm promotion gate):")
    for k, v in readiness.items():
        if v["n_du_kien_trong_DEV60"] or v["n_da_gan"]:
            print(f"   {k:24} đã gán {v['n_da_gan']:2d} / dự kiến "
                  f"{v['n_du_kien_trong_DEV60']:2d}  → {v['trang_thai']}")
    print(f"\n{rep['VERDICT']}" + (f" · chặn: {rep['chan_gi']}" if rep["chan_gi"] else ""))
    print("-> reports/dev_label_status_v1.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
