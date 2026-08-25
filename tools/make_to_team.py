#!/usr/bin/env python3
"""Gộp bộ bàn giao thành MỘT tệp `to_team.zip`.

Dùng ZIP_STORED chứ không DEFLATE: bốn thành phần lớn đã là zip nén sẵn, nén
lại chỉ tốn vài phút CPU để đổi lấy vài phần nghìn dung lượng. Store cũng giữ
được tính tất định mà không phụ thuộc phiên bản zlib.

Sau khi đóng, tự mở lại và đối chiếu sha256 TỪNG tệp bên trong với
`SHA256SUMS.txt` — đóng gói mà không kiểm lại thì không biết bytes có qua
nguyên vẹn hay không.
"""
from __future__ import annotations

import hashlib, sys, zipfile
from pathlib import Path

H = Path("artifacts/rc2/handoff")
OUT = H / "to_team.zip"
ROOT = "to_team"

# Danh sách bốn tệp lớn từng được ghi cứng theo tên A3. Mỗi vòng dựng lại là
# một lần sửa bốn dòng, và quên một dòng thì `to_team.zip` mang ba artifact
# mới cộng một artifact cũ — thứ không ai phát hiện được từ bên ngoài.
#
# Nay suy ra từ CHÍNH thư mục bàn giao: `build_handoff_set.sh` đã dọn bản cũ
# sang `_to_delete` trước khi dựng bản mới, nên những gì còn lại trong `H` là
# bộ hiện hành. Khớp theo TIỀN TỐ, và đòi ĐÚNG MỘT tệp cho mỗi tiền tố —
# hai tệp cùng tiền tố nghĩa là bản cũ chưa được dọn, và đó là lỗi phải dừng.
_PREFIX = ("silver_v1_rc2_", "rc2_acceptance_", "data_pipeline_source_",
           "_build_evidence_")
_TEXT = ("RC2_FINAL_HANDOFF_ANSWERS.md", "SHA256SUMS.txt")


def _resolve() -> list[str]:
    zips = sorted(f.name for f in H.glob("*.zip") if f.name != OUT.name)
    out: list[str] = []
    for pre in _PREFIX:
        hop = [n for n in zips if (n.startswith(pre) if not pre.startswith("_")
                                   else pre in n)]
        if len(hop) != 1:
            raise SystemExit(
                f"✗ cần ĐÚNG MỘT tệp khớp {pre!r} trong {H}, thấy {hop}")
        out.append(hop[0])
    for n in _TEXT:
        if not (H / n).is_file():
            raise SystemExit(f"✗ thiếu {H / n}")
        out.append(n)
    return out


FILES = _resolve()
FIXED = (1980, 1, 1, 0, 0, 0)


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()


def main() -> int:
    if OUT.exists():
        print(f"✗ {OUT} đã tồn tại — đổi tên bản cũ thay vì ghi đè", file=sys.stderr)
        return 2
    missing = [f for f in FILES if not (H / f).is_file()]
    if missing:
        print(f"✗ thiếu: {missing}", file=sys.stderr); return 2

    # Ghi theo thứ tự SORT, không theo thứ tự liệt kê. Mọi zip trong dự án
    # này đều sort entry để tất định; một gói vận chuyển không phải lý do để
    # phá quy ước, nhất là khi chính tool này cảnh báo về nó.
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_STORED) as z:
        for n in sorted(FILES):
            zi = zipfile.ZipInfo(f"{ROOT}/{n}", date_time=FIXED)
            zi.external_attr = 0o644 << 16
            with (H / n).open("rb") as src, z.open(zi, "w") as dst:
                while chunk := src.read(1 << 22):
                    dst.write(chunk)
            print(f"  + {n}")

    want = {}
    for line in (H / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        if line.strip():
            w, _, r = line.partition("  ")
            want[r.strip()] = w.strip()

    bad = 0
    with zipfile.ZipFile(OUT) as z:
        names = z.namelist()
        if names != sorted(names):
            print("  ⚠ entry chưa sort")
        for n in names:
            rel = n[len(ROOT) + 1:]
            h = hashlib.sha256()
            with z.open(n) as f:
                for c in iter(lambda: f.read(1 << 22), b""):
                    h.update(c)
            got = h.hexdigest()
            if rel in want and got != want[rel]:
                print(f"  ✗ SAI BYTES: {rel}", file=sys.stderr); bad += 1
            elif rel in want:
                print(f"  ✓ {rel[:52]:52} {got[:16]}")
    print(f"\n  {OUT}  {len(names)} entry  {OUT.stat().st_size:,} B")
    print(f"  sha256 {sha(OUT)}")
    print(f"  → {'PASS' if bad == 0 else f'FAIL ({bad} tệp sai bytes)'}")
    return 0 if bad == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
