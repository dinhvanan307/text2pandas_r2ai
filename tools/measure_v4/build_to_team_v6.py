#!/usr/bin/env python3
"""Đóng `to_team_v6.zip` — handoff cho review 171.

Theo đúng convention của to_team_V4/v5:
  * staging dir có prefix nhận dạng;
  * `MANIFEST.sha256` tính sau cùng, trừ chính nó;
  * **ZIP TẤT ĐỊNH**: mọi entry ghim `date_time` cố định và entry được sort.
    Không có nó thì hai lần đóng cùng nội dung cho hai SHA khác nhau và
    checksum trong packet mất hết giá trị kiểm chứng (bài học AG1).
  * file `.sha256` nằm NGOÀI zip, hash đúng chính zip được gửi.

Chạy:
    python3 tools/measure_v4/build_to_team_v6.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MOC = (2026, 1, 1, 0, 0, 0)          # mốc thời gian cố định cho mọi entry

PARENT = "artifacts/submissions/legacy/submission_P0I.zip"

# ---- source: đúng những gì tạo ra artifact, không thừa ----------------------
SOURCE_PKG = "src/text2pandas/answer_pipeline"
SOURCE_TOOLS = "tools/measure_v4"
TESTS = [
    "tests/test_unitlex.py",
    "tests/test_unit_contract.py",
    "tests/test_operation_ir.py",
    "tests/test_pipeline_e2e.py",
    "tests/test_period.py",
]
DOCS = [
    "docs/170_EXECUTION_CLOSURE_AND_GENERAL_ANSWER_PATH.md",
    "docs/172_TECHNICAL_AUDIT_GENERAL_ANSWER_PATH.md",
]
ARTIFACT_DIR = "artifacts/handoff_v6"

SKIP_DIRS = {"__pycache__", ".pytest_cache", ".ipynb_checkpoints"}


def _force_rmtree(path: Path) -> None:
    """rmtree that survives read-only files copied off a mounted volume."""
    def onerror(func, name, _exc):
        try:
            os.chmod(name, stat.S_IWUSR | stat.S_IRUSR)
            func(name)
        except OSError:
            pass
    shutil.rmtree(path, onerror=onerror)


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def copy_tree(src: Path, dst: Path) -> list[Path]:
    out = []
    for p in sorted(src.rglob("*")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if not p.is_file():
            continue
        rel = p.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
        target.chmod(target.stat().st_mode | stat.S_IWUSR)
        out.append(target)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist" / "to_team_v6.zip"))
    ap.add_argument("--stage", default=None)
    ap.add_argument("--no-parent", action="store_true",
                    help="không bundle parent ZIP (dùng khi gửi qua kênh giới hạn)")
    a = ap.parse_args()

    parent_path = ROOT / PARENT
    if not parent_path.exists():
        sys.exit(f"parent không tồn tại: {parent_path}")
    parent_sha = sha_file(parent_path)

    name = f"general_answer_path_handoff_{parent_sha[:8]}_v6"
    # Stage in a temp dir, never inside the repo: copy2 preserves source
    # permissions, and read-only files on a mounted volume then make the
    # staging dir undeletable on the next build.
    stage_root = Path(a.stage) if a.stage else Path(tempfile.mkdtemp(prefix="to_team_v6_"))
    if stage_root.exists() and a.stage:
        _force_rmtree(stage_root)
    stage = stage_root / name
    stage.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- source
    copy_tree(ROOT / SOURCE_PKG, stage / "source" / SOURCE_PKG)
    copy_tree(ROOT / SOURCE_TOOLS, stage / "source" / SOURCE_TOOLS)
    for t in TESTS:
        dst = stage / "source" / t
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / t, dst)

    # ------------------------------------------------------------- artifacts
    copy_tree(ROOT / ARTIFACT_DIR, stage / "artifacts")

    # ------------------------------------------------------------------ docs
    for d in DOCS:
        dst = stage / "docs" / Path(d).name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / d, dst)

    # ---------------------------------------------------------------- parent
    (stage / "parent").mkdir(parents=True, exist_ok=True)
    if not a.no_parent:
        shutil.copy2(parent_path, stage / "parent" / "submission_P0I.zip")
    (stage / "parent" / "identity.json").write_text(json.dumps({
        "repo_relative_path": PARENT,
        "sha256": parent_sha,
        "bundled_in_packet": not a.no_parent,
        "placement_if_not_bundled":
            "đặt file có đúng SHA trên vào <repo>/artifacts/submissions/legacy/submission_P0I.zip",
        "n_prediction_records": 1012,
        "n_csv_members": 982,
    }, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    # ----------------------------------------------------------- environment
    env = stage / "environment"
    env.mkdir(parents=True, exist_ok=True)
    (env / "python_version.txt").write_text(sys.version + "\n", encoding="utf-8")
    try:
        freeze = subprocess.run([sys.executable, "-m", "pip", "freeze"],
                                capture_output=True, text=True, timeout=120).stdout
    except Exception as exc:                                   # pragma: no cover
        freeze = f"pip freeze failed: {exc}\n"
    (env / "dependency_freeze.txt").write_text(freeze, encoding="utf-8")
    (env / "command_log.md").write_text(COMMAND_LOG, encoding="utf-8")

    # ------------------------------------------------------------ identity
    ident = stage / "identity"
    ident.mkdir(parents=True, exist_ok=True)
    src_files = sorted((stage / "source").rglob("*.py"))
    src_map = {str(p.relative_to(stage / "source")): sha_file(p) for p in src_files}
    art_files = sorted((stage / "artifacts").rglob("*"))
    art_map = {str(p.relative_to(stage / "artifacts")): sha_file(p)
               for p in art_files if p.is_file()}
    (ident / "source_identity.json").write_text(json.dumps({
        "n_source_files": len(src_map),
        "aggregate_sha256": hashlib.sha256(
            json.dumps(src_map, sort_keys=True).encode()).hexdigest(),
        "files": src_map,
    }, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (ident / "artifact_identity.json").write_text(json.dumps({
        "n_artifact_files": len(art_map),
        "aggregate_sha256": hashlib.sha256(
            json.dumps(art_map, sort_keys=True).encode()).hexdigest(),
        "files": art_map,
    }, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    # -------------------------------------------------------------- README
    (stage / "README.md").write_text(readme(parent_sha, name), encoding="utf-8")

    # ------------------------------------------- MANIFEST (sau cùng, trừ nó)
    lines = []
    for p in sorted(stage.rglob("*")):
        if p.is_file() and p.name != "MANIFEST.sha256":
            lines.append(f"{sha_file(p)}  {p.relative_to(stage)}")
    (stage / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ------------------------------------------------------- ZIP tất định
    out_zip = Path(a.out)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    entries = sorted(p for p in stage.rglob("*") if p.is_file())
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for p in entries:
            zi = zipfile.ZipInfo(str(Path(name) / p.relative_to(stage)), date_time=MOC)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, p.read_bytes())

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    zip_sha = sha_file(out_zip)
    sha_path = out_zip.with_suffix(out_zip.suffix + ".sha256")
    sha_path.write_text(f"{zip_sha}  {out_zip.name}\n", encoding="utf-8")

    _force_rmtree(stage_root)

    print(json.dumps({
        "zip": str(out_zip.relative_to(ROOT)),
        "sha256": zip_sha,
        "sha_file": str(sha_path.relative_to(ROOT)),
        "n_entries": len(entries),
        "bytes": out_zip.stat().st_size,
        "parent_sha256": parent_sha,
        "parent_bundled": not a.no_parent,
    }, ensure_ascii=False, indent=2))
    return 0


COMMAND_LOG = """# Command log — mọi artifact trong packet được sinh bằng đúng các lệnh sau

