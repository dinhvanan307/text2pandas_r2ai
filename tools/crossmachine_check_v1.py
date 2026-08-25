#!/usr/bin/env python3
"""Chụp số ranking theo TỪNG MÔI TRƯỜNG rồi so — kiểm tie-break bằng thực nghiệm.

VÌ SAO TỆP NÀY TỒN TẠI
----------------------
`docs/128` §3.1 tuyên bố: `75,9%@20` và `20,7%@1` **không phải bất biến của
thuật toán** vì bản V1 không `ORDER BY`, không tie-break, và 39/45 QID có nhiều
ô cùng điểm tại ngưỡng cắt. Bằng chứng cho tới nay là **gián tiếp**: đổi quy
ước sắp xếp trong CÙNG một máy thì số đổi.

Bằng chứng TRỰC TIẾP là: chạy cùng một code, cùng một `work.db`, trên HAI môi
trường khác nhau — nếu số khác nhau thì tuyên bố được chứng minh; nếu giống
nhau thì rủi ro có thật nhưng CHƯA hiện thực hoá, và phải nói đúng như vậy.

Cho tới 21/08 dự án chỉ có một môi trường đo. Nay có hai:

    Linux  aarch64 · CPython 3.10.12 · pandas 2.3.3 · numpy 2.2.6
    macOS  arm64   · CPython 3.13.7  · pandas 2.3.3 · numpy 2.5.2

Phép đo này tốn ~2 phút và trả lời được một câu mà không lượt nộp nào mua được.

    # trên MỖI máy, sau khi đã chạy tools/fact_slot_report_v1.py
    python3 tools/crossmachine_check_v1.py --snapshot
    # sau khi có >= 2 snapshot
    python3 tools/crossmachine_check_v1.py --compare
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "reports/fact_slot_evidence_v1.json"
SNAP_DIR = ROOT / "reports/crossmachine"

# Các số PHẢI bất biến giữa hai máy nếu thuật toán tất định.
KEYS = ["slot_recall", "qid_all_slots_in_top20", "miss_taxonomy",
        "recall_at_1_theo_lop", "DEPTH_CURVE", "TIE_INSTABILITY"]


def env_id() -> str:
    return (f"{platform.system().lower()}-{platform.machine()}"
            f"-py{'.'.join(platform.python_version_tuple()[:3])}")


def snapshot() -> int:
    if not SRC.is_file():
        print(f"✗ chưa có {SRC.relative_to(ROOT)} — chạy trước:")
        print("    python3 tools/fact_slot_report_v1.py")
        return 2
    d = json.loads(SRC.read_text(encoding="utf-8"))
    eid = env_id()
    out = {
        "env_id": eid,
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "workdb_sha256_ky_vong":
            "e9f62775a75794d770954ba1903f7a90c8b97467e5398b0baa2057bec8e67d5f",
        **{k: d.get(k) for k in KEYS},
    }
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    dst = SNAP_DIR / f"fact_slot__{eid}.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"env: {eid}")
    print(f"  slot_recall V1.2      {d['slot_recall']['V1.2']}")
    print(f"  lookup recall@1       {d['recall_at_1_theo_lop']['V1.2']['lookup']}")
    print(f"  qid_all_slots_top20   {d['qid_all_slots_in_top20']}")
    print("->", dst.relative_to(ROOT))
    return 0


def _flat(d, pre=""):
    """Duyệt phẳng để chỉ ra ĐÚNG trường nào lệch, không chỉ 'có lệch'."""
    if isinstance(d, dict):
        for k, v in d.items():
            yield from _flat(v, f"{pre}.{k}" if pre else str(k))
    elif isinstance(d, list):
        yield pre, tuple(d) if all(not isinstance(x, (dict, list)) for x in d) else str(d)
    else:
        yield pre, d


def compare() -> int:
    snaps = sorted(SNAP_DIR.glob("fact_slot__*.json")) if SNAP_DIR.is_dir() else []
    if len(snaps) < 2:
        print(f"✗ mới có {len(snaps)} snapshot, cần ≥2 môi trường khác nhau.")
        for s in snaps:
            print("   ", s.name)
        print("\nChạy `--snapshot` trên máy còn lại (cùng repo, cùng work.db).")
        return 3

    loaded = [json.loads(p.read_text(encoding="utf-8")) for p in snaps]
    base = loaded[0]
    diffs: list[dict] = []
    for other in loaded[1:]:
        fb = dict(_flat({k: base.get(k) for k in KEYS}))
        fo = dict(_flat({k: other.get(k) for k in KEYS}))
        for k in sorted(set(fb) | set(fo)):
            if fb.get(k) != fo.get(k):
                diffs.append({"truong": k, base["env_id"]: fb.get(k),
                              other["env_id"]: fo.get(k)})

    rep = {
        "_schema": "crossmachine_check v1 — kiểm tie-break bằng hai môi trường thật",
        "cau_hoi": ("Cùng code, cùng work.db, hai môi trường khác nhau — "
                    "số ranking có đổi không?"),
        "moi_truong": [{"env_id": d["env_id"], "platform": d["platform"]} for d in loaded],
        "n_truong_le_ch": len(diffs),
        "diffs": diffs,
        "VERDICT": ("TIE_ORDER_INSTABILITY_XAC_NHAN" if diffs
                    else "BAT_BIEN_GIUA_HAI_MOI_TRUONG"),
        "doc_the_nao": (
            "CÓ lệch ⇒ tuyên bố docs/128 §3.1 được chứng minh TRỰC TIẾP: số cũ "
            "phụ thuộc thứ tự quét bảng, phải khoá tie-break trước mọi phép đo "
            "ranking tiếp theo."
            if diffs else
            "KHÔNG lệch ⇒ rủi ro tie-break là THẬT (39/45 QID có ô cùng điểm) "
            "nhưng CHƯA hiện thực hoá trên hai môi trường này. Không được nói "
            "'số ổn định' — chỉ được nói 'chưa quan sát thấy lệch trên 2 môi "
            "trường'. SQLite không hứa thứ tự; một lần VACUUM/ANALYZE hay một "
            "bản work.db dựng lại có thể làm lệch."),
    }
    dst = ROOT / "reports/crossmachine_check_v1.json"
    dst.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"môi trường: {', '.join(d['env_id'] for d in loaded)}")
    print(f"trường lệch: {len(diffs)}")
    for d in diffs[:20]:
        print("  ", json.dumps(d, ensure_ascii=False))
    print(f"\n{rep['VERDICT']}")
    print(rep["doc_the_nao"])
    print("->", dst.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--snapshot", action="store_true")
    g.add_argument("--compare", action="store_true")
    a = ap.parse_args()
    raise SystemExit(snapshot() if a.snapshot else compare())
