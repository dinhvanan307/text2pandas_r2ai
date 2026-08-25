"""Dựng GOLD ĐẠI DIỆN cho bảng, không dùng S1.

VÌ SAO CẦN
----------
`questions.jsonl` không có gold table, và thể lệ nói rõ BTC không phát tập
train/dev nào. Không có gold thì `Recall@K` không tính được, và mọi tối ưu
truy hồi là mò.

VÌ SAO KHÔNG VÒNG TRÒN
----------------------
Cạm bẫy hiển nhiên: dùng chính S1+S2 để dựng gold rồi đo S1+S2 trên đó — số
sẽ đẹp và vô nghĩa. Nên gold ở đây dựng bằng **quét vét cạn toàn bộ Silver**:

    tìm ô có nhãn khớp cụm chỉ tiêu VÀ kỳ khớp năm hỏi
    → KHÔNG lọc theo mã, KHÔNG lọc theo scope, KHÔNG xếp hạng, KHÔNG cắt top-K
    → rồi mới kiểm mã của bảng tìm được có khớp câu hỏi không

Nhờ vậy bộ lọc cứng S1 **không tham gia** dựng gold, và ta đo được đúng thứ
cần đo: S1 có âm thầm loại mất bảng đúng không, và S2 có xếp nó lên cao không.

GIỚI HẠN PHẢI KHAI
------------------
Đây là gold ĐẠI DIỆN, không phải gold thật:

  · nó chỉ tìm được bảng cho câu mà cụm chỉ tiêu xuất hiện gần nguyên văn
    trong nhãn dòng — câu cần suy luận nhiều bước sẽ không có gold;
  · nó có thể trả nhiều bảng, trong đó chỉ một là bảng BTC coi là vàng;
  · nó KHÔNG đo được câu hỏi phái sinh (tỷ lệ, tăng trưởng) vì Silver không
    lưu giá trị phái sinh.

Nên mọi con số đo trên nó phải đọc là "trên tập con đo được", không phải
"trên toàn đề". Tập con đó vẫn đủ lớn để hướng dẫn tối ưu.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from text2pandas.pipelines.retrieval.query_terms import content_terms

__all__ = ["ProxyGold", "build_proxy_gold"]


@dataclass(frozen=True, slots=True)
class ProxyGold:
    qid: int
    tables: frozenset[str]        # table_uid có ô khớp
    docs: frozenset[str]
    n_cells: int
    how: str                      # phrase | terms | none
    note: str = ""


def _phrase_match(conn, phrase: str, period_ends: tuple[str, ...],
                  tickers: frozenset[str] = frozenset(),
                  limit: int = 400) -> list[tuple[str, str]]:
    """Quét FTS trên `row_labels` cho CỤM, không giới hạn mã hay tài liệu."""
    sql = ("SELECT t.table_uid, t.doc_id FROM table_cards_fts f "
           "JOIN table_cards t ON t.rowid=f.rowid "
           "WHERE table_cards_fts MATCH ? ")
    mt = f'row_labels : "{phrase}"'
    if tickers:
        mt = "(" + " OR ".join(f"ticker : {t}" for t in sorted(tickers)) + ") AND " + mt
    args: list = [mt]
    if period_ends:
        sql += " AND (" + " OR ".join("t.periods LIKE ?" for _ in period_ends) + ")"
        args += [f"%{p}%" for p in period_ends]
    sql += f" LIMIT {limit}"
    try:
        return conn.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []


def build_proxy_gold(conn, qid: int, question: str, tickers: frozenset[str],
                     years: tuple[int, ...], alias: dict,
                     explicit_scope: str | None = None) -> ProxyGold:
    period_ends = tuple(f"{y}-12-31" for y in years)
    drop = tuple(n for t in tickers for n in alias.get(t, [])) + tuple(tickers)
    terms = content_terms(question, drop=drop)
    if not terms:
        return ProxyGold(qid, frozenset(), frozenset(), 0, "none", "khong co tu noi dung")

    # Thử cụm dài nhất trước, ngắn dần — cụm dài khớp thì gold sạch hơn nhiều.
    for n in range(min(4, len(terms)), 1, -1):
        for i in range(len(terms) - n + 1):
            phrase = " ".join(terms[i:i + n])
            hits = _phrase_match(conn, phrase, period_ends, tickers)
            if not hits:
                continue
            # CHỈ TỚI ĐÂY mới xét mã — bộ lọc cứng S1 không tham gia ở trên.
            keep = [(u, d) for u, d in hits
                    if not tickers or any(d.startswith(t + "_") for t in tickers)]
            # Scope chỉ áp khi câu hỏi NÓI RÕ ("công ty mẹ" / "hợp nhất").
            # Không áp mặc định — mặc định `hợp nhất` là quyết định của S1, và
            # nhét nó vào gold là đo S1 bằng chính S1.
            if explicit_scope:
                hau = "_separate" if explicit_scope == "công ty mẹ" else "_consolidated"
                loc = [(u, d) for u, d in keep if d.endswith(hau)]
                if loc:
                    keep = loc
            if keep:
                return ProxyGold(qid, frozenset(u for u, _ in keep),
                                 frozenset(d for _, d in keep), len(keep),
                                 "phrase", phrase)
    return ProxyGold(qid, frozenset(), frozenset(), 0, "none", "khong khop cum nao")
