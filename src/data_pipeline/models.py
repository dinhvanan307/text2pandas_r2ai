"""DP-001 — Contracts: enums và models cho toàn bộ data pipeline.

Mọi stage đọc/ghi qua các model ở đây. Không stage nào được tự định nghĩa
shape riêng — đó là cách hai stage phân kỳ mà không ai phát hiện.

Nguyên tắc mã hoá:
  - Decimal lưu bằng canonical TEXT, KHÔNG dùng SQLite REAL (DI-05)
  - list/map lưu bằng canonical JSON TEXT, sort key, không khoảng trắng thừa
  - text_source và text_clean là hai trường riêng, không ghi đè nhau (DI-04)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

__all__ = [
    "StageStatus", "DiscoveryStatus", "ParseStatus", "CleanStatus",
    "ColumnRole", "RowRole", "CellRole", "ValueKind", "UnitKind",
    "PeriodType", "PeriodRole", "Severity", "EvidenceSource",
    "SourceCell", "GridCell", "RowInfo", "ColumnInfo", "Observation",
    "QualityIssue", "TableRecord", "DocumentRecord",
    "canonical_json", "decimal_to_text", "text_to_decimal", "make_uid",
]


# ─────────────────────────── enums ───────────────────────────

class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class DiscoveryStatus(str, Enum):
    """Kết quả tìm bảng trong một tài liệu."""
    OK = "ok"
    NO_MARKUP = "no_markup"          # 8 tài liệu không có <table>
    MULTILINE = "multiline"          # 3 bảng trải nhiều dòng
    UNCLOSED = "unclosed"


class ParseStatus(str, Enum):
    OK = "ok"
    EMPTY = "empty"
    DASH = "dash"                    # quy ước kế toán = khuyết, KHÔNG phải 0
    NOT_A_NUMBER = "not_a_number"
    AMBIGUOUS = "ambiguous"          # không đủ bằng chứng phân định — không đoán
    MALFORMED = "malformed"
    TABLE_TOO_LARGE = "table_too_large"
    TABLE_PARSE_FAILED = "table_parse_failed"


class CleanStatus(str, Enum):
    UNCHANGED = "unchanged"
    CLEANED = "cleaned"
    HAS_BROKEN_ENTITY = "has_broken_entity"   # &IR; &2; — giữ nguyên, không sửa


class ColumnRole(str, Enum):
    LABEL = "label"
    VALUE = "value"
    METRIC_CODE = "metric_code"       # cột "Mã số"
    NOTE_REFERENCE = "note_reference"  # cột "Thuyết minh" — số hiệu, không phải giá trị
    ORDINAL = "ordinal"                # cột "STT" — số đếm dòng, không phải số liệu
    DATE = "date"
    DIMENSION = "dimension"
    UNKNOWN = "unknown"


class RowRole(str, Enum):
    HEADER = "header"
    SECTION = "section"
    METRIC = "metric"
    SUBTOTAL = "subtotal"
    TOTAL = "total"
    DIMENSION_MEMBER = "dimension_member"
    EMPTY = "empty"
    UNKNOWN = "unknown"


class CellRole(str, Enum):
    HEADER = "header"
    LABEL = "label"
    VALUE = "value"
    CODE = "code"
    NOTE_REF = "note_ref"
    EMPTY = "empty"
    UNKNOWN = "unknown"


class ValueKind(str, Enum):
    MONEY = "money"
    PERCENTAGE = "percentage"
    RATIO = "ratio"
    SHARE_COUNT = "share_count"
    QUANTITY = "quantity"
    DAYS = "days"
    INTEREST_RATE = "interest_rate"
    DATE = "date"
    METRIC_CODE = "metric_code"
    NOTE_REFERENCE = "note_reference"
    PLAIN_NUMBER = "plain_number"
    NOT_A_VALUE = "not_a_value"
    UNKNOWN = "unknown"


class UnitKind(str, Enum):
    MONEY = "money"
    PERCENT = "percent"
    SHARES = "shares"
    DAYS = "days"
    RATE = "rate"
    COUNT = "count"
    NONE = "none"
    UNKNOWN = "unknown"


class PeriodType(str, Enum):
    INSTANT = "instant"      # số dư tại một thời điểm
    DURATION = "duration"    # phát sinh trong một kỳ
    QUARTER = "quarter"
    YTD = "ytd"
    UNKNOWN = "unknown"


class PeriodRole(str, Enum):
    CURRENT = "current"
    PRIOR = "prior"
    OPENING = "opening"   # 01/01/YYYY — chính là closing của YYYY-1
    CLOSING = "closing"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EvidenceSource(str, Enum):
    """Nơi một quyết định ngữ nghĩa được rút ra. Bắt buộc lưu (DI-07)."""
    CELL = "cell"
    COLUMN_PATH = "column_path"
    ROW_CONTEXT = "row_context"
    TABLE_CONTEXT = "table_context"
    SECTION_CONTEXT = "section_context"
    DOCUMENT_DEFAULT = "document_default"
    CORPUS_PRIOR = "corpus_prior"
    ASSUMED = "assumed"
    NONE = "none"


# ───────────────────── mã hoá canonical ─────────────────────

def canonical_json(value) -> str:
    """JSON tất định: sort key, không khoảng trắng thừa, giữ Unicode."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def decimal_to_text(d: Decimal | None) -> str | None:
    """Decimal -> canonical TEXT. Không dùng ký hiệu mũ, giữ đúng chữ số.

    `Decimal("1E+3")` trở thành `"1000"`; `Decimal("100.00")` giữ nguyên
    `"100.00"` vì số chữ số thập phân là thông tin (độ chính xác báo cáo).
    """
    if d is None:
        return None
    # `format(d, "f")` đã khai triển số mũ dương: Decimal("1E+3") -> "1000".
    # KHÔNG dùng `quantize` — nó ném InvalidOperation khi kết quả vượt
    # precision mặc định 28 chữ số, và corpus có giá trị tới 10^15.
    return format(d, "f")


