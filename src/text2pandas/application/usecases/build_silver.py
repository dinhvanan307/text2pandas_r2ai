"""Bronze -> Silver: một lần quét, sinh ra đặc trưng bảng + ô định dạng dài.

Trước module này mọi thí nghiệm đều phải parse lại 146.246 bảng từ HTML rồi
vứt đi. Silver giữ kết quả lại, nên vòng lặp thử nghiệm sau đó tính bằng giây
thay vì phút — và đó mới là thứ quyết định tốc độ cải thiện trong 29 ngày.

Quét theo TÀI LIỆU chứ không theo bảng, vì đặc trưng của một bảng phụ thuộc
vào những dòng phía trên nó (khai báo đơn vị, tiêu đề thuyết minh).
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from text2pandas.domain.rules.row_path import build_row_paths, extract_section
from text2pandas.domain.rules.table_features import extract_features
from text2pandas.domain.values.vn_number import (
    ParseStatus,
    SepConvention,
    parse_vn_number,
)
from text2pandas.infrastructure.parsing.html_table import parse_table_html

__all__ = ["SilverReport", "build_silver", "SILVER_SCHEMA"]

_PAGE = re.compile(r"^===== PAGE \d+ =====$")
_CONTEXT_LINES = 8

SILVER_SCHEMA = """
PRAGMA journal_mode=MEMORY;
PRAGMA synchronous=OFF;

CREATE TABLE IF NOT EXISTS table_features (
    doc_id          TEXT NOT NULL,
    line_no         INTEGER NOT NULL,
    ticker          TEXT NOT NULL,
    doc_year        INTEGER,
    basis           TEXT,
    statement_type  TEXT NOT NULL,
    is_data_table   INTEGER NOT NULL,
    numeric_ratio   REAL NOT NULL,
    unit_exponent   INTEGER NOT NULL,
    unit_source     TEXT NOT NULL,
    unit_raw        TEXT,
    sep_convention  TEXT NOT NULL,
    n_rows          INTEGER NOT NULL,
    n_cols          INTEGER NOT NULL,
    ma_so_col       INTEGER,
    years           TEXT,
    col_labels      TEXT,
    section         TEXT,
    context         TEXT,
    flags           TEXT,
    PRIMARY KEY (doc_id, line_no)
);

CREATE TABLE IF NOT EXISTS cells (
    doc_id      TEXT NOT NULL,
    line_no     INTEGER NOT NULL,
    row_idx     INTEGER NOT NULL,
    col_idx     INTEGER NOT NULL,
    row_label   TEXT NOT NULL,
    row_path    TEXT NOT NULL,
    col_label   TEXT NOT NULL,
    period_year INTEGER,
    ma_so       TEXT,
    value_raw   TEXT NOT NULL,
    value       TEXT NOT NULL,
    PRIMARY KEY (doc_id, line_no, row_idx, col_idx)
);

