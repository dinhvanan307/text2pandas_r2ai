"""Lưu catalog bằng SQLite.

Sai lệch có chủ đích so với CORPUS_CATALOG_SPEC [D-05] (Parquet): máy chạy
không có `pyarrow` và không có mạng để cài. SQLite là stdlib, một tệp duy
nhất, có chỉ mục và truy vấn được — đủ tốt cho ~148k dòng. Xem ADR-027.

`raw_html` được lưu vào catalog để tầng parse không phải mở lại 1.973 tệp cho
mỗi lần thử nghiệm. Đánh đổi: catalog nặng hơn (~250 MB) nhưng vòng lặp thí
nghiệm nhanh hơn nhiều lần.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from text2pandas.infrastructure.catalog.scanner import ScannedDocument

__all__ = ["CatalogStore", "SCHEMA_VERSION"]

SCHEMA_VERSION = 1

_SCHEMA = """
PRAGMA journal_mode=MEMORY;
PRAGMA synchronous=OFF;
PRAGMA temp_store=MEMORY;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id_stripped TEXT PRIMARY KEY,
    doc_id_literal  TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    year            INTEGER,
    basis_from_name TEXT,
    basis_from_text TEXT,
    report_type     TEXT NOT NULL,
    id_pattern      TEXT NOT NULL,
    duplicate_index INTEGER,
    is_explanatory  INTEGER NOT NULL,
    rel_path        TEXT NOT NULL,
    n_lines         INTEGER NOT NULL,
    n_bytes         INTEGER NOT NULL,
    n_pages         INTEGER NOT NULL,
    n_tables        INTEGER NOT NULL,
    sha256          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tables (
    doc_id_stripped TEXT NOT NULL,
    line_no_1based  INTEGER NOT NULL,
    line_no_0based  INTEGER NOT NULL,
    table_ordinal   INTEGER NOT NULL,
    page_no         INTEGER,
    char_offset     INTEGER NOT NULL,
    n_lines         INTEGER NOT NULL,
    n_chars         INTEGER NOT NULL,
    raw_html        TEXT NOT NULL,
    PRIMARY KEY (doc_id_stripped, line_no_1based)
);

CREATE TABLE IF NOT EXISTS pages (
    doc_id_stripped TEXT NOT NULL,
    page_no         INTEGER NOT NULL,
    line_start      INTEGER NOT NULL,
    PRIMARY KEY (doc_id_stripped, page_no)
);

CREATE INDEX IF NOT EXISTS ix_doc_ticker_year ON documents(ticker, year);
CREATE INDEX IF NOT EXISTS ix_tables_doc      ON tables(doc_id_stripped);
"""


class CatalogStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(_SCHEMA)
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
            (str(SCHEMA_VERSION),),
        )
        self.conn.commit()

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, value)
        )

    def write_documents(self, docs: Iterable[ScannedDocument]) -> int:
        n = 0
        for d in docs:
            i = d.identity
            self.conn.execute(
                "INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    i.doc_id_stripped, i.doc_id_literal, i.ticker, i.year,
                    i.basis, d.content_basis, i.report_type, i.id_pattern,
                    i.duplicate_index, int(d.is_explanatory), i.rel_path,
                    d.n_lines, d.n_bytes, d.n_pages, d.n_tables, d.sha256,
                ),
            )
            self.conn.executemany(
                "INSERT OR REPLACE INTO tables VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    (t.doc_id_stripped, t.line_no_1based, t.line_no_0based,
                     t.table_ordinal, t.page_no, t.char_offset, t.n_lines,
                     t.n_chars, t.raw_html)
                    for t in d.tables
                ],
            )
            self.conn.executemany(
                "INSERT OR REPLACE INTO pages VALUES (?,?,?)",
                [
                    (i.doc_id_stripped, p + 1, ls)
                    for p, ls in enumerate(d.page_line_starts)
                ],
            )
            n += 1
        self.conn.commit()
        return n

    def counts(self) -> dict[str, int]:
        cur = self.conn.cursor()
        out = {}
        for t in ("documents", "tables", "pages"):
            out[t] = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return out

    def close(self) -> None:
        self.conn.close()
