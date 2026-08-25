"""DP-007 — D3b Structural Interpretation: hiểu hình học bảng trước ngữ nghĩa.

Đây là stage thiếu trong thiết kế cũ và là nguyên nhân của phụ thuộc vòng:
resolver ngữ nghĩa cần biết cột nào là giá trị, dòng nào là tiêu đề — nhưng
tầng đặc trưng lại sinh ra chúng sau. Tách ra thành stage riêng gỡ vòng đó.

Hai luật chi phối:

**Dùng span replica để lan nhãn tiêu đề.** Header có `colspan` phủ nhiều cột;
grid replica cho biết cột nào được nhãn đó phủ. Đây chính là lý do phải giữ
replica thay vì vứt đi — chúng vô dụng cho giá trị nhưng cần cho nhãn.

**Không hard-exclude bằng classifier.** `row_role`, `column_role`,
`statement_type` đều có thể sai; chúng luôn có giá trị `unknown` và không bao
giờ được dùng để xoá dữ liệu trước quality review (DI-02).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from data_pipeline.html_parser import ParsedTable
from data_pipeline.models import (
    CellRole,
    ColumnInfo,
    ColumnRole,
    RowInfo,
    RowRole,
)

__all__ = ["StructuredTable", "interpret_structure", "STRUCTURE_VERSION",
           "classify_statement"]

STRUCTURE_VERSION = "1.2"
MAX_HEADER_ROWS = 4
MAX_PATH_DEPTH = 4

# ── tiền tố đánh số theo Thông tư 200/202 → cấp ─────────────────────────────
# La Mã đứng TRƯỚC chữ cái đơn: I, V, X vừa là chữ hoa vừa là số La Mã.
_LEVEL_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"^(I{1,3}|IV|VI{0,3}|IX|XI{0,3}|V|X)\s*[.)]\s+"), 1),
    (re.compile(r"^([A-HJ-UWYZ])\s*[.)]\s+"), 0),
    (re.compile(r"^(\d{1,2}\.\d{1,2})\s*[.)]?\s+"), 3),
    (re.compile(r"^(\d{1,2})\s*[.)]\s+(?!\d)"), 2),
    (re.compile(r"^([a-z])\s*[)]\s+"), 3),
    (re.compile(r"^[-–—▪•+*]\s+"), 3),
)
_NUMBERING = re.compile(
    r"^\s*(?:[A-Za-z]\s*[.)]|\d{1,2}(?:\.\d{1,2})*\s*[.)]?|[-–—▪•+*])\s+")
_PURE_SYMBOLIC = re.compile(r"^[\d.,()%\-–—\s/]+$")
_WS = re.compile(r"\s+")

_MA_SO = re.compile(r"\bmã\s*số\b|^ms$|^mã$", re.I)
_NOTE_REF = re.compile(r"thuyết\s*minh|^tm$|^v\.$", re.I)
# `\b` KHÔNG dùng được ở đây: OCR nối đơn vị vào năm — `2021VND` là dạng phổ
# biến, và giữa `1` và `V` không có ranh giới từ. Cùng lớp lỗi với `\bVND`.
_DATE_LIKE = re.compile(r"\d{1,2}\s*/\s*\d{1,2}\s*/\s*20\d{2}|(?<!\d)20[0-2]\d(?!\d)")
# Cột "STT" toàn chữ số nên tỷ lệ numeric = 1,0 và bị gán VALUE. Nó là số đếm
# dòng, không phải số liệu tài chính — cùng bản chất với `Mã số`.
_ORDINAL = re.compile(r"^\s*(stt|s\.?\s*t\.?\s*t|tt|số\s*tt|thứ\s*tự)\s*$", re.I)
_PERCENT_HDR = re.compile(r"%|tỷ\s*lệ|phần\s*trăm", re.I)

_GENERIC = {
    "cong", "tong cong", "tong", "tong so", "cong don",
    "so du cuoi nam", "so du dau nam", "so cuoi nam", "so dau nam",
    "so du cuoi ky", "so du dau ky", "khac",
}
_SUBTOTAL_HINT = re.compile(r"^(cộng|tổng|tổng cộng|cộng dồn)\b", re.I)
_TOTAL_HINT = re.compile(r"^(tổng cộng|tổng số|tổng tài sản|tổng nguồn vốn)", re.I)

# ── tín hiệu phân loại báo cáo ─────────────────────────────────────────────
_SIG = {
    "balance_sheet": ("TÀI SẢN NGẮN HẠN", "TÀI SẢN DÀI HẠN", "NỢ PHẢI TRẢ",
                      "VỐN CHỦ SỞ HỮU", "TỔNG CỘNG TÀI SẢN", "TỔNG CỘNG NGUỒN VỐN"),
    "income_statement": ("Doanh thu bán hàng", "Giá vốn hàng bán", "Lợi nhuận gộp",
                         "Lợi nhuận sau thuế", "Lãi cơ bản trên cổ phiếu"),
    "cash_flow": ("Lưu chuyển tiền thuần", "hoạt động kinh doanh",
                  "hoạt động đầu tư", "hoạt động tài chính",
                  "Tiền và tương đương tiền cuối"),
    "equity_change": ("Số dư đầu năm", "Số dư cuối năm", "Tăng vốn",
                      "Lợi nhuận sau thuế chưa phân phối"),
    "personnel": ("Ông ", "Bà ", "Chủ tịch", "Tổng Giám đốc", "Kế toán trưởng",
                  "Bổ nhiệm", "Miễn nhiệm", "Trưởng ban"),
    "subsidiary": ("Tỷ lệ sở hữu", "Quyền biểu quyết", "Nơi thành lập",
                   "Hoạt động chính", "Công ty con", "Công ty liên kết"),
    "toc": ("Trang", "MỤC LỤC", "Báo cáo kiểm toán độc lập"),
}
# Tín hiệu bắt từ CONTEXT phải nhẹ hơn tín hiệu bắt từ NỘI DUNG bảng: bảng
# thuyết minh luôn nhắc tên báo cáo mà nó giải thích ("TRÌNH BÀY TRÊN BẢNG
# CÂN ĐỐI KẾ TOÁN"), và tính điểm ngang nhau sẽ gán nhầm nó thành balance_sheet.
_CONTEXT_WEIGHT = 0.34
_NOTE_MARKER = re.compile(r"\b\d{1,2}(\.\d{1,2}){0,2}\s*[.)]?\s+[A-ZÀ-Ỹ]")


@dataclass(slots=True)
class StructuredTable:
    table_uid: str
    n_header_rows: int
    rows: list[RowInfo] = field(default_factory=list)
    columns: list[ColumnInfo] = field(default_factory=list)
    statement_type: str = "unknown"
    statement_rule: str = ""
    is_data_table: bool = False
    numeric_ratio: float = 0.0
    label_col_idx: int | None = None
    ma_so_col_idx: int | None = None
    note_ref_col_idx: list[int] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def value_columns(self) -> list[int]:
        return [c.grid_col_idx for c in self.columns
                if c.column_role is ColumnRole.VALUE]


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return _WS.sub(" ", s.replace("đ", "d")).strip()


def normalize_label(label: str) -> str:
    s = unicodedata.normalize("NFC", label).strip()
    s = _NUMBERING.sub("", s)
    return _WS.sub(" ", s).strip(" .:–—-")


def _level_of(label: str) -> int | None:
    for pat, lvl in _LEVEL_PATTERNS:
        if pat.match(label):
            return lvl
    return None


def _looks_numeric(text: str) -> bool:
    t = text.strip()
    return bool(t) and bool(re.search(r"\d", t)) and bool(_PURE_SYMBOLIC.match(t))


# ── phân loại ô theo KIỂU, không theo "có chữ số hay không" ──────────────────
# `_looks_numeric` đang gánh bốn câu hỏi khác nhau ở bốn chỗ trong file này:
# "đây có phải tiêu đề", "cột này có phải cột giá trị", "dòng này có số liệu",
# "nhãn này có phải nhãn". Mỗi câu cần một ngưỡng riêng. Đây là bước đầu tách
# chúng ra; hai chỗ còn lại giữ nguyên trong đợt này để không đổi hai thứ cùng lúc.
_GROUPED_NUM = re.compile(r"\d[.,]\d")
_PERCENT_VAL = re.compile(r"\d\s*[.,]?\s*\d*\s*%")
_BARE_YEAR = re.compile(r"^\s*\(?\s*(?:19|20)\d{2}\s*\)?\s*$")
_MONTH_YEAR = re.compile(r"^\s*(?:tháng\s*)?\d{1,2}\s*/\s*(?:19|20)\d{2}\s*$", re.I)
_FULL_DATE = re.compile(r"\d{1,2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*(?:19|20)\d{2}")


def _is_period_label(t: str) -> bool:
    """Ngày, năm trần, tháng/năm — NHÃN KỲ của tiêu đề, không phải giá trị.

    Đây là chỗ luật "ô ≥6 chữ số thì dòng đó không thể là tiêu đề" tự mâu
    thuẫn: `31/12/2023` có tám chữ số mà vẫn là nhãn cột hợp lệ.
    """
    return bool(_FULL_DATE.search(t) or _BARE_YEAR.match(t) or _MONTH_YEAR.match(t))


def _cell_value_kind(text: str) -> str | None:
    """`money` | `percent` | `number` | None.

    None nghĩa là ô KHÔNG mang giá trị: chữ, nhãn kỳ, token đơn vị (`VND`,
    `triệu đồng`, `%` đứng một mình), hoặc số 1–2 chữ số.

    Số 1–2 chữ số cố ý không tính là giá trị: biểu mẫu Thông tư 200 có dòng
    đánh số cột `A | B | C | 1 | 2` nằm TRONG vùng tiêu đề, và cột STT, cột
    Mã số cũng toàn số ngắn.
    """
    t = (text or "").strip()
    if not t or _is_period_label(t):
        return None
    if _PERCENT_VAL.search(t):
        return "percent"
    if not _PURE_SYMBOLIC.match(t):
        return None
    n = len(_DIGIT.findall(t))
    if n >= 6 or (n >= 4 and _GROUPED_NUM.search(t)):
        return "money"
    return "number" if n >= 3 else None


def _row_has_small_numbers(texts: list[str]) -> bool:
    """Dòng có dáng DỮ LIỆU nhưng chỉ mang số 1–2 chữ số.

    `_cell_value_kind` cố ý bỏ qua số 1–2 chữ số vì biểu mẫu TT200 có dòng
    đánh số cột `A | B | C | 1`. Cái giá là: bảng đếm nhân sự hay bảng số ngày
    mà toàn số ngắn có thể bị nhận nhầm là tiêu đề.

    Rủi ro đó nhỏ nhưng phải ĐO ĐƯỢC ở mọi build, không phải chờ một script
    chạy tay — đúng bài học M-03: khiếm khuyết nào không có thước đo thì đi
    qua mọi cổng mà không ai biết.

    Dấu hiệu: có ô số ngắn (không phải nhãn kỳ) VÀ có nhãn chữ đủ dài.
    """
    co_so_ngan = any(
        (t or "").strip() and _PURE_SYMBOLIC.match((t or "").strip())
        and not _is_period_label((t or "").strip())
        and 1 <= len(_DIGIT.findall(t or "")) <= 2
        for t in texts)
    co_nhan_chu = any(
        (t or "").strip() and not _PURE_SYMBOLIC.match((t or "").strip())
        and len((t or "").strip()) >= 4
        for t in texts)
    return co_so_ngan and co_nhan_chu


def _detect_header_rows(pt: ParsedTable) -> tuple[int, list[str]]:
    """Số dòng đầu là tiêu đề CỘT. Trả thêm cờ chẩn đoán.

    **Luật cũ và vì sao nó xoá dữ liệu.** Bản trước tính "đa số ô parse được
    thành số" với mẫu số là **số ô KHÁC RỖNG**. Dòng thưa làm mẫu số co lại và
    phép so sánh đảo chiều: `['Các công ty con','','','323.162.400.000','']`
    có 1 số trên 2 ô khác rỗng, `1 > 2//2` sai, nên dòng dữ liệu đó thành tiêu
    đề. Mà `observation_builder` bỏ qua mọi dòng `HEADER`, nên nó bị **xoá
    cứng** — đi vòng qua DI-02, không cờ, không log.

    Đo được trên toàn corpus: **85.095 giá trị ở 29.071 bảng** (tiền 63.414 ·
    phần trăm 17.537 · số khác 4.144).

    **Luật mới.** Dừng quét ở dòng đầu tiên chứa BẤT KỲ GIÁ TRỊ nào. Điều kiện
    này không phụ thuộc độ thưa của dòng nên không bị mẫu số đánh lừa. Đo được
    thiệt hại còn lại: 0.

    Hai luật trung gian đã bị loại bằng số đo, ghi lại để không ai thử lại:
      * "dừng khi gặp SỐ TIỀN" — bảng tỷ lệ sở hữu và bảng nhân sự không có
        đồng nào nên nó quét hết 4 dòng: xoá thêm ở 12.013 bảng, mất 21.967 ô
        phần trăm và 5.446 ô số khác.
      * "ô ≥6 chữ số thì không phải tiêu đề" — `31/12/2023` có tám chữ số.

    **Bỏ sàn `max(n_header, 1)`.** Bảng thật sự không có tiêu đề thì `n_header
    = 0` là câu trả lời đúng; ép sàn 1 là xoá cứng dòng dữ liệu đầu tiên. Đo
    được 5.069 bảng như vậy.
    """
    flags: list[str] = []
    n_header = 0
    for r in range(min(MAX_HEADER_ROWS, pt.n_grid_rows)):
        texts = pt.row_texts(r)
        if any(_cell_value_kind(t) for t in texts):
            break
        # Số 1–2 chữ số bên cạnh một nhãn chữ có thể là dữ liệu thật (bảng đếm
        # nhân sự, bảng số ngày). Luật này KHÔNG dừng vì chúng, nên phải gắn cờ
        # để `Q-TAB-HEADER-SMALL-NUM` đếm được — rủi ro tồn dư phải đo được ở
        # mọi build, không phải chờ một script chạy tay.
        if _row_has_small_numbers(texts):
            flags.append("header_row_has_small_numbers")
        n_header = r + 1
    # DI-02: bộ nhận diện tiêu đề KHÔNG BAO GIỜ được nhận trọn cả bảng.
    # Bảng đếm nhân sự hai dòng toàn số 1–2 chữ số sẽ khớp điều kiện tiêu đề ở
    # mọi dòng, và `observation_builder` bỏ qua mọi dòng HEADER — tức là xoá
    # sạch bảng. Giữ dữ liệu kèm cờ luôn tốt hơn xoá dữ liệu không dấu vết.
    if pt.n_grid_rows and n_header >= pt.n_grid_rows:
        flags.append("header_would_consume_table")
        n_header = 0
    if n_header == 0 and pt.n_grid_rows:
        flags.append("no_header_row")
    return n_header, flags


def _column_paths(pt: ParsedTable, n_header: int) -> list[list[str]]:
    """Nhãn cột nhiều tầng, dựng từ span replica của các dòng tiêu đề."""
    paths: list[list[str]] = [[] for _ in range(pt.n_grid_cols)]
    for r in range(n_header):
        texts = pt.row_texts(r)
        for c, t in enumerate(texts):
            t = t.strip()
            if t and (not paths[c] or paths[c][-1] != t):
                paths[c].append(t)
    return [p[:MAX_PATH_DEPTH] for p in paths]


def _global_header_segments(paths: list[list[str]]) -> set[tuple[int, str]]:
    """Đoạn nhãn phủ TOÀN BỘ bảng — tiêu đề trang, không phải nhãn của cột nào.

    Một ô tiêu đề `colspan` bằng số cột đẻ ra **cùng một chuỗi ở cùng vị trí**
    cho mọi cột. Nếu chuỗi đó chứa "Thuyết minh" — và tiêu đề "BẢN THUYẾT MINH
    BÁO CÁO TÀI CHÍNH" thì bảng nào cũng có — thì `_classify_column` gán
    `note_reference` cho **mọi** cột, và cả bảng mất sạch observation.

    Đây là nguyên nhân đo được của 1.171 bảng `note` có `numeric_ratio` 0,369
    mà không có cột giá trị nào: bảng nghiệp vụ bên liên quan, đầu tư tài chính
    — toàn bảng câu hỏi hay hỏi tới.

    Chỉ loại đoạn phủ **toàn bộ** cột. `Số cuối năm` phủ hai cột con
    (`Giá gốc`, `Dự phòng`) là nhãn thật, phải giữ.
    """
    n = len(paths)
    if n < 3:
        return set()
    out: set[tuple[int, str]] = set()
    for i in range(max((len(p) for p in paths), default=0)):
        present = [p[i] for p in paths if len(p) > i]
        if len(present) == n and len(set(present)) == 1:
            out.add((i, present[0]))
    return out


def _classify_column(
    idx: int, path: list[str], col_texts: list[str],
    global_segments: frozenset[tuple[int, str]] = frozenset(),
) -> ColumnRole:
    own = [seg for i, seg in enumerate(path) if (i, seg) not in global_segments]
    joined = " ".join(own)
    if _ORDINAL.match(joined):
        return ColumnRole.ORDINAL
    if _MA_SO.search(joined):
        return ColumnRole.METRIC_CODE
    if _NOTE_REF.search(joined):
        return ColumnRole.NOTE_REFERENCE
    body = [t for t in col_texts if t.strip()]
    if not body:
        return ColumnRole.UNKNOWN
    n_num = sum(1 for t in body if _looks_numeric(t))
    ratio = n_num / len(body)
    if ratio >= 0.5:
        return ColumnRole.VALUE
    if idx == 0 or ratio < 0.15:
        return ColumnRole.LABEL
    return ColumnRole.UNKNOWN


_DIGIT = re.compile(r"\d")


def _digit_count(text: str) -> int | None:
    """Số chữ số của một ô SỐ. Trả None nếu ô không phải số."""
    t = text.strip()
    if not t or not _PURE_SYMBOLIC.match(t):
        return None
    return len(_DIGIT.findall(t)) or None


def _demote_reference_columns(st: StructuredTable, grid, body_rows) -> None:
    """Hạ cột `value` toàn số RẤT NGẮN xuống `note_reference`.

    Đo được 14.459 ô "tiền" có |giá trị| < 1.000 VND trong báo cáo chính, và mẫu
    chỉ đúng thủ phạm: một cột mang mã 110→4, 120→5, 131→6, 132→7 — số hiệu
    thuyết minh chạy tuần tự, không phải số liệu.

    Cột `Thuyết minh` không phải lúc nào cũng có nhãn đọc được. Khi nhãn mất,
    thứ duy nhất còn phân biệt được số hiệu với số tiền là **độ dài chữ số**:
    số hiệu có 1–2 chữ số, số tiền trong báo cáo tài chính Việt Nam có 6 chữ số
    trở lên.

    Điều kiện chặt để không hạ nhầm: phải có ít nhất một cột giá trị khác trong
    cùng bảng đạt trung vị ≥ 6 chữ số. Bảng toàn số nhỏ (bảng đếm nhân sự, bảng
    tỷ lệ) không có cột nào như vậy nên không bị đụng tới.
    """
    stats: dict[int, tuple[float, float]] = {}   # col → (trung vị, tỷ lệ ≤2 chữ số)
    for c in st.columns:
        if c.column_role is not ColumnRole.VALUE or "percent_header" in c.flags:
            continue
        lens = sorted(x for x in (_digit_count(grid[r][c.grid_col_idx])
                                  for r in body_rows) if x)
        if len(lens) >= 3:
            stats[c.grid_col_idx] = (
                lens[len(lens) // 2],
                sum(1 for x in lens if x <= 2) / len(lens),
            )
    if len(stats) < 2 or max(m for m, _ in stats.values()) < 6:
        return
    for c in st.columns:
        s = stats.get(c.grid_col_idx)
        if s and s[0] <= 2 and s[1] >= 0.8:
            c.column_role = ColumnRole.NOTE_REFERENCE
            c.flags.append("demoted_short_digits")


def _row_role(label_raw: str, has_value: bool, is_generic: bool) -> RowRole:
    if not label_raw.strip():
        return RowRole.EMPTY if not has_value else RowRole.UNKNOWN
    if _TOTAL_HINT.match(label_raw.strip()):
        return RowRole.TOTAL
    if _SUBTOTAL_HINT.match(label_raw.strip()) or is_generic:
        return RowRole.SUBTOTAL if has_value else RowRole.SECTION
    if not has_value:
        return RowRole.SECTION
    return RowRole.METRIC


def classify_statement(
    body_text: str, context_text: str, numeric_ratio: float
) -> tuple[str, str]:
    """Trả (statement_type, rule_id). Tín hiệu context có trọng số thấp hơn."""
    if _NOTE_MARKER.search(context_text) and numeric_ratio >= 0.15:
        note_score = 1.0
    else:
        note_score = 0.0

    scores: dict[str, float] = {}
    for kind, sigs in _SIG.items():
        body_hits = sum(1 for s in sigs if s in body_text)
        ctx_hits = sum(1 for s in sigs if s in context_text)
        scores[kind] = body_hits + _CONTEXT_WEIGHT * ctx_hits

    if scores["toc"] >= 2 and numeric_ratio < 0.35:
        return "toc", "R-TOC"
    if scores["personnel"] >= 2 and numeric_ratio < 0.30:
        return "personnel", "R-PERSONNEL"
    if scores["subsidiary"] >= 2:
        return "subsidiary", "R-SUBSIDIARY"

    best = max(("balance_sheet", "income_statement", "cash_flow", "equity_change"),
               key=lambda k: scores[k])
    # Bảng thuyết minh thắng khi có số hiệu mục ở context và tín hiệu báo cáo
    # chính chỉ đến từ context chứ không từ nội dung bảng.
    if note_score > 0 and scores[best] < 2.0:
        return "note", "R-NOTE-MARKER"
    if scores[best] >= 2.0:
        return best, f"R-BODY-{best.upper()}"
    if numeric_ratio >= 0.20:
        return "note", "R-NUMERIC-FALLBACK"
    return "other", "R-NONE"


def interpret_structure(
    pt: ParsedTable, context_text: str, section_text: str
) -> StructuredTable:
    st = StructuredTable(table_uid=pt.table_uid, n_header_rows=0)
    if not pt.ok or pt.n_grid_rows == 0:
        st.flags.append(f"parse_{pt.parse_status.value}")
        return st

    n_header, hdr_flags = _detect_header_rows(pt)
    st.n_header_rows = n_header
    st.flags += hdr_flags
    paths = _column_paths(pt, n_header)

    body_rows = range(n_header, pt.n_grid_rows)
    grid = [pt.row_texts(r) for r in range(pt.n_grid_rows)]

    all_body = [grid[r][c] for r in body_rows for c in range(pt.n_grid_cols)]
    filled = [t for t in all_body if t.strip()]
    st.numeric_ratio = (
        sum(1 for t in filled if _looks_numeric(t)) / len(filled) if filled else 0.0
    )

    global_segments = frozenset(_global_header_segments(paths))
    if global_segments:
        st.flags.append("global_header_segment")

    for c in range(pt.n_grid_cols):
        col_texts = [grid[r][c] for r in body_rows]
        role = _classify_column(c, paths[c], col_texts, global_segments)
        body = [t for t in col_texts if t.strip()]
        ratio = (sum(1 for t in body if _looks_numeric(t)) / len(body)) if body else 0.0
        info = ColumnInfo(
            table_uid=pt.table_uid, grid_col_idx=c, column_role=role,
            header_path_json=paths[c] or [f"c{c}"], numeric_ratio=round(ratio, 4),
        )
        if _PERCENT_HDR.search(" ".join(paths[c])):
            info.flags.append("percent_header")
        st.columns.append(info)
        if role is ColumnRole.METRIC_CODE and st.ma_so_col_idx is None:
            st.ma_so_col_idx = c
        elif role is ColumnRole.NOTE_REFERENCE:
            st.note_ref_col_idx.append(c)
        elif role is ColumnRole.LABEL and st.label_col_idx is None:
            st.label_col_idx = c

    if st.label_col_idx is None:
        st.label_col_idx = 0
        st.flags.append("label_col_fallback")

    # Phải chạy TRƯỚC khi chốt `value_cols`: cột bị hạ không được tính là cột
    # giá trị khi dựng nhãn dòng, và không được sinh observation.
    _demote_reference_columns(st, grid, body_rows)
    st.note_ref_col_idx = [c.grid_col_idx for c in st.columns
                           if c.column_role is ColumnRole.NOTE_REFERENCE]

    value_cols = {c.grid_col_idx for c in st.columns
                  if c.column_role is ColumnRole.VALUE}
    stack: list[tuple[int, str]] = []
    last_level = -1
    section_parts = [section_text] if section_text else []

    for r in range(pt.n_grid_rows):
        if r < n_header:
            st.rows.append(RowInfo(
                pt.table_uid, r, RowRole.HEADER, "", "", list(section_parts), 0))
            continue
        raw = ""
        for c in range(pt.n_grid_cols):
            if c in value_cols or c == st.ma_so_col_idx:
                continue
            t = grid[r][c].strip()
            if t and not _PURE_SYMBOLIC.match(t):
                raw = t
                break
        has_value = any(_looks_numeric(grid[r][c]) for c in value_cols)
        label = normalize_label(raw) or raw
        is_generic = _fold(label) in _GENERIC
        role = _row_role(raw, has_value, is_generic)

        lvl = _level_of(raw)
        if lvl is None:
            lvl = last_level + 1 if stack else 0
        else:
            last_level = lvl
        while stack and stack[-1][0] >= lvl:
            stack.pop()

        parts = list(section_parts) + [p for _, p in stack]
        parts = parts[-(MAX_PATH_DEPTH - 1):] + ([label] if label else [])

        st.rows.append(RowInfo(
            table_uid=pt.table_uid, grid_row_idx=r, row_role=role,
            label_source=raw, label_clean=label,
            row_path_json=parts or [f"r{r}"], row_level=lvl,
            metric_code=(grid[r][st.ma_so_col_idx].strip()
                         if st.ma_so_col_idx is not None else None) or None,
            is_generic_label=is_generic,
        ))
        if role in (RowRole.SECTION, RowRole.HEADER) and label:
            stack.append((lvl, label))

    body_text = " ".join(filled)
    st.statement_type, st.statement_rule = classify_statement(
        body_text, context_text, st.numeric_ratio)
    st.is_data_table = (
        st.statement_type not in {"toc", "personnel", "other"}
        and st.numeric_ratio >= 0.15
        and bool(value_cols)
    )
    if not value_cols:
        st.flags.append("no_value_column")
    if st.numeric_ratio < 0.10:
        st.flags.append("low_numeric")
    return st
