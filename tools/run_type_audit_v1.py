#!/usr/bin/env python3
"""Audit hợp đồng kiểu trên đủ 1.012 câu — C0 vs C3 vs trọng tài.

Trả lời ba câu, bằng số, trên TOÀN BỘ tập chấm chứ không phải mẫu 45 câu:

    1. Bao nhiêu câu có ràng buộc kiểu suy được từ văn bản câu hỏi?
    2. Bài nộp hiện hành (C0) vi phạm bao nhiêu?
    3. Trọng tài kiểu giữa C0 và C3 dịch chuyển được bao nhiêu câu, và ở đâu?

⚠️ ĐỌC KỸ GIỚI HẠN
`đúng kiểu` là điều kiện CẦN, KHÔNG phải điều kiện ĐỦ. Một đáp án đúng kiểu vẫn
có thể sai giá trị. Vì vậy mọi con số dưới đây là **trần trên** của phần điểm có
thể lấy lại, không phải dự báo điểm. Không được trích chúng như "sẽ tăng X câu".

Ngược lại, `sai kiểu` là bằng chứng ĐỦ để kết luận câu đó sai — không cần gold.
Đó là lý do audit này chạy được trên cả 1.012 câu trong khi gold chỉ có 45.

Chạy:  python3 tools/run_type_audit_v1.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from execution.answer_type_v1 import kiem, suy_hop_dong, trong_tai  # noqa: E402
from execution.emit_arith_v1 import ARITH_INTENTS, ARITH_PIPE, LADDER, emit  # noqa: E402
from build_candidate_v1 import load_control, registry_labels  # noqa: E402


def main() -> int:
    con = sqlite3.connect(
        f"file:{ROOT/'data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db'}?mode=ro&immutable=1", uri=True)
    plans = {p["qid"]: p for p in (json.loads(l) for l in
             (ROOT / "data/curated/evaluation/legacy/question_plans_1012.jsonl").open(encoding="utf-8"))}
    labs = registry_labels()
    C3 = LADDER["C3"]
    sub, _ = load_control()
    c0 = {r["id"]: r for r in sub}

    phu = Counter()
    vi_pham_c0 = Counter()
    theo_intent = defaultdict(lambda: Counter())
    ly_do = Counter()
    chuyen = Counter()
    vd = defaultdict(list)
    per = []
    t0 = time.time()

    for q, p in sorted(plans.items()):
        Q = p.get("question", "")
        it = p.get("intent_v1") or "?"
        hd = suy_hop_dong(Q)
        phu[hd.kind] += 1

        a0 = (c0.get(q) or {}).get("answer")
        r0 = kiem(hd, a0)

        # nhánh C3 — chỉ chạy khi intent có emitter
        a3, ab3 = None, None
        if it in ARITH_INTENTS:
            r = emit(con, p, it, replace(C3, pipeline=ARITH_PIPE), labs)
            if r is None:
                ab3 = "INTENT_OFF"
            elif r.get("abstain"):
                ab3 = r.get("abstain_reason")
            else:
                a3 = r.get("answer")
        r3 = kiem(hd, a3) if a3 is not None else {"ok": None, "ly_do": "KHONG_CO_C3"}

        # trọng tài: ưu tiên C0 (bài nộp hiện hành) rồi mới tới C3
        uv = [("C0", a0)] + ([("C3", a3)] if a3 is not None else [])
        tt = trong_tai(hd, uv)

        if hd.co_rang_buoc:
            theo_intent[it][f"{hd.kind}_tong"] += 1
            if r0["ok"] is False:
                vi_pham_c0[hd.kind] += 1
                theo_intent[it][f"{hd.kind}_C0_vi_pham"] += 1
                ly_do[r0["ly_do"]] += 1
                if len(vd[hd.kind]) < 3:
                    vd[hd.kind].append({"qid": q, "cau_hoi": Q[:110],
                                        "C0": a0, "C3": a3, "abstain_C3": ab3})
            if r3.get("ok") is True and r0["ok"] is False:
                chuyen["C0_sai_kieu_C3_dung_kieu"] += 1
                theo_intent[it]["trong_tai_cuu_duoc"] += 1
            elif r3.get("ok") is False and r0["ok"] is True:
                chuyen["C0_dung_kieu_C3_sai_kieu"] += 1
            if r0["ok"] is False and a3 is None:
                chuyen["C0_sai_kieu_C3_KHONG_CO"] += 1

        per.append({"qid": q, "intent": it, "kind": hd.kind, "cu": hd.cu,
                    "C0_ok": r0["ok"], "C0_ly_do": r0["ly_do"],
                    "C3_ok": r3.get("ok"), "C3_abstain": ab3,
                    "trong_tai_nhanh": tt["nhanh"], "trong_tai_ly_do": tt["ly_do"]})

    n_rb = sum(v for k, v in phu.items() if k != "UNKNOWN")
    n_vp = sum(vi_pham_c0.values())

    rep = {
        "_schema": "type_audit v1 — hợp đồng kiểu đáp án trên 1.012 câu",
        "date": "2026-08-21",
        "dataset": "toàn bộ 1.012 câu chấm (KHÔNG phải mẫu gold-45)",
        "evaluation_mode": ("KHÔNG cần gold — 'sai kiểu' là bằng chứng ĐỦ để kết "
                            "luận sai; 'đúng kiểu' KHÔNG đủ để kết luận đúng"),
        "metric_BTC": ("Execution Accuracy = (code chạy được VÀ kết quả đúng) / "
                       "tổng query — COMPETITION_SPEC §4.3. Abstain và sai đều 0 "
                       "điểm, nên bộ kiểm kiểu KHÔNG tự sinh điểm; giá trị của nó "
                       "là làm TRỌNG TÀI và ĐỊNH TUYẾN."),

        "phu_song_hop_dong": {
            "theo_kind": dict(phu.most_common()),
            "n_co_rang_buoc": n_rb,
            "ty_le_co_rang_buoc": round(n_rb / len(plans), 4),
            "n_UNKNOWN": phu["UNKNOWN"],
            "ghi_chu": "UNKNOWN là câu trả lời hợp lệ — thà im lặng còn hơn đoán",
        },

        "vi_pham_cua_bai_nop_hien_hanh_C0": {
            "theo_kind": dict(vi_pham_c0.most_common()),
            "tong": n_vp,
            "ty_le_tren_co_rang_buoc": round(n_vp / n_rb, 4) if n_rb else None,
            "ty_le_tren_1012": round(n_vp / len(plans), 4),
            "theo_ly_do": dict(ly_do.most_common()),
            "doi_chieu": ("EXECUTION 0,1225 ⇒ khoảng 124/1012 câu đúng. Số câu "
                          "CHẮC CHẮN sai vì sai kiểu lớn hơn số câu đang đúng."),
        },

        "trong_tai_C0_vs_C3": dict(chuyen.most_common()),
        "theo_intent": {k: dict(v) for k, v in sorted(theo_intent.items())},
        "vi_du": {k: v for k, v in vd.items()},
        "latency_s": round(time.time() - t0, 1),
        "per_qid": per,
        "command": "python3 tools/run_type_audit_v1.py",
    }
    (ROOT / "reports/type_audit_v1.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"phủ sóng hợp đồng: {dict(phu.most_common())}")
    print(f"  có ràng buộc {n_rb}/{len(plans)} = {n_rb/len(plans)*100:.1f}%")
    print(f"\nC0 vi phạm: {n_vp}/{n_rb} câu có ràng buộc = "
          f"{n_vp/len(plans)*100:.1f}% của 1.012")
    for k, v in vi_pham_c0.most_common():
        print(f"   {k:6} {v:>4}/{phu[k]}")
    print(f"\ntrọng tài C0↔C3: {json.dumps(dict(chuyen), ensure_ascii=False)}")
    print("-> reports/type_audit_v1.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
