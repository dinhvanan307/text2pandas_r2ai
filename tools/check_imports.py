#!/usr/bin/env python3
"""RC2-021 · Lock có phủ hết thứ mã nguồn THẬT SỰ import không?

Vì sao cần công cụ này — một defect có thật, không phải giả định:

`dp-env-check` báo `lock_matches_installed = True` và mọi người coi đó là
"môi trường đã đóng băng". Nhưng phép so đó chỉ hỏi *"những gói ĐÃ PIN có
khớp bản ĐANG CÀI không"*. Nó **không bao giờ hỏi ngược lại**: *"mã nguồn
import những gì, và lock có phủ hết không?"*

Kết quả: `lxml` được `html_parser` import không điều kiện, `pyproject.toml`
ghi `parsing = []   # lxml, ...` — tức là *nhắc đến* nhưng **không khai báo**
— nên `pip-compile` không đưa nó vào lock, và `pip install --no-deps` (đúng
ngữ nghĩa: pip KHÔNG tự kéo dependency, lock là con đường DUY NHẤT để một gói
vào venv) tạo ra một venv thiếu `lxml`. Ba lớp kiểm tra đều xanh, còn
`make dp-test` chết bằng `ModuleNotFoundError`.

Công cụ này đóng đúng khoảng trống đó, theo chiều ngược lại:

    AST quét `src/` -> tập module bên thứ ba -> ánh xạ sang tên phân phối
    -> đối chiếu `requirements.lock`

Không dùng regex trên mã nguồn: `import lxml` trong docstring hay chuỗi phải
KHÔNG được tính, còn `from lxml import etree` trong một hàm thì PHẢI tính.
Chỉ AST phân biệt được hai thứ đó.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

# Ánh xạ module -> tên phân phối cho các trường hợp KHÔNG suy ra được bằng
# tên. Dùng làm đường lui khi gói chưa cài (lúc đó `packages_distributions()`
# không biết gì về nó) — đây chính là tình huống ta muốn bắt.
MODULE_TO_DIST = {
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "PIL": "pillow",
    "sklearn": "scikit-learn",
    "fitz": "pymupdf",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "cv2": "opencv-python",
    "attr": "attrs",
    "pkg_resources": "setuptools",
}


def _norm(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _stdlib() -> set[str]:
    names = set(getattr(sys, "stdlib_module_names", ()))
    # `sys.stdlib_module_names` không có ở <3.10; và vài tên hay gặp không nằm
    # trong đó tuỳ bản. Bổ sung thủ công thì rẻ hơn báo động giả.
    names |= {"__future__", "typing", "dataclasses", "collections", "importlib",
              "concurrent", "email", "html", "http", "json", "logging", "os",
              "re", "sqlite3", "sys", "unittest", "urllib", "xml", "zoneinfo"}
    return names


# Thu muc co the nam tren `sys.path` luc chay, nen module top-level trong do
# la MA CUA CHINH DU AN — khong phai gói bên thứ ba.
#
# Vi du that: `release.py` co `from make_preview import build_html`, va
# `make_preview.py` nam o `tools/`. Neu chi coi `src/` la first-party thi
# `make_preview` bi bao la "gói chua pin" — mot bao dong gia, va bao dong gia
# la thu nhanh nhat giet mot cong cu kiem tra.
FIRST_PARTY_DIRS = ("src", "tools", ".")


def _first_party(repo: Path) -> set[str]:
    """Package/module top-level thuoc chinh repo nay."""
    out: set[str] = set()
    for d in FIRST_PARTY_DIRS:
        base = repo / d if d != "." else repo
        if not base.is_dir():
            continue
        for child in base.iterdir():
            if child.name.startswith("."):
                continue
            if child.is_dir() and (child / "__init__.py").is_file():
                out.add(child.name)
            elif child.is_file() and child.suffix == ".py":
                out.add(child.stem)
    return out


def _guarded_lines(tree: ast.AST) -> set[int]:
    """Dòng nằm trong `try:` có handler bắt ImportError/ModuleNotFoundError.

    Import kiểu đó là import TUỲ CHỌN có phòng bị. Nó vẫn phải được báo cáo,
    nhưng phải tách khỏi import BẮT BUỘC, vì hai loại có hệ quả khác nhau:
    một cái làm build chết, một cái làm build rụng tính năng trong im lặng.
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        catches = False
        for h in node.handlers:
            t = h.type
            names = []
            if isinstance(t, ast.Name):
                names = [t.id]
            elif isinstance(t, ast.Tuple):
                names = [e.id for e in t.elts if isinstance(e, ast.Name)]
            elif t is None:
                names = ["ImportError"]
            if {"ImportError", "ModuleNotFoundError", "Exception"} & set(names):
                catches = True
        if not catches:
            continue
        for stmt in node.body:
            for sub in ast.walk(stmt):
                if hasattr(sub, "lineno"):
                    lines.add(sub.lineno)
    return lines


