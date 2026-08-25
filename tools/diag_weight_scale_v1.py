#!/usr/bin/env python3
"""Vì sao workstream B thất bại — chẩn đoán THANG TRỌNG SỐ, không phải tín hiệu.

Kết quả B (reports/scoring_ablation_v3.json): cả 4 feature `row_path` đều bị GỠ.
Trước khi gọi đó là "giả thuyết row_path bị bác bỏ", phải phân biệt hai khả năng
rất khác nhau:

    (a) row_path KHÔNG mang tín hiệu           → giả thuyết sai, bỏ hướng
    (b) row_path CÓ tín hiệu nhưng bị NUỐT     → giả thuyết đúng, thang sai

Đã đo được: feature kích hoạt trên 17–95% số ô, biên độ ±0,5 đến +5,7 — tức
chúng KHÔNG chết. Nhưng chúng chỉ đổi pick ở 1/70 slot. Vậy nghi (b).

Tệp này đo trực tiếp: với mỗi slot mà gold KHÔNG ở hạng 1, khoảng cách điểm
giữa top-1 và gold là bao nhiêu, và thành phần nào tạo ra khoảng cách ấy.

Nếu khoảng cách phần lớn do `exact_phrase` (+3,0) và `period_end_year` (+2,5) —
hai hằng số chỉnh tay lớn gấp 3–6 lần mọi feature khác — thì việc cần làm KHÔNG
phải thêm feature, mà là hiệu chuẩn thang.

⚠️ Tệp này KHÔNG sửa trọng số. Sửa trọng số sau khi nhìn kết quả là tuning
post-hoc, trái §4.4 của PREREGISTRATION_D1A. Việc hiệu chuẩn phải được đăng ký
trước ở vòng sau, kèm ngưỡng khai trước.

Chạy:  python3 tools/diag_weight_scale_v1.py
"""
from __future__ import annotations

import json
import sqlite3
import statistics as st
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from execution.emit_arith_v1 import ARITH_INTENTS  # noqa: E402
from execution.emit_lookup_v1 import metric_phrase, spec_text  # noqa: E402
from execution.fact_rank_v1 import fetch_pool  # noqa: E402
from execution.operand_pipeline_v1 import load_aliases, slots_for  # noqa: E402
from execution.score_v2 import LADDER as SL, rank_pool  # noqa: E402
from build_candidate_v1 import registry_labels  # noqa: E402


