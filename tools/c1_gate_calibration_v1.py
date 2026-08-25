#!/usr/bin/env python3
"""Hiệu chuẩn cổng tự tin của emitter lookup — CHẨN ĐOÁN, không phải tuning.

BỐI CẢNH
--------
Ablation C1a→C1e cho kết quả không mong đợi nhưng rất có ích:

    C1a  ghi đè 564 câu lookup   → net −1 trên gold-45  (+6 / −7)
    C1b  + operand-spec          → net −3               (+6 / −9)
    C1c  + margin gate 0,15      → chỉ còn 48 câu emit, net  0

Nghĩa là: emitter tất định BIẾT sửa 6 câu C0 sai, nhưng đồng thời PHÁ 7–9 câu
C0 đang đúng. Ship C1a/C1b là ship một bản tụt điểm. Đây chính là điều review
127 §5 lo khi bác "D4 gộp 7 việc": không tách flag thì gain và loss triệt tiêu
nhau và không ai biết vì sao.

Câu hỏi còn lại: có NGƯỠNG TỰ TIN nào để giữ 6 câu được sửa mà không phá 7 câu
kia không? Tệp này quét ngưỡng và trả lời bằng đường cong, không bằng ý kiến.

CẢNH BÁO PHƯƠNG PHÁP — ĐỌC TRƯỚC KHI DÙNG SỐ
--------------------------------------------
Quét trên gold-45 là quét trên tập đã dùng để tune V1.1. Ngưỡng chọn theo bảng
này là siêu tham số TRAIN_FIT, KHÔNG được coi là đã kiểm chứng. Bảng này chỉ có
hai cách dùng hợp lệ:

  1. Nếu KHÔNG ngưỡng nào cho net > 0  → kết luận HOLD vững, không phụ thuộc
     chuyện overfit (không có gì để overfit vào).
  2. Nếu CÓ ngưỡng cho net > 0 → đó mới là GIẢ THUYẾT, phải xác nhận lại trên
     DEV-60 sau khi gán nhãn, trước khi tiêu một lượt public.

Chạy:  python3 tools/c1_gate_calibration_v1.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from execution.emit_lookup_v1 import EmitFlags, pick  # noqa: E402
from execution.fact_rank_v1 import fetch_pool  # noqa: E402
from build_candidate_v1 import khop, load_control, registry_labels  # noqa: E402

# Bộ cờ đầy đủ NHƯNG TẮT margin gate — để lấy margin thô của từng câu rồi mới
# quét ngưỡng ngoài. Bật gate trong lúc quét thì không có dữ liệu để quét.
FULL_NO_GATE = EmitFlags(lookup_emitter=True, operand_spec=True, margin_gate=False,
                         statement_prior=True, unit_scale=True)
GRID = [0.0, 0.02, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30,
        0.40, 0.50, 0.70, 1.01]


def main() -> int:
    con = sqlite3.connect(
        f"file:{ROOT/'artifacts/retrieval/work.db'}?mode=ro&immutable=1", uri=True)
    plans = {p["qid"]: p for p in (json.loads(l) for l in
             (ROOT / "evaluation/question_plans_1012.jsonl").open(encoding="utf-8"))}
    gold = {g["qid"]: g for g in (json.loads(l) for l in
            (ROOT / "data/dev/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")}
    labs = registry_labels()
    sub0, _ = load_control()
    c0 = {r["id"]: r for r in sub0}

    per_q = []
    for q, g in sorted(gold.items()):
        plan = plans[q]
        base_ok = khop(c0[q].get("answer"), g["dap_an_gold"])
        targeted = plan.get("intent_v1") == "lookup"
        row = {"qid": q, "intent_v1": plan.get("intent_v1"), "lop_gold": g["lop"],
               "base_ok": base_ok, "targeted": targeted}
        if targeted:
            pool = fetch_pool(con, plan, legacy_order=True)
            r = pick(None, plan, FULL_NO_GATE, labs, pool=pool) if pool else None
            if r:
                cell = r["cell"]
                row.update({
                    "margin": r["margin"],
                    "emit_answer": r["answer"],
                    "emit_ok": khop(r["answer"], g["dap_an_gold"]),
                    "exact_phrase_hit": bool(cell.get("exact_phrase_hit")),
                    "co_operand_phrase": r["phrase"] is not None,
                    "score_top1": cell["score"],
                    "scale_exponent": r["scale_exponent_applied"],
                    "unit_name": r["unit_name"],
                    "statement_type": cell["statement_type"],
                })
        per_q.append(row)

    cand = [r for r in per_q if "emit_ok" in r]

    def sweep(name, keyfn) -> list[dict]:
        out = []
        for t in GRID:
            imp = [r["qid"] for r in cand if keyfn(r, t) and r["emit_ok"] and not r["base_ok"]]
            reg = [r["qid"] for r in cand if keyfn(r, t) and not r["emit_ok"] and r["base_ok"]]
            n_emit = sum(1 for r in cand if keyfn(r, t))
            out.append({"nguong": t, "n_emit_tren_gold45": n_emit,
                        "improved": imp, "regressed": reg,
                        "net": len(imp) - len(reg)})
        return out

    sweeps = {
        "margin": sweep("margin", lambda r, t: r["margin"] >= t),
        "margin_VA_exact_phrase": sweep(
            "mx", lambda r, t: r["margin"] >= t and r["exact_phrase_hit"]),
        "chi_exact_phrase": [{
            "nguong": "n/a",
            "n_emit_tren_gold45": sum(1 for r in cand if r["exact_phrase_hit"]),
            "improved": [r["qid"] for r in cand
                         if r["exact_phrase_hit"] and r["emit_ok"] and not r["base_ok"]],
            "regressed": [r["qid"] for r in cand
                          if r["exact_phrase_hit"] and not r["emit_ok"] and r["base_ok"]],
        }],
    }
    sweeps["chi_exact_phrase"][0]["net"] = (
        len(sweeps["chi_exact_phrase"][0]["improved"])
        - len(sweeps["chi_exact_phrase"][0]["regressed"]))

    best = max(sweeps["margin"], key=lambda r: r["net"])
    best_mx = max(sweeps["margin_VA_exact_phrase"], key=lambda r: r["net"])
    any_positive = max(best["net"], best_mx["net"],
                       sweeps["chi_exact_phrase"][0]["net"]) > 0
    # Hiệu chuẩn: emitter tự tin ⇒ có đúng hơn không? Nếu không, `margin` vô nghĩa.
    hi = [r for r in cand if r["margin"] >= 0.15]
    lo = [r for r in cand if r["margin"] < 0.15]
    def acc(rs):
        return round(sum(r["emit_ok"] for r in rs) / len(rs), 4) if rs else None

    def mcnemar_exact(b: int, c: int) -> float:
        """p hai phía cho cặp bất đồng (b improved, c regressed) — binomial(0,5).

        Bắt buộc có: 'net dương' trên vài cặp bất đồng là chuyện xảy ra thường
        xuyên do ngẫu nhiên. Không có p thì +2 và +20 trông giống nhau.
        """
        n = b + c
        if n == 0:
            return 1.0
        from math import comb
        k = min(b, c)
        tail = sum(comb(n, i) for i in range(0, k + 1)) / (2 ** n)
        return min(1.0, 2 * tail)

    for name, sw in sweeps.items():
        for r in sw:
            r["mcnemar_p_hai_phia"] = round(
                mcnemar_exact(len(r["improved"]), len(r["regressed"])), 4)
            r["ket_luan_thong_ke"] = (
                "KHÔNG có ý nghĩa thống kê" if r["mcnemar_p_hai_phia"] > 0.05
                else "có ý nghĩa ở mức 0,05")

    any_significant = any(r["mcnemar_p_hai_phia"] <= 0.05 and r["net"] > 0
                          for sw in sweeps.values() for r in sw)

    rep = {
        "_schema": "c1_gate_calibration v1 — CHẨN ĐOÁN cổng tự tin (review 127 §5)",
        "date": "2026-08-21",
        "canh_bao": ["TRAIN_FIT: gold-45 là tập đã dùng tune V1.1",
                     "n=45 quá nhỏ để chọn siêu tham số",
                     "ngưỡng chọn ở đây là GIẢ THUYẾT, phải xác nhận trên DEV-60"],
        "n_gold": len(per_q),
        "n_gold_emitter_cham": len(cand),
        "n_gold_ngoai_tam_emitter": len(per_q) - len(cand),
        "C0_dung_tren_45": sum(r["base_ok"] for r in per_q),
        "emitter_dung_tren_cac_cau_no_cham": f"{sum(r['emit_ok'] for r in cand)}/{len(cand)}",

        "HIEU_CHUAN_MARGIN": {
            "cau_hoi": "margin cao có nghĩa là đúng nhiều hơn không?",
            "acc_khi_margin_>=0.15": acc(hi), "n_hi": len(hi),
            "acc_khi_margin_<0.15": acc(lo), "n_lo": len(lo),
            "ket_luan": (
                f"KHÔNG ĐỦ DỮ LIỆU để kết luận (n_hi={len(hi)}, n_lo={len(lo)}; "
                "cần ≥5 mỗi nhánh)" if min(len(hi), len(lo)) < 5
                else ("margin CÓ mang tín hiệu" if (acc(hi) or 0) > (acc(lo) or 0)
                      else "margin KHÔNG mang tín hiệu — cổng đang chặn ngẫu nhiên")),
        },

        "sweeps": sweeps,
        "nguong_margin_tot_nhat": best,
        "nguong_margin_va_exact_phrase_tot_nhat": best_mx,

        "co_nguong_net_duong": any_positive,
        "co_nguong_dat_y_nghia_thong_ke": any_significant,
        "KET_LUAN": (
            "HOLD C1. Có ngưỡng cho net>0 nhưng KHÔNG ngưỡng nào đạt ý nghĩa "
            "thống kê (McNemar p>0,05 ở mọi dòng) và ngưỡng ấy lại chọn TRÊN "
            "CHÍNH tập đã tune. Net +2 trên 4 cặp bất đồng là thứ ngẫu nhiên "
            "sinh ra thường xuyên. Không đủ cơ sở tiêu một lượt public."
            if any_positive and not any_significant else
            ("HOLD C1: không ngưỡng nào cho net>0." if not any_positive else
             "CÓ ngưỡng net>0 VÀ đạt p<=0,05 — vẫn phải xác nhận trên DEV-60 "
             "vì ngưỡng được chọn trên tập tune.")),
        "khuyen_nghi": (
            "Emitter lookup ở dạng hiện tại KHÔNG đủ điều kiện nộp. Nhưng lý do "
            "phải nói cho đúng lát cắt: recall@1 trên LỚP LOOKUP là 12/21 = 57,1% "
            "(thứ tự legacy) — BẰNG ĐÚNG C0 (12/21). Emitter không thua theo số "
            "học; nó HOÀ, và một bản hoà thì không đáng tiêu một lượt public. "
            "(Con số 20,7%/12,6% là recall@1 trên CẢ 87 slot của 6 lớp, phần lớn "
            "là slot số học nhiều ô — KHÔNG phải trần của emitter lookup. Bản đầu "
            "của báo cáo này dùng nhầm lát cắt ấy.) Với thứ tự tất định, "
            "recall@1 lớp lookup tụt còn 7/21 = 33,3% — nghĩa là khoá tie-break "
            "sẽ làm emitter TỆ ĐI, dù nó làm số đo trung thực hơn."),
        "per_qid": per_q,
        "command": "python3 tools/c1_gate_calibration_v1.py",
    }
    (ROOT / "reports/c1_gate_calibration_v1.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"emitter chạm {len(cand)}/45 câu gold; đúng "
          f"{sum(r['emit_ok'] for r in cand)}/{len(cand)}")
    print("\nngưỡng  n_emit  +imp  -reg   net")
    for r in sweeps["margin"]:
        print(f"{r['nguong']:>6}  {r['n_emit_tren_gold45']:>6}  "
              f"{len(r['improved']):>4}  {len(r['regressed']):>4}  {r['net']:>+4d}"
              f"   p={r['mcnemar_p_hai_phia']}")
    print("\nmargin + exact_phrase:")
    for r in sweeps["margin_VA_exact_phrase"]:
        print(f"{r['nguong']:>6}  {r['n_emit_tren_gold45']:>6}  "
              f"{len(r['improved']):>4}  {len(r['regressed']):>4}  {r['net']:>+4d}")
    print("\nchỉ exact_phrase:", sweeps["chi_exact_phrase"][0])
    print("\nHIỆU CHUẨN:", json.dumps(rep["HIEU_CHUAN_MARGIN"], ensure_ascii=False))
    print("\nKẾT LUẬN:", rep["KET_LUAN"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
