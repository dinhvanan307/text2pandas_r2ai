#!/usr/bin/env python3
"""RC-23 · zip TẤT ĐỊNH. Cùng thư mục vào → cùng byte ra, cùng sha256.

Gói RC1 được tạo bằng Finder nên chứa `__MACOSX/` và extended attribute. Tool
này khoá năm thứ Finder không khoá: thứ tự entry, timestamp, bit quyền, một
root duy nhất, và không đường dẫn tuyệt đối.
"""
from __future__ import annotations

import argparse, hashlib, os, stat, sys, zipfile
from pathlib import Path

FORBIDDEN = {"__MACOSX", ".DS_Store", "Thumbs.db", ".AppleDouble", "._"}
FIXED_DATE = (1980, 1, 1, 0, 0, 0)          # timestamp cố định — zip epoch


def _skip(rel: Path) -> bool:
    return any(p in FORBIDDEN or p.startswith("._") for p in rel.parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="thư mục release (một root)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    src = Path(a.dir).resolve()
    if not src.is_dir():
        print(f"✗ không thấy thư mục: {src}", file=sys.stderr); return 2
    out = Path(a.out)
    if out.exists():
        print(f"✗ {out} đã tồn tại — từ chối ghi đè", file=sys.stderr); return 2

    # RC2-051 · sort theo CHUỖI đường dẫn tương đối, không theo `Path`.
    #
    # `sorted(Path)` so sánh tuple `parts`, còn `namelist()` của zip là chuỗi.
    # Hai thứ tự đó khác nhau ngay khi một thư mục là tiền tố của tên anh em
    # cạnh nó: `src/text2pandas/` và `src/text2pandas.egg-info/`. Theo `parts`,
    # `"text2pandas" < "text2pandas.egg-info"`; theo chuỗi thì ngược lại, vì
    # `"."` (0x2E) đứng trước `"/"` (0x2F).
    #
    # Hậu quả: entry trong gói KHÔNG sort, tức gói không tất định theo đúng
    # định nghĩa mà chính assert ở cuối hàm này đòi. Assert đó đã bắt được —
    # nhưng chỉ ở lần đầu có va chạm tên, sau nhiều gói đã đi qua.
    _all = sorted((p for p in src.rglob("*") if p.is_file()),
                  key=lambda p: p.relative_to(src).as_posix())
    files = [p for p in _all if not _skip(p.relative_to(src))]
    # LOẠI thì phải NÓI RA. Loại im lặng nghĩa là gói khác với thư mục mà người
    # vận hành vừa xem, và không có dòng nào cho họ biết. Ở đây loại là hành vi
    # ĐÚNG (một tệp `.DS_Store` do Finder sinh không đáng làm hỏng cả lần đóng
    # gói), nhưng nó phải hiện ra trong log.
    dropped = [p.relative_to(src).as_posix() for p in _all if _skip(p.relative_to(src))]
    for d in dropped:
        print(f"  ⊘ loại rác hệ điều hành: {d}")
    if dropped:
        print(f"  ⊘ tổng {len(dropped)} tệp bị loại khỏi gói")
    if not files:
        print("✗ thư mục rỗng", file=sys.stderr); return 2
    for p in files:
        if p.is_symlink():
            print(f"✗ symlink không được phép: {p}", file=sys.stderr); return 2

    root = src.name
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in files:
            rel = p.relative_to(src)
            zi = zipfile.ZipInfo(f"{root}/{rel.as_posix()}", date_time=FIXED_DATE)
            # Bit quyền cố định: 0644 cho tệp thường. Quyền của máy dev không
            # được rò vào gói — đó là một nguồn nondeterminism.
            zi.external_attr = (stat.S_IFREG | 0o644) << 16
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, p.read_bytes())

    # Kiểm lại chính archive vừa tạo (Plan 17 §RC-23 đòi).
    with zipfile.ZipFile(out) as z:
        bad = z.testzip()
        if bad:
            print(f"✗ archive hỏng ở {bad}", file=sys.stderr); return 3
        names = z.namelist()
    assert names == sorted(names), "entry chưa sort"
    roots = {n.split("/")[0] for n in names}
    if len(roots) != 1:
        print(f"✗ nhiều root: {roots}", file=sys.stderr); return 3
    if any(n.startswith("/") or ".." in n for n in names):
        print("✗ có đường dẫn tuyệt đối hoặc path traversal", file=sys.stderr); return 3

    h = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"  {out}  {len(names)} entry  {out.stat().st_size:,} B")
    print(f"  sha256 {h}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
