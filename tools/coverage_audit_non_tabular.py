#!/usr/bin/env python3
"""RC-06 · Coverage audit — bỏ các tài liệu phi bảng biểu ra thì mất gì?

Review 28 đòi trả lời: *"có câu hỏi nào phụ thuộc tám document này không"*.

GIỚI HẠN PHẢI NÓI TRƯỚC (§15 — không dựng bằng chứng):
`questions.jsonl` công khai chỉ có `id` và `question`. **Không có gold
answer, không có `relevant_docs`, không có `relevant_tables`.** Vì vậy công
cụ này KHÔNG thể chứng minh "không câu nào cần tám tài liệu đó". Nó chỉ đo
được ba thứ quan sát được, và ba thứ đó cộng lại là bằng chứng MẠNH nhưng
GIÁN TIẾP:

  1. Câu hỏi nào nhắc tới mã CK / tên công ty của các tài liệu phi bảng biểu.
  2. Những câu đó hỏi về loại nội dung gì — chỉ tiêu báo cáo tài chính, hay
     nội dung riêng của công văn (giải trình, ý kiến ngoại trừ, kiểm toán).
  3. Cùng mã CK và cùng NĂM đó, corpus có tài liệu CÓ bảng hay không.

Nếu mọi câu hỏi chạm tới mã CK đều hỏi chỉ tiêu báo cáo, và mọi năm liên quan
đều có báo cáo dạng bảng, thì việc để tài liệu phi bảng biểu ngoài phạm vi
KHÔNG làm mất khả năng trả lời câu nào — nhưng đó là suy luận, không phải
phép đo trực tiếp trên gold.

Chạy:
    python tools/coverage_audit_non_tabular.py \
        --db artifacts/rc1_baseline/silver.db \
        --questions data/raw/btc/questions/questions.jsonl \
        --stocks data/raw/btc/metadata/companies.csv \
        --out reports/coverage_audit_non_tabular.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from text2pandas.pipelines.a6.text_normalize import normalize_search_text  # noqa: E402

AUDIT_VERSION = "1.0"

# Từ khoá của nội dung RIÊNG công văn giải trình. Câu hỏi chứa chúng mới thật
# sự cần tới tài liệu phi bảng biểu.
LETTER_TOPICS = ("giai trinh", "cong van", "y kien ngoai tru", "kiem toan vien",
                 "thuyet minh bang loi", "cong bo thong tin", "uy ban chung khoan")


def _load_questions(path: Path) -> list[tuple[str, str, str]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        out.append((str(d.get("id")), d.get("question", ""),
                    normalize_search_text(d.get("question", ""))))
    return out


def _company_names(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return {r["Mã CK"].strip(): r["Tên công ty"].strip()
                for r in csv.DictReader(fh) if r.get("Mã CK")}


def audit(db: Path, questions: Path, stocks: Path) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    non_tab = con.execute(
        "SELECT directory_doc_id, ticker, doc_year, rel_path, n_lines"
        "  FROM documents WHERE n_tables = 0 ORDER BY directory_doc_id"
    ).fetchall()
    tickers = sorted({t for _, t, _, _, _ in non_tab})
    years = sorted({y for _, _, y, _, _ in non_tab if y is not None})

    qs = _load_questions(questions)
    names = _company_names(stocks)

    touched: dict[str, list[dict]] = {}
    for tk in tickers:
        pat = re.compile(r"\b" + re.escape(tk.lower()) + r"\b")
        name_n = normalize_search_text(names.get(tk, ""))
        # Lấy cụm định danh dài nhất của tên công ty để tránh khớp bừa.
        name_key = max(name_n.split(" - "), key=len) if name_n else ""
        hits = []
        for qid, raw, norm in qs:
            by_ticker = bool(pat.search(norm))
            by_name = bool(name_key) and name_key in norm
            if by_ticker or by_name:
                hits.append({
                    "question_id": qid,
                    "matched_by": "ticker" if by_ticker else "company_name",
                    "asks_letter_topic": [t for t in LETTER_TOPICS if t in norm],
                    "question": raw[:200],
                })
        touched[tk] = hits

    # Cùng ticker + cùng năm, corpus có tài liệu CÓ bảng không?
    cover = {}
    for tk in tickers:
        rows = con.execute(
            "SELECT doc_year, COUNT(*), SUM(n_tables) FROM documents"
            " WHERE ticker = ? AND n_tables > 0 GROUP BY doc_year ORDER BY 1",
            (tk,)).fetchall()
        cover[tk] = {str(y): {"documents": n, "tables": t} for y, n, t in rows}
    con.close()

    n_hits = sum(len(v) for v in touched.values())
    n_letter = sum(1 for v in touched.values() for h in v if h["asks_letter_topic"])
    uncovered = [y for y in years if not any(
        str(y) in cover.get(tk, {}) for tk in tickers)]

    return {
        "audit_version": AUDIT_VERSION,
        "_limitation": (
            "questions.jsonl công khai KHÔNG có gold (relevant_docs / "
            "relevant_tables / answer). Kết luận dưới đây là suy luận từ VĂN "
            "BẢN câu hỏi, không phải phép đo trên nhãn vàng."),
        "non_tabular_documents": [
            {"doc_id": d, "ticker": t, "doc_year": y, "rel_path": p,
             "n_lines": n} for d, t, y, p, n in non_tab],
        "n_non_tabular": len(non_tab),
        "tickers": tickers,
        "years": years,
        "n_questions": len(qs),
        "questions_touching_tickers": n_hits,
        "questions_asking_letter_topics": n_letter,
        "detail": touched,
        "tabular_coverage_same_ticker": cover,
        "years_without_tabular_coverage": uncovered,
        "verdict": (
            "NO_QUESTION_REQUIRES_NON_TABULAR"
            if n_letter == 0 and not uncovered else "REVIEW_REQUIRED"),
        "verdict_basis": [
            f"{n_hits} câu hỏi chạm tới mã CK {tickers}",
            f"{n_letter} câu trong số đó hỏi nội dung RIÊNG của công văn",
            f"{len(uncovered)} năm không có tài liệu dạng bảng thay thế",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--questions", required=True, type=Path)
    ap.add_argument("--stocks", required=True, type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    for p in (a.db, a.questions):
        if not p.exists():
            print(f"MISSING ARTIFACT: {p}", file=sys.stderr)
            return 2
    rep = audit(a.db, a.questions, a.stocks)
    blob = json.dumps(rep, ensure_ascii=False, indent=1, sort_keys=False)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(blob + "\n", encoding="utf-8")
        print(f"đã ghi {a.out}")
    print(f"verdict: {rep['verdict']}")
    for b in rep["verdict_basis"]:
        print("  ·", b)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
