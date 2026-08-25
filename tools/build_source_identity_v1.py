#!/usr/bin/env python3
"""Sinh `identity/source_identity.json` — per-file SHA của SSOT source.

VÌ SAO TỆP NÀY TỒN TẠI (review 127 §3-D0)
-----------------------------------------
`SOURCE_SELECTION.json` khai *root nào là SSOT* và commit + patch, nhưng KHÔNG
khai từng file. Người review vì thế không thể trả lời "file X trong packet có
đúng là file X trên máy build không" nếu không giải nén và so tay. Packet 125
yêu cầu `identity/source_identity.json` riêng; sync_122_1 thiếu.

Tệp này khoá:
  - per-file sha256 của `src/`, `tools/*.py|*.sh` cấp 1, `configs/`, `tests/`;
  - tổng hợp `tree_sha256` = sha256 của chuỗi "path\\0sha\\n" đã sắp xếp;
  - commit + dirty state + danh sách tracked-modified/untracked.

`tree_sha256` là một con số duy nhất so được giữa hai máy. Nếu nó khớp thì
KHÔNG cần so 460 dòng manifest.

Chạy:  python3 tools/build_source_identity_v1.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# SSOT theo SOURCE_SELECTION.json. `tools/` chỉ lấy cấp 1 + evalkit vì các thư
# mục con khác là scratch khảo sát, không nằm trong đường ống nộp bài.
INCLUDE_DIRS = ["src", "configs", "tests"]
INCLUDE_GLOBS = ["tools/*.py", "tools/*.sh", "tools/evalkit/**/*.py",
                 "tools/execution/**/*.py", "pyproject.toml", "requirements.lock"]
# .pyc là artifact biên dịch, trộn nhiều interpreter (review 127 §2.1) — cấm.
EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".git", ".venv-build", ".venv-review",
                 ".venv", "node_modules", "site-packages"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def keep(p: Path) -> bool:
    if not p.is_file():
        return False
    if p.suffix in {".pyc", ".pyo"}:
        return False
    return not (EXCLUDE_PARTS & set(p.parts))


def sh(*cmd: str) -> str:
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)
        return r.stdout.strip()
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None,
                    help="cây source cần băm. Mặc định là repo chứa tệp này. "
                         "Cần khi tool được chạy TỪ packet nhưng phải băm repo.")
    ap.add_argument("--min-files", type=int, default=0,
                    help="thoát lỗi nếu quét được ÍT HƠN ngần này file. Chặn "
                         "dấu XANH SAI: chạy trong packet bổ sung chỉ thấy ~22 "
                         "file lẻ nhưng vẫn exit 0 và sinh một tree_sha256 vô "
                         "nghĩa — nguy hiểm hơn một dấu đỏ.")
    a = ap.parse_args()
    global ROOT
    if a.root:
        ROOT = Path(a.root).resolve()

    files: dict[str, str] = {}
    for d in INCLUDE_DIRS:
        for p in sorted((ROOT / d).rglob("*")):
            if keep(p):
                files[str(p.relative_to(ROOT))] = sha256(p)
    for g in INCLUDE_GLOBS:
        for p in sorted(ROOT.glob(g)):
            if keep(p):
                files[str(p.relative_to(ROOT))] = sha256(p)

    blob = "".join(f"{k}\0{v}\n" for k, v in sorted(files.items())).encode()
    tree_sha = hashlib.sha256(blob).hexdigest()

    status = sh("git", "status", "--porcelain")
    modified = sorted(l[3:] for l in status.splitlines() if l[:2].strip() in {"M", "MM", "AM"})
    untracked = sorted(l[3:] for l in status.splitlines() if l.startswith("??"))

    by_root: dict[str, int] = {}
    for k in files:
        by_root[k.split("/")[0]] = by_root.get(k.split("/")[0], 0) + 1

    out = {
        "_schema": "source_identity v1 — per-file SHA của SSOT (review 127 §3-D0 'thiếu identity/source_identity.json')",
        "generated": sh("date", "-u", "+%Y-%m-%dT%H:%M:%SZ"),
        "generator": "tools/build_source_identity_v1.py",
        "source_commit": sh("git", "rev-parse", "HEAD"),
        "dirty": bool(status),
        "n_tracked_modified": len(modified),
        "n_untracked_paths": len(untracked),
        "tracked_modified": modified,
        "untracked_paths": untracked,
        "include_dirs": INCLUDE_DIRS,
        "include_globs": INCLUDE_GLOBS,
        "excluded": {"suffixes": [".pyc", ".pyo"], "dir_parts": sorted(EXCLUDE_PARTS),
                     "vi_sao": "bytecode trộn interpreter 3.10/3.11/3.13/3.14 làm phình packet và không phải source"},
        "n_files": len(files),
        "n_files_by_root": dict(sorted(by_root.items())),
        "tree_sha256": tree_sha,
        "tree_sha256_definition": "sha256 của nối chuỗi f'{relpath}\\0{sha256}\\n' trên danh sách path ĐÃ SẮP XẾP (sorted, byte-order của str Python)",
        "files": files,
    }
    dst = ROOT / "identity/source_identity.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"n_files={len(files)}  tree_sha256={tree_sha}")
    print("->", dst)
    if a.min_files and len(files) < a.min_files:
        print(f"\n✗ chỉ quét được {len(files)} file (< --min-files {a.min_files}).",
              file=sys.stderr)
        print("  Gần như chắc chắn đang chạy NGOÀI cây source đầy đủ — ví dụ "
              "trong một packet bổ sung.", file=sys.stderr)
        print(f"  `tree_sha256` vừa ghi ({tree_sha[:16]}…) KHÔNG so được với "
              "bản sinh từ repo. Đừng dùng nó.", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
