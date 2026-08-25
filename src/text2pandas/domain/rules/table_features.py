"""Hiểu một bảng: loại gì, cột nào là kỳ nào, đơn vị bao nhiêu.

Đây là tầng ngữ nghĩa mà toàn bộ chất lượng truy hồi phụ thuộc vào. Index cũ
dựng trên văn bản phẳng có 44% token là số — bảng danh sách nhân sự ngắn gọn
thắng bảng tài chính dài đầy số vì BM25 phạt độ dài. Module này tạo ra thứ
thay thế: đặc trưng để lọc, và nhãn để index.

Ba nhóm việc:
  1. Phân loại   — bảng này có phải dữ liệu tài chính không, thuộc báo cáo nào
  2. Giải kỳ     — cột này ứng với thời điểm nào
  3. Giải đơn vị — giá trị trong bảng nhân với 10^mấy
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from text2pandas.domain.values.vn_number import (
    ParseStatus,
    SepConvention,
    detect_convention,
    parse_vn_number,
)
from text2pandas.infrastructure.parsing.html_table import TableGrid

__all__ = [
    "TableFeatures",
    "ColumnSpec",
    "extract_features",
    "STATEMENT_TYPES",
]

STATEMENT_TYPES = (
    "balance_sheet", "income_statement", "cash_flow", "equity_change",
    "note", "personnel", "toc", "subsidiary", "other",
)

# ── tín hiệu phân loại ──────────────────────────────────────────────────────
_SIG_BALANCE = ("BẢNG CÂN ĐỐI KẾ TOÁN", "CÂN ĐỐI KẾ TOÁN", "TÀI SẢN NGẮN HẠN",
                "NỢ PHẢI TRẢ", "VỐN CHỦ SỞ HỮU", "TỔNG CỘNG TÀI SẢN")
_SIG_INCOME = ("KẾT QUẢ HOẠT ĐỘNG KINH DOANH", "Doanh thu bán hàng",
               "Lợi nhuận gộp", "Lợi nhuận sau thuế", "Giá vốn hàng bán")
_SIG_CASHFLOW = ("LƯU CHUYỂN TIỀN TỆ", "Lưu chuyển tiền thuần",
                 "hoạt động kinh doanh", "hoạt động đầu tư", "hoạt động tài chính")
_SIG_EQUITY = ("VỐN CHỦ SỞ HỮU", "Thay đổi vốn chủ sở hữu", "Số dư đầu năm")
_SIG_PERSON = ("Ông ", "Bà ", "Chủ tịch", "Thành viên", "Tổng Giám đốc",
               "Kế toán trưởng", "Trưởng ban", "Bổ nhiệm", "Miễn nhiệm")
_SIG_TOC = ("Trang", "MỤC LỤC", "Thông tin chung", "Báo cáo kiểm toán")
_SIG_SUBSIDIARY = ("Tỷ lệ sở hữu", "Quyền biểu quyết", "Công ty con",
                   "Công ty liên kết", "Nơi thành lập", "Hoạt động chính")

# ── kỳ ──────────────────────────────────────────────────────────────────────
_DATE_DMY = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(20\d{2})")
_YEAR = re.compile(r"\b(20[0-2]\d)\b")
_QUARTER = re.compile(r"[Qq]uý\s*([1-4])")
_REL_END = ("Số cuối năm", "Số cuối kỳ", "Cuối năm", "Cuối kỳ", "31/12")
_REL_BEGIN = ("Số đầu năm", "Số đầu kỳ", "Đầu năm", "Đầu kỳ", "01/01")

# ── đơn vị ──────────────────────────────────────────────────────────────────
_UNIT_TABLE: tuple[tuple[str, int], ...] = (
    ("nghìn tỷ đồng", 12), ("nghìn tỷ", 12),
    ("tỷ đồng", 9), ("tỷ vnd", 9), ("tỉ đồng", 9), ("tỷ", 9),
    ("triệu đồng", 6), ("triệu vnd", 6), ("triệu", 6),
    ("nghìn đồng", 3), ("nghìn vnd", 3), ("ngàn đồng", 3),
    ("đồng", 0), ("vnd", 0), ("vnđ", 0),
)
_UNIT_DECL = re.compile(r"Đơn vị(?:\s*tính)?\s*[:：]?\s*(.{0,40})", re.I)


@dataclass(slots=True)
class ColumnSpec:
    idx: int
    label: str
    year: int | None = None
    month: int | None = None
    day: int | None = None
    quarter: int | None = None
    role: str | None = None  # 'current' | 'prior' | None
    is_ma_so: bool = False
    is_note_ref: bool = False
    numeric_ratio: float = 0.0


@dataclass(slots=True)
class TableFeatures:
    statement_type: str
    is_data_table: bool
    numeric_ratio: float
    unit_exponent: int
    unit_source: str  # 'column' | 'in_table' | 'above' | 'default'
    unit_raw: str
    sep_convention: str
    columns: list[ColumnSpec] = field(default_factory=list)
    row_labels: list[str] = field(default_factory=list)
    ma_so_col: int | None = None
    header_rows: int = 0
    context: str = ""  # dòng tiêu đề/thuyết minh ngay trên bảng
    flags: list[str] = field(default_factory=list)

    @property
    def years(self) -> list[int]:
        return sorted({c.year for c in self.columns if c.year})


def _classify(text: str, grid: TableGrid, numeric_ratio: float) -> str:
    def hits(sigs: tuple[str, ...]) -> int:
        return sum(1 for s in sigs if s in text)

    # Bảng phi dữ liệu nhận diện trước — chúng là nguồn nhiễu chính của index.
    if hits(_SIG_TOC) >= 2 and numeric_ratio < 0.35:
        return "toc"
    if hits(_SIG_PERSON) >= 2 and numeric_ratio < 0.30:
        return "personnel"
    if hits(_SIG_SUBSIDIARY) >= 2:
        return "subsidiary"

    scores = {
        "balance_sheet": hits(_SIG_BALANCE),
        "income_statement": hits(_SIG_INCOME),
        "cash_flow": hits(_SIG_CASHFLOW),
        "equity_change": hits(_SIG_EQUITY),
    }
    best = max(scores, key=lambda k: scores[k])
    if scores[best] >= 2:
        return best
    return "note" if numeric_ratio >= 0.20 else "other"


def _parse_column(idx: int, label: str, doc_year: int | None) -> ColumnSpec:
    spec = ColumnSpec(idx=idx, label=label)
    low = label.lower()

    if "mã số" in low or low.strip() in {"ms", "mã"}:
        spec.is_ma_so = True
    if "thuyết minh" in low or low.strip() in {"tm", "v.", "vi"}:
        spec.is_note_ref = True

    if m := _DATE_DMY.search(label):
        spec.day, spec.month, spec.year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    elif m := _YEAR.search(label):
        spec.year = int(m.group(1))
    if m := _QUARTER.search(label):
        spec.quarter = int(m.group(1))

    # "Số cuối năm" / "Số đầu năm" chỉ giải được khi biết năm của TÀI LIỆU.
    # Đây là dạng nhãn cột phổ biến nhất trong BCTC Việt Nam và bỏ qua nó
    # đồng nghĩa mất khả năng phân biệt cột năm nay với cột năm trước.
    if any(s in label for s in _REL_END):
        spec.role = "current"
        if spec.year is None and doc_year:
            spec.year, spec.month, spec.day = doc_year, 12, 31
    elif any(s in label for s in _REL_BEGIN):
        spec.role = "prior"
        if spec.year is None and doc_year:
            spec.year, spec.month, spec.day = doc_year - 1, 12, 31
    return spec


def _unit_from_text(text: str) -> tuple[int, str] | None:
    if m := _UNIT_DECL.search(text):
        tail = m.group(1).lower()
        for pat, exp in _UNIT_TABLE:
            if pat in tail:
                return exp, m.group(0).strip()[:60]
    return None


def _unit_from_columns(labels: list[str]) -> tuple[int, str] | None:
    """Đơn vị dính vào nhãn cột: `31/12/2015VND`, `Miền BắcTriệu VND`."""
    for lab in labels:
        low = lab.lower()
        for pat, exp in _UNIT_TABLE:
            if pat in low:
                return exp, lab[:60]
    return None


def extract_features(
    grid: TableGrid,
    col_labels: list[str],
    context_before: str,
    doc_year: int | None,
) -> TableFeatures:
    """Tính toàn bộ đặc trưng của một bảng.

    `context_before` là mấy dòng văn bản ngay phía trên bảng. Bắt buộc phải có:
    9.099 khai báo `Đơn vị tính` nằm NGOÀI bảng (so với 7.111 nằm trong), phổ
    biến nhất là cách đúng 2 dòng. Parser chỉ nhìn HTML sẽ không bao giờ thấy.
    Ngoài ra đây cũng là nơi chứa tiêu đề thuyết minh ("12. Tiền và các khoản
    tương đương tiền") — chính là cụm từ mà câu hỏi hay dùng.
    """
    flat_cells = [c for row in grid.cells for c in row]
    filled = [c for c in flat_cells if c.strip()]
    conv = detect_convention(flat_cells)
    if conv is SepConvention.UNKNOWN:
        conv = SepConvention.DOT_THOUSANDS

    n_num = sum(
        1 for c in filled if parse_vn_number(c, conv).status is ParseStatus.OK
    )
    ratio = n_num / len(filled) if filled else 0.0

    text = " ".join(filled)
    stype = _classify(text + " " + context_before, grid, ratio)

    cols = [_parse_column(i, lab, doc_year) for i, lab in enumerate(col_labels)]
    for c in cols:
        col_cells = [r[c.idx] for r in grid.cells if c.idx < len(r) and r[c.idx].strip()]
        if col_cells:
            c.numeric_ratio = sum(
                1 for x in col_cells if parse_vn_number(x, conv).status is ParseStatus.OK
            ) / len(col_cells)

    # Đơn vị: ưu tiên nguồn gần dữ liệu nhất trước.
    unit_exp, unit_src, unit_raw = 0, "default", ""
    if got := _unit_from_columns(col_labels):
        unit_exp, unit_raw, unit_src = got[0], got[1], "column"
    elif got := _unit_from_text(text):
        unit_exp, unit_raw, unit_src = got[0], got[1], "in_table"
    elif got := _unit_from_text(context_before):
        unit_exp, unit_raw, unit_src = got[0], got[1], "above"

    ma_so = next((c.idx for c in cols if c.is_ma_so), None)

    # Nhãn dòng = ô văn bản trái nhất của mỗi hàng dữ liệu.
    row_labels: list[str] = []
    for row in grid.cells:
        for cell in row:
            s = cell.strip()
            if s and parse_vn_number(s, conv).status is not ParseStatus.OK:
                row_labels.append(s)
                break

    flags: list[str] = []
    if ratio < 0.10:
        flags.append("low_numeric")
    if not any(c.year for c in cols):
        flags.append("no_period_column")
    if unit_src == "default":
        flags.append("unit_assumed_vnd")

    return TableFeatures(
        statement_type=stype,
        is_data_table=stype not in {"toc", "personnel", "other"} and ratio >= 0.15,
        numeric_ratio=round(ratio, 4),
        unit_exponent=unit_exp,
        unit_source=unit_src,
        unit_raw=unit_raw,
        sep_convention=conv.value,
        columns=cols,
        row_labels=row_labels,
        ma_so_col=ma_so,
        header_rows=sum(1 for c in col_labels if c and not c.startswith("c")),
        context=context_before[-400:],
        flags=flags,
    )
