"""Quét corpus -> catalog. Đây là module nền: mọi thứ khác phụ thuộc nó.

Bất biến bắt buộc: **số dòng không bao giờ được thay đổi**. Bài nộp định danh
bảng bằng `<doc_id>|<số dòng>`, nên mọi thao tác làm sạch phải là *phép chiếu*
song song, không phải phép ghi đè lên tệp. Catalog ghi lại toạ độ gốc một lần
và toạ độ đó là bất biến của cả hệ thống.

Corpus đã đo trước khi viết module này (1.973 tệp):
  LF 100%, 0 BOM, 0 lỗi UTF-8, 0 ký tự NUL
  121.756 page marker, đồng nhất tuyệt đối dạng `===== PAGE N =====`
  146.246 bảng, 100% mở đầu ở đầu dòng, 3 bảng trải nhiều dòng
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from text2pandas.domain.values.document_id import DocumentIdentity, parse_document_path

__all__ = ["ScannedDocument", "ScannedTable", "scan_document", "iter_corpus"]

_PAGE = re.compile(r"^===== PAGE (\d+) =====$")
_TABLE_OPEN = "<table"
_TABLE_CLOSE = "</table>"

# Tín hiệu nội dung dùng để xác nhận lại `basis`/`report_type` từ NỘI DUNG
# thay vì tin tên tệp — đã có trường hợp tên tệp nói dối.
_SIG_CONSOLIDATED = ("hợp nhất", "HỢP NHẤT")
_SIG_SEPARATE = ("riêng", "RIÊNG", "công ty mẹ")
_SIG_EXPLANATORY = ("giải trình", "GIẢI TRÌNH", "Kính gửi")


@dataclass(slots=True)
class ScannedTable:
    doc_id_stripped: str
    line_no_1based: int
    line_no_0based: int
    table_ordinal: int  # 0-based, thứ tự trong tài liệu
    page_no: int | None
    char_offset: int
    n_lines: int  # 1 với 146.243/146.246 bảng
    raw_html: str
    n_chars: int

    @property
    def locator_1based(self) -> str:
        return f"{self.doc_id_stripped}|{self.line_no_1based}"


@dataclass(slots=True)
class ScannedDocument:
    identity: DocumentIdentity
    n_lines: int
    n_bytes: int
    sha256: str
    n_pages: int
    n_tables: int
    content_basis: str | None
    is_explanatory: bool
    tables: list[ScannedTable]
    page_line_starts: list[int]  # dòng 1-based của từng page marker


def _content_basis(text: str) -> str | None:
    """Suy `basis` từ nội dung. Trả None khi không đủ bằng chứng — không đoán."""
    head = text[:200_000]
    cons = sum(head.count(s) for s in _SIG_CONSOLIDATED)
    sep = sum(head.count(s) for s in _SIG_SEPARATE)
    if cons == 0 and sep == 0:
        return None
    if cons >= 2 * max(sep, 1):
        return "consolidated"
    if sep >= 2 * max(cons, 1):
        return "separate"
    return None


def scan_document(path: Path, corpus_root: Path) -> ScannedDocument:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    identity = parse_document_path(path, corpus_root)

    lines = text.split("\n")
    tables: list[ScannedTable] = []
    page_starts: list[int] = []
    page_no: int | None = None
    ordinal = 0
    offset = 0
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        if m := _PAGE.match(line):
            page_no = int(m.group(1))
            page_starts.append(i + 1)
        elif line.startswith(_TABLE_OPEN):
            start_i, start_off = i, offset
            if line.endswith(_TABLE_CLOSE):
                html, span = line, 1
            else:
                # 3 ca trong toàn corpus. Gom tới khi gặp thẻ đóng.
                buf = [line]
                j = i + 1
                while j < n and _TABLE_CLOSE not in lines[j]:
                    buf.append(lines[j])
                    j += 1
                if j < n:
                    buf.append(lines[j])
                html, span = "\n".join(buf), j - start_i + 1
                for k in range(start_i, min(j + 1, n)):
                    if k > start_i:
                        offset += len(lines[k].encode("utf-8")) + 1
                i = j
            tables.append(
                ScannedTable(
                    doc_id_stripped=identity.doc_id_stripped,
                    line_no_1based=start_i + 1,
                    line_no_0based=start_i,
                    table_ordinal=ordinal,
                    page_no=page_no,
                    char_offset=start_off,
                    n_lines=span,
                    raw_html=html,
                    n_chars=len(html),
                )
            )
            ordinal += 1
        offset += len(lines[i].encode("utf-8")) + 1
        i += 1

    return ScannedDocument(
        identity=identity,
        n_lines=len(lines),
        n_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        n_pages=len(page_starts),
        n_tables=len(tables),
        content_basis=_content_basis(text),
        is_explanatory=any(s in text[:50_000] for s in _SIG_EXPLANATORY)
        and "BẢNG CÂN ĐỐI KẾ TOÁN" not in text,
        tables=tables,
        page_line_starts=page_starts,
    )


def iter_corpus(corpus_root: Path) -> Iterator[Path]:
    yield from sorted(corpus_root.rglob("*.txt"))
