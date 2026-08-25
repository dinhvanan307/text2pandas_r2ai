"""Chỉ mục truy hồi bảng — SQLite FTS5.

Vì sao FTS5 chứ không phải embedding: bài toán này là **grounding trên bảng**,
không phải tìm ý nghĩa xa. Nhãn chỉ tiêu trong câu hỏi gần như trùng nguyên
văn nhãn trong bảng ("Lãi tiền gửi", "Lưu chuyển tiền thuần từ hoạt động kinh
doanh"). Từ vựng thắng ngữ nghĩa ở đây, chạy trong bộ nhớ máy cá nhân, không
cần GPU và không có ràng buộc model. Embedding chỉ nên thêm vào khi đo được là
lexical đang hụt — không phải trước đó.

`remove_diacritics 2` giúp khớp cả khi câu hỏi và corpus gõ dấu khác nhau.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from text2pandas.infrastructure.parsing.html_table import parse_table_html

__all__ = ["TableHit", "build_index", "build_card_index", "search_tables", "STOPWORDS"]

# Từ quá phổ biến trong BCTC — giữ lại chỉ làm loãng điểm BM25.
STOPWORDS = {
    "là", "bao", "nhiêu", "của", "và", "trong", "năm", "cho", "các", "có",
    "được", "tại", "với", "từ", "đến", "theo", "về", "một", "những", "này",
    "công", "ty", "đồng", "tỷ", "triệu", "nghìn", "vnd", "hỏi", "cuối", "đầu",
}

_TOKEN = re.compile(r"[0-9A-Za-zÀ-ỹ]+", re.UNICODE)

_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS table_fts USING fts5(
    body,
    doc_id UNINDEXED,
    line_no UNINDEXED,
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS table_meta (
    doc_id   TEXT NOT NULL,
    line_no  INTEGER NOT NULL,
    n_rows   INTEGER NOT NULL,
    n_cols   INTEGER NOT NULL,
    n_numeric INTEGER NOT NULL,
    unit_exponent INTEGER,
    PRIMARY KEY (doc_id, line_no)
);
"""

# Đơn vị khai báo trong tiêu đề bảng -> số mũ 10.
_UNIT_HINTS: tuple[tuple[str, int], ...] = (
    ("nghìn tỷ", 12), ("tỷ vnd", 9), ("tỷ đồng", 9), ("tỉ đồng", 9),
    ("triệu vnd", 6), ("triệu đồng", 6), ("triệu", 6),
    ("nghìn vnd", 3), ("nghìn đồng", 3), ("ngàn đồng", 3),
)


@dataclass(slots=True)
class TableHit:
    doc_id: str
    line_no: int
    score: float
    n_rows: int
    n_cols: int
    unit_exponent: int | None

    @property
    def locator(self) -> str:
        return f"{self.doc_id}|{self.line_no}"


def tokenize(text: str) -> list[str]:
    return [
        t for t in (m.group(0).lower() for m in _TOKEN.finditer(text))
        if len(t) > 1 and t not in STOPWORDS
    ]


def _unit_exponent(text: str) -> int | None:
    low = text.lower()
    for pat, exp in _UNIT_HINTS:
        if pat in low:
            return exp
    return None


def build_index(catalog_db: Path, index_db: Path, progress=None) -> dict[str, float]:
    t0 = time.time()
    index_db.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{catalog_db}?mode=ro", uri=True)
    dst = sqlite3.connect(index_db)
    dst.executescript("PRAGMA journal_mode=MEMORY;PRAGMA synchronous=OFF;" + _SCHEMA)

    n = n_fail = 0
    buf_fts: list[tuple[str, str, int]] = []
    buf_meta: list[tuple] = []
    cur = src.execute("SELECT doc_id_stripped, line_no_1based, raw_html FROM tables")
    for doc_id, line_no, html in cur:
        grid = parse_table_html(html)
        if not grid.ok:
            n_fail += 1
            continue
        flat = grid.flat_text()
        n_numeric = sum(
            1 for row in grid.cells for c in row if c and any(ch.isdigit() for ch in c)
        )
        buf_fts.append((" ".join(tokenize(flat)), doc_id, line_no))
        buf_meta.append(
            (doc_id, line_no, grid.n_rows, grid.n_cols, n_numeric, _unit_exponent(flat))
        )
        n += 1
        if len(buf_fts) >= 5000:
            dst.executemany("INSERT INTO table_fts(body,doc_id,line_no) VALUES(?,?,?)", buf_fts)
            dst.executemany("INSERT OR REPLACE INTO table_meta VALUES(?,?,?,?,?,?)", buf_meta)
            dst.commit()
            buf_fts.clear()
            buf_meta.clear()
            if progress:
                progress(n)
    if buf_fts:
        dst.executemany("INSERT INTO table_fts(body,doc_id,line_no) VALUES(?,?,?)", buf_fts)
        dst.executemany("INSERT OR REPLACE INTO table_meta VALUES(?,?,?,?,?,?)", buf_meta)
    dst.commit()
    dst.close()
    src.close()
    return {"indexed": n, "failed": n_fail, "seconds": round(time.time() - t0, 1)}


def _fts_query(tokens: list[str]) -> str:
    # OR để không bỏ sót; BM25 lo phần xếp hạng.
    return " OR ".join(f'"{t}"' for t in dict.fromkeys(tokens) if t)


