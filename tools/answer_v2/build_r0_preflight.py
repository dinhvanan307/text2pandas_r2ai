#!/usr/bin/env python3
"""R0 preflight — recall@K, eligibility 66, hai mẫu số, tuyên bố KHÔNG gọi model.

Doc 159 §6.8 · §6.9. Ba điều tài liệu nhấn mạnh và được thi hành ở đây:

1. **Tách hai phép đo, ghi rõ mẫu số.**
   `MODEL_CAPABILITY_66` chấm trên `gold_in_topK` — đo *khả năng chọn*.
   `PRODUCTION_POLICY_66` chấm trên đủ 66 — đo *chính sách sẽ chạy thật*.
   Gate `policy_correct ≥ 37/66` và `regressed ≤ 2` chỉ áp cho B. Gate schema
   áp trên `model_attempted` (A) hoặc `attempted_by_policy` (B), và phải nói rõ
   đang nói về mẫu số nào — trộn hai mẫu số là cách tạo ra một con số vô nghĩa
   trông như bằng chứng.

2. **K phải chọn bằng dữ liệu per-slot.** Nếu không K nào đạt 0,90 thì tuyên
   `STOP_AND_FIX_CANDIDATE_GENERATION`, **không** hạ ngưỡng cho gate xanh.

3. **Đếm gọi model = 0.** File này không import `llm_client`; `verify_patch`
   kiểm lại bằng cách quét chính source.

Chạy:  python3 tools/answer_v2/build_r0_preflight.py --inputs <thư mục train_fit>
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

K_LIST = (4, 8, 12, 16)
NGUONG_RECALL = 0.90
GATE_POLICY_CORRECT = 37
GATE_REGRESSED_MAX = 2


def doc_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", type=Path,
                    default=ROOT / "reports/answer_v2/train_fit_inputs")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "reports/answer_v2/r0_preflight")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    slots = doc_jsonl(a.inputs / "train_fit_66_slots.jsonl")
    pools = doc_jsonl(a.inputs / "candidate_pools_top16.jsonl")
    golds = {(g["qid"], g["slot_id"]): g
             for g in doc_jsonl(a.inputs / "train_fit_gold_labels.jsonl")}
    base = {(b["qid"], b["slot_id"]): b
            for b in doc_jsonl(a.inputs / "baseline_predictions.jsonl")}

    theo_slot = collections.defaultdict(list)
    for c in pools:
        theo_slot[(c["qid"], c["slot_id"])].append(c)
    for v in theo_slot.values():
        v.sort(key=lambda c: c["deterministic_rank"])

    # ── recall@K per-slot ──────────────────────────────────────────────────
    per_slot, dem = [], collections.Counter()
    thieu_gold = collections.Counter()
    for s in slots:
        key = (s["qid"], s["slot_id"])
        g = golds[key]
        gid, grank = g["gold_candidate_id"], g["gold_rank_in_ranked"]
        ids = [c["stable_candidate_id"] for c in theo_slot.get(key, [])]
        row = {"qid": s["qid"], "slot_id": s["slot_id"],
               "supported_slot": s["supported_slot"], "ambiguous": s["ambiguous"],
               "gold_candidate_id": gid, "gold_rank_in_ranked": grank,
               "n_pool_raw": s["n_pool_raw"], "n_ranked": s["n_ranked"],
               "gold_in_raw_pool": gid is not None,
               "gold_after_hard_filter": gid is not None and grank is not None}
        for k in K_LIST:
            hit = bool(gid) and gid in ids[:k]
            row[f"gold_in_top{k}"] = hit
            dem[f"top{k}"] += hit
        if gid is None:
            thieu_gold["GOLD_KHONG_CO_TRONG_RANKED"] += 1
        elif grank is not None and grank >= max(K_LIST):
            thieu_gold[f"GOLD_SAU_HANG_{max(K_LIST)}"] += 1
        per_slot.append(row)

    n = len(slots)
    evaluable = sum(1 for r in per_slot if r["gold_after_hard_filter"])
    recall = {f"recall_at_{k}": {"n": dem[f'top{k}'], "tren": n,
                                 "ty_le": round(dem[f"top{k}"] / n, 4)}
              for k in K_LIST}

    # K nhỏ nhất đạt ngưỡng — KHÔNG hạ ngưỡng để gate xanh
    dat = [k for k in K_LIST if dem[f"top{k}"] / n >= NGUONG_RECALL]
    chosen_k = min(dat) if dat else None
    verdict = ("K_LOCKED" if chosen_k
               else "STOP_AND_FIX_CANDIDATE_GENERATION")

    (a.out / "recall_per_slot.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in per_slot) + "\n",
        encoding="utf-8")
    (a.out / "recall_at_k.json").write_text(json.dumps({
        "_schema": "recall_at_k v1 — doc 159 §6.9",
        "n_slot": n,
        "raw_pool_recall": {"n": sum(r["gold_in_raw_pool"] for r in per_slot),
                            "tren": n},
        "after_hard_filter_recall": {"n": evaluable, "tren": n},
        "evaluable_denominator": evaluable,
        **recall,
        "nguong": NGUONG_RECALL,
        "chosen_K": chosen_k,
        "verdict": verdict,
        "missing_gold_taxonomy": dict(thieu_gold),
        "ghi_chu": ("Không K nào đạt ngưỡng ⇒ STOP. KHÔNG hạ ngưỡng để gate "
                    "xanh; đổi ngưỡng phải tạo version mới TRƯỚC model call."
                    if not chosen_k else
                    "Khoá K nhỏ nhất đạt ngưỡng."),
        "per_slot_file": "recall_per_slot.jsonl",
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── eligibility 66 (§6.7) ──────────────────────────────────────────────
    ly_do_khong = collections.Counter(
        s["unsupported_reason"] for s in slots if not s["supported_slot"])
    theo_route = collections.Counter(s["answer_route"] for s in slots)
    qid_r2 = {s["qid"] for s in slots if s["answer_route"] == "R2"}
    eligible = [s for s in slots if s["supported_slot"]]
    amb = [s for s in eligible if s["ambiguous"]]

    (a.out / "eligibility_report_66.json").write_text(json.dumps({
        "_schema": "eligibility_report_66 v2 — doc 159 §6.7",
        "total": n,
        "supported_slot": len(eligible),
        "unsupported_by_reason": dict(ly_do_khong),
        "eligible": len(eligible),
        "ambiguous": len(amb),
        "attempted_by_policy": len(amb),
        "slot_theo_answer_route": dict(theo_route),
        "n_qid_route_R2": len(qid_r2),
        "quy_tac": ("SUPPORTED_SLOT = OperandKey hợp lệ AND pool qua hard filter "
                    "đúng entity/period AND pool ≥2 ứng viên. `answer_route` chỉ "
                    "là trường BÁO CÁO, KHÔNG dùng làm điều kiện loại."),
        "vi_sao_khong_khoa_R2": (
            "Sau P0 chỉ còn rất ít QID route R2. Khoá theo R2 sẽ làm cỡ mẫu quá "
            "nhỏ và phải rút request TRAIN_FIT với mã "
            "RERANK_STOP_OPPORTUNITY_TOO_SMALL."),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── hai mẫu số (§6.8) — khung, chưa có số model vì chưa gọi ───────────
    n_base_dung = sum(1 for b in base.values() if b["correct"])
    cap = {
        "_schema": "MODEL_CAPABILITY_66 — mẫu số là gold_in_topK",
        "raw_pool_total": sum(r["n_pool_raw"] for r in per_slot),
        "gold_after_hard_filter": evaluable,
        "gold_in_topK": dem[f"top{chosen_k}"] if chosen_k else dem["top16"],
        "K_dung_de_tinh": chosen_k or 16,
        "model_attempted": 0, "valid_schema": 0, "correct": 0,
        "invalid_schema": 0, "id_not_in_whitelist": 0,
        "endpoint_error": 0, "timeout": 0, "abstain": 0,
        "TRANG_THAI": "NOT_MEASURED — chưa gọi model lần nào",
    }
    pol = {
        "_schema": "PRODUCTION_POLICY_66 — mẫu số là đủ 66 slot",
        "baseline_correct": f"{n_base_dung}/{n}",
        "policy_correct": None, "improved": None, "regressed": None, "net": None,
        "attempted_by_policy": 0, "fallback_count": n,
        "TRANG_THAI": "NOT_MEASURED — chưa gọi model lần nào",
    }
    (a.out / "capability_denominator.json").write_text(
        json.dumps(cap, ensure_ascii=False, indent=1), encoding="utf-8")
    (a.out / "production_policy_denominator.json").write_text(
        json.dumps(pol, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── tuyên bố không gọi model ──────────────────────────────────────────
    (a.out / "NO_MODEL_CALL_DECLARATION.json").write_text(json.dumps({
        "_schema": "NO_MODEL_CALL_DECLARATION v1",
        "model_call_count": 0,
        "endpoint_configured": False,
        "bang_chung": [
            "configs/answer_v2/llm_v1.yaml có `endpoint:` trống",
            "artifacts/llm_cache/ không có tệp cache rerank_v1_* nào ngoài fixture test",
            "rerank_eval.json có exercised=false",
            "verify_patch.py kiểm lại bằng cách quét source và cache",
        ],
        "pham_vi": "toàn bộ R0 preflight — recall, eligibility, mẫu số",
        "ghi_chu": ("Doc 159 §5 đặt Qwen smoke/TRAIN_FIT ở HOLD. Mọi số trong "
                    "preflight này sinh từ scorer tất định, không có LLM."),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── báo cáo tổng ──────────────────────────────────────────────────────
    (a.out / "preflight_report.json").write_text(json.dumps({
        "_schema": "preflight_report v1",
        "n_slot": n, "supported": len(eligible), "ambiguous": len(amb),
        "evaluable": evaluable,
        "recall": {k: v["ty_le"] for k, v in recall.items()},
        "chosen_K": chosen_k, "k_verdict": verdict,
        "baseline": f"{n_base_dung}/{n}",
        "gate_policy_correct_min": GATE_POLICY_CORRECT,
        "gate_regressed_max": GATE_REGRESSED_MAX,
        "model_call_count": 0,
        "TRANG_THAI": ("READY_FOR_MODEL_CALL_REQUEST" if chosen_k
                       else "BLOCKED_" + verdict),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"slot {n} · supported {len(eligible)} · ambiguous {len(amb)} "
          f"· evaluable {evaluable}")
    for k in K_LIST:
        print(f"  recall@{k:<2} {dem[f'top{k}']}/{n} = {dem[f'top{k}']/n:.4f}")
    print(f"chosen K: {chosen_k} · verdict {verdict}")
    print(f"baseline {n_base_dung}/{n} · model_call_count 0")
    print(f"-> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
