"""DP-009 — D4c: giải đơn vị theo BA thuộc tính độc lập.

Thiết kế cũ dùng một `unit_exponent` cấp bảng. Nó không biểu diễn được phần
trăm, số cổ phiếu, ngày, lãi suất, và không xử lý được bảng có đơn vị khác
nhau theo cột. Tách ba khái niệm:

    unit_kind        money · percent · shares · days · rate · count
    currency         VND · USD · EUR · null
    scale_exponent   0 · 3 · 6 · 9 · 12

Mỗi thuộc tính có **thứ bậc bằng chứng riêng**, không dùng một priority chung.
Nhãn cột `VND` chỉ xác nhận *currency*; nó KHÔNG nói gì về scale. Chỉ
`Đơn vị: triệu đồng` mới xác nhận scale 10⁶. Gộp hai thứ này là cách một cột
`Triệu VND` bị hiểu thành 10⁰.

9.099 khai báo `Đơn vị tính` nằm NGOÀI bảng (so với 7.111 nằm trong), phổ biến
nhất là cách đúng 2 dòng — nên resolver bắt buộc nhận cửa sổ ngữ cảnh.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from text2pandas.pipelines.a6.models import EvidenceSource, UnitKind

__all__ = ["UnitResolution", "resolve_unit", "reconcile_scale", "UNIT_VERSION"]

UNIT_VERSION = "1.9"

# ── RC-04 · biên trái: KHÔNG phải chữ cái, thay vì `\b` ─────────────────────
#
# `\b` giữa `0` và `T` không tồn tại, vì cả hai đều là ký tự từ. Nên
# `\btriệu\s*(?:đồng|vnd)` KHÔNG khớp `2020Triệu VND` — dạng nhãn cột phổ biến
# nhất của corpus này, nơi bộ trích xuất nối đơn vị vào ngay sau năm.
#
# Chính tệp này đã biết chuyện đó: `_CURRENCY_PATTERNS` bỏ `\b` ở đầu với đúng
# lý do đó (xem chú thích bên dưới, `31/12/2018VND`). Nhưng bản vá ấy chỉ áp
# cho TRỤC TIỀN TỆ, còn TRỤC BẬC thì vẫn `\b` — nên `31/12/2018Triệu VND` nhận
# đúng `VND` và mất `10⁶`.
#
# Đo trên RC1: **26.515 cột (4,48%)** có lời khai bậc trong nhãn mà regex hiện
# tại bỏ sót vì lý do này; **172.373 observation tiền** trong các cột đó đang
# mang `scale_exponent` 0 hoặc NULL.
#
# Dùng lookbehind "không phải CHỮ CÁI" chứ không phải "không phải ký tự từ":
# chữ số đứng trước là hợp lệ (`2020Triệu`), còn chữ cái đứng trước thì không
# (`batriệu`, `Xtriệu` là từ khác, không phải lời khai đơn vị).
#
# `[^\W\d_]` = ký tự từ, trừ chữ số, trừ gạch dưới = **chữ cái** theo Unicode.
# Viết vậy thay vì liệt kê `[a-zà-ỹ…]`: dải `à-ỹ` là U+00E0–U+1EF9, nó nuốt
# nguyên khối Thái, Hy Lạp, Kirin. Đo được hậu quả: nhãn
# `Dự phòng cụthe์Triệu đồng` có một dấu phụ Thái (U+0E4C) lọt vào giữa, và
# dải ấy coi nó là chữ cái nên CHẶN mất một lời khai hợp lệ. Bản liệt kê tay
# làm mất đúng 1 ca trên 591.775 — nhỏ, nhưng sai theo cách không tự lộ ra.
_NL = r"(?<![^\W\d_])"

# ── scale: từ chỉ bậc phải DÍNH VỚI ĐƠN VỊ TIỀN ─────────────────────────────
#
# `tỷ\b` khớp "tỷ lệ", "tỷ giá", "tỷ suất" — ba cụm có mặt ở gần như mọi báo
# cáo tài chính. Hậu quả đo được trên bản dựng d576dd73: một bảng ghi rõ
# `Đơn vị: VND` vẫn nhận `scale_exponent = 9`, và 1.135.279.409.795 VND thành
# 1,14 × 10²¹ VND — sai một tỷ lần, trong khi cổng vẫn xanh.
#
# "tỷ" một mình KHÔNG phải lời khai bậc. "tỷ đồng" mới là.
_SCALE_STRICT: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(_NL + r"(?:nghìn|ngàn)\s*tỷ\s*(?:đồng|vnd|đ)\b", re.I), 12),
    (re.compile(_NL + r"(?:tỷ|tỉ)\s*(?:đồng|vnd|đ)\b|" + _NL
                + r"billion\s*(?:vnd|dong)\b", re.I), 9),
    (re.compile(_NL + r"triệu\s*(?:đồng|vnd|đ)\b|" + _NL
                + r"million\s*(?:vnd|dong)\b", re.I), 6),
    (re.compile(_NL + r"(?:nghìn|ngàn)\s*(?:đồng|vnd|đ)\b|" + _NL
                + r"thousand\s*(?:vnd|dong)\b", re.I), 3),
)
# Extracted multi-level headers can concatenate the unit directly after a
# textual header leaf: ``Tổng cộngtriệu đồng`` and
# ``Giá trị ghi nhận tại thời điểm muaTriệu VND`` are common corpus forms.
# The paired currency token makes these expressions unambiguous, but this
# relaxed boundary is safe only on the column axis.  Applying it to prose or
# row labels would turn narrative amounts into table-wide unit declarations.
_SCALE_ATTACHED_COLUMN: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"(?:nghìn|ngàn)\s*tỷ\s*(?:đồng|vnd|đ)", re.I), 12),
    (re.compile(r"(?:tỷ|tỉ)\s*(?:đồng|vnd|đ)|billion\s*(?:vnd|dong)", re.I), 9),
    (re.compile(r"triệu\s*(?:đồng|vnd|đ)|million\s*(?:vnd|dong)", re.I), 6),
    (re.compile(
        r"(?:nghìn|ngàn)\s*(?:đồng|vnd|đ)|thousand\s*(?:vnd|dong)",
        re.I,
    ), 3),
)
# Trong cụm `Đơn vị tính: …` thì từ chỉ bậc đứng một mình vẫn là lời khai hợp lệ
# — "Đơn vị tính: triệu" không mơ hồ. Ngoài cụm đó thì có.
_SCALE_IN_DECL: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(_NL + r"(?:nghìn|ngàn)\s*tỷ", re.I), 12),
    # Ngay trong cụm khai báo, `tỷ` vẫn có bốn người bạn giả: tỷ lệ, tỷ giá,
    # tỷ suất, tỷ trọng. Chặn đúng bốn cụm đó thay vì nới cả nhóm.
    (re.compile(_NL + r"(?:tỷ|tỉ)\b(?!\s*(?:lệ|giá|suất|trọng))|" + _NL
                + r"billion\b", re.I), 9),
    (re.compile(_NL + r"triệu\b|" + _NL + r"million\b|" + _NL + r"mn\b", re.I), 6),
    (re.compile(_NL + r"(?:nghìn|ngàn)\b|" + _NL + r"thousand\b", re.I), 3),
)
_SCALE_PATTERNS = _SCALE_STRICT   # giữ tên cũ cho mã gọi ngoài
# currency: độc lập với scale
# KHÔNG dùng \b ở đầu: OCR nối đơn vị vào ngày tháng — `31/12/2018VND` là
# dạng phổ biến nhất (105.138 bảng khai đơn vị ở nhãn cột). `\bVND` không khớp
# vì giữa `8` và `V` không có ranh giới từ.
_CURRENCY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"VND\b|VNĐ\b|\bđồng\b|\bdong\b", re.I), "VND"),
    (re.compile(r"USD\b|US\$|\bđô\s*la\b", re.I), "USD"),
    (re.compile(r"EUR\b|€", re.I), "EUR"),
    (re.compile(r"JPY\b|\byên\b", re.I), "JPY"),
)
# Trên column axis, extractor còn có thể dính NHÃN KẾ TIẾP vào sau currency:
# ``31/12/2024Triệu VNDPhải thu``.  Vì vậy chỉ nới biên phải tại đúng tầng
# column, song song với `_SCALE_ATTACHED_COLUMN`; prose/row/table vẫn dùng bộ
# strict để không biến một từ chứa chuỗi currency thành bằng chứng đơn vị.
_CURRENCY_ATTACHED_COLUMN: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"VND|VNĐ|đồng|dong", re.I), "VND"),
    (re.compile(r"USD|US\$|đô\s*la", re.I), "USD"),
    (re.compile(r"EUR|€", re.I), "EUR"),
    (re.compile(r"JPY|yên", re.I), "JPY"),
)
_KIND_PATTERNS: tuple[tuple[re.Pattern[str], UnitKind], ...] = (
    (re.compile(r"%|phần\s*trăm|tỷ\s*lệ\s*\(%\)", re.I), UnitKind.PERCENT),
    (re.compile(r"lãi\s*suất|interest\s*rate|/\s*năm", re.I), UnitKind.RATE),
    (re.compile(r"cổ\s*phi[ếe]u|cổ\s*phần|\bshares?\b", re.I), UnitKind.SHARES),
    # `\bngày\b` khớp cả "cho năm tài chính kết thúc ngày 31 tháng 12" — câu có
    # trong ngữ cảnh của gần như mọi bảng. Chỉ nhận khi `ngày` đứng như một ĐẠI
    # LƯỢNG. Đây đúng luật đã áp cho `classify_value_kind`; thiếu đồng bộ giữa
    # hai nơi là cách 1.251.583 ô tiền bị gán đơn vị `days`.
    (re.compile(r"số\s*ngày|\(\s*ngày\s*\)|\bngày\s*$|\bdays?\b", re.I),
     UnitKind.DAYS),
    (re.compile(r"\bsố\s*lượng\b|\bcount\b", re.I), UnitKind.COUNT),
)
# Cửa sổ đếm-ký-tự KHÔNG dùng được ở đây. Cửa sổ ngữ cảnh nối các dòng bằng một
# dấu cách, nên `Đơn vị tính: VND` dính liền câu kế tiếp:
#
#     "Đơn vị: VND Tỷ lệ sở hữu của Công ty mẹ 51%"
#
# Bất kỳ cửa sổ nào đủ rộng để chứa "nghìn tỷ đồng" cũng đủ rộng để nuốt
# "Tỷ lệ … 51%" — và cụm khai báo lại quyết định CẢ loại lẫn bậc đơn vị.
#
# Lời khai đơn vị không phải văn xuôi; nó là một chuỗi ngắn các TỪ ĐƠN VỊ. Nên
# dừng theo TỪ VỰNG chứ không theo độ dài: gặp từ ngoài danh sách là hết lời khai.
# Lời khai đơn vị là ĐÚNG MỘT biểu thức đơn vị, không phải một chuỗi từ.
#
# Bản trước cho phép một CHUỖI từ đơn vị, và `Đơn vị: VND Tỷ lệ sở hữu 51%` bắt
# được "VND Tỷ " — đủ để `tỷ` lọt vào cụm khai báo rồi thành bậc 10⁹, đúng lỗi
# đang đi sửa. Danh sách dưới đây xếp DÀI TRƯỚC nên "triệu đồng" thắng "triệu",
# và bất cứ thứ gì sau biểu thức đầu tiên đều nằm ngoài lời khai.
_UNIT_DECL = re.compile(
    r"Đơn\s*vị(?:\s*tính)?\s*[:：]?\s*"
    r"((?:nghìn|ngàn)\s*tỷ\s*(?:đồng|VN[DĐ])|(?:tỷ|tỉ)\s*(?:đồng|VN[DĐ])|"
    r"triệu\s*(?:đồng|VN[DĐ])|(?:nghìn|ngàn)\s*(?:đồng|VN[DĐ])|"
    r"VN[DĐ]|USD|EUR|JPY|đồng|triệu|tỷ|tỉ|nghìn|ngàn|"
    r"cổ\s*phi[ếe]u|%)", re.I)


@dataclass(slots=True)
class UnitResolution:
    unit_kind: UnitKind
    currency: str | None
    scale_exponent: int | None
    unit_kind_source: EvidenceSource
    currency_source: EvidenceSource
    scale_source: EvidenceSource
    unit_raw: str = ""
    assumed: bool = False

    @property
    def flags(self) -> list[str]:
        out: list[str] = []
        if self.assumed:
            # RC-04 mục 3: đổi tên vì tên cũ MÔ TẢ SAI. `unit_assumed` gợi ý
            # "loại đơn vị được giả định", nhưng đo trên `b927c3e8f90aed74`
            # thì phần lớn ca thực tế là **currency** được giả định (4.298 ca)
            # trong khi `unit_kind` vẫn có bằng chứng. Một cờ mô tả sai làm
            # người đọc chính sách readiness quyết định sai.
            out.append("unit_scale_assumed_no_evidence")
        if self.scale_source is EvidenceSource.NONE and self.unit_kind is UnitKind.MONEY:
            out.append("scale_unknown")
        return out


def _find_scale(
    text: str,
    in_declaration: bool = False,
    *,
    allow_attached_column_unit: bool = False,
) -> int | None:
    patterns = (
        _SCALE_IN_DECL
        if in_declaration
        else _SCALE_ATTACHED_COLUMN
        if allow_attached_column_unit
        else _SCALE_STRICT
    )
    for pat, exp in patterns:
        if pat.search(text):
            return exp
    return None


def _find_currency(
    text: str,
    *,
    allow_attached_column_unit: bool = False,
) -> str | None:
    patterns = (
        _CURRENCY_ATTACHED_COLUMN
        if allow_attached_column_unit
        else _CURRENCY_PATTERNS
    )
    for pat, cur in patterns:
        if pat.search(text):
            return cur
    return None


# `CÔNG TY CỔ PHẦN` nằm trong TÊN của gần như mọi doanh nghiệp niêm yết, và tên
# đó lặp ở đầu mỗi trang báo cáo — tức là nằm trong cửa sổ ngữ cảnh của hầu hết
# bảng. Không gỡ ra thì `cổ\s*phần` khớp, đơn vị thành SHARES, và **bậc 10 của
# tiền bị mất** (`scale_exponent = None`): giá trị khai bằng "triệu đồng" sẽ
# được đọc như đồng, sai 10⁶ mà không cổng nào bắt được.
#
# Một cụm từ trong tên pháp nhân không bao giờ là lời khai đơn vị đo.
_LEGAL_FORM = re.compile(
    r"c[oô]ng\s*ty\s*c[oổ]\s*ph[aầ]n|\bCTCP\b|c[oô]ng\s*ty\s*CP\b", re.I)


def _find_kind(text: str) -> UnitKind | None:
    text = _LEGAL_FORM.sub(" ", text or "")
    for pat, kind in _KIND_PATTERNS:
        if pat.search(text):
            return kind
    return None


def _declaration(text: str) -> str:
    m = _UNIT_DECL.search(text or "")
    return m.group(0) if m else ""


def resolve_unit(
    cell_text: str,
    column_header: str,
    row_label: str,
    table_text: str,
    context_before: str,
    value_kind_hint: UnitKind | None = None,
    money_view: bool = False,
) -> UnitResolution:
    """Giải ba thuộc tính độc lập theo thứ bậc riêng của từng thuộc tính.

    Thứ bậc chung: cell → column → row → table → context → mặc định.
    Nhưng mỗi thuộc tính dừng ở tầng đầu tiên cho bằng chứng về CHÍNH nó.
    """
    # Cờ thứ ba: tầng này có được dùng để suy LOẠI đơn vị không.
    #
    # Đây là ràng buộc quan trọng nhất của module. `table_text` và
    # `context_before` là VĂN XUÔI, không phải nhãn. Trong văn xuôi báo cáo tài
    # chính, "ngày" / "tỷ lệ" / "cổ phần" / "lãi suất" xuất hiện như từ ngữ bình
    # thường, không phải lời khai đơn vị đo. Dò loại đơn vị ở đó cho ra:
    #
    #     days   1.251.583 ô tiền (52,0%)   ← "kết thúc ngày 31 tháng 12"
    #     shares   659.904 ô tiền (27,4%)   ← "CÔNG TY CỔ PHẦN …"
    #     percent  277.041 ô tiền (11,5%)
    #     rate      83.172 ô tiền ( 3,5%)
    #
    # và vì loại phi tiền tệ thoát sớm không mang `scale_exponent`, **95% ô tiền
    # mất bậc 10**. Giá trị khai "triệu đồng" bị đọc như đồng.
    #
    # Tiền tệ và bậc 10 thì VẪN lấy từ văn xuôi được: "Đơn vị tính: triệu đồng"
    # nằm ngoài bảng ở 9.099 chỗ, và `VND`/`triệu` không có nghĩa nào khác.
    # BẬC 10 cũng không được suy từ văn xuôi, vì đúng lý do như LOẠI đơn vị.
    #
    # Thuyết minh vay mô tả hợp đồng bằng câu văn: "theo hợp đồng hạn mức
    # **500 tỷ đồng**, lãi suất 7%/năm". Cụm `tỷ đồng` ở đó là HẠN MỨC HỢP
    # ĐỒNG, không phải đơn vị của bảng. Đo được 71.809 ô nhận scale 10⁶/10⁹ từ
    # `section_context` trong khi chữ số thô đã có 11–15 chữ số — tức giá trị
    # vốn là VND đầy đủ, và nhân thêm cho ra 1,7×10²⁰ VND.
    #
    # Lời khai đơn vị chỉ đến từ hai chỗ: NHÃN (ô, cột, dòng) hoặc cụm
    # `Đơn vị tính:`. 9.099 khai báo nằm ngoài bảng vẫn bắt được — chúng là
    # cụm `Đơn vị tính:`, do `_declaration()` lo, không phải văn xuôi thô.
    #
    # Văn xuôi thô chỉ còn được dùng cho TIỀN TỆ: `VND`/`đồng` không có nghĩa
    # nào khác, và đoán sai tiền tệ không nhân giá trị lên tỷ lần.
    #
    # (văn bản, nguồn, suy LOẠI?, là cụm KHAI BÁO?, suy BẬC?)
    layers = (
        (cell_text or "", EvidenceSource.CELL, True, False, True),
        (column_header or "", EvidenceSource.COLUMN_PATH, True, False, True),
        (row_label or "", EvidenceSource.ROW_CONTEXT, True, False, True),
        (_declaration(table_text), EvidenceSource.TABLE_CONTEXT, True, True, True),
        (table_text or "", EvidenceSource.TABLE_CONTEXT, False, False, False),
        (_declaration(context_before), EvidenceSource.SECTION_CONTEXT, True, True, True),
        (context_before or "", EvidenceSource.SECTION_CONTEXT, False, False, False),
    )

    kind, kind_src = None, EvidenceSource.NONE
    currency, cur_src = None, EvidenceSource.NONE
    scale, scale_src = None, EvidenceSource.NONE
    unit_raw = ""

    for text, source, allow_kind, is_decl, allow_scale in layers:
        if not text:
            continue
        if allow_kind and kind is None and (k := _find_kind(text)):
            # RC2-036 · `money_view` — gọi khi tầng trên ĐÃ kết luận ô này mang
            # TIỀN (`classify_value_kind` trả `MONEY` sau khi qua cổng hình
            # dạng `_shape_allows`). Khi đó một TỪ KHOÁ trong nhãn cột không
            # được quyền lật `unit_kind` sang loại phi tiền tệ.
            #
            # Vì sao đây là lỗi thật, đo được trên `4c86c9e43915694a`:
            # `classify_value_kind` có cổng hình dạng, `_find_kind` thì KHÔNG.
            # Nên ô `10.805.901` dưới nhãn cột "Thời hạn định lại lãi suất"
            # nhận `value_kind=money` (đúng, vì `_shape_allows(rate)` loại nó)
            # nhưng `unit_kind=rate` (sai, vì từ khoá "lãi suất" không bị chặn).
            # Kết quả: 20.378 bản ghi TỰ MÂU THUẪN — tiền mang đơn vị lãi suất.
            #
            # Ở đây KHÔNG ép `MONEY`: chỉ bỏ qua bằng chứng loại phi tiền tệ và
            # để logic sẵn có kết luận. Không có tiền tệ và không có bậc thì kết
            # quả vẫn là `UNKNOWN` — `unknown` là "chưa biết", hợp lệ; còn
            # `rate` trên một ô tiền là SAI.
            if money_view and k in (UnitKind.PERCENT, UnitKind.RATE,
                                    UnitKind.SHARES, UnitKind.DAYS,
                                    UnitKind.COUNT):
                pass
            else:
                kind, kind_src = k, source
        if currency is None and (
            c := _find_currency(
                text,
                allow_attached_column_unit=source is EvidenceSource.COLUMN_PATH,
            )
        ):
            currency, cur_src = c, source
        if allow_scale and scale is None and (
            sc := _find_scale(
                text,
                is_decl,
                allow_attached_column_unit=source is EvidenceSource.COLUMN_PATH,
            )
        ):
            scale, scale_src = sc, source
            if not unit_raw:
                unit_raw = text.strip()[:60]
        if kind is not None and currency is not None and scale is not None:
            break

    if value_kind_hint is not None and kind is None:
        kind, kind_src = value_kind_hint, EvidenceSource.CELL

    assumed = False
    if kind is None:
        # Suy `money` TỪ tiền tệ hoặc bậc đã tìm được không phải là "mặc định" —
        # đó là suy diễn từ bằng chứng thật. Gọi nó `assumed` làm cờ này bùng từ
        # 59.331 lên 2.267.258 ô (88%); và vì `confidence` dùng cờ đó để hạ
        # xuống `low`, cả cột `confidence` mất khả năng phân biệt.
        #
        # `assumed` chỉ đúng khi KHÔNG có bằng chứng nào — nhánh dưới lo việc đó.
        if currency is not None:
            kind, kind_src = UnitKind.MONEY, cur_src
        elif scale is not None:
            kind, kind_src = UnitKind.MONEY, scale_src
        else:
            kind, kind_src = UnitKind.UNKNOWN, EvidenceSource.NONE

    if kind in (UnitKind.PERCENT, UnitKind.RATE, UnitKind.SHARES,
                UnitKind.DAYS, UnitKind.COUNT):
        # Không áp hệ số tiền tệ cho các loại phi tiền tệ.
        return UnitResolution(kind, None, None, kind_src,
                              EvidenceSource.NONE, EvidenceSource.NONE,
                              unit_raw, assumed=False)

    if kind is UnitKind.MONEY:
        if currency is None:
            currency, cur_src = "VND", EvidenceSource.ASSUMED
            assumed = True
        elif scale is None:
            # `Đơn vị tính: VND` KHÔNG phải thiếu bằng chứng về bậc — nó khai
            # bậc 10⁰ một cách tường minh. Phần lớn báo cáo Việt Nam lập bằng
            # đồng và không có từ chỉ bậc nào cả; gọi đó là "mặc định" làm số
            # đo phủ đơn vị thấp giả và che mất chỗ thiếu bằng chứng thật.
            scale, scale_src = 0, cur_src
        if scale is None:
            scale, scale_src = 0, EvidenceSource.ASSUMED
            assumed = True

    return UnitResolution(kind, currency, scale, kind_src, cur_src, scale_src,
                          unit_raw, assumed)


# Trần độ lớn — cùng ngưỡng với `number_parser._MAX_MONEY`. Đặt lại ở đây thay
# vì import chéo: hai module không phụ thuộc nhau, và ngưỡng này là hằng số
# nghiệp vụ (10^16 VND ≈ 10.000 nghìn tỷ) chứ không phải chi tiết của parser.
_MAX_MONEY_SCALED = 10 ** 16


def reconcile_scale(
    value_abs: float | int | None,
    is_money: bool,
    scale_exponent: int | None,
    scale_source: EvidenceSource,
) -> tuple[int | None, EvidenceSource, str | None]:
    """Đối chiếu BẬC đã khai với ĐỘ LỚN chữ số thực tế của ô.

    Bậc đơn vị là một LỜI KHAI. Chữ số in trong ô là BẰNG CHỨNG. Khi hai thứ
    mâu thuẫn đến mức không thể đồng thời đúng, lời khai thua.

    Đo được 2.075 observation vượt 10^16 VND SAU khi áp bậc, trong khi chữ số
    thô **không** ô nào vượt (khối B của `diag_2075.sql`: 2075/2075 rơi vào
    nhánh "chỉ vượt sau scale"). Mẫu điển hình:

        69.361.062.377.286  ×  10^9  =  6,9 × 10^22 VND

    14 chữ số thô đã là VND đầy đủ. Bảng lập bằng tỷ đồng in ra 4–6 chữ số,
    không phải 14 — nên `tỷ đồng` bắt được từ `section_context` là lời khai của
    một bảng KHÁC trong cùng mục, không phải của bảng này.

    Đây không phải đoán bậc. Số chữ số in ra là bằng chứng về cách trình bày,
    và nó bác bỏ lời khai. Ràng buộc tự giới hạn: bảng lập bằng triệu in
    `5.341.160` (7 chữ số) cho ra 5,3×10^12 — hợp lệ, luật không kích hoạt.

    Trả về `(bậc, nguồn, cờ)`. Cờ khác None nghĩa là lời khai đã bị bác.
    """
    if not is_money or not scale_exponent or value_abs is None:
        return scale_exponent, scale_source, None
    if value_abs > _MAX_MONEY_SCALED:
        # Chữ số thô ĐÃ vượt trần — đây là lỗi tách số, không phải lỗi bậc.
        # Sửa ở đây sẽ che mất lỗi thật. Để nguyên cho `Q-OBS-IMPLAUSIBLE-RAW`.
        return scale_exponent, scale_source, None
    if value_abs * (10 ** scale_exponent) <= _MAX_MONEY_SCALED:
        return scale_exponent, scale_source, None
    return 0, EvidenceSource.NONE, "scale_rejected_implausible"