def text_to_decimal(t: str | None) -> Decimal | None:
    return None if t is None or t == "" else Decimal(t)


def make_uid(*parts: object) -> str:
    """UID tất định 16 hex từ các thành phần. Cùng input -> cùng UID (DI-09)."""
    raw = "\x1f".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ───────────────────────── models ─────────────────────────

@dataclass(slots=True)
class DocumentRecord:
    """Bronze: chỉ giá trị QUAN SÁT ĐƯỢC. Không chứa trường suy diễn."""
    document_uid: str
    literal_file_stem: str      # tên tệp bỏ .txt
    directory_doc_id: str       # tên thư mục cha = doc_id nộp bài
    ticker_path: str
    year_path: int | None
    basis_path: str | None
    rel_path: str
    n_bytes: int
    n_lines: int
    n_pages: int
    n_tables: int
    sha256: str
    corpus_id: str
    scan_status: StageStatus
    discovery_status: DiscoveryStatus
    # ── RC-06 · APPEND-ONLY. Ba số ĐO TRỰC TIẾP TRÊN VĂN BẢN THÔ ────────────
    #
    # `n_tables` là kết quả của bộ PHÂN TÍCH. Nó không phân biệt được hai tình
    # huống hoàn toàn khác nhau: tệp vốn không có markup bảng (ngoài phạm vi,
    # bình thường) và tệp CÓ markup nhưng bộ phân tích không dựng nổi bảng nào
    # (lỗi thật, mất dữ liệu). Gộp hai thứ lại là cách một lỗi parser nấp sau
    # một con số nghe có vẻ vô hại.
    #
    # Hai số còn lại là TÓM TẮT NỘI DUNG SỐ: người nhận gói tự trả lời được
    # câu "bỏ tám tài liệu này ra thì mất bao nhiêu con số", không phải tin
    # một dòng trong markdown.
    n_table_markup: int = 0     # số lần `<table` xuất hiện trong văn bản THÔ
    n_numeric_tokens: int = 0   # token dạng số
    n_grouped_numbers: int = 0  # số có phân nhóm nghìn (`1.234.567`) — tiền tệ


@dataclass(slots=True)
class TableRecord:
    table_uid: str
    document_uid: str
    line_start_1based: int
    line_end_1based: int
    line_start_0based: int
    table_ordinal_document: int
    table_ordinal_page: int | None
    page_no: int | None
    char_start: int
    char_end: int
    raw_html: str
    raw_html_sha256: str
    discovery_status: DiscoveryStatus


@dataclass(slots=True)
class SourceCell:
    """Ô THẬT trong HTML. Một `<td>` = một SourceCell."""
    source_cell_uid: str
    table_uid: str
    source_row_idx: int
    source_col_idx: int
    grid_row_idx: int            # vị trí anchor trên lưới
    grid_col_idx: int
    rowspan: int
    colspan: int
    text_source: str
    text_clean: str
    clean_rules: list[str] = field(default_factory=list)
    clean_status: CleanStatus = CleanStatus.UNCHANGED


