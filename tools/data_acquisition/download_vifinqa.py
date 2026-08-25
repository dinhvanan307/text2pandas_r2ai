#!/usr/bin/env python3
"""
download_vifinqa.py — Tải và kiểm tra toàn vẹn bộ dữ liệu ViFinQA.

Phạm vi CỐ Ý GIỚI HẠN: script này CHỈ tải dữ liệu và kiểm kê tính đầy đủ.
Nó KHÔNG tiền xử lý, KHÔNG parse bảng, KHÔNG dựng DataFrame, KHÔNG embedding,
KHÔNG OCR, KHÔNG xây dựng bất kỳ thành phần AI nào.

Nguồn:
  - Dataset : https://huggingface.co/datasets/AIGuruTinix/ViFinQA
  - Codebase: https://github.com/DSKT-NOWJ/ViFinQA

Đặc tính:
  - Idempotent : chạy lại nhiều lần không tải lại file đã có (dựa trên cache của
                 huggingface_hub + kiểm tra commit hash cho git).
  - Resumable  : gián đoạn giữa chừng thì chạy lại sẽ tiếp tục.
  - Logging    : ghi ra console và ra file log có dấu thời gian.

Yêu cầu: Python >= 3.11 (khuyến nghị 3.12), xem requirements.txt.

Cách dùng:
    python download_vifinqa.py                      # tải + kiểm tra + sinh báo cáo
    python download_vifinqa.py --dest <thư_mục>     # đổi đích lưu
    python download_vifinqa.py --verify-only        # chỉ kiểm tra, không tải
    python download_vifinqa.py --skip-github        # bỏ qua clone codebase
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ─────────────────────────── Hằng số ───────────────────────────

HF_REPO_ID = "AIGuruTinix/ViFinQA"
HF_REPO_TYPE = "dataset"
GITHUB_URL = "https://github.com/DSKT-NOWJ/ViFinQA.git"

DEFAULT_DEST = Path("data/external/vifinqa")
GITHUB_SUBDIR = "_codebase"  # tách khỏi dữ liệu, không trộn lẫn

# Giá trị công bố trong Dataset Card — dùng để đối chiếu.
# KHÔNG suy diễn thêm; chỉ những con số tài liệu nêu tường minh.
EXPECTED: dict[str, Any] = {
    "questions": 1012,
    "reports": 1973,
    "companies": 100,
    "year_min": 2015,
    "year_max": 2025,
    "question_id_min": 1,
    "question_id_max": 1012,
    "report_types": {  # theo tên file, Dataset Card §Dataset Structure
        "consolidated": 957,
        "separate": 954,
        "aggregated": 7,
        "other": 55,
    },
    "license": "CC BY-NC 4.0 (corpus nguồn TiniX); "
               "license riêng cho phần annotation câu hỏi: KHÔNG nêu",
}

LOG = logging.getLogger("vifinqa")


# ─────────────────────────── Logging ───────────────────────────

def setup_logging(dest: Path, verbose: bool = False) -> Path:
    """Cấu hình log ra console + file. Trả về đường dẫn file log."""
    log_dir = dest.parent / "_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = log_dir / f"download_vifinqa_{stamp}.log"

    LOG.setLevel(logging.DEBUG if verbose else logging.INFO)
    LOG.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(fmt)
    LOG.addHandler(console)

    filehandler = logging.FileHandler(log_path, encoding="utf-8")
    filehandler.setLevel(logging.DEBUG)
    filehandler.setFormatter(fmt)
    LOG.addHandler(filehandler)

    return log_path


# ─────────────────────────── Tải dữ liệu ───────────────────────────

def download_hf_dataset(dest: Path) -> dict[str, Any]:
    """
    Tải toàn bộ dataset từ Hugging Face vào `dest`.

    Dùng snapshot_download: đã sẵn tính idempotent và resumable —
    file nào khớp hash thì bỏ qua, file dở dang thì tải tiếp.
    """
    from huggingface_hub import snapshot_download
    from huggingface_hub import HfApi

    LOG.info("Bắt đầu tải dataset %s → %s", HF_REPO_ID, dest)
    dest.mkdir(parents=True, exist_ok=True)

    # Ghi lại revision để biết chính xác phiên bản đã tải
    api = HfApi()
    info = api.dataset_info(HF_REPO_ID)
    revision = info.sha
    LOG.info("Revision (commit sha) trên Hub: %s", revision)
    LOG.info("Ngày sửa gần nhất trên Hub    : %s", info.last_modified)

    local_path = snapshot_download(
        repo_id=HF_REPO_ID,
        repo_type=HF_REPO_TYPE,
        local_dir=str(dest),
        revision=revision,
        max_workers=8,
    )

    LOG.info("Tải xong dataset vào: %s", local_path)
    return {
        "revision": revision,
        "last_modified": str(info.last_modified),
        "local_path": str(local_path),
    }


def clone_github(dest: Path) -> dict[str, Any]:
    """
    Clone (hoặc cập nhật) codebase companion.
    Idempotent: đã có thì fetch + reset, chưa có thì clone.
    """
    repo_dir = dest / GITHUB_SUBDIR
    try:
        if (repo_dir / ".git").exists():
            LOG.info("Codebase đã tồn tại — cập nhật: %s", repo_dir)
            subprocess.run(["git", "-C", str(repo_dir), "fetch", "--all", "--tags"],
                           check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo_dir), "pull", "--ff-only"],
                           check=True, capture_output=True)
        else:
            LOG.info("Clone codebase %s → %s", GITHUB_URL, repo_dir)
            repo_dir.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", GITHUB_URL, str(repo_dir)],
                           check=True, capture_output=True)

        sha = subprocess.run(["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
                             check=True, capture_output=True, text=True).stdout.strip()
        LOG.info("Codebase commit: %s", sha)
        return {"ok": True, "commit": sha, "path": str(repo_dir)}
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else str(exc.stderr)
        LOG.error("Clone/cập nhật codebase thất bại: %s", stderr.strip()[:300])
        return {"ok": False, "error": stderr.strip()[:300]}


# ─────────────────────────── Kiểm kê ───────────────────────────

def classify_report_type(rel_path: str) -> str:
    """
    Phân loại báo cáo theo tên, đúng cách Dataset Card mô tả.

    Xét TOÀN BỘ đường dẫn tương đối (thư mục tài liệu + tên file), vì từ khoá
    loại báo cáo nằm ở tên thư mục DOCUMENT và thường lặp lại ở tên file.
    Chỉ dựa vào tên file sẽ bỏ sót khi quy ước đặt tên khác đi.
    """
    low = rel_path.lower()
    if "consolidated" in low:
        return "consolidated"
    if "separate" in low:
        return "separate"
    if "aggregated" in low:
        return "aggregated"
    return "other"


def inspect(dest: Path) -> dict[str, Any]:
    """
    Kiểm kê nội dung đã tải. CHỈ đếm và đối chiếu — không phân tích nội dung,
    không parse bảng, không trích xuất số liệu.
    """
    from tqdm import tqdm

    LOG.info("Bắt đầu kiểm kê tại: %s", dest)
    result: dict[str, Any] = {"errors": [], "warnings": []}

    # ── Câu hỏi ───────────────────────────────────────────────
    q_path = dest / "questions" / "questions.jsonl"
    if not q_path.exists():
        result["errors"].append(f"THIẾU FILE: {q_path}")
        result["questions"] = {"count": 0}
    else:
        ids: list[int] = []
        malformed = 0
        empty_q = 0
        with q_path.open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    result["errors"].append(f"questions.jsonl dòng {lineno}: JSON hỏng")
                    continue
                if "id" not in obj or "question" not in obj:
                    malformed += 1
                    result["errors"].append(
                        f"questions.jsonl dòng {lineno}: thiếu trường id/question")
                    continue
                ids.append(obj["id"])
                if not str(obj["question"]).strip():
                    empty_q += 1

        id_set = set(ids)
        expected_ids = set(range(EXPECTED["question_id_min"],
                                 EXPECTED["question_id_max"] + 1))
        result["questions"] = {
            "count": len(ids),
            "unique_ids": len(id_set),
            "id_min": min(ids) if ids else None,
            "id_max": max(ids) if ids else None,
            "duplicates": len(ids) - len(id_set),
            "missing_ids": sorted(expected_ids - id_set)[:20],
            "extra_ids": sorted(id_set - expected_ids)[:20],
            "malformed_lines": malformed,
            "empty_question_text": empty_q,
            "file_size_bytes": q_path.stat().st_size,
        }
        LOG.info("Câu hỏi: %d dòng, %d id duy nhất, khoảng id [%s..%s]",
                 len(ids), len(id_set), min(ids, default="-"), max(ids, default="-"))

    # ── code_stock.csv ────────────────────────────────────────
    cs_path = dest / "code_stock.csv"
    if not cs_path.exists():
        result["errors"].append(f"THIẾU FILE: {cs_path}")
        result["code_stock"] = {"rows": 0}
    else:
        with cs_path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            headers = reader.fieldnames or []
            rows = list(reader)
        tickers = [r.get("Mã CK", "").strip() for r in rows if r.get("Mã CK", "").strip()]
        result["code_stock"] = {
            "rows": len(rows),
            "headers": headers,
            "unique_tickers": len(set(tickers)),
            "duplicated_tickers": len(tickers) - len(set(tickers)),
            "file_size_bytes": cs_path.stat().st_size,
        }
        LOG.info("code_stock.csv: %d dòng, %d mã CK duy nhất, cột=%s",
                 len(rows), len(set(tickers)), headers)

    # ── Báo cáo tài chính ─────────────────────────────────────
    fs_root = dest / "financial_statements"
    if not fs_root.is_dir():
        result["errors"].append(f"THIẾU THƯ MỤC: {fs_root}")
        result["reports"] = {"count": 0}
    else:
        txt_files = sorted(fs_root.glob("*/*/*/*.txt"))
        other_depth = [p for p in fs_root.rglob("*.txt") if p not in set(txt_files)]

        tickers_dir: set[str] = set()
        years: Counter[str] = Counter()
        types: Counter[str] = Counter()
        total_bytes = 0
        empty_files: list[str] = []
        per_ticker: Counter[str] = Counter()

        for p in tqdm(txt_files, desc="Kiểm kê báo cáo", unit="file"):
            rel = p.relative_to(fs_root)
            ticker, year = rel.parts[0], rel.parts[1]
            tickers_dir.add(ticker)
            per_ticker[ticker] += 1
            years[year] += 1
            types[classify_report_type(str(rel))] += 1
            size = p.stat().st_size
            total_bytes += size
            if size == 0:
                empty_files.append(str(rel))

        numeric_years = sorted({int(y) for y in years if y.isdigit()})
        result["reports"] = {
            "count": len(txt_files),
            "unexpected_depth_files": len(other_depth),
            "tickers_in_tree": len(tickers_dir),
            "year_min": numeric_years[0] if numeric_years else None,
            "year_max": numeric_years[-1] if numeric_years else None,
            "years_present": numeric_years,
            "non_numeric_year_dirs": sorted(y for y in years if not y.isdigit()),
            "by_type": dict(types),
            "by_year": {y: years[y] for y in sorted(years)},
            "total_bytes": total_bytes,
            "empty_files": empty_files,
            "reports_per_ticker_min": min(per_ticker.values()) if per_ticker else 0,
            "reports_per_ticker_max": max(per_ticker.values()) if per_ticker else 0,
        }
        LOG.info("Báo cáo: %d file .txt, %d ticker, năm [%s..%s], tổng %.1f MiB",
                 len(txt_files), len(tickers_dir),
                 result["reports"]["year_min"], result["reports"]["year_max"],
                 total_bytes / 1024 / 1024)
        if empty_files:
            result["errors"].append(f"Có {len(empty_files)} file .txt rỗng")
        if other_depth:
            result["warnings"].append(
                f"Có {len(other_depth)} file .txt nằm ngoài cấu trúc TICKER/YEAR/DOC/")

    # ── Toàn bộ file trong thư mục đích ───────────────────────
    all_files = [p for p in dest.rglob("*") if p.is_file()]
    # loại trừ codebase và metadata của hf
    data_files = [p for p in all_files
                  if GITHUB_SUBDIR not in p.parts and ".cache" not in p.parts]
    ext_counter: Counter[str] = Counter(p.suffix.lower() or "<no-ext>" for p in data_files)
    result["filesystem"] = {
        "total_files_all": len(all_files),
        "total_files_data": len(data_files),
        "total_bytes_data": sum(p.stat().st_size for p in data_files),
        "by_extension": dict(ext_counter.most_common()),
    }

    return result


def cross_check(inv: dict[str, Any]) -> list[dict[str, Any]]:
    """Đối chiếu kiểm kê thực tế với con số công bố trong Dataset Card."""
    checks: list[dict[str, Any]] = []

    def add(name: str, expected: Any, actual: Any) -> None:
        checks.append({
            "item": name,
            "expected": expected,
            "actual": actual,
            "ok": expected == actual,
        })

    add("Số câu hỏi", EXPECTED["questions"], inv.get("questions", {}).get("count"))
    add("Số id câu hỏi duy nhất", EXPECTED["questions"],
        inv.get("questions", {}).get("unique_ids"))
    add("id nhỏ nhất", EXPECTED["question_id_min"], inv.get("questions", {}).get("id_min"))
    add("id lớn nhất", EXPECTED["question_id_max"], inv.get("questions", {}).get("id_max"))
    add("Số báo cáo (.txt)", EXPECTED["reports"], inv.get("reports", {}).get("count"))
    add("Số công ty (code_stock.csv)", EXPECTED["companies"],
        inv.get("code_stock", {}).get("unique_tickers"))
    add("Số ticker trong cây thư mục", EXPECTED["companies"],
        inv.get("reports", {}).get("tickers_in_tree"))
    add("Năm nhỏ nhất", EXPECTED["year_min"], inv.get("reports", {}).get("year_min"))
    add("Năm lớn nhất", EXPECTED["year_max"], inv.get("reports", {}).get("year_max"))

    by_type = inv.get("reports", {}).get("by_type", {})
    for tname, tcount in EXPECTED["report_types"].items():
        add(f"Báo cáo loại '{tname}'", tcount, by_type.get(tname, 0))

    return checks


# ─────────────────────────── Báo cáo ───────────────────────────

def human(n: int) -> str:
    x = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if x < 1024 or unit == "GiB":
            return f"{x:,.2f} {unit}" if unit != "B" else f"{int(x):,} B"
        x /= 1024
    return f"{x:.2f} GiB"


def render_tree(dest: Path, max_entries: int = 3) -> str:
    """Vẽ cây thư mục rút gọn (mô tả cấu trúc, không liệt kê hết 2000 file)."""
    lines = [f"{dest.name}/"]
    fs = dest / "financial_statements"
    if fs.is_dir():
        tickers = sorted(p.name for p in fs.iterdir() if p.is_dir())
        lines.append("├── financial_statements/")
        for t in tickers[:max_entries]:
            lines.append(f"│   ├── {t}/")
            years = sorted(p.name for p in (fs / t).iterdir() if p.is_dir())
            for y in years[:2]:
                lines.append(f"│   │   ├── {y}/")
                docs = sorted(p.name for p in (fs / t / y).iterdir() if p.is_dir())
                for d in docs[:1]:
                    lines.append(f"│   │   │   └── {d}/")
                    files = sorted(p.name for p in (fs / t / y / d).iterdir() if p.is_file())
                    for f in files[:1]:
                        lines.append(f"│   │   │       └── {f}")
                if len(years) > 2:
                    lines.append(f"│   │   └── ... ({len(years) - 2} năm khác)")
        if len(tickers) > max_entries:
            lines.append(f"│   └── ... ({len(tickers) - max_entries} ticker khác)")
    if (dest / "questions").is_dir():
        lines.append("├── questions/")
        lines.append("│   └── questions.jsonl")
    if (dest / "code_stock.csv").exists():
        lines.append("└── code_stock.csv")
    return "\n".join(lines)


def write_report(dest: Path, report_path: Path, inv: dict[str, Any],
                 checks: list[dict[str, Any]], hf_meta: dict[str, Any],
                 gh_meta: dict[str, Any], log_path: Path) -> None:
    now = datetime.now(timezone.utc)
    n_ok = sum(1 for c in checks if c["ok"])
    n_total = len(checks)
    verdict = "✅ ĐẠT" if n_ok == n_total and not inv["errors"] else "⚠️ CÓ SAI LỆCH"

    L: list[str] = []
    A = L.append

    A("# dataset_report.md — Báo cáo tải & kiểm tra toàn vẹn ViFinQA")
    A("")
    A(f"> **Trạng thái:** {verdict} — {n_ok}/{n_total} mục kiểm tra khớp Dataset Card")
    A(f"> **Sinh tự động bởi:** `download_vifinqa.py`")
    A(f"> **Phạm vi:** CHỈ tải và kiểm kê. Không tiền xử lý, không parse bảng, "
      "không dựng DataFrame, không embedding, không OCR, không xây dựng module AI.")
    A("")
    A("---")
    A("")
    A("## 1. Nguồn tải")
    A("")
    A("| Mục | Giá trị |")
    A("|---|---|")
    A(f"| Dataset (Hugging Face) | `{HF_REPO_ID}` |")
    A(f"| Loại repo | `{HF_REPO_TYPE}` |")
    A(f"| URL | https://huggingface.co/datasets/{HF_REPO_ID} |")
    A(f"| Codebase (GitHub) | {GITHUB_URL} |")
    A(f"| Phương thức | `huggingface_hub.snapshot_download` (idempotent, resumable) |")
    A("")
    A("## 2. Ngày tải & phiên bản")
    A("")
    A("| Mục | Giá trị |")
    A("|---|---|")
    A(f"| Ngày tải (UTC) | {now.strftime('%Y-%m-%d %H:%M:%S')} |")
    A(f"| Revision dataset (commit sha) | `{hf_meta.get('revision', 'N/A')}` |")
    A(f"| Sửa đổi gần nhất trên Hub | {hf_meta.get('last_modified', 'N/A')} |")
    if gh_meta.get("ok"):
        A(f"| Commit codebase | `{gh_meta.get('commit', 'N/A')}` |")
    else:
        A(f"| Commit codebase | KHÔNG clone được — {gh_meta.get('error', 'N/A')} |")
    A(f"| File log | `{log_path}` |")
    A("")
    A("## 3. License")
    A("")
    A(f"- **Corpus báo cáo tài chính:** {EXPECTED['license']}")
    A("- Corpus nguồn: `tinixai/ocr_annual_financials` — **CC BY-NC 4.0**")
    A("  (Creative Commons Attribution-NonCommercial 4.0 International)")
    A("- **Ràng buộc:** phải giữ ghi công (attribution) và **chỉ dùng phi thương mại**.")
    A("- **Lưu ý:** Dataset Card nêu rõ *không có file license riêng cho phần annotation "
      "câu hỏi*; không được giả định quyền rộng hơn những gì đã được cấp tường minh.")
    A("")
    A("## 4. Kích thước & tổng số file")
    A("")
    fsx = inv.get("filesystem", {})
    A("| Mục | Giá trị |")
    A("|---|---|")
    A(f"| Tổng số file dữ liệu | **{fsx.get('total_files_data', 0):,}** |")
    A(f"| Tổng dung lượng dữ liệu | **{human(fsx.get('total_bytes_data', 0))}** |")
    A(f"| Dung lượng riêng phần báo cáo `.txt` | {human(inv.get('reports', {}).get('total_bytes', 0))} |")
    A(f"| Tổng số file (gồm cả codebase & metadata) | {fsx.get('total_files_all', 0):,} |")
    A("")
    A("**Phân bố theo phần mở rộng:**")
    A("")
    A("| Đuôi file | Số lượng |")
    A("|---|---:|")
    for ext, cnt in fsx.get("by_extension", {}).items():
        A(f"| `{ext}` | {cnt:,} |")
    A("")
    A("## 5. Cấu trúc thư mục")
    A("")
    A("```text")
    A(render_tree(dest))
    A("```")
    A("")
    A("## 6. Kiểm tra tính đầy đủ")
    A("")
    A("Đối chiếu số đếm thực tế với con số **công bố trong Dataset Card**.")
    A("")
    A("| Mục kiểm tra | Card công bố | Thực tế | Kết quả |")
    A("|---|---:|---:|:---:|")
    for c in checks:
        mark = "✅" if c["ok"] else "❌"
        A(f"| {c['item']} | {c['expected']} | {c['actual']} | {mark} |")
    A("")
    A(f"**Tổng kết: {n_ok}/{n_total} mục khớp.**")
    A("")

    # Chi tiết câu hỏi
    q = inv.get("questions", {})
    A("### 6.1. Chi tiết `questions/questions.jsonl`")
    A("")
    A("| Mục | Giá trị |")
    A("|---|---|")
    A(f"| Số dòng hợp lệ | {q.get('count', 0):,} |")
    A(f"| Số `id` duy nhất | {q.get('unique_ids', 0):,} |")
    A(f"| Khoảng `id` | [{q.get('id_min')} .. {q.get('id_max')}] |")
    A(f"| `id` trùng lặp | {q.get('duplicates', 0)} |")
    A(f"| `id` thiếu so với 1..1012 | {len(q.get('missing_ids', []))} |")
    A(f"| `id` ngoài dải 1..1012 | {len(q.get('extra_ids', []))} |")
    A(f"| Dòng JSON hỏng | {q.get('malformed_lines', 0)} |")
    A(f"| Câu hỏi rỗng | {q.get('empty_question_text', 0)} |")
    A(f"| Kích thước file | {human(q.get('file_size_bytes', 0))} |")
    A("")

    # Chi tiết code_stock
    cs = inv.get("code_stock", {})
    A("### 6.2. Chi tiết `code_stock.csv`")
    A("")
    A("| Mục | Giá trị |")
    A("|---|---|")
    A(f"| Số dòng | {cs.get('rows', 0)} |")
    A(f"| Cột | `{cs.get('headers', [])}` |")
    A(f"| Mã CK duy nhất | {cs.get('unique_tickers', 0)} |")
    A(f"| Mã CK trùng | {cs.get('duplicated_tickers', 0)} |")
    A("")

    # Chi tiết báo cáo
    r = inv.get("reports", {})
    A("### 6.3. Chi tiết `financial_statements/`")
    A("")
    A("| Mục | Giá trị |")
    A("|---|---|")
    A(f"| Số file `.txt` đúng cấu trúc `TICKER/YEAR/DOC/` | {r.get('count', 0):,} |")
    A(f"| File `.txt` nằm sai độ sâu | {r.get('unexpected_depth_files', 0)} |")
    A(f"| Số ticker trong cây thư mục | {r.get('tickers_in_tree', 0)} |")
    A(f"| Khoảng năm | [{r.get('year_min')} .. {r.get('year_max')}] |")
    A(f"| Thư mục năm không phải số | {r.get('non_numeric_year_dirs', [])} |")
    A(f"| Số báo cáo/ticker (min–max) | {r.get('reports_per_ticker_min')}–{r.get('reports_per_ticker_max')} |")
    A(f"| File rỗng (0 byte) | {len(r.get('empty_files', []))} |")
    A("")
    A("**Phân bố theo loại báo cáo** (phân loại theo tên file):")
    A("")
    A("| Loại | Card công bố | Thực tế |")
    A("|---|---:|---:|")
    bt = r.get("by_type", {})
    for tname, tcount in EXPECTED["report_types"].items():
        A(f"| {tname} | {tcount} | {bt.get(tname, 0)} |")
    A("")
    A("**Phân bố theo năm:**")
    A("")
    A("| Năm | Số báo cáo |")
    A("|---|---:|")
    for y, c in sorted(r.get("by_year", {}).items()):
        A(f"| {y} | {c} |")
    A("")

    # Lỗi
    A("## 7. Lỗi & cảnh báo phát hiện")
    A("")
    errs = inv.get("errors", [])
    warns = inv.get("warnings", [])
    if not errs and not warns:
        A("Không phát hiện lỗi hay cảnh báo nào.")
    else:
        if errs:
            A(f"### Lỗi ({len(errs)})")
            A("")
            for e in errs[:50]:
                A(f"- ❌ {e}")
            if len(errs) > 50:
                A(f"- … và {len(errs) - 50} lỗi khác (xem file log)")
            A("")
        if warns:
            A(f"### Cảnh báo ({len(warns)})")
            A("")
            for w in warns[:50]:
                A(f"- ⚠️ {w}")
            A("")

    A("## 8. Vị trí lưu trữ")
    A("")
    A(f"```")
    A(f"{dest}")
    A(f"```")
    A("")
    A("Toàn bộ tên file và cấu trúc thư mục **giữ nguyên như nguồn**. "
      "Không đổi tên, không sửa nội dung, không chuyển đổi định dạng.")
    A("")
    A("---")
    A("")
    A(f"*Sinh tự động lúc {now.strftime('%Y-%m-%d %H:%M:%S')} UTC. "
      "Script chỉ tải và kiểm kê — không thực hiện bất kỳ bước xử lý dữ liệu nào.*")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(L), encoding="utf-8")
    LOG.info("Đã ghi báo cáo: %s", report_path)


# ─────────────────────────── main ───────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Tải và kiểm tra toàn vẹn dataset ViFinQA (không xử lý dữ liệu).")
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST,
                    help=f"Thư mục đích (mặc định: {DEFAULT_DEST})")
    ap.add_argument("--report", type=Path, default=None,
                    help="Đường dẫn file báo cáo (mặc định: <dest>/dataset_report.md)")
    ap.add_argument("--skip-github", action="store_true",
                    help="Bỏ qua clone codebase companion")
    ap.add_argument("--verify-only", action="store_true",
                    help="Chỉ kiểm kê dữ liệu đã có, không tải")
    ap.add_argument("-v", "--verbose", action="store_true", help="Log chi tiết")
    args = ap.parse_args()

    dest: Path = args.dest.expanduser().resolve()
    report_path: Path = args.report or (dest / "dataset_report.md")

    log_path = setup_logging(dest, args.verbose)
    LOG.info("=" * 70)
    LOG.info("ViFinQA — tải & kiểm tra toàn vẹn")
    LOG.info("Python %s | đích: %s", sys.version.split()[0], dest)
    LOG.info("=" * 70)

    hf_meta: dict[str, Any] = {}
    gh_meta: dict[str, Any] = {"ok": False, "error": "bỏ qua"}

    if args.verify_only:
        LOG.info("Chế độ --verify-only: bỏ qua bước tải.")
    else:
        try:
            hf_meta = download_hf_dataset(dest)
        except Exception as exc:
            LOG.exception("Tải dataset thất bại: %s", exc)
            return 2
        if not args.skip_github:
            gh_meta = clone_github(dest)

    try:
        inv = inspect(dest)
    except Exception as exc:
        LOG.exception("Kiểm kê thất bại: %s", exc)
        return 3

    checks = cross_check(inv)
    write_report(dest, report_path, inv, checks, hf_meta, gh_meta, log_path)

    n_ok = sum(1 for c in checks if c["ok"])
    LOG.info("-" * 70)
    for c in checks:
        LOG.info("%s %-34s card=%-8s thực tế=%s",
                 "OK  " if c["ok"] else "SAI ", c["item"], c["expected"], c["actual"])
    LOG.info("-" * 70)
    LOG.info("Kết quả: %d/%d mục khớp | %d lỗi | %d cảnh báo",
             n_ok, len(checks), len(inv["errors"]), len(inv["warnings"]))
    LOG.info("Báo cáo: %s", report_path)

    if n_ok != len(checks) or inv["errors"]:
        LOG.warning("CÓ SAI LỆCH — xem mục 6 và 7 của báo cáo.")
        return 1
    LOG.info("ĐẠT — dữ liệu khớp hoàn toàn với Dataset Card.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
