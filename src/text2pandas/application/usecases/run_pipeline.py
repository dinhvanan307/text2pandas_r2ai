"""Use case: chạy toàn bộ pipeline cho 1.012 câu hỏi -> ZIP bài nộp."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from text2pandas.application.usecases.answer import (
    AnswerResult,
    answer_question,
    write_long_csv,
)
from text2pandas.domain.rules.question import CompanyIndex, parse_question
from text2pandas.infrastructure.retrieval.index import search_cards, search_tables, tokenize

__all__ = ["PipelineReport", "run_pipeline"]


@dataclass(slots=True)
class PipelineReport:
    n_questions: int
    n_with_ticker: int
    n_with_year: int
    n_retrieved: int
    n_answered: int
    n_zero_docs: int
    seconds: float
    ticker_sources: dict[str, int]
    results: list[AnswerResult]


def _candidate_docs(
    cat: sqlite3.Connection, tickers: list[str], years: list[int], basis: str | None
) -> list[str]:
    """Lọc tài liệu ứng viên.

    Báo cáo năm Y chứa cả cột năm Y và Y-1, nên câu hỏi về năm Y có thể được
    trả lời bởi tài liệu năm Y **hoặc** Y+1. Không thu hẹp sớm hơn thế.
    """
    if not tickers:
        return []
    q = "SELECT doc_id_stripped, basis_from_name, basis_from_text, year FROM documents WHERE ticker IN ({})".format(
        ",".join("?" * len(tickers))
    )
    rows = cat.execute(q, tickers).fetchall()
    if years:
        lo, hi = min(years), max(years) + 1
        rows = [r for r in rows if r[3] is not None and lo <= r[3] <= hi]
    if basis:
        matched = [r for r in rows if (r[2] or r[1]) == basis]
        if matched:
            rows = matched
    return [r[0] for r in rows]


def run_pipeline(
    catalog_db: Path,
    index_db: Path,
    questions_path: Path,
    code_stock_csv: Path,
    data_dir: Path,
    records_path: Path,
    offset: int = 0,
    limit: int = 0,
    n_tables: int = 20,
    n_docs: int = 5,
    progress=None,
) -> PipelineReport:
    # CSV được ghi NGAY trong vòng lặp. Giữ `csv_rows` của cả 1.012 câu trong
    # RAM làm tiến trình bị OOM giết im lặng ở khoảng câu 500 trên máy 3 GB —
    # không log, không traceback. Ghi rồi giải phóng là cách rẻ nhất để tránh.
    data_dir.mkdir(parents=True, exist_ok=True)
    written: set[str] = set()
    t0 = time.time()
    cat = sqlite3.connect(f"file:{catalog_db}?mode=ro", uri=True)
    idx = sqlite3.connect(f"file:{index_db}?mode=ro", uri=True)

    known = {r[0] for r in cat.execute("SELECT DISTINCT ticker FROM documents")}
    companies = CompanyIndex.from_csv(code_stock_csv)

    questions = [
        json.loads(line) for line in questions_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    questions = questions[offset:]
    if limit:
        questions = questions[:limit]
    # Ghi từng bản ghi ra JSONL ngay khi có. Tiến trình nền trên máy này bị
    # giết sau ~45–60 giây nên chạy một mạch 1.012 câu là không khả thi; điểm
    # lưu biến việc đó thành nhiều lô nối tiếp, và tự nhiên cho khả năng resume.
    records_path.parent.mkdir(parents=True, exist_ok=True)
    fh = records_path.open("a", encoding="utf-8")

    results: list[AnswerResult] = []
    n_tick = n_year = n_ret = n_ans = n_zero = 0
    sources: dict[str, int] = {}

    for i, q in enumerate(questions, 1):
        slots = parse_question(q["id"], q["question"], companies, known)
        sources[slots.ticker_source] = sources.get(slots.ticker_source, 0) + 1
        n_tick += bool(slots.tickers)
        n_year += bool(slots.years)

        docs = _candidate_docs(cat, slots.tickers, slots.years, slots.basis)
        if not docs:
            n_zero += 1
            miss = AnswerResult(slots.qid, 0.0, [], [], [], "", 0.0,
                                notes=["không có tài liệu ứng viên"])
            fh.write(json.dumps({
                "qid": miss.qid, "answer": 0.0, "relevant_docs": [],
                "relevant_tables": [], "evidence": [], "pandas_query": "",
                "confidence": 0.0, "csv_name": "", "has_csv": False,
                "notes": miss.notes}, ensure_ascii=False) + "\n")
            results.append(miss)
            continue

        hits = search_cards(idx, tokenize(slots.text), docs, limit=max(25, n_tables * 2))
        if hits:
            n_ret += 1
        locators = [h.locator for h in hits[:5]]
        html = {}
        if locators:
            for loc in locators:
                d, _, ln = loc.rpartition("|")
                row = cat.execute(
                    "SELECT raw_html FROM tables WHERE doc_id_stripped=? AND line_no_1based=?",
                    (d, int(ln)),
                ).fetchone()
                if row:
                    html[loc] = row[0]

        # Xếp hạng tài liệu: điểm bảng tốt nhất bên trong mỗi tài liệu; tài liệu
        # là ứng viên nhưng không có bảng nào trúng thì xếp cuối, vẫn giữ lại.
        best: dict[str, float] = {}
        for h in hits:
            if h.score > best.get(h.doc_id, -1e9):
                best[h.doc_id] = h.score
        ranked = sorted(best, key=lambda d: -best[d])
        ranked += [d for d in docs if d not in best]
        res = answer_question(slots, hits, html, n_tables=n_tables,
                              doc_ranking=ranked, n_docs=n_docs)
        if res.csv_rows and res.csv_name and res.csv_name not in written:
            write_long_csv(data_dir / res.csv_name, res.csv_rows)
            written.add(res.csv_name)
        res.has_csv = bool(res.csv_rows) or res.csv_name in written
        res.csv_rows = []
        n_ans += res.answer is not None
        fh.write(json.dumps({
            "qid": res.qid, "answer": res.answer,
            "relevant_docs": res.relevant_docs, "relevant_tables": res.relevant_tables,
            "evidence": res.evidence, "pandas_query": res.pandas_query,
            "confidence": res.confidence, "csv_name": res.csv_name,
            "has_csv": res.has_csv, "notes": res.notes,
        }, ensure_ascii=False) + "\n")
        results.append(res)
        if progress and i % 100 == 0:
            progress(i, n_ans)

    fh.close()
    cat.close()
    idx.close()
    return PipelineReport(
        n_questions=len(questions),
        n_with_ticker=n_tick,
        n_with_year=n_year,
        n_retrieved=n_ret,
        n_answered=n_ans,
        n_zero_docs=n_zero,
        seconds=round(time.time() - t0, 1),
        ticker_sources=sources,
        results=results,
    )
