#!/usr/bin/env python3
"""RC-00 · `make dp-env-check` — in đủ tám mục §3.2, và FAIL nếu thiếu.

Đây là lệnh đầu tiên người review chạy. Nó phải trả lời được câu hỏi *"tôi
đang cầm cái gì"* mà không cần hỏi ai:

    OS · Python · SQLite · pandas/pyarrow/PyYAML · source commit
    config path/hash · corpus path/hash

Quan trọng hơn việc in ra: nó **thoát khác 0** khi thiếu commit hoặc thiếu
dependency. RC1 bị từ chối một phần vì *"test không chạy được do thiếu
dependency"* — một môi trường thiếu thứ cần thiết phải nói ra ngay ở bước
đầu, không phải nửa chừng lúc build.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

REQUIRED = ("pandas", "pyarrow", "yaml")
# `pytest` KHÔNG chặn env-check (build không cần nó) nhưng phải in phiên bản:
# RC-11 phải pin nó vào `requirements.lock`, và không ai được đoán con số đó.
OPTIONAL = ("pytest",)
_LABEL = {"yaml": "PyYAML"}

# Review 28 §RC-12 — dung lượng tối thiểu trước khi build:
#   2 × build DB (~5,5 GB) + release dir (~6,6 GB) + zip/giải nén + reports
#   + 20% biên an toàn  →  làm tròn 40 GB.
# Hết đĩa GIỮA build sinh ra một DB cụt trông như build hợp lệ. Chặn ở đây rẻ
# hơn nhiều so với phát hiện ở RC-14.
MIN_FREE_GB_BUILD = 40.0


# Thư mục mà một tệp CHƯA COMMIT nằm trong đó có thể đổi hành vi build mà
# KHÔNG đổi `source_hash` — vì `source_hash` chỉ băm tệp đã tracked. Một
# `.py` lạ trong `src/` được import vẫn chạy; một `.md` ở gốc repo thì không.
# Phân biệt hai loại này là khác nhau giữa "cảnh báo" và "chặn build".
SOURCE_PATHS = ("src/", "tools/", "configs/", "Makefile", "pyproject.toml")


def _sh(*cmd: str, strip: bool = True) -> str | None:
    """Chay lenh, tra stdout. `strip=False` khi KHOANG TRANG DAU DONG CO NGHIA.

    `git status --porcelain` dung hai ky tu dau lam **truong trang thai**: dong
    ` M configs/a.yaml` co mot khoang trang o cot 1. `.strip()` an mat khoang
    trang do o DONG DAU TIEN, va moi bo tach theo vi tri co dinh sau do lech
    mot ky tu -> `onfigs/a.yaml`. Loi chi hien o dong dau, nen no song sot qua
    ca test lan mat nguoi doc log.
    """
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return None
        out = r.stdout.strip() if strip else r.stdout.rstrip("\n")
        return out or None
    except (OSError, subprocess.SubprocessError):
        return None


def _hash_file(p: Path) -> str | None:
    if not p.is_file():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def _classify_dirty(porcelain: str | None) -> dict:
    """Tách `git status --porcelain` thành ba loại, vì chúng có hệ quả khác nhau.

    - `tracked`   : tệp đã commit mà bị sửa → build KHÔNG quy được về commit nào.
    - `untracked_source`: tệp lạ trong `src/`, `tools/`, `configs/` → có thể
      được import/đọc lúc build nhưng KHÔNG nằm trong `source_hash`. Đây là
      loại nguy hiểm nhất vì nó vô hình với mọi phép băm.
    - `untracked_other` : tệp lạ ở chỗ khác → không vào build, chỉ cần biết.
    """
    tracked, unt_src, unt_other = [], [], []
    for line in (porcelain or "").splitlines():
        if not line.strip():
            continue
        # porcelain v1: hai ky tu trang thai, mot khoang trang, roi duong dan.
        # Cat tu cot 2 roi `lstrip()` — KHONG cat cung tu cot 3. Neu dong bi
        # mat khoang trang dau (do mot lop goi nao do da `.strip()`), cat cung
        # se an mat ky tu dau cua duong dan.
        path = line[2:].lstrip().strip('"')
        if not path:
            continue
        # đổi tên có dạng `R  cũ -> mới`; lấy vế đích.
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if line.startswith("??"):
            (unt_src if any(path.startswith(p) for p in SOURCE_PATHS)
             else unt_other).append(path)
        else:
            tracked.append(path)
    return {"tracked": tracked, "untracked_source": unt_src,
            "untracked_other": unt_other}


def _parse_lock(p: Path) -> dict:
    """Đọc pin từ `requirements.lock` (định dạng pip-compile hoặc pin trần)."""
    pins: dict[str, str] = {}
    n_hash = 0
    if not p.is_file():
        return {"exists": False, "pins": {}, "n_hashes": 0}
    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if "--hash=sha256:" in line:
            n_hash += line.count("--hash=sha256:")
        if line.startswith("#") or not line:
            continue
        head = line.split(";")[0].split("--hash")[0].strip().rstrip("\\").strip()
        if "==" in head:
            name, _, ver = head.partition("==")
            # `coverage[toml]==7.x` — extras KHÔNG thuộc tên phân phối; để
            # nguyên thì tra metadata trượt và gói bị báo nhầm là "chưa cài".
            name = name.split("[", 1)[0]
            name = name.strip().lower().replace("_", "-")
            ver = ver.strip()
            if name and ver:
                pins[name] = ver
    return {"exists": True, "pins": pins, "n_hashes": n_hash}


def _installed_version(dist: str) -> str | None:
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:
        return None
    try:
        return version(dist)
    except PackageNotFoundError:
        return None
    except Exception:
        return None


def _lock_report(lock: Path) -> dict:
    """So pin trong lock với thứ ĐANG CÀI THẬT.

    Đây là điều kiện thoát của RC2-006. Trước bản này `dp-env-check` không đo
    nó, nên câu "lock_matches_installed = true" là một tiêu chí KHÔNG đo được
    bằng công cụ có sẵn — đúng loại khoảng trống mà evidence discipline cấm.
    """
    info = _parse_lock(lock)
    out = {
        "lock_path": str(lock),
        "lock_exists": info["exists"],
        "lock_sha256": _hash_file(lock),
        "lock_n_pins": len(info["pins"]),
        "lock_n_hashes": info["n_hashes"],
        "lock_has_hashes": info["n_hashes"] > 0,
    }
    if not info["exists"]:
        out["lock_matches_installed"] = None
        out["lock_note"] = "không có requirements.lock — RC2-006 chưa gỡ"
        return out
    mismatches, absent = [], []
    for name, ver in sorted(info["pins"].items()):
        got = _installed_version(name)
        if got is None:
            absent.append(name)
        elif got != ver:
            mismatches.append(f"{name}: lock=={ver} · đang cài {got}")
    out["lock_mismatches"] = mismatches
    out["lock_not_installed"] = absent
    out["lock_matches_installed"] = not mismatches and not absent
    if not out["lock_has_hashes"]:
        out["lock_note"] = ("lock KHÔNG có --hash → không cài được bằng "
                            "`pip install --require-hashes`, chưa phải frozen")
    return out


def _imports_report(root: Path) -> dict:
    """RC2-021 · lock có phủ hết thứ mã nguồn IMPORT không?

    `lock_matches_installed` chỉ so pin với bản đang cài. Nó không bao giờ hỏi
    ngược lại — và chính khoảng trống đó để `lxml` lọt: import không điều
    kiện, chỉ được *nhắc* trong một comment của `pyproject.toml`, nên không
    vào lock, nên venv `--no-deps` thiếu nó, mà ba lớp kiểm tra vẫn xanh.

    Đo ở đây, tại lệnh ĐẦU TIÊN người review chạy, chứ không chỉ trong test:
    một môi trường thiếu thứ cần thiết phải nói ra ngay, không phải nửa chừng.
    """
    out: dict[str, object] = {}
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_check_imports", Path(__file__).with_name("check_imports.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rep = mod.check(root, ["src", "@contract"])
    except Exception as exc:                                 # pragma: no cover
        out["lock_covers_imports"] = None
        out["imports_note"] = f"KHÔNG ĐO ĐƯỢC ({exc.__class__.__name__}: {exc})"
        return out
    bad = list(rep["unpinned_required"]) + list(rep["unpinned_optional"])
    out["lock_covers_imports"] = not bad
    out["imports_third_party_count"] = rep["n_third_party_modules"]
    out["imports_unpinned"] = bad
    return out


def _corpus_root_from_config(cfg: Path) -> Path:
    """Đọc `corpus.root` từ config. Một nguồn sự thật, không có mặc định thứ hai."""
    fallback = Path("data/external/vifinqa/financial_statements")
    if not cfg.is_file():
        return fallback
    try:
        import yaml
        raw = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except Exception:                                        # pragma: no cover
        return fallback
    return Path((raw.get("corpus") or {}).get("root") or fallback)


def _disk_free_gb(path: Path) -> float:
    st = shutil.disk_usage(path)
    return round(st.free / 1e9, 1)


def _writable(path: Path) -> bool:
    """Thử GHI THẬT, không hỏi `os.access`.

    `os.access` trả lời theo bit quyền, còn thứ làm build chết giữa chừng là
    read-only mount, quota, hoặc SIP — cả ba đều qua được `os.access`.
    """
    probe = path / ".dp_write_probe"
    try:
        probe.write_bytes(b"x")
        probe.unlink()
        return True
    except OSError:
        return False


def _build_id_fingerprint() -> dict[str, str]:
    """Lấy `source_hash`/`config_hash` TỪ CHÍNH hàm sinh `build_id`.

    Không tính lại ở đây. Tính lại là tạo nguồn sự thật thứ hai, và dự án này
    đã trả giá cho đúng lỗi đó ba lần: `corpus.root`, `config_hash`, và
    `build_id` ở `cmd_publish`.
    """
    try:
        sys.path.insert(0, str(Path.cwd() / "src"))
        from data_pipeline.storage import source_fingerprint
        return source_fingerprint()
    except Exception as exc:                                 # pragma: no cover
        return {"source_hash": f"KHÔNG TÍNH ĐƯỢC ({exc.__class__.__name__})",
                "config_hash": "KHÔNG TÍNH ĐƯỢC"}


def _hash_tree(root: Path, patterns=("*.txt", "*.html")) -> tuple[str | None, int]:
    """Băm corpus theo (đường dẫn tương đối, kích thước) — KHÔNG đọc nội dung.

    Corpus là hàng nghìn tệp; băm nội dung đầy đủ mất vài phút cho một lệnh
    lẽ ra phải chạy trong một giây. Băm tên và kích thước bắt được thay đổi
    thành phần corpus — thứ mà bước này cần khẳng định. Băm nội dung đầy đủ
    thuộc về `corpus_id` trong manifest, sinh ở bước snapshot.
    """
    if not root.is_dir():
        return None, 0
    items = []
    for pat in patterns:
        for f in root.rglob(pat):
            if f.is_file():
                items.append((str(f.relative_to(root)), f.stat().st_size))
    if not items:
        return None, 0
    items.sort()
    h = hashlib.sha256(repr(items).encode()).hexdigest()[:16]
    return h, len(items)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/vifinqa_silver_v1.yaml")
    ap.add_argument("--corpus", default=None,
                    help="ghi đè `corpus.root` của config; để trống thì ĐỌC TỪ CONFIG")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    root = Path.cwd()
    cfg = Path(a.config)

    # Gốc corpus phải ĐỌC TỪ CONFIG, không phải một mặc định riêng.
    #
    # Bản đầu mặc định `data/external/vifinqa` trong khi config khai
    # `data/external/vifinqa/financial_statements`. Chênh **15 tệp**: toàn bộ
    # `_codebase/prompts/*.txt` của ban tổ chức bị gộp vào băm.
    #
    # Hệ quả nặng hơn vẻ ngoài: `corpus_hash` khi đó KHÔNG mô tả corpus thật
    # sự được dựng. Sửa một prompt template làm đổi `corpus_hash` → đổi
    # `build_id` → báo động giả "corpus đã thay đổi". Và ngược lại, nó cho
    # cảm giác sai rằng băm đã ghim đúng corpus.
    corp = Path(a.corpus) if a.corpus else _corpus_root_from_config(cfg)
    corpus_hash, n_files = _hash_tree(corp)

    deps, missing = {}, []
    for mod in REQUIRED:
        try:
            m = importlib.import_module(mod)
            deps[_LABEL.get(mod, mod)] = getattr(m, "__version__", "?")
        except ImportError:
            deps[_LABEL.get(mod, mod)] = None
            missing.append(_LABEL.get(mod, mod))
    for mod in OPTIONAL:
        try:
            deps[mod] = getattr(importlib.import_module(mod), "__version__", "?")
        except ImportError:
            deps[mod] = "(chưa cài — RC-11 cần)"

    commit = _sh("git", "rev-parse", "HEAD")
    dirty = _sh("git", "status", "--porcelain", strip=False)
    dcls = _classify_dirty(dirty)
    tracked = _sh("git", "ls-tree", "-r", "--name-only", "HEAD", "src/data_pipeline")
    lockrep = _lock_report(root / "requirements.lock")
    imprep = _imports_report(root)

    info = {
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "sqlite": sqlite3.sqlite_version,
        "dependencies": deps,
        "source_commit": commit,
        # `source_tree_dirty` CHỈ nói về tệp đã tracked mà bị sửa — đó mới là
        # thứ làm build không quy được về commit. Trước bản này nó bật True vì
        # bất kỳ tệp untracked nào, kể cả một `.md` ở gốc repo, nên nó vừa gây
        # báo động giả vừa che mất trường hợp thật sự nguy hiểm.
        "source_tree_dirty": bool(dcls["tracked"]),
        "dirty_tracked_files": dcls["tracked"][:20],
        "untracked_in_source_paths": dcls["untracked_source"][:20],
        "untracked_elsewhere_count": len(dcls["untracked_other"]),
        "data_pipeline_tracked_files": len(tracked.splitlines()) if tracked else 0,
        **lockrep,
        **imprep,
        # HAI giá trị KHÁC NHAU, nên phải mang HAI tên khác nhau.
        #
        #   `config_file_hash`  băm đúng một tệp — tệp `--config` đang dùng
        #   `config_hash`       thứ ĐI VÀO `build_id`, băm cả `configs/*.yaml`
        #
        # Bản đầu gọi cả hai là `config_hash`: log in `2b292b82e437116b` còn
        # `build_meta` ghi `02ee1eeb3114c749`. Cùng một cái tên, hai con số,
        # và không ai đối chiếu được — đó là cách một sai lệch sống sót.
        "config_path": str(cfg), "config_file_hash": _hash_file(cfg),
        **_build_id_fingerprint(),
        "corpus_path": str(corp), "corpus_hash": corpus_hash,
        "corpus_file_count": n_files,
        "repository_root": str(root),
        # Review 28 §RC-12 — preflight. Build chết vì hết đĩa để lại một DB
        # cụt trông hệt build hợp lệ; đó là kiểu hỏng đắt nhất.
        "disk_free_gb": _disk_free_gb(root),
        "disk_min_required_gb_for_build": MIN_FREE_GB_BUILD,
        "repo_writable": _writable(root),
    }

    if a.json:
        print(json.dumps(info, ensure_ascii=False, indent=1))
    else:
        print("╔═══════════ dp-env-check ═══════════╗")
        for k, v in info.items():
            if k == "dependencies":
                for d, ver in v.items():
                    print(f"  {d:<22} {ver or '✗ CHƯA CÀI'}")
            else:
                print(f"  {k:<22} {v}")

    # ── điều kiện đóng RC-00, thi hành bằng exit code ────────────────────
    fail = []
    if missing:
        fail.append(f"thiếu dependency: {', '.join(missing)} — `pip install -e \".[dev]\"`")
    if not commit:
        fail.append("không có git commit — không xác định được source của build")
    if info["data_pipeline_tracked_files"] == 0:
        fail.append("`src/data_pipeline/` CHƯA ĐƯỢC COMMIT (0 file tracked ở HEAD)"
                    " — đây là blocker A-01, xem RC-00")
    if not cfg.is_file():
        fail.append(f"không thấy config: {cfg}")
    if corpus_hash is None:
        fail.append(f"không thấy corpus hoặc corpus rỗng: {corp}")
    if not info["repo_writable"]:
        fail.append(f"không ghi được vào repository root: {root}")
    # RC2-038 · `source_tree_dirty = false` là ĐIỀU KIỆN THOÁT mà chính
    # `configs/execution_sequence_v1.yaml` khai cho bước `env_check`. Trước bản
    # này nó chỉ là CẢNH BÁO, nên `dp-env-check` in "✓ RC-00 env-check đạt" và
    # thoát 0 trong khi vi phạm đúng tiêu chí nó vừa in ra.
    #
    # Hậu quả đã xảy ra thật: bản dựng `5ffc07216708d9fd` sinh ra từ cây có 19
    # tệp tracked bị sửa và 3 tệp untracked trong đường dẫn nguồn, và không có
    # gì chặn lại. `source_commit` khi đó không định danh được nguồn.
    #
    # Một công cụ khai điều kiện rồi không thi hành thì nó là tài liệu, không
    # phải cổng.
    if info["source_tree_dirty"]:
        fail.append(
            f"{len(dcls['tracked'])} tệp đã tracked bị sửa — build sẽ KHÔNG quy "
            "được về commit nào. Commit hoặc stash trước build: "
            + ", ".join(dcls["tracked"][:5]))

    # RC2-021 · import không có trong lock = venv frozen sẽ chết ở giữa build.
    # Đây là FAIL, không phải warn: nó đã xảy ra thật với `lxml`, và nó xảy ra
    # ở chỗ đắt nhất — sau khi build đã chạy được một lúc.
    if imprep.get("lock_covers_imports") is False:
        fail.append(
            "mã nguồn import gói KHÔNG có trong requirements.lock: "
            + ", ".join(imprep.get("imports_unpinned", [])[:5])
            + " — `python tools/check_imports.py --root .` để xem chi tiết")

    # Tệp lạ trong src/tools/configs KHÔNG nằm trong `source_hash` nhưng vẫn
    # có thể được nạp lúc build → bản dựng không tái lập được. Chặn cứng.
    if dcls["untracked_source"]:
        fail.append(
            "tệp CHƯA COMMIT trong đường dẫn nguồn — không vào `source_hash` "
            "nhưng vẫn có thể được nạp lúc build: "
            + ", ".join(dcls["untracked_source"][:5]))

    # Đĩa là CẢNH BÁO ở env-check, không phải fail: `dp-env-check` còn được
    # chạy trên máy chỉ để đọc/review. `dp-build` mới là chỗ phải chặn cứng.
    warn = []
    if info["disk_free_gb"] < MIN_FREE_GB_BUILD:
        warn.append(f"đĩa trống {info['disk_free_gb']} GB < {MIN_FREE_GB_BUILD} GB"
                    " — ĐỦ để env-check nhưng KHÔNG đủ để chạy dp-build")

    if info.get("lock_exists") and not info.get("lock_matches_installed"):
        det = info.get("lock_mismatches") or []
        nyi = info.get("lock_not_installed") or []
        warn.append(
            "môi trường ĐANG CÀI khác requirements.lock → đây KHÔNG phải môi "
            "trường frozen (RC2-006 chưa gỡ). "
            + (f"lệch: {'; '.join(det[:3])}. " if det else "")
            + (f"chưa cài: {', '.join(nyi[:5])}." if nyi else ""))
    elif info.get("lock_exists") and not info.get("lock_has_hashes"):
        warn.append("requirements.lock không có --hash → chưa cài frozen được")

    for w in warn:
        print(f"\n⚠ {w}", file=sys.stderr)
    if fail:
        print("\n✗ CHƯA ĐẠT RC-00:", file=sys.stderr)
        for f in fail:
            print(f"  · {f}", file=sys.stderr)
        return 2
    # RC2-052 · ở chế độ `--json`, stdout phải là JSON THUẦN.
    #
    # Bản trước in dòng kết luận này ra stdout **sau** khối JSON, nên
    # `python tools/env_check.py --json > env_check.json` cho ra một tệp
    # `json.load()` không đọc nổi ("Extra data: line 43"). Lỗi chỉ lộ ra khi
    # env-check ĐẠT — lúc fail thì dòng kết luận đi stderr nên tệp lại hợp lệ.
    # Một tệp bằng chứng chỉ hỏng ở đường thành công là loại hỏng tệ nhất.
    print("\n✓ RC-00 env-check đạt", file=sys.stderr if a.json else sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
