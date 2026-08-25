#!/usr/bin/env python3
"""Đo lại thang đơn vị của cột `value` trong CSV bằng chứng — sửa lỗi của doc 166.

Doc 166 §3.1 phân loại "ô đã được nhân thang" bằng `abs(value) >= 1e11`. Đó là
phép đo **độ lớn tuyệt đối**, không phải phép đo thang: một giá trị ghi bằng ĐỒNG
(vd `3.227.004.714.155`) vượt 1e11 mà **không** hề bị nhân thang. Vì vậy con số
75,1% của doc 166 là **measurement artifact**, không phải phát hiện.

Phép đo đúng là **tỉ số `value / parse(value_raw)`** trên từng ô, rồi phân loại
theo luỹ thừa 10. Ô không parse được `value_raw` phải vào nhóm `parse_failed`
riêng, không được ép vào ×1 hay ×10⁶.

Chạy trên CẢ HAI nguồn vì chúng khác nhau (drift 19/08 17:31):
  --source zip   : CSV nằm trong submission_P0I.zip  (bản ĐÃ CHẤM 0,1225)
  --source disk  : data/dev/answer_a6/data/          (bản HIỆN TẠI trên đĩa)
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# 10^0 = 1 PHẢI có trong danh sách. Bản đầu của script này thiếu nó, khiến toàn
# bộ ô KHÔNG bị nhân thang rơi vào `other_ratio` — đúng cùng một loại lỗi phân
# loại đã làm doc 166 sai. Ghi lại để không ai lặp lần thứ ba.
LUY_THUA = [10 ** e for e in (-9, -6, -3, -2, -1, 0, 1, 2, 3, 6, 9, 12)]


def parse_raw(s: str):
    """Parse số kiểu Việt, giữ dấu âm/ngoặc. Trả (giá trị, trạng thái)."""
    t = str(s or "").strip()
    if not t or t in {"-", "–", "—", "..", "…", "N/A", "n/a"}:
        return None, "MISSING_TOKEN"
    am = t.startswith("(") and t.endswith(")")
    if am:
        t = t[1:-1].strip()
    if t.startswith("-"):
        am, t = True, t[1:].strip()
    if re.fullmatch(r"\d{1,3}(\.\d{3})*(,\d+)?", t):
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d+(,\d+)?", t):
        t = t.replace(",", ".")
    elif re.fullmatch(r"\d+(\.\d+)?", t):
        pass
    else:
        return None, "UNPARSEABLE"
    try:
        v = float(t)
    except ValueError:
        return None, "UNPARSEABLE"
    return (-v if am else v), "OK"


def phan_loai_ty_le(val, raw):
    if raw in (None, 0):
        return "raw_zero_or_missing"
    r = val / raw
    for k in LUY_THUA:
        if abs(r - k) <= abs(k) * 1e-6:
            return f"x{k:g}"
    return "other_ratio"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["zip", "disk"], default="zip")
    ap.add_argument("--zip", type=Path,
                    default=ROOT / "data/submissions/submission_P0I.zip")
    ap.add_argument("--disk", type=Path,
                    default=ROOT / "data/dev/answer_a6/data")
    ap.add_argument("--out", type=Path, default=ROOT / "reports/167/csv_scale_audit")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    if a.source == "zip":
        z = zipfile.ZipFile(a.zip)
        files = [(n, z.read(n).decode("utf-8", "replace"))
                 for n in z.namelist() if n.startswith("data/") and n.endswith(".csv")]
        import hashlib
        nguon = {"kind": "zip", "path": str(a.zip.relative_to(ROOT)),
                 "zip_sha256": hashlib.sha256(a.zip.read_bytes()).hexdigest()}
    else:
        files = [(p.name, p.read_text(encoding="utf-8", errors="replace"))
                 for p in sorted(a.disk.glob("*.csv"))]
        nguon = {"kind": "disk", "path": str(a.disk.relative_to(ROOT)),
                 "n_file": len(files)}

    per_file, dem_o, dem_file = [], collections.Counter(), collections.Counter()
    fails = []
    for name, txt in files:
        rows = list(csv.DictReader(io.StringIO(txt)))
        if not rows or "value" not in rows[0] or "value_raw" not in rows[0]:
            dem_file["KHONG_DU_COT"] += 1
            per_file.append({"file": name, "category": "KHONG_DU_COT"})
            continue
        c = collections.Counter()
        for i, r in enumerate(rows):
            raw, st = parse_raw(r.get("value_raw"))
            try:
                val = float(r.get("value"))
            except (TypeError, ValueError):
                val, st = None, (st if st != "OK" else "VALUE_UNPARSEABLE")
            if st != "OK" or val is None:
                c["parse_failed"] += 1
                fails.append({"file": name, "row": i, "value_raw": r.get("value_raw"),
                              "value": r.get("value"), "reason": st})
                continue
            c[phan_loai_ty_le(val, raw)] += 1
        dem_o.update(c)
        do_duoc = {k: v for k, v in c.items() if k.startswith("x")}
        if not do_duoc:
            cat = "KHONG_O_NAO_DO_DUOC"
        elif len(do_duoc) == 1:
            cat = f"DONG_NHAT_{next(iter(do_duoc))}"
        else:
            cat = "TRON_NHIEU_THANG"
        dem_file[cat] += 1
        per_file.append({"file": name, "category": cat, "n_row": len(rows),
                         "ty_le": dict(c)})

    tong = sum(dem_file.values())
    tom = {
        "_schema": "csv_scale_audit v2 — phép đo TỈ SỐ value/parse(value_raw)",
        "nguon": nguon,
        "PHUONG_PHAP_CU_SAI": ("doc 166 dùng abs(value) >= 1e11 làm tiêu chí "
                               "'đã nhân thang'. Đó là đo ĐỘ LỚN, không phải "
                               "đo THANG — giá trị ghi bằng ĐỒNG vượt 1e11 mà "
                               "không hề bị nhân. Con số 75,1% là measurement "
                               "artifact và ĐƯỢC RÚT."),
        "n_file": tong,
        "phan_loai_file": dict(dem_file),
        "tong_o_theo_ty_le": dict(dem_o),
        "n_parse_failed": dem_o.get("parse_failed", 0),
        "file_TRON_NHIEU_THANG": dem_file.get("TRON_NHIEU_THANG", 0),
        "ty_le_file_tron": (round(dem_file.get("TRON_NHIEU_THANG", 0) / tong, 4)
                            if tong else None),
        "CATEGORY_LOAI_TRU_LAN_NHAU": True,
        "TONG_KIEM": sum(dem_file.values()) == tong,
    }
    h = a.source
    (a.out / f"per_file_results_{h}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in per_file) + "\n",
        encoding="utf-8")
    (a.out / f"parse_failures_{h}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in fails) + "\n",
        encoding="utf-8")
    (a.out / f"summary_{h}.json").write_text(
        json.dumps(tom, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(tom, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