Chạy từ root repo. Cần `pandas` và `pytest`. Parent ZIP phải nằm ở
`artifacts/submissions/legacy/submission_P0I.zip` (SHA trong `parent/identity.json`).

```bash
A=artifacts/handoff_v6
M=tools/measure_v4

# 1. Measurement closure (AST /1e6, storage scale, unit convention per QID)
python3 $M/run_measurement_closure.py \\
    --submission-zip artifacts/submissions/legacy/submission_P0I.zip \\
    --out-dir $A/measurement_closure

# 2. Pinned ablation — ghim vào đúng ô parent đã chọn.
#    Cô lập tầng SINH ĐÁP ÁN khỏi selection/retrieval.
python3 $M/run_pipeline_e2e.py \\
    --submission-zip artifacts/submissions/legacy/submission_P0I.zip \\
    --out-dir $A/pinned --pin-parent-cells

# 3. Unpinned smoke run — selector thật (còn là stub).
python3 $M/run_pipeline_e2e.py \\
    --submission-zip artifacts/submissions/legacy/submission_P0I.zip \\
    --out-dir $A/unpinned

# 4. Set relations + funnel loại trừ lẫn nhau
python3 $M/reconcile_sets.py   --measure $A/measurement_closure \\
                               --pinned  $A/pinned --out $A/reconciliation
python3 $M/reconcile_funnel.py --pinned  $A/pinned --out $A/reconciliation

# 5. Audit EXTREMUM (subtype + trục độ khó)
python3 $M/audit_extremum.py --submission <giải nén>/submission.json \\
                             --out $A/extremum

# 6. Candidate coverage (operand có thật sự nằm trong pool không)
python3 $M/audit_candidate_coverage.py --root <giải nén> \\
                                       --out $A/candidate_coverage

# 7. Test
python3 -m pytest tests/test_unitlex.py tests/test_unit_contract.py \\
                  tests/test_operation_ir.py tests/test_pipeline_e2e.py \\
                  tests/test_period.py -v
```