CREATE INDEX IF NOT EXISTS ix_tf_type  ON table_features(statement_type, is_data_table);
CREATE INDEX IF NOT EXISTS ix_tf_tick  ON table_features(ticker, doc_year);
CREATE INDEX IF NOT EXISTS ix_cell_tbl ON cells(doc_id, line_no);
CREATE INDEX IF NOT EXISTS ix_cell_path ON cells(row_path);
"""


@dataclass(slots=True)
class SilverReport:
    n_documents: int
    n_tables: int
    n_cells: int
    n_data_tables: int
    by_type: dict[str, int]
    by_unit_source: dict[str, int]
    n_with_period: int
    n_with_ma_so: int
    seconds: float


def _col_labels(grid, conv: SepConvention) -> list[str]:
    """Nhãn cột — ghép các dòng tiêu đề ở đầu bảng.

    Dòng tiêu đề của BCTC LUÔN chứa chữ số (`31/12/2015VND`, `Quý 4/2023`),
    nên tiêu chí phải là "parse được thành số", không phải "có chữ số".
    """
    labels = [""] * grid.n_cols
    for row in grid.cells[:3]:
        filled = [c for c in row if c.strip()]
        if not filled:
            continue
        numeric = sum(
            1 for c in filled if parse_vn_number(c, conv).status is ParseStatus.OK
        )
        if numeric > len(filled) // 2:
            break
        for i, c in enumerate(row):
            s = c.strip()
            if s and s not in labels[i]:
                labels[i] = (labels[i] + " " + s).strip()
    return [lab or f"c{i}" for i, lab in enumerate(labels)]


def _context_before(lines: list[str], line_no_1based: int) -> str:
    """Mấy dòng văn bản có nghĩa ngay trên bảng."""
    out: list[str] = []
    i = line_no_1based - 2
    while i >= 0 and len(out) < _CONTEXT_LINES:
        ln = lines[i].strip()
        i -= 1
        if not ln or ln.startswith("<table") or _PAGE.match(ln):
            continue
        out.append(ln)
    return " ".join(reversed(out))


def build_silver(
    catalog_db: Path, corpus_root: Path, silver_db: Path, progress=None,
    offset: int = 0, limit: int = 0,
) -> SilverReport:
    # Phân lô theo TÀI LIỆU: tiến trình nền trên máy chạy bị giết sau ~45 giây
    # (ADR-028), toàn bộ 1.973 tài liệu mất khoảng gấp ba lần thế.
    t0 = time.time()
    if offset == 0:
        silver_db.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{catalog_db}?mode=ro", uri=True)
    dst = sqlite3.connect(silver_db)
    dst.executescript(SILVER_SCHEMA)

    docs = src.execute(
        "SELECT doc_id_stripped, rel_path, ticker, year,"
        " COALESCE(basis_from_text, basis_from_name) FROM documents ORDER BY doc_id_stripped"
    ).fetchall()
    docs = docs[offset:]
    if limit:
        docs = docs[:limit]

    n_tab = n_cell = n_data = 0
    by_type: dict[str, int] = {}
    by_unit: dict[str, int] = {}
    n_period = n_maso = 0
    buf_t: list[tuple] = []
    buf_c: list[tuple] = []

    for k, (doc_id, rel, ticker, year, basis) in enumerate(docs, 1):
        lines = (corpus_root / rel).read_text(encoding="utf-8").split("\n")
        tables = src.execute(
            "SELECT line_no_1based, raw_html FROM tables WHERE doc_id_stripped=?"
            " ORDER BY line_no_1based",
            (doc_id,),
        ).fetchall()

        for line_no, html in tables:
            grid = parse_table_html(html)
            if not grid.ok:
                continue
            conv = SepConvention.DOT_THOUSANDS
            labels = _col_labels(grid, conv)
            ctx = _context_before(lines, line_no)
            f = extract_features(grid, labels, ctx, year)
            conv = SepConvention(f.sep_convention)
            section = extract_section(ctx)
            numeric_row = [
                any(
                    cell.strip()
                    and parse_vn_number(cell, conv).status is ParseStatus.OK
                    for j, cell in enumerate(row)
                    if j != f.ma_so_col
                )
                for row in grid.cells
            ]
            header_n = 0
            for r_i, row in enumerate(grid.cells[:3]):
                fl = [x for x in row if x.strip()]
                if not fl:
                    continue
                nm = sum(
                    1 for x in fl if parse_vn_number(x, conv).status is ParseStatus.OK
                )
                if nm > len(fl) // 2:
                    break
                header_n = r_i + 1
            paths = build_row_paths(grid.cells, numeric_row, section, header_n)

            n_tab += 1
            n_data += f.is_data_table
            by_type[f.statement_type] = by_type.get(f.statement_type, 0) + 1
            by_unit[f.unit_source] = by_unit.get(f.unit_source, 0) + 1
            n_period += bool(f.years)
            n_maso += f.ma_so_col is not None

            buf_t.append((
                doc_id, line_no, ticker, year, basis, f.statement_type,
                int(f.is_data_table), f.numeric_ratio, f.unit_exponent,
                f.unit_source, f.unit_raw, f.sep_convention, grid.n_rows,
                grid.n_cols, f.ma_so_col,
                ",".join(str(y) for y in f.years),
                " | ".join(labels), section, f.context, ",".join(f.flags),
            ))

            if not f.is_data_table:
                continue  # không lưu ô của bảng phi dữ liệu — nhiễu thuần

            year_by_col = {c.idx: c.year for c in f.columns}
            for ri, row in enumerate(grid.cells):
                rl = ""
                ms = ""
                for cell in row:
                    s = cell.strip()
                    if s and parse_vn_number(s, conv).status is not ParseStatus.OK:
                        rl = s
                        break
                if f.ma_so_col is not None and f.ma_so_col < len(row):
                    ms = row[f.ma_so_col].strip()
                if not rl:
                    continue
                for ci, cell in enumerate(row):
                    if not cell.strip() or ci == f.ma_so_col:
                        continue
                    # Cột "Thuyết minh" chứa SỐ HIỆU tham chiếu (5.1, 12), không
                    # phải giá trị tài chính. 97.861 ô đang lẫn vào — hệ thống có
                    # thể trả lời "5.1" cho câu hỏi về tiền mặt.
                    if ci < len(f.columns) and f.columns[ci].is_note_ref:
                        continue
                    p = parse_vn_number(cell, conv)
                    if p.status is not ParseStatus.OK or p.value is None:
                        continue
                    buf_c.append((
                        doc_id, line_no, ri, ci, rl,
                        paths[ri].text() if ri < len(paths) else rl,
                        labels[ci] if ci < len(labels) else f"c{ci}",
                        year_by_col.get(ci), ms, cell, str(p.value),
                    ))
                    n_cell += 1

        if len(buf_t) >= 400:
            dst.executemany(
                "INSERT OR REPLACE INTO table_features VALUES (" + ",".join("?" * 20) + ")",
                buf_t)
            dst.executemany(
                "INSERT OR REPLACE INTO cells VALUES (" + ",".join("?" * 11) + ")", buf_c)
            dst.commit()
            buf_t.clear()
            buf_c.clear()
            if progress:
                progress(k, n_tab, n_cell)

    if buf_t:
        dst.executemany(
            "INSERT OR REPLACE INTO table_features VALUES (" + ",".join("?" * 20) + ")", buf_t)
    if buf_c:
        dst.executemany(
            "INSERT OR REPLACE INTO cells VALUES (" + ",".join("?" * 11) + ")", buf_c)
    dst.commit()
    dst.close()
    src.close()

    return SilverReport(
        n_documents=len(docs), n_tables=n_tab, n_cells=n_cell,
        n_data_tables=n_data, by_type=by_type, by_unit_source=by_unit,
        n_with_period=n_period, n_with_ma_so=n_maso,
        seconds=round(time.time() - t0, 1),
    )
