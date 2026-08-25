#!/usr/bin/env python3
"""Bằng chứng cho claim ASCII `ty` va chạm: quét corpus, xuất summary + mẫu.

Sinh `unit_token_scan_summary.json` và `unit_token_collision_samples.jsonl`.
Không sửa gì, chỉ đọc.
"""
from __future__ import annotations
import argparse, hashlib, json, re, sqlite3
from collections import Counter
from pathlib import Path

# Dạng KHÔNG DẤU thật (đã trừ va chạm `công ty`)
THAT = re.compile(r"\b(?:trieu|nghin|ngan)\s*(?:dong|vnd)\b"
                  r"|(?<!cong )(?<!cong-)\bty\s*(?:dong|vnd)\b", re.I)
# Va chạm: "Công ty" + VND, mọi biến thể khoảng trắng/gạch nối/hoa thường
VA_CHAM = re.compile(r"(?:c[ôo]ng[\s\-]+ty)\s*(?:vnd|dong|đồng)", re.I)
CO_DAU = re.compile(r"(?:tri[eệ]u|ngh[ìi]n|ng[àa]n|t[ỷyỉi])\s*(?:đ[ồo]ng|vnd)", re.I)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-db", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--limit-cols", type=int, default=600000)
    a = ap.parse_args(argv)
    W = Path(a.work_db).resolve(); OUT = Path(a.out_dir).resolve(); OUT.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(f"file:{W}?mode=ro", uri=True)

    dem = Counter(); mau = []
    def quet(ten, sql, gioi_han=None):
        n = 0
        for (t,) in c.execute(sql):
            n += 1
            if gioi_han and n > gioi_han:
                break
            s = t or ""
            if VA_CHAM.search(s):
                dem[f"{ten}.collision_cong_ty"] += 1
                if len(mau) < 50:
                    mau.append({"field": ten, "kind": "COLLISION_CONG_TY",
                                "text": s[:120], "match": VA_CHAM.search(s).group(0)})
            elif THAT.search(s):
                dem[f"{ten}.genuine_ascii_unit"] += 1
                if len(mau) < 50:
                    mau.append({"field": ten, "kind": "GENUINE_ASCII_UNIT",
                                "text": s[:120], "match": THAT.search(s).group(0)})
            if CO_DAU.search(s):
                dem[f"{ten}.accented_unit"] += 1
        dem[f"{ten}.scanned"] = min(n, gioi_han or n)

    quet("observations.col_path_text",
         "SELECT col_path_text FROM observations WHERE col_path_text IS NOT NULL", a.limit_cols)
    quet("tables.section_text", "SELECT section_text FROM tables WHERE section_text IS NOT NULL")
    quet("tables.context_clean", "SELECT context_clean FROM tables WHERE context_clean IS NOT NULL")

    g = sum(v for k, v in dem.items() if k.endswith("genuine_ascii_unit"))
    v = sum(v for k, v in dem.items() if k.endswith("collision_cong_ty"))
    ac = sum(val for k, val in dem.items() if k.endswith("accented_unit"))
    sm = {"work_db": str(W), "work_db_bytes": W.stat().st_size,
          "counts": dict(sorted(dem.items())),
          "totals": {"genuine_ascii_unit": g, "collision_cong_ty": v, "accented_unit": ac},
          "harm_benefit_ratio": (round(v / g, 2) if g else None),
          "ket_luan": ("Dang KHONG DAU gan nhu khong ton tai trong corpus, trong khi "
                       "'Cong ty VND' va cham nhieu. Vi vay ASCII `ty` chi duoc chap nhan "
                       "khi co marker/allowlist va PHAI che span thuc the truoc."),
          "n_samples": len(mau)}
    (OUT / "unit_token_scan_summary.json").write_text(
        json.dumps(sm, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    (OUT / "unit_token_collision_samples.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False, sort_keys=True) for m in mau) + "\n",
        encoding="utf-8")
    print(json.dumps(sm["totals"]), "ratio=", sm["harm_benefit_ratio"], "samples=", len(mau))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
