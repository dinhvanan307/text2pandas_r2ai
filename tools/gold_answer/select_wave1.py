#!/usr/bin/env python3
"""Chọn 40 QID Wave 1 từ dev60 — doc 161 §6 Pha 1.

Ba ràng buộc của doc 161 được thi hành ở đây, không phải ghi trong tài liệu:

1. **Không chọn lại theo prediction/error.** Script này chỉ đọc `question_plans_1012`
   (entity/period/intent parse từ CÂU HỎI) và `dev60_selection.json`. Không đọc
   submission, không đọc candidate pool, không đọc điểm.
2. **audit40 sealed.** Universe cứng là 60 QID của dev60; nếu strata thiếu thì
   **báo thiếu**, tuyệt đối không mượn QID từ audit40.
3. **Tất định.** Thứ tự trong mỗi stratum = QID tăng dần. Không random, không seed
   ẩn — chạy lại cho cùng danh sách.

Strata doc 161 yêu cầu: 20 single-entity/single-period lookup · 8 single-entity/
multi-period · 8 multi-entity · 4 ratio/operation/other.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/curated/dev-legacy/answer_gold"

CHI_TIEU = [
    ("S1_lookup_1entity_1period", 20),
    ("S2_1entity_multi_period", 8),
    ("S3_multi_entity", 8),
    ("S4_ratio_operation_khac", 4),
]
RATIO_INTENT = {"ratio", "percentage_change", "average", "count", "sum"}


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def phan_tang(p: dict) -> str:
    ne = len(p.get("entities") or [])
    ny = len(p.get("years") or [])
    it = p.get("intent_v1")
    if ne > 1:
        return "S3_multi_entity"
    if it == "lookup" and ne <= 1 and ny <= 1:
        return "S1_lookup_1entity_1period"
    if ne <= 1 and ny > 1:
        return "S2_1entity_multi_period"
    if it in RATIO_INTENT:
        return "S4_ratio_operation_khac"
    return "S2_1entity_multi_period" if ny > 1 else "S4_ratio_operation_khac"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    p_sel = ROOT / "data/curated/dev-legacy/execution_gold/dev60_selection.json"
    p_plan = ROOT / "evaluation/question_plans_1012.jsonl"
    dev = json.loads(p_sel.read_text(encoding="utf-8"))
    plans = {r["qid"]: r for r in (json.loads(l) for l in
                                   p_plan.open(encoding="utf-8") if l.strip())}

    tang: dict[str, list[int]] = {k: [] for k, _ in CHI_TIEU}
    chi_tiet = []
    for q in sorted(dev["qids"]):
        p = plans[q]
        t = phan_tang(p)
        tang[t].append(q)
        chi_tiet.append({"qid": q, "stratum": t,
                         "entities": p.get("entities"), "years": p.get("years"),
                         "intent_v1": p.get("intent_v1"),
                         "output_unit": p.get("output_unit"),
                         "basis": p.get("basis"),
                         "question": p.get("question")})

    chon, thieu = [], []
    for ten, n in CHI_TIEU:
        co = sorted(tang[ten])
        lay = co[:n]
        chon += lay
        if len(co) < n:
            thieu.append({"stratum": ten, "can": n, "co": len(co),
                          "thieu": n - len(co)})

    du = sorted(set(dev["qids"]) - set(chon))
    bu = []
    if len(chon) < 40:
        # bù TẤT ĐỊNH theo QID tăng dần từ phần còn lại CỦA CHÍNH dev60
        bu = du[:40 - len(chon)]
        chon += bu

    kq = {
        "_schema": "wave1_selection v1 — doc 161 §6 Pha 1",
        "universe": "dev60 (audit40 SEALED, không đụng)",
        "dev60_selection_sha256": sha_file(p_sel),
        "question_plans_sha256": sha_file(p_plan),
        "quy_tac_chon": ("theo stratum, QID tăng dần, KHÔNG random; thiếu thì bù "
                         "tất định từ phần còn lại của dev60"),
        "khong_dung_prediction": True,
        "chi_tieu_doc161": dict(CHI_TIEU),
        "phan_bo_thuc_te_cua_dev60": {k: len(v) for k, v in tang.items()},
        "THIEU_STRATA": thieu,
        "n_bu_tat_dinh": len(bu),
        "qid_bu": bu,
        "wave1_qids": sorted(chon),
        "n": len(chon),
    }
    (OUT / "wave1_selection.json").write_text(
        json.dumps(kq, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "dev60_cohort.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in chi_tiet) + "\n",
        encoding="utf-8")

    print(json.dumps({k: v for k, v in kq.items() if k != "wave1_qids"},
                     ensure_ascii=False, indent=1))
    print("wave1:", sorted(chon))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