`<giải nén>` là thư mục đã unzip parent (chứa `submission.json` + `data/`).
Bước 1–3 tự unzip vào temp nên không cần bước này; bước 5–6 cần đường dẫn.
"""


def readme(parent_sha: str, name: str) -> str:
    return f"""# to_team_v6 · {name}

Handoff cho **review 171**: source + test + artifact của general answer path,
đủ để reviewer tái lập độc lập mọi con số trong doc 170 và doc 172.

**Parent:** `submission_P0I.zip` · SHA256 `{parent_sha}`
**Không có submission mới trong packet này.** Đây là gói *verification*, không
phải gói nộp bài.

## Kiểm chứng KHÔNG cần data

```bash
sha256sum -c MANIFEST.sha256          # toàn bộ packet
cat identity/source_identity.json     # aggregate SHA của source
cat identity/artifact_identity.json   # aggregate SHA của artifact
```

Test suite (cần `pandas` + `pytest`, **không** cần parent data):

```bash
cd source && python3 -m pytest tests/ -v     # kỳ vọng 162 passed
```
Test tự thêm `source/src` vào `sys.path`, chạy được từ thư mục bất kỳ.
Log của lần chạy trên máy build: `artifacts/tests/pytest_full.log`.

## Kiểm chứng CẦN data

Đặt parent ZIP đúng chỗ rồi chạy lại theo `environment/command_log.md`.
Nếu packet có bundle sẵn:

```bash
mkdir -p <repo>/artifacts/submissions/legacy
cp parent/submission_P0I.zip <repo>/artifacts/submissions/legacy/
```

Mọi generator đều **tất định**: chạy hai lần cho SHA giống hệt (đã kiểm với
`run_measurement_closure.py`). Output phải khớp `identity/artifact_identity.json`.

## Nội dung

```
source/src/text2pandas/answer_pipeline/   pipeline sinh đáp án (units, ir, frame,
                                          router, binding, render, validate,
                                          period, adapters, pipeline)
source/tools/measure_v4/                  generator đo lường + audit + builder
source/tests/                             5 file test, 162 ca
artifacts/measurement_closure/            AST /1e6, storage scale, unit per QID
artifacts/pinned/                         ablation tầng sinh đáp án, per-QID
artifacts/unpinned/                       smoke run selector thật
artifacts/reconciliation/                 set relations + funnel loại trừ + attribution
artifacts/extremum/                       226 EXTREMUM: subtype + trục độ khó
artifacts/candidate_coverage/             operand có nằm trong pool không
artifacts/tests/pytest_full.log           log test máy build
docs/170, docs/172                        báo cáo + audit kỹ thuật
parent/                                   identity + (tuỳ chọn) parent ZIP
environment/                              python, dependency freeze, command log
identity/                                 aggregate SHA source & artifact
```

## Đọc theo thứ tự

**172** (audit kỹ thuật, có ba nhãn rút lại khỏi 170) → **170** (báo cáo gốc) →
`artifacts/reconciliation/unit_set_relations.json` (đóng 35/25/24/21/U1-7) →
`artifacts/reconciliation/funnel_reconciliation.json` (đóng 182 vs 166) →
`artifacts/extremum/extremum_summary.json` → `artifacts/candidate_coverage/`.

## Ba điều reviewer nên kiểm trước

1. **`funnel_reconciliation.json` → `sums_to_n_records`** phải là `true`.
   Bảng stage×reason cộng đúng 1012, không có case ẩn trong aggregate.
2. **`unit_set_relations.json` → `primary_cause_sums_to_1012`** phải là `true`.
   Mỗi QID đúng **một** primary cause theo causal precedence, không double count.
3. **`test_emitter_contains_no_scale_literal`** và
   **`test_no_qid_whitelist_in_the_package`** trong `test_unit_contract.py` —
   hai guard cấu trúc thay cho whitelist U1-7.

## Trạng thái tự khai (đọc 172 §14 trước khi tin bất kỳ nhãn PASS nào)

| Hạng mục | Trạng thái |
|---|---|
| Unit Contract | component test PASS, 53 ca |
| OperationIR | component test PASS, 18 ca |
| Period resolver | component test PASS, 22 ca — **sửa một defect của chính doc 170** |
| E2E tổng hợp | PASS, 15 ca |
| Semantic frame accuracy | **UNKNOWN** — chưa có local gold |
| Operand binding accuracy | **UNKNOWN** — selector là stub |
| General answer path | **CHƯA wire vào production, CHƯA có fallback** |
| Candidate generation | **KHÔNG TỒN TẠI** — pool là evidence của parent |
"""


if __name__ == "__main__":
    raise SystemExit(main())