def _scan_one(f: Path) -> dict[str, dict]:
    """Quet MOT tep .py. Tach rieng de `@contract` dung lai duoc."""
    found: dict[str, dict] = {}
    try:
        tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"),
                         filename=str(f))
    except (SyntaxError, OSError):
        return found
    guarded = _guarded_lines(tree)
    for node in ast.walk(tree):
        mods: list[str] = []
        if isinstance(node, ast.Import):
            mods = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            # `from . import x` / `from .mod import y` -> level > 0, noi bo.
            if node.level and node.level > 0:
                continue
            if node.module:
                mods = [node.module.split(".")[0]]
        for m in mods:
            rec = found.setdefault(m, {"files": [], "required": False})
            if str(f) not in rec["files"]:
                rec["files"].append(str(f))
            if node.lineno not in guarded:
                rec["required"] = True
    return found


def scan_imports(root: Path) -> dict[str, dict]:
    """Trả `{module_top_level: {"files": [...], "required": bool}}`.

    `required=True` nghĩa là có ÍT NHẤT một chỗ import mà không có
    `try/except ImportError` che. Một module import cả hai kiểu thì tính là
    bắt buộc — chỗ trần mới là chỗ làm chết tiến trình.
    """
    found: dict[str, dict] = {}
    for f in sorted(root.rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        for m, v in _scan_one(f).items():
            rec = found.setdefault(m, {"files": [], "required": False})
            rec["files"].extend(x for x in v["files"] if x not in rec["files"])
            rec["required"] = rec["required"] or v["required"]
    return found


def third_party(root: Path, repo: Path | None = None) -> dict[str, dict]:
    std = _stdlib()
    first = _first_party(repo or root)
    return {m: v for m, v in scan_imports(root).items()
            if m not in std and m not in first and not m.startswith("_")}


def module_to_dist(mod: str) -> str:
    if mod in MODULE_TO_DIST:
        return MODULE_TO_DIST[mod]
    try:
        from importlib.metadata import packages_distributions
        dists = packages_distributions().get(mod)
        if dists:
            return _norm(sorted(dists)[0])
    except Exception:                                        # pragma: no cover
        pass
    return _norm(mod)


def _lock_pins(lock: Path) -> dict[str, str]:
    """Đọc pin bằng CHÍNH bộ tách của `env_check` — một nguồn sự thật.

    Viết lại một bộ tách thứ hai ở đây là tái phạm đúng lỗi đã trả giá ba lần
    trong dự án này (`corpus.root`, `config_hash`, `build_id`).
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_env_check_for_imports", Path(__file__).with_name("env_check.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._parse_lock(lock)["pins"]


# Tep hop dong khai bao ĐUONG CHAY THAT cua RC2. Lay danh sach cong cu TU DO,
# khong go tay o day: go tay tao nguon su that thu hai, va no se lech ngay lan
# dau ai them mot buoc vao pipeline.
CONTRACT_FILES = ("Makefile", "configs/execution_sequence_v1.yaml")
_TOOL_RE = re.compile(r"tools/[A-Za-z_0-9/]+\.py")


def contract_tools(repo: Path) -> list[Path]:
    """Cac `tools/*.py` ma Makefile va execution_sequence THUC SU goi."""
    out: set[str] = set()
    for name in CONTRACT_FILES:
        f = repo / name
        if f.is_file():
            out |= set(_TOOL_RE.findall(f.read_text(encoding="utf-8",
                                                    errors="replace")))
    return [repo / r for r in sorted(out) if (repo / r).is_file()]


def _expand(repo: Path, target: str) -> list[Path]:
    """`@contract` -> cong cu tren duong chay; con lai la thu muc hoac tep."""
    if target == "@contract":
        return contract_tools(repo)
    p = repo / target
    if p.is_file():
        return [p]
    return [p] if p.is_dir() else []


def _scan_paths(paths: list[Path], repo: Path) -> dict[str, dict]:
    std, first = _stdlib(), _first_party(repo)
    merged: dict[str, dict] = {}
    for p in paths:
        raw = scan_imports(p) if p.is_dir() else _scan_one(p)
        for m, v in raw.items():
            if m in std or m in first or m.startswith("_"):
                continue
            rec = merged.setdefault(m, {"files": [], "required": False})
            rec["files"].extend(v["files"])
            rec["required"] = rec["required"] or v["required"]
    return merged


def check(repo: Path, scan_dirs: list[str], lock_name: str = "requirements.lock",
          allow: tuple[str, ...] = ()) -> dict:
    pins = _lock_pins(repo / lock_name)
    allowed = {_norm(a) for a in allow}
    paths: list[Path] = []
    for d in scan_dirs:
        paths.extend(_expand(repo, d))
    mods = _scan_paths(paths, repo)

    rows, unpinned_required, unpinned_optional = [], [], []
    for m in sorted(mods):
        dist = module_to_dist(m)
        pinned = dist in pins
        row = {"module": m, "dist": dist,
               "pinned_version": pins.get(dist),
               "pinned": pinned,
               "required": mods[m]["required"],
               "allowlisted": dist in allowed,
               "files": sorted(mods[m]["files"])[:8]}
        rows.append(row)
        if not pinned and dist not in allowed:
            (unpinned_required if row["required"] else unpinned_optional).append(m)

    verdict = "PASS" if not unpinned_required and not unpinned_optional else "FAIL"
    return {
        "check": "RC2-021 · lock phủ hết import",
        "repo": str(repo), "scanned": scan_dirs,
        "lock": lock_name, "lock_n_pins": len(pins),
        "n_third_party_modules": len(rows),
        "unpinned_required": sorted(unpinned_required),
        "unpinned_optional": sorted(unpinned_optional),
        "modules": rows,
        "verdict": verdict,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--scan", action="append", default=None,
                    help="thư mục/tệp cần quét, hoặc `@contract` = mọi "
                         "`tools/*.py` mà Makefile + execution_sequence gọi. "
                         "Mặc định: src + @contract. Lặp lại được.")
    ap.add_argument("--lock", default="requirements.lock")
    ap.add_argument("--allow-unpinned", action="append", default=[],
                    help="tên PHÂN PHỐI được phép vắng trong lock — phải có lý do")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)

    rep = check(Path(a.root).resolve(), a.scan or ["src", "@contract"], a.lock,
                tuple(a.allow_unpinned))
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                               encoding="utf-8")

    print("╔═══════ RC2-021 · lock phủ import ═══════╗")
    print(f"  quét            {', '.join(rep['scanned'])}")
    print(f"  lock            {rep['lock']}  ({rep['lock_n_pins']} pin)")
    print(f"  module bên thứ 3 {rep['n_third_party_modules']}")
    for r in rep["modules"]:
        mark = "✓" if r["pinned"] else ("~" if r["allowlisted"] else "✗")
        kind = "bắt buộc" if r["required"] else "tuỳ chọn"
        print(f"   {mark} {r['module']:<16} -> {r['dist']:<20} "
              f"{r['pinned_version'] or '(KHÔNG CÓ TRONG LOCK)':<14} {kind}")
    if rep["verdict"] == "PASS":
        print("\n✓ lock phủ hết import của mã nguồn")
        return 0
    print("\n✗ CÓ IMPORT KHÔNG NẰM TRONG LOCK:", file=sys.stderr)
    for m in rep["unpinned_required"]:
        print(f"  · {m}  (BẮT BUỘC — venv `--no-deps` sẽ chết ở đây)", file=sys.stderr)
    for m in rep["unpinned_optional"]:
        print(f"  · {m}  (tuỳ chọn, có try/except — vẫn phải khai hoặc allowlist)",
              file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
