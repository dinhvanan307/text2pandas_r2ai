"""DP-008 — D4a/D4b: phân loại value-kind và parse số exact.

Hai điều không bao giờ được làm, đã ghi thành test:
  - `dash`, ô rỗng, `N/A` **không** thành 0 (DI-06). Chúng chiếm 17,0% số ô;
    điền 0 là tạo ra hơn nửa triệu con số không tồn tại trong báo cáo.
  - Ô mơ hồ **không** bị đoán (DI-07). Trả `ambiguous` kèm bằng chứng.

Quy ước phân cách nghìn được quyết định theo **thứ bậc bằng chứng**, không
theo một hằng số toàn corpus: 1.961 tài liệu dùng dấu chấm, 141 dùng dấu
phẩy, **139 dùng cả hai**, và 70 bảng trộn hai quy ước trên cùng một dòng.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from data_pipeline.models import EvidenceSource, ParseStatus, ValueKind

__all__ = ["NumberParse", "SepConvention", "parse_number", "detect_convention",
           "classify_value_kind", "is_unit_ambiguous_share_cell",
           "is_percent_value_implausible", "PERCENT_ABS_MAX", "NUMBER_VERSION"]

NUMBER_VERSION = "1.4"

# A5-A2 · trần độ lớn của một ô được phân loại PHẦN TRĂM.
#
# Ngưỡng đến từ số đo, không từ cảm tính. Trên build A4, 103.193 ô
# `percentage` là candidate; phân bố |value| của chúng:
#
#     < 1.000        102.748
#     [1e3, 1e4)          2
#     [1e4, 1e6)         75
#     >= 1e6            368
#
# Đuôi đó không phải tỷ lệ. Mẫu: 38.708.428.190.000 ở cột
# `01/01/2024 › (%)`, 3.900.000.000.000 ở `31/12/2021 › % sở hữu` — ô TIỀN
# bị gán nhầm vì `header_path` gộp cột tiền với cột `%` liền kề.
#
# Đặt trần ở 1.000 loại 445 ô, trong đó chỉ 2 ô ở dải [1e3,1e4) là còn có
# thể là tỷ lệ thật (nợ/vốn chủ sở hữu của doanh nghiệp kiệt quệ). Đổi 2 ô
# nghi-đúng lấy 443 ô chắc-sai. Và 2 ô đó KHÔNG mất: cờ này chặn ready,
# không loại observation.
PERCENT_ABS_MAX = Decimal("1000")


class SepConvention(str):
    DOT = "dot_thousands"      # 1.234.567,89 — quy ước VN
    COMMA = "comma_thousands"  # 1,234,567.89 — quy ước Anh/Mỹ
    UNKNOWN = "unknown"


_DASH_ONLY = {"-", "–", "—", "‐", "−", "--", "---", "- -"}
_NA = {"n/a", "na", "n.a.", "không", "ko", "-/-", "n/m"}
_MINUS = "-−–—"
_DIGIT = re.compile(r"\d")
_SHAPE = re.compile(r"^[\d.,\s ]+$")
_GROUP = re.compile(r"[.,](\d+)")
_DATE = re.compile(r"^\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{2,4}$|^\d{1,2}\s*/\s*20\d{2}$")
_CODE = re.compile(r"^\d{2,3}$")
_NOTE = re.compile(r"^\d{1,2}(\.\d{1,2}){1,2}$")
_MULTI_DOT = re.compile(r"\d(\.\d{3}){2,}(?!\d)")
_MULTI_COMMA = re.compile(r"\d(,\d{3}){2,}(?!\d)")
# Một số có phân cách nghìn có HÌNH DẠNG chặt: 1–3 chữ số rồi từng nhóm đúng 3.
# `97.158.150.939396.219.749.004` vi phạm (nhóm `939396` có 6 chữ số) — đó là
# HAI con số dính liền, không phải một số 23 chữ số.
_GROUPED = {".": re.compile(r"^\d{1,3}(?:\.\d{3})+$"),
            ",": re.compile(r"^\d{1,3}(?:,\d{3})+$")}

# Trần độ lớn cho ô TIỀN. Tổng tài sản lớn nhất corpus ở mức 2×10^15 VND, nên
# 10^16 để dư 5 lần. Và vì `scale_exponent` chỉ NHÂN LÊN ở bước sau, một ô đã
# vượt trần ngay từ chữ số thô thì không có cách nào là số liệu thật.
#
# Kiểm hình dạng bắt được 3.629/3.633 ca hai số dính liền. Bốn ca sót lại dính
# nhau qua đúng một dấu phân cách (`…939.396…`), nên hình dạng vẫn hợp lệ —
# không cấu trúc nào phân biệt được. Chỉ còn độ lớn.
_MAX_MONEY = Decimal(10) ** 16


@dataclass(slots=True)
class NumberParse:
    value_source: str
    value_clean: str
    value_decimal: Decimal | None
    status: ParseStatus
    parse_rule: str
    is_negative: bool = False
    value_kind: ValueKind = ValueKind.UNKNOWN
    convention_used: str = SepConvention.UNKNOWN
    evidence: EvidenceSource = EvidenceSource.NONE

    @property
    def ok(self) -> bool:
        return self.status is ParseStatus.OK


def _clean(raw: str) -> str:
    s = unicodedata.normalize("NFC", raw)
    return s.replace(" ", " ").replace(" ", " ").strip()


def detect_convention(cells: list[str]) -> tuple[str, int, int]:
    """Suy quy ước từ các ô có bằng chứng RÕ RÀNG (≥2 nhóm 3 chữ số).

    Một dấu phân cách đơn lẻ với đúng 3 chữ số (`1,216`) là MƠ HỒ và không
    được dùng làm bằng chứng — corpus có 1.288 ô như vậy.
    """
    dot = comma = 0
    for cell in cells:
        s = _clean(cell)
        if not _SHAPE.match(s):
            continue
        if _MULTI_DOT.search(s):
            dot += 1
        if _MULTI_COMMA.search(s):
            comma += 1
    if dot and not comma:
        return SepConvention.DOT, dot, comma
    if comma and not dot:
        return SepConvention.COMMA, dot, comma
    if dot and comma:
        return (SepConvention.DOT if dot >= comma else SepConvention.COMMA), dot, comma
    return SepConvention.UNKNOWN, 0, 0


def _shape_allows(s: str, kind: str) -> bool:
    """Hình dạng chuỗi thô có cho phép ô này mang `kind` không?

    Chạy TRƯỚC khi parse, nên không dùng được giá trị số. Nhưng hình dạng đủ
    để loại những ca bất khả:

    * **Nhóm nghìn** — `485.554` khớp `\\d{1,3}(\\.\\d{3})+` nghĩa là một số
      LỚN, không phải `4,85%`. Đây là dấu hiệu quyết định, vì lãi suất và số
      ngày không bao giờ được viết dưới dạng phân cách nghìn.
    * **Số chữ số** — lãi suất tối đa `100,00` là 5 chữ số; số ngày tối đa
      `36.500` là 5. Vượt là bất khả.
    * **Dấu âm** — số cổ phiếu âm không tồn tại.

    Không đoán chiều nào là đúng: chỉ trả `False` khi hình dạng **loại trừ**
    kiểu đó. Nghi ngờ thì cho qua, để tầng sau xử lý (DI-07).
    """
    body = s.lstrip("(").rstrip(")%").strip()
    negative = body[:1] in _MINUS or s.startswith("(")
    digits = len(_DIGIT.findall(body))
    grouped = any(rx.match(body.lstrip("".join(_MINUS))) for rx in _GROUPED.values())

    if kind == "rate":
        # `12,75` · `7,5` · `4.4` qua được. `485.554` · `4.400.485` bị loại.
        return not grouped and digits <= 5
    if kind == "days":
        return not grouped and digits <= 5 and not negative
    if kind == "count_signed":
        # RC2-037 · CỔ PHIẾU QUỸ được trình bày trong ngoặc đơn vì nó là khoản
        # TRỪ khỏi vốn chủ sở hữu — `(978.328)` cổ phiếu quỹ là số cổ phiếu
        # thật, không phải tiền. Luật "số cổ phiếu âm không tồn tại" đúng với
        # số lượng lưu hành nhưng SAI với cổ phiếu quỹ, và nó đã đẩy 2.599 ô
        # trên cột ghi rõ "Số cổ phiếu" sang `money`.
        #
        # Chỉ nới cho cột đếm TƯỜNG MINH (xem `_explicit_share_count_column`),
        # không nới cho mọi nhãn có chữ "cổ phần".
        return digits <= 12
    if kind == "count":
        # Nhóm nghìn HỢP LỆ với số cổ phiếu (`1.000.000` cổ phiếu). Chỉ loại
        # số âm và số vượt 12 chữ số — tổng số cổ phiếu niêm yết toàn thị
        # trường Việt Nam còn chưa tới 10¹¹.
        return not negative and digits <= 12
    return True


# RC2-037 · Cột ĐẾM cổ phiếu tường minh.
#
# Ba loại nhãn dễ nhầm, và chúng phải được đối xử khác nhau:
#   "Số cổ phiếu", "Cổ phiếu quỹ"        -> ĐẾM (được phép âm)
#   "Thặng dư vốn cổ phần", "Vốn cổ phần VND" -> TIỀN (chỉ tình cờ có "cổ phần")
#   "Lãi cơ bản trên cổ phiếu"           -> TIỀN trên mỗi cổ phiếu, KHÔNG phải đếm
#
# Có dấu hiệu tiền tệ trong nhãn thì loại thẳng: một cột vừa khai VND vừa đếm
# cổ phiếu không tồn tại.
# RC2-039 · HAI mức tín hiệu đếm, vì cùng một cụm từ không mang cùng sức nặng
# ở nhãn cột và nhãn dòng.
#
# MẠNH — tự nói ra rằng đang đếm ("số lượng", "đơn vị tính là cổ phiếu"), hoặc
# là khoản trừ đo bằng cổ phiếu ("cổ phiếu quỹ"). Đúng ở CẢ hai nhãn.
_SHARE_COUNT_STRONG = re.compile(
    r"số\s*(?:lượng\s*)?(?:cổ\s*phi[ếe]u|cp)\b"
    r"|cổ\s*phi[ếe]u\s*quỹ"
    r"|đơn\s*vị\s*(?:tính)?\s*[::]?\s*(?:là\s*)?cổ\s*phi[ếe]u", re.I)
# YẾU — chỉ nêu LOẠI cổ phiếu. Ở tiêu đề CỘT nó thường là cột đếm; ở nhãn DÒNG
# thì "Cổ phiếu phổ thông" gần như luôn là khoản mục vốn tính bằng VND. Đo trên
# `7aa8b4c22984bf5f`: áp bộ này sang nhãn dòng làm 30.622 ô đổi sang đếm, gấp
# sáu lần bán kính đã khảo sát. Nên nó bị giữ lại ở phạm vi nhãn cột.
_SHARE_COUNT_WEAK = re.compile(
    r"cổ\s*phi[ếe]u\s*(?:thường|phổ\s*thông|ưu\s*đãi)", re.I)
_SHARE_COUNT_COL = re.compile(
    f"({_SHARE_COUNT_STRONG.pattern})|({_SHARE_COUNT_WEAK.pattern})", re.I)
# Chỉ loại khi nhãn mang dấu hiệu TIỀN thật sự. Từ chỉ BẬC đứng một mình
# (`triệu`, `nghìn`) KHÔNG bị loại: "triệu cổ phiếu" là bậc của số lượng, không
# phải tiền — loại nó sẽ đẩy một cột đếm sang `money`, đúng lỗi đang đi sửa.
_SHARE_COUNT_COL_NOT = re.compile(
    r"vnd|vnđ|\bđồng\b"
    r"|lãi\s*(?:cơ\s*bản|suy\s*giảm)\s*trên"   # EPS: tiền TRÊN MỖI cổ phiếu
    r"|thặng\s*dư|mệnh\s*giá|giá\s*trị|\bvốn\b", re.I)


def _explicit_share_count_column(header_low: str) -> bool:
    if _SHARE_COUNT_COL_NOT.search(header_low):
        return False
    return bool(_SHARE_COUNT_COL.search(header_low))


def _explicit_share_count_ctx(col_low: str, row_low: str) -> bool:
    """Tín hiệu đếm tường minh, xét đúng sức nặng của từng nhãn.

    Loại trừ dấu hiệu TIỀN giữ nguyên phạm vi nhãn CỘT như bản trước. Mở nó
    sang nhãn dòng làm 10.969 ô đang là đếm rơi ngược về tiền — một thay đổi
    hai chiều nằm ngoài phạm vi đã khảo sát.
    """
    if _SHARE_COUNT_COL_NOT.search(col_low):
        return False
    if _SHARE_COUNT_COL.search(col_low):          # cột: mạnh + yếu
        return True
    return bool(_SHARE_COUNT_STRONG.search(row_low))   # dòng: chỉ mạnh


def is_percent_value_implausible(value_kind, value_decimal) -> bool:
    """A5-A2 · ô phân loại PHẦN TRĂM mà độ lớn không thể là phần trăm.

    Đối xứng với `N-IMPLAUSIBLE-MAGNITUDE` của tiền, khác một điểm có chủ ý:
    tiền quá lớn thì DỪNG parse (giá trị vô nghĩa), còn phần trăm quá lớn thì
    giá trị vẫn là một con số THẬT trong tài liệu — chỉ có nhãn đơn vị là sai.
    Loại nó đi là mất dữ liệu; gắn cờ để readiness chặn là giữ dữ liệu mà
    không cho nó tự động chảy vào phép tính.

    Ngưỡng: xem `PERCENT_ABS_MAX`.
    """
    if value_kind is not ValueKind.PERCENTAGE or value_decimal is None:
        return False
    return abs(value_decimal) >= PERCENT_ABS_MAX


def is_unit_ambiguous_share_cell(
    value_text: str, header_path: str, row_path: str, is_negative: bool
) -> bool:
    """RC2-039 · ô mà nhãn nói "cổ phiếu" nhưng KHÔNG đủ bằng chứng để kết luận
    đơn vị là đếm hay tiền.

    Đây là phần dư sau khi `classify_value_kind` đã lấy hết những ca kết luận
    được: nhãn cột nêu cổ phiếu, giá trị âm, không quá 12 chữ số, mà không có
    tín hiệu đếm tường minh ở cả hai nhãn và cũng không có dấu hiệu tiền.

    Trước đây phần dư này im lặng đi vào `execution_ready`. Đo trên
    `7aa8b4c22984bf5f`: 98 ô như vậy được phát hành như dữ liệu sẵn sàng, 65
    trong đó mang tín hiệu đếm mà luật cũ không nhìn thấy. Bản này gắn cờ để
    readiness chặn chúng theo chính sách, thay vì để người dùng cuối tự phát
    hiện.
    """
    low = (header_path or "").lower()
    row_low = (row_path or "").lower()
    if "cổ phi" not in low and "cổ phần" not in low:
        return False
    if not is_negative:
        return False
    if _SHARE_COUNT_COL_NOT.search(low):
        return False
    if _SHARE_COUNT_COL.search(low) or _SHARE_COUNT_STRONG.search(row_low):
        return False                       # đã kết luận được là ĐẾM
    return len(re.sub(r"\D", "", value_text or "")) <= 12


def classify_value_kind(
    text: str, column_role: str, header_path: str, has_percent: bool,
    row_path: str = "",
) -> ValueKind:
    """Phân loại TRƯỚC khi parse số. Ngăn nhân hệ số tiền tệ vào ô phần trăm.

    RC2-039 · `row_path` được thêm vì bản trước CHỈ đọc nhãn cột, và đo trên
    build `7aa8b4c22984bf5f` cho thấy điều đó bỏ sót cả một lớp lỗi: trong 65
    ô `execution_ready` mang tín hiệu đếm tường minh, **50 ô có tín hiệu chỉ ở
    nhãn dòng và 0 ô chỉ ở nhãn cột**. Nhãn dòng "Số lượng cổ phiếu được mua
    lại" nói rõ đây là số lượng, còn nhãn cột chỉ ghi kỳ.

    Chỉ nhánh ĐẾM cổ phiếu đọc ngữ cảnh mở rộng. Các nhánh khác — phần trăm,
    lãi suất, ngày — giữ nguyên phạm vi nhãn cột, vì mở rộng chúng là thay đổi
    ngoài phạm vi đã đo.
    """
    s = _clean(text)
    if not s:
        return ValueKind.NOT_A_VALUE
    if column_role == "metric_code":
        return ValueKind.METRIC_CODE
    if column_role == "note_reference":
        return ValueKind.NOTE_REFERENCE
    if _DATE.match(s):
        return ValueKind.DATE
    if s.endswith("%") or has_percent:
        return ValueKind.PERCENTAGE
    low = header_path.lower()
    # Ngữ cảnh ĐẾM = nhãn cột + nhãn dòng. Loại trừ dấu hiệu TIỀN cũng xét
    # trên cùng ngữ cảnh đó, nếu không thì mở một nửa và bịt nửa kia.
    row_low = (row_path or "").lower()
    # Cổng vào nhánh đếm mở sang nhãn dòng, nhưng CHỈ với tín hiệu mạnh.
    ctx = low if not row_low else (
        low if not _SHARE_COUNT_STRONG.search(row_low) else f"{low} {row_low}")
    if "%" in low or "tỷ lệ" in low or "phần trăm" in low:
        return ValueKind.PERCENTAGE
    # Ba kiểu dưới đây suy từ TỪ KHOÁ trong nhãn cột, và từ khoá là bằng chứng
    # YẾU: một bảng ngân hàng có tiêu đề chứa "lãi suất" thì MỌI ô trong bảng
    # nhận `interest_rate`, kể cả số dư tiền. Đo trên `b927c3e8f90aed74`:
    #
    #     interest_rate       52 / 9.997  hợp lý =  0,5%
    #     days                21 /   969  hợp lý =  2,2%
    #     share_count     39.384 / 57.037 hợp lý = 69,0%
    #
    # Mẫu thật: `485.554` với nhãn dòng `Tiền mặt` được gán `interest_rate`.
    #
    # Đây là cùng lớp lỗi với tiny-money: phân loại bằng tín hiệu văn bản rồi
    # KHÔNG BAO GIỜ kiểm lại kết quả có khả dĩ không. Nên mỗi nhánh phải qua
    # `_shape_allows()` — cổng hình dạng rẻ, chạy trên chuỗi thô.
    if ("lãi suất" in low or "interest" in low) and _shape_allows(s, "rate"):
        return ValueKind.INTEREST_RATE
    if (("cổ phiếu" in ctx or "cổ phần" in ctx or "số lượng cp" in ctx)
            and not _SHARE_COUNT_COL_NOT.search(low)):
        # RC2-037 · ba loại nhãn, ba cách đối xử:
        #   "Số cổ phiếu", "Cổ phiếu quỹ"   -> ĐẾM, được phép âm (cổ phiếu quỹ
        #                                      là khoản TRỪ nên ghi trong ngoặc)
        #   "Cổ phiếu phổ thông" + số 13 chữ số -> không phải đếm (toàn thị
        #                                      trường VN chưa tới 10¹¹ cổ phiếu)
        #   "Thặng dư vốn cổ phần", "Lãi cơ bản trên cổ phiếu" -> TIỀN, đã bị
        #                                      `_SHARE_COUNT_COL_NOT` loại ở trên
        if _explicit_share_count_ctx(low, row_low):
            if _shape_allows(s, "count_signed"):
                return ValueKind.SHARE_COUNT
        elif _shape_allows(s, "count"):
            return ValueKind.SHARE_COUNT
    # "ngày" chỉ là đơn vị khi nó đứng như một đại lượng ("số ngày", "kỳ thu
    # tiền (ngày)"). Trong "cho năm tài chính kết thúc ngày 31 tháng 12" nó là
    # một phần của cụm ngày tháng — nhận nhầm sẽ tước mất hệ số tiền tệ.
    if (re.search(r"số\s*ngày|\(\s*ngày\s*\)|ngày\s*$", low) and "/" not in s
            and _shape_allows(s, "days")):
        return ValueKind.DAYS
    if not _DIGIT.search(s):
        return ValueKind.NOT_A_VALUE
    if _NOTE.match(s) and column_role == "unknown":
        return ValueKind.NOTE_REFERENCE
    return ValueKind.MONEY


def _well_grouped(int_part: str, sep: str) -> bool:
    """Phần nguyên có đúng hình dạng phân cách nghìn không?"""
    if sep not in int_part:
        return int_part.isdigit()
    return bool(_GROUPED[sep].match(int_part))


def _resolve_separators(
    body: str, hint: str
) -> tuple[str | None, str, str, EvidenceSource]:
    """Trả (chuỗi chuẩn Anh, quy ước, rule, nguồn bằng chứng)."""
    has_dot, has_comma = "." in body, "," in body

    if has_dot and has_comma:
        if body.rfind(",") > body.rfind("."):
            if not _well_grouped(body[:body.rfind(",")], "."):
                return None, SepConvention.UNKNOWN, "N-MALFORMED-GROUPS", EvidenceSource.NONE
            return (body.replace(".", "").replace(",", "."),
                    SepConvention.DOT, "N-BOTH-COMMA-LAST", EvidenceSource.CELL)
        if not _well_grouped(body[:body.rfind(".")], ","):
            return None, SepConvention.UNKNOWN, "N-MALFORMED-GROUPS", EvidenceSource.NONE
        return (body.replace(",", ""),
                SepConvention.COMMA, "N-BOTH-DOT-LAST", EvidenceSource.CELL)

    if not has_dot and not has_comma:
        return body, hint, "N-NO-SEP", EvidenceSource.CELL

    sep = "." if has_dot else ","
    n_sep = body.count(sep)
    groups = _GROUP.findall(body)

    if n_sep >= 2:
        conv = SepConvention.DOT if sep == "." else SepConvention.COMMA
        if not _well_grouped(body, sep):
            # Nhiều dấu phân cách nhưng hình dạng sai ⇒ không phải một con số.
            # DI-07: không đoán. Đo được 3.633 ô vượt 10^16 VND đi lối này.
            return None, SepConvention.UNKNOWN, "N-MALFORMED-GROUPS", EvidenceSource.NONE
        return body.replace(sep, ""), conv, "N-MULTI-SEP", EvidenceSource.CELL

    tail = groups[0] if groups else ""
    if len(tail) != 3:
        conv = SepConvention.COMMA if sep == "." else SepConvention.DOT
        norm = body if sep == "." else body.replace(",", ".")
        return norm, conv, "N-DECIMAL-TAIL", EvidenceSource.CELL

    # `1.216` / `1,216` — mơ hồ, phải dựa vào quy ước cấp trên.
    if hint == SepConvention.DOT:
        norm = body.replace(".", "") if sep == "." else body.replace(",", ".")
        return norm, hint, "N-AMBIG-BY-TABLE", EvidenceSource.TABLE_CONTEXT
    if hint == SepConvention.COMMA:
        norm = body.replace(",", "") if sep == "," else body
        return norm, hint, "N-AMBIG-BY-TABLE", EvidenceSource.TABLE_CONTEXT
    return None, SepConvention.UNKNOWN, "N-AMBIGUOUS", EvidenceSource.NONE


def parse_number(
    raw: str,
    convention: str = SepConvention.UNKNOWN,
    value_kind: ValueKind = ValueKind.UNKNOWN,
) -> NumberParse:
    if raw is None:
        return NumberParse("", "", None, ParseStatus.EMPTY, "N-NULL")

    s = _clean(raw)
    if not s:
        return NumberParse(raw, "", None, ParseStatus.EMPTY, "N-EMPTY")
    if s in _DASH_ONLY:
        # Quy ước kế toán: khuyết dữ liệu. TUYỆT ĐỐI không thành 0.
        return NumberParse(raw, s, None, ParseStatus.DASH, "N-DASH")
    if s.lower() in _NA:
        return NumberParse(raw, s, None, ParseStatus.NOT_A_NUMBER, "N-NA")
    if not _DIGIT.search(s):
        return NumberParse(raw, s, None, ParseStatus.NOT_A_NUMBER, "N-NO-DIGIT")
    if value_kind in (ValueKind.DATE, ValueKind.METRIC_CODE,
                      ValueKind.NOTE_REFERENCE):
        return NumberParse(raw, s, None, ParseStatus.NOT_A_NUMBER,
                           f"N-KIND-{value_kind.value.upper()}",
                           value_kind=value_kind)

    negative = False
    body = s
    if body.startswith("(") and body.endswith(")"):
        negative = True
        body = body[1:-1].strip()
    is_percent = body.endswith("%")
    if is_percent:
        body = body[:-1].strip()
    if body[:1] in _MINUS:
        negative = not negative
        body = body[1:].strip()
    # Khoảng trắng GIỮA số: hoặc là quy ước phân cách nghìn bằng dấu cách
    # (`1 234 567`), hoặc là HAI con số nằm chung một ô. Phân biệt được bằng
    # hình dạng: quy ước dấu cách cho các nhóm đúng 3 chữ số và không có dấu
    # phân cách nào khác. Gộp thẳng như bản cũ (`body.replace(" ", "")`) biến
    # hai số thành một số khổng lồ mà không ai biết.
    tokens = body.split()
    if len(tokens) > 1:
        if (any("." in t or "," in t for t in tokens)
                or len(tokens[0]) > 3
                or any(len(t) != 3 or not t.isdigit() for t in tokens[1:])):
            return NumberParse(raw, s, None, ParseStatus.AMBIGUOUS,
                               "N-MULTI-NUMBER", negative, value_kind)
    body = "".join(tokens)

    if not body or not _SHAPE.match(body):
        return NumberParse(raw, s, None, ParseStatus.NOT_A_NUMBER,
                           "N-SHAPE", negative, value_kind)

    norm, conv, rule, evidence = _resolve_separators(body, convention)
    if norm is None:
        return NumberParse(raw, s, None, ParseStatus.AMBIGUOUS, rule,
                           negative, value_kind, conv, evidence)
    try:
        value = Decimal(norm)
    except (InvalidOperation, ValueError):
        return NumberParse(raw, s, None, ParseStatus.MALFORMED, "N-DECIMAL-FAIL",
                           negative, value_kind, conv, evidence)
    if negative:
        value = -value
    kind = value_kind
    if kind is ValueKind.UNKNOWN:
        kind = ValueKind.PERCENTAGE if is_percent else ValueKind.MONEY
    if kind is ValueKind.MONEY and abs(value) > _MAX_MONEY:
        return NumberParse(raw, s, None, ParseStatus.AMBIGUOUS,
                           "N-IMPLAUSIBLE-MAGNITUDE", negative, kind,
                           conv, evidence)
    return NumberParse(raw, s, value, ParseStatus.OK, rule,
                       negative, kind, conv, evidence)