def search_tables(
    conn: sqlite3.Connection,
    tokens: list[str],
    doc_ids: list[str],
    limit: int = 40,
) -> list[TableHit]:
    if not tokens or not doc_ids:
        return []
    q = _fts_query(tokens)
    if not q:
        return []
    placeholders = ",".join("?" * len(doc_ids))
    sql = f"""
        SELECT f.doc_id, f.line_no, bm25(table_fts) AS s,
               m.n_rows, m.n_cols, m.unit_exponent
        FROM table_fts f
        JOIN table_meta m ON m.doc_id = f.doc_id AND m.line_no = f.line_no
        WHERE table_fts MATCH ? AND f.doc_id IN ({placeholders}) AND m.n_numeric > 0
        ORDER BY s LIMIT ?
    """
    rows = conn.execute(sql, [q, *doc_ids, limit]).fetchall()
    # bm25() của SQLite: càng ÂM càng khớp. Đổi dấu cho trực giác.
    return [TableHit(d, ln, -s, nr, nc, ue) for d, ln, s, nr, nc, ue in rows]


_CARD_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS card_fts USING fts5(
    body,
    doc_id UNINDEXED,
    line_no UNINDEXED,
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS card_meta (
    doc_id TEXT NOT NULL,
    line_no INTEGER NOT NULL,
    statement_type TEXT NOT NULL,
    is_data_table INTEGER NOT NULL,
    unit_exponent INTEGER NOT NULL,
    n_rows INTEGER NOT NULL,
    n_cols INTEGER NOT NULL,
    PRIMARY KEY (doc_id, line_no)
);
"""


def build_card_index(silver_db, index_db, progress=None) -> dict:
    """Dựng FTS5 trên Table Card thay vì văn bản phẳng của bảng.

    Index cũ có 44% token là số — chúng không bao giờ khớp câu hỏi nhưng làm
    BM25 phạt độ dài các bảng tài chính. Card chỉ chứa chữ.
    """
    import sqlite3 as _sq
    import time as _t

    from text2pandas.infrastructure.retrieval.table_card import build_card

    t0 = _t.time()
    index_db.unlink(missing_ok=True)
    src = _sq.connect(f"file:{silver_db}?mode=ro", uri=True)
    dst = _sq.connect(index_db)
    dst.executescript("PRAGMA journal_mode=MEMORY;PRAGMA synchronous=OFF;" + _CARD_SCHEMA)

    rows = src.execute(
        "SELECT doc_id, line_no, ticker, doc_year, basis, statement_type,"
        " is_data_table, unit_exponent, unit_raw, years, col_labels, context,"
        " n_rows, n_cols FROM table_features"
    )
    buf_f, buf_m = [], []
    n = 0
    for (doc_id, line_no, ticker, year, basis, stype, is_data, uexp, uraw,
         years, col_labels, ctx, nr, nc) in rows:
        # Dùng row_path chứ không phải row_label: nhãn phẳng có 39,9% số ô
        # trùng khoá qua hơn 200 bảng, đường dẫn kéo con số đó xuống 9,9%.
        labels = src.execute(
            "SELECT DISTINCT row_path FROM cells WHERE doc_id=? AND line_no=? LIMIT 200",
            (doc_id, line_no),
        ).fetchall()
        card = build_card(
            statement_type=stype, ticker=ticker, doc_year=year, basis=basis,
            years=[int(y) for y in years.split(",") if y],
            context=ctx or "",
            row_labels=[r[0] for r in labels],
            col_labels=(col_labels or "").split(" | "),
            unit_raw=uraw or "",
        )
        buf_f.append((" ".join(tokenize(card)), doc_id, line_no))
        buf_m.append((doc_id, line_no, stype, is_data, uexp, nr, nc))
        n += 1
        if len(buf_f) >= 5000:
            dst.executemany("INSERT INTO card_fts(body,doc_id,line_no) VALUES(?,?,?)", buf_f)
            dst.executemany("INSERT OR REPLACE INTO card_meta VALUES(?,?,?,?,?,?,?)", buf_m)
            dst.commit()
            buf_f.clear()
            buf_m.clear()
            if progress:
                progress(n)
    if buf_f:
        dst.executemany("INSERT INTO card_fts(body,doc_id,line_no) VALUES(?,?,?)", buf_f)
        dst.executemany("INSERT OR REPLACE INTO card_meta VALUES(?,?,?,?,?,?,?)", buf_m)
    dst.commit()
    dst.close()
    src.close()
    return {"cards": n, "seconds": round(_t.time() - t0, 1)}


def search_cards(conn, tokens, doc_ids, limit=40, data_only=True):
    """Truy hồi trên chỉ mục Card. `data_only` loại mục lục/nhân sự/danh sách."""
    if not tokens or not doc_ids:
        return []
    q = _fts_query(tokens)
    if not q:
        return []
    ph = ",".join("?" * len(doc_ids))
    sql = f"""
        SELECT f.doc_id, f.line_no, bm25(card_fts) AS s,
               m.n_rows, m.n_cols, m.unit_exponent
        FROM card_fts f
        JOIN card_meta m ON m.doc_id = f.doc_id AND m.line_no = f.line_no
        WHERE card_fts MATCH ? AND f.doc_id IN ({ph})
              {"AND m.is_data_table = 1" if data_only else ""}
        ORDER BY s LIMIT ?
    """
    rows = conn.execute(sql, [q, *doc_ids, limit]).fetchall()
    return [TableHit(d, ln, -s, nr, nc, ue) for d, ln, s, nr, nc, ue in rows]
