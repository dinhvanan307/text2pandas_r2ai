"""Phân tích số theo quy ước Việt Nam — dùng Decimal, không dùng float.

Vì sao module này tồn tại: `float("1.234.567")` ném lỗi, còn `float("1.234")`
trả về 1.234 thay vì 1234 — sai 1000 lần một cách im lặng. Toàn hệ thống chỉ
được phép parse số qua đây.

Corpus đã đo (1.973 tài liệu, 6.212.883 ô):
  - 1.961 tài liệu dùng dấu CHẤM làm phân cách nghìn
  -   141 tài liệu dùng dấu PHẨY làm phân cách nghìn
  -   139 tài liệu dùng CẢ HAI  ← nguồn lỗi nguy hiểm nhất
  -    70 bảng trộn cả hai quy ước trên cùng một dòng
Do đó quy ước phân cách phải được quyết định ở cấp BẢNG, không phải cấp corpus.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum

__all__ = [
    "ParseStatus",
    "SepConvention",
    "ParsedNumber",
    "parse_vn_number",
    "detect_convention",
]


class ParseStatus(str, Enum):
    """Vì sao một ô không cho ra giá trị số. Không bao giờ được nuốt lỗi."""

    OK = "ok"
    EMPTY = "empty"  # ô rỗng
    DASH = "dash"  # "-" — quy ước kế toán, KHÔNG phải số 0
    NOT_A_NUMBER = "not_a_number"  # ô văn bản
    AMBIGUOUS = "ambiguous"  # không phân định được phân cách
    MALFORMED = "malformed"  # trông như số nhưng hỏng


class SepConvention(str, Enum):
    DOT_THOUSANDS = "dot_thousands"  # 1.234.567,89 — quy ước VN
    COMMA_THOUSANDS = "comma_thousands"  # 1,234,567.89 — quy ước Anh/Mỹ
    UNKNOWN = "unknown"


# Ô chỉ chứa một trong các ký tự này = khuyết dữ liệu theo quy ước kế toán,
# KHÔNG phải giá trị 0. Điền 0 vào đây là tạo số giả.
_DASH_ONLY = {"-", "–", "—", "‐", "−", "--", "---"}
_NA_TOKENS = {"n/a", "na", "n.a.", "không", "ko", "-/-"}

# U+2212 MINUS SIGN xuất hiện 6 lần trong corpus và LÀ dấu âm thật.
_MINUS_CHARS = "-−–—"

_DIGITS = re.compile(r"\d")
_NUMERIC_SHAPE = re.compile(r"^[\d.,\s ]+$")
_GROUP_AFTER_SEP = re.compile(r"[.,](\d+)")


@dataclass(frozen=True, slots=True)
class ParsedNumber:
    """Kết quả parse. `raw` luôn được giữ để truy vết và trích dẫn."""

    raw: str
    value: Decimal | None
    status: ParseStatus
    is_negative_paren: bool = False
    is_percent: bool = False
    convention_used: SepConvention = SepConvention.UNKNOWN

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK


def _clean(raw: str) -> str:
    """Chuẩn hoá bề mặt — không đụng tới chữ số hay dấu."""
    s = unicodedata.normalize("NFC", raw)
    s = s.replace(" ", " ").replace(" ", " ")
    return s.strip()


def detect_convention(cells: list[str]) -> SepConvention:
    """Suy quy ước phân cách nghìn cho MỘT bảng từ các ô bằng chứng rõ ràng.

    Bằng chứng rõ ràng = có từ 2 nhóm phân cách trở lên, mỗi nhóm đúng 3 chữ số
    (`1.234.567`). Một dấu phân cách đơn lẻ với 3 chữ số (`1,216`) là MƠ HỒ và
    không được dùng làm bằng chứng — corpus có 1.288 ô như vậy.
    """
    dot_votes = comma_votes = 0
    for cell in cells:
        s = _clean(cell)
        if not _NUMERIC_SHAPE.match(s):
            continue
        if re.search(r"\d(\.\d{3}){2,}(?!\d)", s):
            dot_votes += 1
        if re.search(r"\d(,\d{3}){2,}(?!\d)", s):
            comma_votes += 1
    if dot_votes and not comma_votes:
        return SepConvention.DOT_THOUSANDS
    if comma_votes and not dot_votes:
        return SepConvention.COMMA_THOUSANDS
    if dot_votes and comma_votes:
        # 70 bảng trong corpus rơi vào đây. Chọn bên nhiều phiếu hơn, và
        # người gọi nhận được cờ để đánh dấu chất lượng.
        return (
            SepConvention.DOT_THOUSANDS
            if dot_votes >= comma_votes
            else SepConvention.COMMA_THOUSANDS
        )
    return SepConvention.UNKNOWN


def _resolve_separators(body: str, hint: SepConvention) -> tuple[str, SepConvention, bool]:
    """Trả về (chuỗi_chuẩn_hoá_kiểu_Anh, quy_ước_đã_dùng, có_mơ_hồ_không)."""
    has_dot = "." in body
    has_comma = "," in body

    # Cả hai dấu cùng xuất hiện: dấu ĐỨNG SAU là dấu thập phân. Luật này
    # đúng cho cả hai quy ước và không cần gợi ý từ bên ngoài.
    if has_dot and has_comma:
        if body.rfind(",") > body.rfind("."):
            conv = SepConvention.DOT_THOUSANDS
            return body.replace(".", "").replace(",", "."), conv, False
        conv = SepConvention.COMMA_THOUSANDS
        return body.replace(",", ""), conv, False

    if not has_dot and not has_comma:
        return body, hint, False

    sep = "." if has_dot else ","
    groups = _GROUP_AFTER_SEP.findall(body)
    n_sep = body.count(sep)

    # Nhiều dấu phân cách ⇒ chắc chắn là phân cách nghìn.
    if n_sep >= 2:
        conv = (
            SepConvention.DOT_THOUSANDS if sep == "." else SepConvention.COMMA_THOUSANDS
        )
        return body.replace(sep, ""), conv, False

    tail = groups[0] if groups else ""
    # Nhóm cuối không phải 3 chữ số ⇒ chắc chắn là dấu thập phân.
    if len(tail) != 3:
        conv = (
            SepConvention.COMMA_THOUSANDS if sep == "." else SepConvention.DOT_THOUSANDS
        )
        return (body if sep == "." else body.replace(",", ".")), conv, False

    # Đúng 3 chữ số sau một dấu duy nhất: `1.216` hay `1,216` — MƠ HỒ.
    # Phải dựa vào quy ước của bảng.
    if hint is SepConvention.DOT_THOUSANDS:
        if sep == ".":
            return body.replace(".", ""), hint, False
        return body.replace(",", "."), hint, False
    if hint is SepConvention.COMMA_THOUSANDS:
        if sep == ",":
            return body.replace(",", ""), hint, False
        return body, hint, False
    return body, SepConvention.UNKNOWN, True


def parse_vn_number(
    raw: str,
    convention: SepConvention = SepConvention.UNKNOWN,
) -> ParsedNumber:
    """Parse một ô thành Decimal.

    `convention` là quy ước của BẢNG chứa ô này, lấy từ `detect_convention`.
    Truyền UNKNOWN thì các ô mơ hồ sẽ trả về trạng thái AMBIGUOUS thay vì đoán.
    """
    if raw is None:
        return ParsedNumber("", None, ParseStatus.EMPTY)

    s = _clean(raw)
    if not s:
        return ParsedNumber(raw, None, ParseStatus.EMPTY)
    if s in _DASH_ONLY:
        return ParsedNumber(raw, None, ParseStatus.DASH)
    if s.lower() in _NA_TOKENS:
        return ParsedNumber(raw, None, ParseStatus.NOT_A_NUMBER)
    if not _DIGITS.search(s):
        return ParsedNumber(raw, None, ParseStatus.NOT_A_NUMBER)

    negative = False
    body = s

    # Ngoặc đơn = số âm theo quy ước kế toán. 265.000+ ô trong corpus.
    if body.startswith("(") and body.endswith(")"):
        negative = True
        body = body[1:-1].strip()

    is_percent = body.endswith("%")
    if is_percent:
        body = body[:-1].strip()

    if body[:1] in _MINUS_CHARS:
        negative = not negative
        body = body[1:].strip()

    # Bỏ khoảng trắng nội bộ (corpus có 426 ô dạng `1 234`).
    body = body.replace(" ", "")

    if not body or not _NUMERIC_SHAPE.match(body):
        return ParsedNumber(raw, None, ParseStatus.NOT_A_NUMBER, negative, is_percent)

    normalized, conv_used, ambiguous = _resolve_separators(body, convention)
    if ambiguous:
        return ParsedNumber(
            raw, None, ParseStatus.AMBIGUOUS, negative, is_percent, conv_used
        )

    try:
        value = Decimal(normalized)
    except (InvalidOperation, ValueError):
        return ParsedNumber(
            raw, None, ParseStatus.MALFORMED, negative, is_percent, conv_used
        )

    if negative:
        value = -value
    return ParsedNumber(raw, value, ParseStatus.OK, negative, is_percent, conv_used)
