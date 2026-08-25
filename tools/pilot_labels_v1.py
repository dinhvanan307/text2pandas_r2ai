#!/usr/bin/env python3
"""Pilot gán nhãn DEV — sinh phiếu, rồi hiệu chỉnh batch size từ phút THỰC ĐO.

VÌ SAO TỆP NÀY TỒN TẠI
----------------------
`reports/labeling_batch_size_report_v2.json` chốt: **pilot 10 NẰM TRONG batch
đầu 20 câu**; dừng sau câu thứ 10, tính median, rồi mới quyết định phần còn lại.
Nhưng chốt trong một tệp JSON không làm ai gán nhãn được. Tệp này biến quy trình
ấy thành hai lệnh.

Nó cũng đóng một lỗ hổng của doc 126: mọi con số "phút/câu" tới giờ là **ước
lượng kế hoạch** (`PRE_PILOT_ESTIMATE`). Trường `thoi_gian_phut` là bắt buộc
trong `label_template_schema.json` chính vì thế — nhưng chưa có gì đọc nó.

    python3 tools/pilot_labels_v1.py --init          # sinh 20 phiếu, 10 đầu là pilot
    python3 tools/pilot_labels_v1.py --report        # sau khi gán 10 câu

`--report` KHÔNG ép bạn gán đủ 20. Đó là điểm của pilot: dừng ở câu 10, đo, rồi
mới quyết định. Nếu median > 8 phút thì kế hoạch DEV-60 phải đổi TRƯỚC khi bạn
tiêu thêm ba buổi tối.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLD_DIR = ROOT / "data/dev/execution_gold"
SEL = GOLD_DIR / "dev60_selection.json"
OUT = GOLD_DIR / "dev60_labels.jsonl"
DOSSIER = GOLD_DIR / "dossiers_dev60"

N_BATCH = 20        # batch đầu
N_PILOT = 10        # pilot NẰM TRONG batch đầu (không cộng thêm)

# Bảng ngưỡng đã preregister — 125 §P0-C, chốt lại trong
# reports/labeling_batch_size_report_v2.json. KHÔNG sửa sau khi thấy số.
NGUONG = [
    (4.5, "GIỮ kế hoạch: DEV-60 trong 3 tối; có thể trả block về 1,5h"),
    (6.0, "GIỮ DEV-60, block 2h (đúng kế hoạch hiện hành)"),
    (8.0, "HẠ DEV 60 -> 48 (bỏ 2 câu ở 2 lớp đông nhất) HOẶC thêm một tối"),
    (float("inf"), "DEV 48 + gộp intent hiếm + BÁO LẠI trước khi gán tiếp"),
]


def init() -> int:
    sel = json.loads(SEL.read_text(encoding="utf-8"))
    qids = sel["qids"][:N_BATCH]          # THỨ TỰ FILE — không xáo, không chọn tay
    plans = {p["qid"]: p for p in (json.loads(l) for l in
             (ROOT / "evaluation/question_plans_1012.jsonl").open(encoding="utf-8"))}

    if OUT.exists():
        done = sum(1 for l in OUT.open(encoding="utf-8")
                   if l.strip() and json.loads(l).get("thoi_gian_phut") is not None)
        print(f"⚠ {OUT.name} đã có ({done} câu đã điền). KHÔNG ghi đè.")
        print("  Muốn làm lại: đổi tên file cũ rồi chạy lại --init.")
        return 1

    with OUT.open("w", encoding="utf-8") as f:
        for i, q in enumerate(qids, 1):
            p = plans[q]
            f.write(json.dumps({
                "qid": q,
                "_thu_tu": i,
                "_la_pilot": i <= N_PILOT,
                "_dossier": f"data/dev/execution_gold/dossiers_dev60/qid_{q:04d}.md",
                "_cau_hoi": p["question"],
                # ── ĐIỀN TỪ ĐÂY ────────────────────────────────────────────
                "dap_an_gold": None,
                "don_vi_dap_an": None,
                "intent_gold": None,
                "operands": [],
                "cong_thuc": None,
                "basis_gold": p.get("basis"),
                "trang_thai": None,
                "ghi_chu": "",
                "thoi_gian_phut": None,
            }, ensure_ascii=False) + "\n")

    print(f"-> {OUT}")
    print(f"   {len(qids)} phiếu · 10 câu đầu (`_la_pilot: true`) là PILOT")
    print(f"   dossier: {DOSSIER}/qid_XXXX.md")
    print("\nQuy trình:")
    print("  1. Gán 10 câu ĐẦU theo thứ tự, ghi `thoi_gian_phut` NGAY sau mỗi câu")
    print("  2. DỪNG. Chạy: python3 tools/pilot_labels_v1.py --report")
    print("  3. Theo quyết định của bảng ngưỡng rồi mới gán tiếp")
    return 0


def report() -> int:
    if not OUT.exists():
        print(f"✗ chưa có {OUT} — chạy --init trước")
        return 2
    rows = [json.loads(l) for l in OUT.open(encoding="utf-8") if l.strip()]
    pilot = [r for r in rows if r.get("_la_pilot")]
    filled = [r for r in pilot if r.get("thoi_gian_phut") is not None]
    mins = sorted(float(r["thoi_gian_phut"]) for r in filled)

    print(f"pilot: {len(filled)}/{len(pilot)} câu đã ghi thoi_gian_phut")
    if len(mins) < 5:
        print("✗ CHƯA ĐỦ DỮ LIỆU. Cần ≥5 câu để median có nghĩa; ≥10 mới nên quyết định.")
        print("  (Kết luận từ n<5 chính là thứ báo cáo này vừa bác ở chỗ khác.)")
        return 3

    med = statistics.median(mins)
    p75 = mins[min(int(len(mins) * 0.75), len(mins) - 1)]
    p95 = mins[min(int(len(mins) * 0.95), len(mins) - 1)]
    quyet_dinh = next(t for lim, t in NGUONG if med <= lim)

    n_ok = sum(1 for r in filled if r.get("trang_thai") == "OK")
    n_unc = sum(1 for r in filled if r.get("trang_thai") == "GOLD_UNCERTAIN")
    n_miss = sum(1 for r in filled if r.get("trang_thai") == "DATA_MISSING")

    rep = {
        "_schema": "pilot_labels v1 — phút/câu THỰC ĐO (thay PRE_PILOT_ESTIMATE)",
        "n_pilot_da_gan": len(mins),
        "phut_moi_cau": {"median": med, "p75": p75, "p95": p95,
                         "min": mins[0], "max": mins[-1]},
        "trang_thai": {"OK": n_ok, "GOLD_UNCERTAIN": n_unc, "DATA_MISSING": n_miss},
        "bang_nguong_preregistered": {str(l): t for l, t in NGUONG},
        "QUYET_DINH": quyet_dinh,
        "du_bao_lai": {
            "DEV_60_gio": round(60 * med / 60, 2),
            "AUDIT_40_blind_gio": round(40 * med * 1.2 / 60, 2),
            "ghi_chu": ("blind cộng ~20% theo giả định cũ — con số ấy vẫn "
                        "CHƯA ĐO. Chỉ đo được sau batch AUDIT đầu tiên."),
        },
        "canh_bao": [
            "n = %d, median trên mẫu nhỏ dao động mạnh — dùng để CHỌN KẾ HOẠCH, "
            "không để báo cáo như hằng số." % len(mins),
            "Người gán học nghề trong lúc gán: 10 câu đầu THƯỜNG chậm hơn phần "
            "sau. Ước lượng này nghiêng về phía an toàn.",
        ],
    }
    dst = ROOT / "reports/pilot_labels_v1.json"
    dst.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nmedian {med:.1f}′ · p75 {p75:.1f}′ · p95 {p95:.1f}′ "
          f"(min {mins[0]:.1f} / max {mins[-1]:.1f})")
    print(f"trạng thái: OK {n_ok} · UNCERTAIN {n_unc} · DATA_MISSING {n_miss}")
    print(f"\nQUYẾT ĐỊNH: {quyet_dinh}")
    print(f"dự báo lại: DEV-60 ≈ {rep['du_bao_lai']['DEV_60_gio']}h · "
          f"AUDIT-40 ≈ {rep['du_bao_lai']['AUDIT_40_blind_gio']}h")
    print("->", dst.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--init", action="store_true", help="sinh 20 phiếu batch đầu")
    g.add_argument("--report", action="store_true", help="đo phút/câu sau pilot")
    a = ap.parse_args()
    raise SystemExit(init() if a.init else report())
