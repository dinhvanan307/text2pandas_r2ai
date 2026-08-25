"""Định danh tài liệu — hai biến thể, chưa chốt biến thể nào đúng.

Thể lệ (bản chụp mới) nói mã báo cáo = "tên file cuối cùng trong đường dẫn tài
liệu và loại bỏ phần mở rộng .txt", kèm ví dụ BTC tự in ra:

    ocr_filter\\AAA\\2015\\AAA_financial_statements_2015_consolidated
    -> AAA_financial_statements_2015_consolidated

Nhưng corpus HuggingFace ta có thêm hậu tố `_extracted`:

    AAA/2015/AAA_..._consolidated/AAA_..._consolidated_extracted.txt

Áp luật theo chữ -> `..._consolidated_extracted`
Khớp ví dụ BTC   -> `..._consolidated`

Cả hai đều tính được. Module này sinh CẢ HAI để một lượt nộp thăm dò phân định
được, thay vì phải quét lại corpus. Xem RULES_SOURCES.md [D-R04].
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = ["DocumentIdentity", "parse_document_path", "DOC_ID_VARIANTS"]

DOC_ID_VARIANTS = ("stripped", "literal")

_SUFFIX = "_extracted.txt"

# Mẫu 1 — chiếm 1.956/1.973 tài liệu.
_PATTERN_STANDARD = re.compile(
    r"^(?P<ticker>[A-Z0-9]+)_financial_statements_(?P<year>\d{4})"
    r"(?:_(?P<basis>consolidated|separate|aggregated))?"
    r"(?:_(?P<dup>\d+))?$"
)

# Mẫu 2 — 17 tài liệu, năm đứng ngay sau ticker, loại tài liệu khác hẳn.
_PATTERN_ALT = re.compile(
    r"^(?P<ticker>[A-Z0-9]+)_(?P<year>\d{4})_(?P<kind>[a-z_]+?)(?:_(?P<dup>\d+))?$"
)


@dataclass(frozen=True, slots=True)
class DocumentIdentity:
    doc_id_stripped: str  # bỏ "_extracted.txt" — khớp ví dụ BTC
    doc_id_literal: str  # chỉ bỏ ".txt" — khớp câu chữ thể lệ
    ticker: str
    year: int | None
    basis: str | None  # nullable: 38 tài liệu thật sự không khai báo
    report_type: str
    duplicate_index: int | None
    rel_path: str
    id_pattern: str

    def doc_id(self, variant: str = "stripped") -> str:
        if variant == "literal":
            return self.doc_id_literal
        return self.doc_id_stripped


def parse_document_path(path: Path, corpus_root: Path) -> DocumentIdentity:
    """Suy định danh từ đường dẫn. Không đọc nội dung tệp.

    `basis` ở đây là GIẢ THUYẾT từ tên tệp. Đã xác nhận ít nhất một tệp mang
    tên `..._separate` nhưng nội dung là công văn giải trình — nên `basis`
    thật phải được xác nhận lại từ nội dung ở tầng sau.
    """
    name = path.name
    doc_id_literal = name[:-4] if name.endswith(".txt") else name
    doc_id_stripped = name[: -len(_SUFFIX)] if name.endswith(_SUFFIX) else doc_id_literal

    rel = path.relative_to(corpus_root).as_posix()
    ticker_from_dir = rel.split("/", 1)[0] if "/" in rel else ""

    if m := _PATTERN_STANDARD.match(doc_id_stripped):
        dup = m.group("dup")
        return DocumentIdentity(
            doc_id_stripped=doc_id_stripped,
            doc_id_literal=doc_id_literal,
            ticker=m.group("ticker"),
            year=int(m.group("year")),
            basis=m.group("basis"),
            report_type="financial_statements",
            duplicate_index=int(dup) if dup else None,
            rel_path=rel,
            id_pattern="standard",
        )

    if m := _PATTERN_ALT.match(doc_id_stripped):
        dup = m.group("dup")
        return DocumentIdentity(
            doc_id_stripped=doc_id_stripped,
            doc_id_literal=doc_id_literal,
            ticker=m.group("ticker"),
            year=int(m.group("year")),
            basis=None,
            report_type=m.group("kind"),
            duplicate_index=int(dup) if dup else None,
            rel_path=rel,
            id_pattern="alt",
        )

    # Nhánh dự phòng — fail loud, không đoán.
    return DocumentIdentity(
        doc_id_stripped=doc_id_stripped,
        doc_id_literal=doc_id_literal,
        ticker=ticker_from_dir,
        year=None,
        basis=None,
        report_type="unknown",
        duplicate_index=None,
        rel_path=rel,
        id_pattern="unrecognized",
    )