def main() -> int:
    con = sqlite3.connect(
        f"file:{ROOT/'data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db'}?mode=ro&immutable=1", uri=True)
    plans = {p["qid"]: p for p in (json.loads(l) for l in
             (ROOT / "data/curated/evaluation/legacy/question_plans_1012.jsonl").open(encoding="utf-8"))}
    gold = {g["qid"]: g for g in (json.loads(l) for l in
            (ROOT / "data/curated/dev-legacy/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")}
    labs, al, fl = registry_labels(), load_aliases(), SL["S5"]

    gaps, thu_pham, chi_tiet = [], Counter(), []
    n_miss = 0
    for q, g in sorted(gold.items()):
        if g["lop"] not in ARITH_INTENTS:
            continue
        plan = plans[q]
        stext = spec_text(plan, metric_phrase(plan, labs))
        gs = {s["slot"]: (s["ref"], str(s["raw"])) for s in g["provenance"]}
        for s in slots_for(plan, g["lop"], al):
            want = gs.get(s.name)
            if not want:
                continue
            sub = dict(plan)
            sub["entities"], sub["years"] = [s.ticker], [s.year]
            r = rank_pool(fetch_pool(con, sub, legacy_order=False), sub, stext, fl, None)
            gi = next((i for i, c in enumerate(r)
                       if c["evidence_ref"] == want[0] and str(c["value"]) == want[1]),
                      None)
            if gi in (None, 0):
                continue
            n_miss += 1
            top, gc = r[0], r[gi]
            gap = top["score"] - gc["score"]
            gaps.append(gap)
            # thành phần nào đóng góp nhiều nhất vào khoảng cách?
            pa, pb = top["score_parts"], gc["score_parts"]
            dong_gop = {k: round(pa.get(k, 0.0) - pb.get(k, 0.0), 4)
                        for k in set(pa) | set(pb)
                        if isinstance(pa.get(k, 0.0), (int, float))
                        and isinstance(pb.get(k, 0.0), (int, float))}
            lon_nhat = max(dong_gop, key=lambda k: dong_gop[k]) if dong_gop else None
            if lon_nhat:
                thu_pham[lon_nhat] += 1
            chi_tiet.append({"qid": q, "slot": s.name, "gold_rank": gi + 1,
                             "gap": round(gap, 4), "thanh_phan_lon_nhat": lon_nhat,
                             "dong_gop": {k: v for k, v in sorted(
                                 dong_gop.items(), key=lambda x: -x[1])[:4]}})

    # thang trọng số hiện hành, lấy từ chính FEATURE_REGISTRY
    from execution.score_v2 import FEATURE_REGISTRY
    from execution.row_feats_v1 import REGISTRY as ROW_REG
    thang = {k: v["weight"] for k, v in FEATURE_REGISTRY.items()
             if isinstance(v["weight"], (int, float))}
    thang |= {k: v["weight"] for k, v in ROW_REG.items()}

    lon = {k: v for k, v in thang.items() if abs(v) >= 1.5}
    nho = {k: v for k, v in thang.items() if abs(v) < 1.5}

    rep = {
        "_schema": "diag_weight_scale v1 — vì sao workstream B thất bại",
        "date": "2026-08-21",
        "dataset": "gold_dap_an_v1 · 24 câu non-lookup · 66 slot",
        "evaluation_mode": "TRAIN_FIT / RESEARCH-ONLY",
        "cau_hoi": "row_path thiếu tín hiệu, hay có tín hiệu mà bị nuốt?",

        "bang_chung_feature_KHONG_chet": {
            "row_path_overlap": "kích hoạt 334/2000 ô, biên độ tới +5,75",
            "row_path_specificity": "kích hoạt 1738/2000 ô, biên độ −0,50…+0,81",
            "row_sibling_penalty": "kích hoạt 1909/2000 ô, biên độ −1,18…0",
            "row_depth_prior": "kích hoạt 1110/2000 ô, biên độ −0,50…0",
            "nhung": "chỉ đổi pick ở 1/70 slot (depth: 0/70)",
        },

        "khoang_cach_diem_top1_vs_gold": {
            "n_miss": n_miss,
            "p50": round(st.median(gaps), 4) if gaps else None,
            "p90": round(sorted(gaps)[int(len(gaps) * 0.9) - 1], 4) if len(gaps) > 1 else None,
            "max": round(max(gaps), 4) if gaps else None,
            "n_gap_lon_hon_1_5": sum(1 for x in gaps if x > 1.5),
            "n_gap_nho_hon_0_5": sum(1 for x in gaps if x < 0.5),
        },

        "thanh_phan_tao_khoang_cach": dict(thu_pham.most_common()),

        "thang_trong_so_hien_hanh": {
            "hang_LON_>=1.5": lon,
            "hang_NHO_<1.5": nho,
            "ty_le": (f"{max(map(abs, lon.values())):.1f} / "
                      f"{min(map(abs, nho.values())):.1f}" if lon and nho else None),
        },

        "ket_luan": {
            # Giả thuyết ban đầu của chính tệp này ("exact_phrase +3,0 và
            # period_end_year +2,5 nuốt mọi thứ") đã bị SỐ ĐO bác bỏ: hai thành
            # phần ấy chỉ chiếm 2/33 khoảng cách. Giữ lại câu này để lần sau
            # không ai lặp lại phán đoán ấy.
            "gia_thuyet_ban_dau_DA_BI_BAC": ("'hằng số lớn nuốt feature nhỏ' — SAI. "
                                             "exact_phrase chỉ tạo 2/33 khoảng cách, "
                                             "period_end_year 0/33."),
            "thanh_phan_thuc_su_quyet_dinh": {
                "idf_overlap": "18/33 — số hạng gốc, biến thiên, đã trộn sẵn row_path",
                "col_year": "12/33 — MỘT hằng số +0,6 quyết định 36% số ca sai",
            },
            "y_nghia_cho_row_path": ("Feature row_* không sai vì bị nuốt bởi hằng số "
                                     "lớn, mà vì chúng nhắm SAI CHIỀU: chiều quyết "
                                     "định thứ hạng là cột (col_year), không phải "
                                     "dòng (row_path)."),
            "SAI_LAM_PHUONG_PHAP_CUA_DOC_138": (
                "Doc 138 xếp B trước C vì 'row_path lệch ở 25/37 miss'. Nhưng "
                "'trường nào KHÁC NHAU' và 'trường nào QUYẾT ĐỊNH thứ hạng' là hai "
                "câu hỏi khác nhau. row_path khác nhau nhiều nhất, nhưng col_year "
                "mới là thứ tạo khoảng cách điểm. Xếp ưu tiên theo tần suất khác "
                "biệt thay vì theo phân rã điểm là lỗi phương pháp — đã đo ra."),
            "he_qua": ("Workstream C (parser kỳ trên col_path) lẽ ra phải đứng "
                       "TRƯỚC B. 16/33 khoảng cách < 0,5 nên feature nhỏ ĐỦ sức "
                       "lật — miễn là nhắm đúng chiều."),
            "KHONG_LAM_GI_O_DAY": ("KHÔNG sửa trọng số. Sửa sau khi nhìn kết quả là "
                                   "tuning post-hoc, trái §4.4 PREREGISTRATION_D1A."),
        },
        "per_slot": chi_tiet,
        "command": "python3 tools/diag_weight_scale_v1.py",
    }
    (ROOT / "reports/diag_weight_scale_v1.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    k = rep["khoang_cach_diem_top1_vs_gold"]
    print(f"n_miss {k['n_miss']} · gap p50 {k['p50']} · p90 {k['p90']} · max {k['max']}")
    print(f"gap > 1,5 : {k['n_gap_lon_hon_1_5']}   ← feature ±0,5 KHÔNG lật nổi")
    print(f"gap < 0,5 : {k['n_gap_nho_hon_0_5']}   ← feature nhỏ CÓ thể lật")
    print(f"\nthành phần tạo khoảng cách: "
          f"{json.dumps(dict(thu_pham.most_common(6)), ensure_ascii=False)}")
    print(f"\nthang trọng số — hạng LỚN: {lon}")
    print(f"                 hạng NHỎ: {nho}")
    print("-> reports/diag_weight_scale_v1.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
