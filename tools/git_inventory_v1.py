#!/usr/bin/env python3
"""Phân loại working tree — review 131 §7. KHÔNG commit mù.

Review 131 bác "commit + backup toàn bộ 167 path": working tree chứa ZIP,
wheelhouse, evidence bundle và dataset lớn. Commit tất cả làm repo phình, chậm
và đưa generated artifact vào Git.

Tiêu chí ĐÚNG (review 131 §7) không phải "0 untracked bằng mọi giá", mà:

    0 unclassified path
    0 source/config change chưa commit
    mọi generated/large artifact có owner, path, SHA và regeneration command

Tệp này chỉ PHÂN LOẠI và sinh manifest + .gitignore đề xuất. Nó KHÔNG tự chạy
`git add`/`git commit` — quyết định đưa gì vào lịch sử repo là của người, và
một script tự commit là đúng thứ review 131 vừa cảnh báo.

Chạy:  python3 tools/git_inventory_v1.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIG = 5 * 1024 * 1024        # >5 MB = large artifact

# Thứ tự QUAN TRỌNG: khớp luật đầu tiên thắng.
RULES: list[tuple[str, str, str]] = [
    # (nhóm, mô tả, tiền tố/hậu tố)
    ("NEVER_COMMIT", "database dẫn xuất", "data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db"),
    ("NEVER_COMMIT", "gói A6 chứng nhận", "artifacts/rc2/packagesa6/"),
    ("NEVER_COMMIT", "release DB", "data/processed/a6/b3e9684004679ffb/"),
    ("NEVER_COMMIT", "wheelhouse", "wheelhouse"),
    ("NEVER_COMMIT", "silver release zip", "silver_release.zip"),
    ("NEVER_COMMIT", "venv", ".venv"),
    ("NEVER_COMMIT", "cache", "__pycache__"),
    ("NEVER_COMMIT", "cache", ".pytest_cache"),
    ("NEVER_COMMIT", "macOS metadata", ".DS_Store"),
    ("NEVER_COMMIT", "candidate ZIP sinh ra", "artifacts/execution/candidates/"),
    ("NEVER_COMMIT", "packet ZIP sinh ra", "sync_122_1.zip"),
    ("NEVER_COMMIT", "packet ZIP sinh ra", "sync_122_2.zip"),
    ("NEVER_COMMIT", "thư mục packet mở", "sync_122_1/"),
    ("NEVER_COMMIT", "thư mục packet mở", "sync_122_2/"),
    ("NEVER_COMMIT", "evidence bundle zip", "_evidence"),
    ("NEVER_COMMIT", "staging", "_h0_stage/"),
    ("NEVER_COMMIT", "scratch", "to_read/"),
    ("NEVER_COMMIT", "output verify", "verify_out/"),
    # `zi8fvJau` là BẢN SAO MỒ CÔI của sync_122_1.zip (520 entries, cùng nội
    # dung) với tên ngẫu nhiên — dấu vết một lần copy hỏng. Không tái tạo được
    # từ tên, nhưng tái tạo được từ nguồn: nó CHÍNH LÀ sync_122_1.zip.
    ("NEVER_COMMIT", "bản sao mồ côi của sync_122_1.zip", "zi8fvJau"),

    # data/curated/dev-legacy: TÁCH metadata nhỏ khỏi dump lớn. Gộp cả `data/curated/dev-legacy/` vào COMMIT
    # sẽ kéo 46,8 MB record dump vào Git — đúng thứ review 131 §7 cấm.
    ("NEVER_COMMIT", "dump bản ghi answer_a6", "data/curated/dev-legacy/answer_a6/"),
    ("NEVER_COMMIT", "dump bản ghi answer_v2", "data/curated/dev-legacy/answer_v2/"),
    ("NEVER_COMMIT", "dump bản ghi answer_v3", "data/curated/dev-legacy/answer_v3/"),
    ("NEVER_COMMIT", "dump so_hoc", "data/curated/dev-legacy/so_hoc/"),
    ("NEVER_COMMIT", "gold pool trung gian", "data/curated/dev-legacy/gold_tay_pool_"),
    ("NEVER_COMMIT", "worksheet trung gian", "data/curated/dev-legacy/gold_worksheet_"),

    ("COMMIT", "source", "src/"),
    ("COMMIT", "tool", "tools/"),
    ("COMMIT", "config", "configs/"),
    ("COMMIT", "test", "tests/"),
    ("COMMIT", "tài liệu", "docs/"),
    ("COMMIT", "môi trường", "env/"),
    ("COMMIT", "identity/metadata nhỏ", "provenance/identity/"),
    ("COMMIT", "selection + dossier + schema nhãn", "data/curated/dev-legacy/execution_gold/"),
    ("COMMIT", "gold đáp án (nhỏ, là SSOT đo)", "data/curated/dev-legacy/gold_dap_an/"),
    # Các gold/sample nhỏ còn lại của data/curated/dev-legacy — đều là metadata đo, vài trăm KB.
    ("COMMIT", "gold BẢNG v1/v2 (dụng cụ đo retrieval)", "data/curated/dev-legacy/gold_v"),
    ("COMMIT", "gold tay sample", "data/curated/dev-legacy/gold_tay_sample_"),
    ("COMMIT", "sample chọn mẫu", "data/curated/dev-legacy/gold_sample_"),
    ("COMMIT", "override thực thể", "data/curated/dev-legacy/gold_entity_override_"),
    ("COMMIT", "audit retrieval (nhỏ)", "data/curated/dev-legacy/audit/"),
    ("COMMIT", "báo cáo JSON nhỏ", "reports/"),
    ("COMMIT", "evaluation JSONL nhỏ", "data/curated/evaluation/legacy/"),
    ("COMMIT", "manifest packet", "packet_kind.json"),
    ("COMMIT", "manifest packet", "sync_122_2.sha256"),
    ("COMMIT", "build config", "pyproject.toml"),
    ("COMMIT", "lock", "requirements.lock"),
    ("COMMIT", "Makefile", "Makefile"),
    ("COMMIT", "gitignore", ".gitignore"),
]

GITIGNORE_LINES = [
    "# ── sinh bởi tools/git_inventory_v1.py (review 131 §7) ──",
    "__pycache__/", "*.py[cod]", ".pytest_cache/",
    ".venv*/", ".DS_Store",
    "",
    "# artifact lớn / dẫn xuất — giữ NGOÀI Git, tra bằng SHA manifest",
    "data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db",
    "artifacts/rc2/packagesa6/",
    "data/processed/a6/b3e9684004679ffb/",
    "artifacts/execution/candidates/",
    "wheelhouse*/", "wheelhouse*.zip",
    "silver_release.zip",
    "*_evidence*.zip",
    "_h0_stage/",
    "to_read/",
    "verify_out/",
    "sync_122_*/", "sync_122_*.zip",
    "!sync_122_2.sha256",
    "zi8fvJau",
    "",
    "# data/curated/dev-legacy: chỉ giữ metadata nhỏ, bỏ dump bản ghi",
    "data/curated/dev-legacy/answer_a6/", "data/curated/dev-legacy/answer_v2/", "data/curated/dev-legacy/answer_v3/",
    "data/curated/dev-legacy/so_hoc/",
    "data/curated/dev-legacy/gold_tay_pool_*.jsonl", "data/curated/dev-legacy/gold_worksheet_*.jsonl",
]


def classify(path: str) -> tuple[str, str]:
    for group, why, pat in RULES:
        if path == pat or path.startswith(pat) or pat in path:
            return group, why
    return "UNCLASSIFIED", "chưa có luật"


def sha256(p: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for c in iter(lambda: f.read(1 << 22), b""):
                h.update(c)
        return h.hexdigest()
    except Exception:
        return None


def main() -> int:
    st = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                        capture_output=True, text=True).stdout.splitlines()
    groups: dict[str, list] = {}
    large: list[dict] = []
    # `git status` gộp một thư mục hoàn toàn untracked thành MỘT dòng. Với thư
    # mục TRỘN (data/curated/dev-legacy vừa có metadata nhỏ vừa có dump 46 MB) thì một nhãn
    # duy nhất là sai dù chọn nhãn nào. Nở một cấp rồi phân loại từng con.
    expanded: list[str] = []
    for line in st:
        code, path = line[:2], line[3:].strip().strip('"')
        pp = ROOT / path
        if path.endswith("/") and pp.is_dir() and classify(path)[0] == "UNCLASSIFIED":
            kids = sorted(c.name + ("/" if c.is_dir() else "") for c in pp.iterdir())
            groups_seen = {classify(path + k)[0] for k in kids}
            if len(groups_seen) > 1 or "UNCLASSIFIED" in groups_seen:
                expanded += [f"{code} {path}{k}" for k in kids]
                continue
        expanded.append(line)
    st = expanded

    for line in st:
        code, path = line[:2], line[3:].strip().strip('"')
        g, why = classify(path)
        p = ROOT / path
        size = p.stat().st_size if p.is_file() else None
        if p.is_dir():
            size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        rec = {"path": path, "git_code": code.strip() or "?", "why": why,
               "bytes": size}
        groups.setdefault(g, []).append(rec)
        if size and size > BIG:
            large.append(rec | {"sha256": sha256(p) if p.is_file() else None,
                                "regeneration": _regen(path)})

    unclassified = groups.get("UNCLASSIFIED", [])
    src_dirty = [r for r in groups.get("COMMIT", [])
                 if r["git_code"] in ("M", "MM", "AM")
                 and r["path"].startswith(("src/", "configs/", "tools/", "tests/"))]

    rep = {
        "_schema": "git_inventory v1 — review 131 §7 (phân loại, KHÔNG commit mù)",
        "date": "2026-08-21",
        "tieu_chi": ["0 unclassified path",
                     "0 source/config change chưa commit",
                     "mọi large artifact có SHA + regeneration command"],
        "n_path": len(st),
        "n_theo_nhom": {k: len(v) for k, v in sorted(groups.items())},
        "bytes_theo_nhom": {k: sum(r["bytes"] or 0 for r in v)
                            for k, v in sorted(groups.items())},
        "n_unclassified": len(unclassified),
        "unclassified": unclassified,
        "source_config_chua_commit": src_dirty,
        "large_artifacts": sorted(large, key=lambda r: -(r["bytes"] or 0)),
        "gitignore_de_xuat": GITIGNORE_LINES,
        "VERDICT": ("INVENTORY_CLEAN" if not unclassified else "CO_PATH_CHUA_PHAN_LOAI"),
        "ghi_chu": ("Tệp này KHÔNG chạy git add/commit. Commit là quyết định của "
                    "người; một script tự commit đúng là thứ review 131 §7 cảnh báo."),
    }
    (ROOT / "reports/git_inventory_v1.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    man = ROOT / "artifacts/LARGE_ARTIFACTS.sha256.json"
    man.parent.mkdir(exist_ok=True)
    man.write_text(json.dumps(
        {"_schema": "large artifact manifest — giữ NGOÀI Git",
         "date": "2026-08-21", "n": len(large),
         "artifacts": rep["large_artifacts"]}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    print(f"tổng path chưa commit: {len(st)}")
    for k, v in sorted(rep["n_theo_nhom"].items()):
        mb = rep["bytes_theo_nhom"][k] / 1e6
        print(f"   {k:14} {v:4d} path · {mb:9.1f} MB")
    print(f"\nsource/config chưa commit: {len(src_dirty)}")
    for r in src_dirty[:10]:
        print(f"   [{r['git_code']}] {r['path']}")
    print(f"\nlarge artifact (>5MB) có SHA: {len(large)}")
    for r in rep["large_artifacts"][:8]:
        print(f"   {(r['bytes'] or 0)/1e6:8.1f} MB  {r['path']}")
    print(f"\nchưa phân loại: {len(unclassified)}")
    for r in unclassified[:10]:
        print(f"   {r['path']}")
    print(f"\n{rep['VERDICT']}")
    print("-> reports/git_inventory_v1.json · artifacts/LARGE_ARTIFACTS.sha256.json")
    return 0


def _regen(path: str) -> str:
    if path.startswith("data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db"):
        return "bash tools/build_retrieval_workdb.sh <silver.db> <work.db> [<a6.zip>]"
    if path.startswith("artifacts/execution/candidates/"):
        return "python3 tools/build_candidate_v1.py --zip <rung>"
    if path.startswith("sync_122_2"):
        return "python3 tools/build_sync_packet_v2.py"
    if "wheelhouse" in path:
        return "pip download -r requirements.lock -d wheelhouse (theo nền tảng đích)"
    return "KHÔNG TÁI TẠO ĐƯỢC — phải sao lưu ngoài Git"


if __name__ == "__main__":
    raise SystemExit(main())
