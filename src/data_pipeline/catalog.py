"""DP-004 — D1 Corpus Catalog: đăng ký document/page/table với multi-locator.

Bronze chỉ lưu giá trị QUAN SÁT ĐƯỢC. `basis_from_text`, `statement_type`,
`industry_class` là suy diễn và thuộc Silver — đưa chúng vào Bronze là biến
một phỏng đoán thành "sự thật".

Multi-locator (DI-08): `table_uid` là khoá nội bộ; `line_no`, `page_no`,
`table_ordinal`, `char_offset` được lưu **độc lập**. Định dạng locator nộp bài
do downstream dựng, data foundation không quyết định thay.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path

from data_pipeline.models import (
    DiscoveryStatus,
    DocumentRecord,
    StageStatus,
    TableRecord,
    make_uid,
)

__all__ = ["CatalogReport", "scan_document", "build_catalog", "CATALOG_VERSION"]

CATALOG_VERSION = "1.0"

_PAGE = re.compile(r"^===== PAGE (\d+) =====$")
_TABLE_OPEN = "<table"
_TABLE_CLOSE = "</table>"
_SUFFIX = "_extracted.txt"

_PATTERN_STD = re.compile(
    r"^(?P<ticker>[A-Z0-9]+)_financial_statements_(?P<year>\d{4})"
    r"(?:_(?P<basis>consolidated|separate|aggregated))?(?:_\d+)?$"
)
_PATTERN_ALT = re.compile(r"^(?P<ticker>[A-Z0-9]+)_(?P<year>\d{4})_[a-z_]+?(?:_\d+)?$")

# ── RC-06 · đo trên văn bản THÔ, trước khi bộ phân tích chạm vào ────────────
#
# `_TABLE_ANY` khác `_TABLE_OPEN` ở một điểm quyết định: nó KHÔNG đòi `<table`
# đứng đầu dòng. Bộ phân tích chỉ nhận bảng mở đầu dòng, nên một tệp có
# `<table` nằm giữa dòng cho `n_tables = 0` — trông y hệt tệp không có bảng
# nào. Đếm cả hai kiểu mới phân biệt được "ngoài phạm vi" với "parser bỏ sót".
_TABLE_ANY = re.compile(r"<table\b", re.I)
_NUM_TOKEN = re.compile(r"\d[\d.,]*")
# Phân nhóm nghìn kiểu Việt (`1.234.567`) hoặc kiểu Anh (`1,234,567`). Đây là
# dấu hiệu mạnh nhất của "con số tiền tệ" mà không cần phân tích ngữ nghĩa.
_GROUPED_NUM = re.compile(r"\d{1,3}(?:[.,]\d{3})+")


@dataclass(slots=True)
class CatalogReport:
    n_documents: int = 0
    n_tables: int = 0
    n_pages: int = 0
    n_no_markup: int = 0
    n_multiline: int = 0
    n_unclosed: int = 0
    n_failed: int = 0
    failures: list[tuple[str, str]] = None  # type: ignore[assignment]
    seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.failures is None:
            self.failures = []


def _parse_identity(stem: str, ticker_dir: str) -> tuple[str, int | None, str | None]:
    if m := _PATTERN_STD.match(stem):
        return m.group("ticker"), int(m.group("year")), m.group("basis")
    if m := _PATTERN_ALT.match(stem):
        return m.group("ticker"), int(m.group("year")), None
    return ticker_dir, None, None


def scan_document(
    path: Path, corpus_root: Path, corpus_id: str
) -> tuple[DocumentRecord, list[TableRecord], list[tuple[int, int, int]]]:
    """Quét một tài liệu. Trả (document, tables, pages)."""
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    lines = text.split("\n")

    rel = path.relative_to(corpus_root).as_posix()
    name = path.name
    literal_stem = name[:-4] if name.endswith(".txt") else name
    directory_doc_id = (
        name[: -len(_SUFFIX)] if name.endswith(_SUFFIX) else literal_stem
    )
    ticker_dir = rel.split("/", 1)[0] if "/" in rel else ""
    ticker, year, basis = _parse_identity(directory_doc_id, ticker_dir)

    document_uid = make_uid(corpus_id, rel)

    pages: list[tuple[int, int, int]] = []   # (page_no, line_start, char_start)
    tables: list[TableRecord] = []
    page_no: int | None = None
    ordinal_doc = 0
    ordinal_page = 0
    offset = 0
    i = 0
    n = len(lines)
    status = DiscoveryStatus.OK

    while i < n:
        line = lines[i]
        if m := _PAGE.match(line):
            page_no = int(m.group(1))
            ordinal_page = 0
            pages.append((page_no, i + 1, offset))
        elif line.startswith(_TABLE_OPEN):
            start_i, start_off = i, offset
            if line.endswith(_TABLE_CLOSE):
                html, end_i = line, i
            else:
                buf = [line]
                j = i + 1
                while j < n and _TABLE_CLOSE not in lines[j]:
                    buf.append(lines[j])
                    j += 1
                if j < n:
                    buf.append(lines[j])
                    end_i = j
                    status = DiscoveryStatus.MULTILINE
                else:
                    end_i = n - 1
                    status = DiscoveryStatus.UNCLOSED
                html = "\n".join(buf)
                for k in range(start_i + 1, min(end_i + 1, n)):
                    offset += len(lines[k].encode("utf-8")) + 1
                i = end_i
            tables.append(
                TableRecord(
                    table_uid=make_uid(document_uid, start_i + 1),
                    document_uid=document_uid,
                    line_start_1based=start_i + 1,
                    line_end_1based=end_i + 1,
                    line_start_0based=start_i,
                    table_ordinal_document=ordinal_doc,
                    table_ordinal_page=ordinal_page,
                    page_no=page_no,
                    char_start=start_off,
                    char_end=start_off + len(html.encode("utf-8")),
                    raw_html=html,
                    raw_html_sha256=hashlib.sha256(html.encode("utf-8")).hexdigest(),
                    discovery_status=(
                        DiscoveryStatus.MULTILINE if end_i > start_i
                        else DiscoveryStatus.OK
                    ),
                )
            )
            ordinal_doc += 1
            ordinal_page += 1
        offset += len(lines[i].encode("utf-8")) + 1
        i += 1

    if not tables:
        status = DiscoveryStatus.NO_MARKUP

    # RC-06 · ba số đo trên `text` GỐC. Đặt ở đây, cạnh nơi `n_tables` được
    # tính, để hai bên luôn nói về cùng một tệp — tách ra chỗ khác là mở đường
    # cho chúng lệch nhau.
    n_table_markup = len(_TABLE_ANY.findall(text))
    n_numeric_tokens = len(_NUM_TOKEN.findall(text))
    n_grouped_numbers = len(_GROUPED_NUM.findall(text))

    doc = DocumentRecord(
        document_uid=document_uid,
        literal_file_stem=literal_stem,
        directory_doc_id=directory_doc_id,
        ticker_path=ticker,
        year_path=year,
        basis_path=basis,
        rel_path=rel,
        n_bytes=len(raw),
        n_lines=len(lines),
        n_pages=len(pages),
        n_tables=len(tables),
        sha256=hashlib.sha256(raw).hexdigest(),
        corpus_id=corpus_id,
        scan_status=StageStatus.COMPLETED,
        discovery_status=status,
        n_table_markup=n_table_markup,
        n_numeric_tokens=n_numeric_tokens,
        n_grouped_numbers=n_grouped_numbers,
    )
    return doc, tables, pages


def build_catalog(
    corpus_root: Path, conn, corpus_id: str, offset: int = 0,
    limit: int = 0, progress=None,
) -> CatalogReport:
    from data_pipeline.models import canonical_json  # noqa: F401 — dùng ở meta

    t0 = time.time()
    rep = CatalogReport()
    files = sorted(corpus_root.rglob("*.txt"))
    files = files[offset:]
    if limit:
        files = files[:limit]

    buf_d, buf_t, buf_p = [], [], []
    for idx, path in enumerate(files, 1):
        try:
            doc, tables, pages = scan_document(path, corpus_root, corpus_id)
        except Exception as exc:  # noqa: BLE001 — cách ly lỗi theo tài liệu
            rep.n_failed += 1
            rep.failures.append((path.name, repr(exc)))
            continue

        rep.n_documents += 1
        rep.n_tables += len(tables)
        rep.n_pages += len(pages)
        rep.n_no_markup += doc.discovery_status is DiscoveryStatus.NO_MARKUP
        rep.n_multiline += sum(
            1 for t in tables if t.discovery_status is DiscoveryStatus.MULTILINE
        )
        rep.n_unclosed += doc.discovery_status is DiscoveryStatus.UNCLOSED

        buf_d.append((
            doc.document_uid, doc.literal_file_stem, doc.directory_doc_id,
            doc.ticker_path, doc.year_path, doc.basis_path, doc.rel_path,
            doc.n_bytes, doc.n_lines, doc.n_pages, doc.n_tables, doc.sha256,
            doc.corpus_id, doc.scan_status.value, doc.discovery_status.value,
            doc.n_table_markup, doc.n_numeric_tokens, doc.n_grouped_numbers,
        ))
        buf_t += [(
            t.table_uid, t.document_uid, t.line_start_1based, t.line_end_1based,
            t.line_start_0based, t.table_ordinal_document, t.table_ordinal_page,
            t.page_no, t.char_start, t.char_end, t.raw_html, t.raw_html_sha256,
            t.discovery_status.value,
        ) for t in tables]
        buf_p += [(
            make_uid(doc.document_uid, p[0]), doc.document_uid, p[0], p[1], None, p[2]
        ) for p in pages]

        if len(buf_d) >= 100:
            _flush(conn, buf_d, buf_t, buf_p)
            if progress:
                progress(idx, rep.n_tables)

    _flush(conn, buf_d, buf_t, buf_p)
    conn.commit()
    rep.seconds = round(time.time() - t0, 1)
    return rep


# RC-06 · CỘT được liệt kê TƯỜNG MINH.
#
# Bản trước chèn theo vị trí với số dấu hỏi viết cứng (`"?" * 15`). Khi RC-06
# thêm ba cột append-only vào `documents`, `build_catalog` đã nối thêm ba giá
# trị nhưng `_flush` vẫn giữ 15 — và 447 unit test đều xanh, vì không test nào
# chạy `build_catalog` thật. Chỉ smoke run trên corpus fixture mới lộ ra:
#
#     sqlite3.OperationalError: table documents has 18 columns but 15 values
#
# Liệt kê tên cột làm hai chuyện: lỗi kiểu này thành lỗi lúc SOẠN câu lệnh chứ
# không phải lúc chạy, và lần thêm cột sau không âm thầm lệch nữa.
_DOC_COLS = ("document_uid, literal_file_stem, directory_doc_id, ticker_path,"
             " year_path, basis_path, rel_path, n_bytes, n_lines, n_pages,"
             " n_tables, sha256, corpus_id, scan_status, discovery_status,"
             " n_table_markup, n_numeric_tokens, n_grouped_numbers")
_TAB_COLS = ("table_uid, document_uid, line_start_1based, line_end_1based,"
             " line_start_0based, table_ordinal_document, table_ordinal_page,"
             " page_no, char_start, char_end, raw_html, raw_html_sha256,"
             " discovery_status")


def _flush(conn, buf_d, buf_t, buf_p) -> None:
    if buf_d:
        n = len(_DOC_COLS.split(","))
        assert len(buf_d[0]) == n, (
            f"documents: {len(buf_d[0])} giá trị / {n} cột khai — "
            "sửa `_DOC_COLS` và `DocumentRecord` cùng lúc")
        conn.executemany(
            f"INSERT OR REPLACE INTO documents ({_DOC_COLS})"
            f" VALUES ({','.join('?' * n)})", buf_d)
        buf_d.clear()
    if buf_t:
        n = len(_TAB_COLS.split(","))
        assert len(buf_t[0]) == n, f"tables: {len(buf_t[0])} giá trị / {n} cột"
        conn.executemany(
            f"INSERT OR REPLACE INTO tables ({_TAB_COLS})"
            f" VALUES ({','.join('?' * n)})", buf_t)
        buf_t.clear()
    if buf_p:
        conn.executemany(
            "INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?)", buf_p)
        buf_p.clear()
    conn.commit()