@dataclass(slots=True)
class GridCell:
    """Vị trí LOGIC trên lưới. Một SourceCell có span phủ nhiều GridCell.

    `is_span_anchor` phân biệt vị trí gốc với vị trí được phủ. Chỉ anchor mới
    được sinh observation — nếu không, một ô số có colspan=2 sẽ tạo hai
    observation trùng.
    """
    table_uid: str
    grid_row_idx: int
    grid_col_idx: int
    source_cell_uid: str
    is_span_anchor: bool
    cell_role: CellRole = CellRole.UNKNOWN


@dataclass(slots=True)
class RowInfo:
    table_uid: str
    grid_row_idx: int
    row_role: RowRole
    label_source: str
    label_clean: str
    row_path_json: list[str]
    row_level: int
    metric_code: str | None = None
    is_generic_label: bool = False
    flags: list[str] = field(default_factory=list)
    # ── [F3] Data Contract v1 — để None ở v1.0, điền ở v1.2 ──
    parent_row_uid: str | None = None
    hierarchy_level: int | None = None
    hierarchy_source: str | None = None
    hierarchy_confidence: str | None = None
    structural_role: str | None = None
    accounting_role: str | None = None

    @property
    def row_uid(self) -> str:
        """Danh tính VẬT LÝ của dòng.

        Không phụ thuộc `label`, `row_path` hay bất kỳ đầu ra nào của resolver.
        Đây là điều kiện để cải thiện ngữ nghĩa sau Contract Freeze mà không
        phá hợp đồng: `row_path` đổi thì `row_uid` vẫn nguyên, nên downstream
        so sánh được build cũ với build mới theo cùng một dòng vật lý.
        """
        return make_uid(self.table_uid, self.grid_row_idx)

    @property
    def row_path_text(self) -> str:
        return " › ".join(self.row_path_json)


@dataclass(slots=True)
class ColumnInfo:
    table_uid: str
    grid_col_idx: int
    column_role: ColumnRole
    header_path_json: list[str]
    period_end: str | None = None
    period_start: str | None = None
    as_of_date: str | None = None
    period_type: PeriodType = PeriodType.UNKNOWN
    period_role: PeriodRole = PeriodRole.UNKNOWN
    period_source: EvidenceSource = EvidenceSource.NONE
    quarter: int | None = None
    is_restated: bool = False
    unit_kind: UnitKind = UnitKind.UNKNOWN
    currency: str | None = None
    scale_exponent: int | None = None
    numeric_ratio: float = 0.0
    flags: list[str] = field(default_factory=list)
    # ── [F3] Data Contract v1 — để None ở v1.0, điền ở v1.1 ──
    parent_column_uid: str | None = None
    column_group_source: str | None = None
    column_group_confidence: str | None = None

    @property
    def column_uid(self) -> str:
        """Danh tính VẬT LÝ của cột. Cùng lý do với `RowInfo.row_uid`."""
        return make_uid(self.table_uid, self.grid_col_idx)

    @property
    def header_path_text(self) -> str:
        return " › ".join(self.header_path_json)


@dataclass(slots=True)
class Observation:
    """Một giá trị tài chính, neo về đúng một SourceCell."""
    observation_uid: str
    table_uid: str
    source_cell_uid: str
    grid_row_idx: int
    grid_col_idx: int
    row_path_json: list[str]
    col_path_json: list[str]
    metric_label_source: str
    metric_label_clean: str
    metric_code_raw: str | None
    value_source: str
    value_clean: str
    value_decimal: Decimal | None
    value_kind: ValueKind
    parse_status: ParseStatus
    parse_rule: str
    is_negative: bool
    unit_kind: UnitKind
    currency: str | None
    scale_exponent: int | None
    unit_kind_source: EvidenceSource
    currency_source: EvidenceSource
    scale_source: EvidenceSource
    period_start: str | None
    period_end: str | None
    as_of_date: str | None
    period_type: PeriodType
    period_role: PeriodRole
    period_source: EvidenceSource
    quarter: int | None
    is_restated: bool
    reported_in_document_year: int | None
    dimensions: dict[str, str] = field(default_factory=dict)
    quality_flags: list[str] = field(default_factory=list)

    @property
    def row_path_text(self) -> str:
        return " › ".join(self.row_path_json)

    @property
    def col_path_text(self) -> str:
        return " › ".join(self.col_path_json)


@dataclass(slots=True)
class QualityIssue:
    issue_uid: str
    scope_type: str          # document | table | column | row | observation
    scope_uid: str
    severity: Severity
    rule_id: str
    message: str
    details: dict = field(default_factory=dict)
