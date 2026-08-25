"""DP-010 — D4d: giải kỳ báo cáo đầy đủ, không chỉ `period_year`.

Đây là hạng mục **đang chặn ANSWER ACCURACY**: 706.901 ô (26,5%) có nhãn cột
tương đối và chỉ giải được khi ghép với năm tài chính của tài liệu.

    Số cuối năm   219.968 ô     Số đầu năm   209.232 ô
    Năm trước     140.710 ô     Năm nay      135.548 ô

Và một lỗi ngữ nghĩa phải sửa: cột `01/01/YYYY` **là số cuối kỳ YYYY−1**, không
phải YYYY. Gán `period_year = YYYY` đúng mặt chữ nhưng sai kế toán — câu hỏi về
năm YYYY−1 sẽ không bao giờ tìm thấy cột này.

Cách xử lý ở đây giữ **cả hai**: `as_of_date` giữ ngày literal, `period_end`
giữ ngày kỳ mà giá trị thật sự thuộc về, `period_role = opening` ghi lại quan
hệ. Không đổi ngầm một trường.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from text2pandas.pipelines.a6.models import EvidenceSource, PeriodRole, PeriodType

__all__ = ["PeriodResolution", "resolve_period", "resolve_row_period",
           "resolve_table_period", "PERIOD_VERSION"]

PERIOD_VERSION = "1.7"

_DMY = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(20\d{2})")
# Dạng viết chữ trong dòng ngữ cảnh: "tại ngày 31 tháng 12 năm 2018".
_DMY_WORDS = re.compile(
    r"ngày\s*(\d{1,2})\s*tháng\s*(\d{1,2})\s*(?:năm\s*)?(20\d{2})", re.I)
_DURATION_PHRASE = re.compile(
    r"cho\s*(?:năm|kỳ|giai\s*đoạn).{0,40}?kết\s*thúc|"
    r"(?:năm|kỳ)\s*tài\s*chính.{0,30}?kết\s*thúc|trong\s*năm\s*tài\s*chính", re.I)
_MY = re.compile(r"(?:tháng\s*)?(\d{1,2})\s*/\s*(20\d{2})")
# KHÔNG dùng `\b`: OCR nối đơn vị vào năm — `2021VND` là nhãn cột phổ biến và
# giữa `1` và `V` không có ranh giới từ, nên `\b(20[0-2]\d)\b` trượt. Đo được
# 1.373 cột chỉ trong 25 nhãn phổ biến nhất chưa giải được kỳ. Cùng lớp lỗi với
# `\bVND` đã sửa ở unit_resolver — lookaround chữ SỐ mới là điều kiện đúng.
_YEAR = re.compile(r"(?<!\d)(20[0-2]\d)(?!\d)")
_QUARTER = re.compile(r"[Qq]uý\s*([1-4])|\bQ([1-4])\b")
# SỐ HIỆU văn bản pháp quy / hợp đồng — hình dạng `nn/yyyy` giống hệt tháng/năm.
# Che ĐÚNG cụm số hiệu, không che cả câu: một câu có thể chứa cả số hiệu văn bản
# lẫn ngày báo cáo thật.
#
# Cụm che phải NUỐT LUÔN NGÀY BAN HÀNH đi kèm. "Thông tư số 200/2014/TT-BTC
# **ngày 22/12/2014** của Bộ Tài chính" — ngày đó là ngày ký văn bản, không
# phải kỳ của bảng. Che mỗi số hiệu mà chừa ngày ban hành lại thì bậc suy diễn
# cấp bảng đọc trúng nó: đo được ngữ cảnh "…kết thúc ngày 31/12/2019 theo Thông
# tư 200/2014/TT-BTC ngày 22/12/2014" ra 2014-12-22 vì luật lấy ngày CUỐI CÙNG.
_LEGAL_NUM = re.compile(
    r"(?:"
    # Có hậu tố mã cơ quan (`/TT-BTC`) — tiền tố loại văn bản là TUỲ CHỌN vì
    # hậu tố đã đủ nhận dạng. `số` phải nằm SAU tên loại văn bản được: bản đầu
    # cho `số` cùng cấp với `thông tư` nên "Thông tư số 200/2014/TT-BTC" khớp
    # nhánh dưới trước (leftmost-match) và bỏ sót đuôi `/TT-BTC` lẫn ngày ký.
    r"(?:(?:thông\s*tư|quyết\s*định|nghị\s*định|nghị\s*quyết|công\s*văn|"
    r"hợp\s*đồng)\s*)?(?:số\s*)?\d{1,4}\s*/\s*20\d{2}\s*/\s*[A-ZĐ][A-ZĐ\-/]*"
    # Không có hậu tố mã — BẮT BUỘC có tên loại văn bản, nếu không `12/2019`
    # (tháng/năm hợp lệ) cũng bị che.
    r"|(?:thông\s*tư|quyết\s*định|nghị\s*định|nghị\s*quyết|công\s*văn|hợp\s*đồng)"
    r"\s*(?:số\s*)?\d{1,4}\s*/\s*20\d{2}"
    r")"
    r"(?:\s*,?\s*ngày\s*\d{1,2}\s*(?:/|-|tháng)\s*\d{1,2}\s*(?:/|-|năm)\s*20\d{2})?",
    re.I)
# Cửa sổ năm cho bậc SUY DIỄN cấp bảng. Một bảng trong tài liệu năm Y không thể
# có ngày chốt cách Y nhiều năm; nếu có, con số đó đến từ trích dẫn hay lịch sử
# pháp lý chứ không phải kỳ. KHÔNG áp cửa sổ này cho nhãn cột: bảng tổng hợp
# 5 năm có cột 2015 hợp lệ trong tài liệu 2019, và nhãn cột là bằng chứng mạnh.
_TABLE_YEAR_BACK = 2
_RESTATED = re.compile(r"trình\s*bày\s*lại|restated|điều\s*chỉnh\s*lại", re.I)

_END_TOKENS = ("số cuối năm", "số cuối kỳ", "cuối năm", "cuối kỳ",
               "năm nay", "kỳ này", "cuối quý")
_BEGIN_TOKENS = ("số đầu năm", "số đầu kỳ", "đầu năm", "đầu kỳ",
                 "năm trước", "kỳ trước", "đầu quý")
_DURATION_HINT = ("trong năm", "trong kỳ", "phát sinh", "lũy kế", "luỹ kế",
                  "cho năm", "cho kỳ")
# Nhãn cột chỉ KỲ PHÁT SINH của năm báo cáo: `Trong năm`, `Tăng trong năm`,
# `Số phải nộp trong năm`, `Biến động trong năm`. Đo được ~1.300 cột chưa giải
# được kỳ chỉ vì "trong năm" nằm trong `_DURATION_HINT` (dùng để chọn KIỂU kỳ)
# mà không có ở tầng nào gán được NGÀY kỳ.
_DURATION_TOKENS = ("trong năm", "trong kỳ", "trong quý")


@dataclass(slots=True)
class PeriodResolution:
    period_start: str | None = None
    period_end: str | None = None
    as_of_date: str | None = None
    period_type: PeriodType = PeriodType.UNKNOWN
    period_role: PeriodRole = PeriodRole.UNKNOWN
    quarter: int | None = None
    is_restated: bool = False
    source: EvidenceSource = EvidenceSource.NONE
    rule: str = "P-NONE"

    @property
    def resolved(self) -> bool:
        return self.period_end is not None

    @property
    def year(self) -> int | None:
        return int(self.period_end[:4]) if self.period_end else None


def _iso(y: int, m: int, d: int) -> str:
    return f"{y:04d}-{m:02d}-{d:02d}"


def _valid_iso(y: int, m: int, d: int) -> str | None:
    """Chỉ trả chuỗi khi (y, m, d) là NGÀY LỊCH có thật.

    Bản đầu ghép chuỗi thẳng, nên corpus sinh ra `2014-00-28`, `2016-58-28`,
    `2025-31-12` — 818 observation mang ngày không tồn tại, mà thước độ phủ kỳ
    vẫn báo 95,12%. Một trường ngày không phải chuỗi tự do; nó phải chứng minh
    được là ngày trước khi được ghi.
    """
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def _mask_legal_ref(text: str) -> str:
    """Che SỐ HIỆU văn bản pháp quy, giữ nguyên phần còn lại.

    Số hiệu văn bản và số hợp đồng có đúng hình dạng `nn/yyyy`, nên regex
    tháng/năm bắt trúng và sinh ra tháng 200, tháng 58.

    Nhưng LOẠI CẢ NGỮ CẢNH thì hỏng nặng hơn: "Thông tư 200/2014/TT-BTC" có
    trong ngữ cảnh của gần như **mọi** bảng thuyết minh, nên chặn theo ngữ cảnh
    làm 29.620 cột mất kỳ và độ phủ tụt từ 95,03% xuống 85,74% — sát ngưỡng.

    Một câu chứa cả số hiệu văn bản LẪN ngày báo cáo thật là chuyện bình thường:
    "Thuyết minh lập theo Thông tư 200/2014/TT-BTC. Tăng giảm TSCĐ tại ngày 31
    tháng 12 năm 2018". Che đúng phần số hiệu giữ lại được ngày thật.
    """
    return _LEGAL_NUM.sub(" ", text or "")


def resolve_period(
    column_header: str,
    doc_year: int | None,
    table_context: str = "",
    fiscal_year_end: tuple[int, int] = (12, 31),
) -> PeriodResolution:
    """Giải kỳ của một CỘT. Không đoán khi thiếu bằng chứng.

    `fiscal_year_end` mặc định 31/12 nhưng là tham số — không giả định mọi
    doanh nghiệp có năm tài chính kết thúc 31/12 khi chưa có bằng chứng.
    """
    header = (column_header or "").strip()
    ctx = f"{header} {table_context}".lower()
    res = PeriodResolution()
    res.is_restated = bool(_RESTATED.search(header) or _RESTATED.search(table_context))

    # Che số hiệu văn bản TRƯỚC khi dò ngày. Che chứ không loại: nhãn cột hiếm
    # khi vừa có số hiệu vừa có ngày, nhưng ngữ cảnh bảng thì thường xuyên.
    header = _mask_legal_ref(header)

    if m := _QUARTER.search(header):
        res.quarter = int(m.group(1) or m.group(2))
        res.period_type = PeriodType.QUARTER

    # `fiscal_year_end` là (tháng, ngày) — khớp giá trị mặc định (12, 31).
    fy_m, fy_d = fiscal_year_end

    # 1. Ngày tuyệt đối trong nhãn cột — bằng chứng mạnh nhất.
    if m := _DMY.search(header):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # Chuẩn Việt Nam là DD/MM. Nhưng corpus có cả MM/DD (`12/31/2025`).
        # Phân biệt được khi ĐÚNG MỘT trong hai số vượt 12; cả hai vượt 12 thì
        # đó không phải ngày, và đoán bừa còn tệ hơn để trống.
        d, mo = (b, a) if (b > 12 and a <= 12) else (a, b)
        res.as_of_date = _valid_iso(y, mo, d)
        if res.as_of_date is None:
            res.rule = "P-INVALID-DATE"
            return res
        res.source = EvidenceSource.COLUMN_PATH
        if (d, mo) == (1, 1):
            # 01/01/YYYY = số dư ĐẦU kỳ YYYY = số dư CUỐI kỳ YYYY−1.
            res.period_end = _valid_iso(y - 1, fy_m, fy_d)
            res.period_role = PeriodRole.OPENING
            res.period_type = PeriodType.INSTANT
            res.rule = "P-OPENING-0101"
        else:
            res.period_end = res.as_of_date
            res.period_role = PeriodRole.CLOSING
            res.period_type = res.period_type if res.quarter else PeriodType.INSTANT
            res.rule = "P-EXPLICIT-DMY"
        return res

    # 2. Quý — phải xét TRƯỚC tháng/năm: `Quý 4/2023` không phải tháng 4.
    if res.quarter and (m := _YEAR.search(header)):
        y = int(m.group(1))
        end_month = res.quarter * 3
        end_day = 31 if end_month in (3, 12) else 30
        res.period_end = _iso(y, end_month, end_day)
        res.period_start = _iso(y, end_month - 2, 1)
        res.as_of_date = res.period_end
        res.period_type = PeriodType.QUARTER
        res.period_role = (PeriodRole.CURRENT if doc_year and y == doc_year
                           else PeriodRole.PRIOR if doc_year and y < doc_year
                           else PeriodRole.UNKNOWN)
        res.source = EvidenceSource.COLUMN_PATH
        res.rule = "P-QUARTER"
        return res

    # 3. Tháng/năm — tháng phải nằm trong 1–12, nếu không thì đó là số hiệu.
    if m := _MY.search(header):
        mo, y = int(m.group(1)), int(m.group(2))
        if not 1 <= mo <= 12:
            res.rule = "P-INVALID-MONTH"
            return res
        res.period_end = _valid_iso(y, mo, 28)
        res.as_of_date = res.period_end
        res.period_type = PeriodType.QUARTER if res.quarter else PeriodType.INSTANT
        res.period_role = PeriodRole.CLOSING
        res.source = EvidenceSource.COLUMN_PATH
        res.rule = "P-EXPLICIT-MY"
        return res

    # 4. Năm tuyệt đối.
    if m := _YEAR.search(header):
        y = int(m.group(1))
        res.period_end = _valid_iso(y, fy_m, fy_d)
        res.as_of_date = res.period_end
        res.source = EvidenceSource.COLUMN_PATH
        res.period_role = (
            PeriodRole.CURRENT if doc_year and y == doc_year else
            PeriodRole.PRIOR if doc_year and y < doc_year else PeriodRole.UNKNOWN
        )
        if res.period_type is PeriodType.UNKNOWN:
            res.period_type = (PeriodType.DURATION
                               if any(h in ctx for h in _DURATION_HINT)
                               else PeriodType.INSTANT)
        res.rule = "P-EXPLICIT-YEAR"
        return res

    # 5. Nhãn tương đối — cần doc_year. Đây là 26,5% số ô.
    low = header.lower()
    if doc_year is None:
        res.rule = "P-RELATIVE-NO-DOCYEAR"
        return res

    if any(t in low for t in _END_TOKENS):
        res.period_end = _iso(doc_year, 12, 31)
        res.as_of_date = res.period_end
        res.period_role = PeriodRole.CURRENT
        res.period_type = (PeriodType.DURATION
                           if any(h in ctx for h in _DURATION_HINT)
                           else PeriodType.INSTANT)
        res.source = EvidenceSource.DOCUMENT_DEFAULT
        res.rule = "P-RELATIVE-END"
        if res.period_type is PeriodType.DURATION:
            res.period_start = _iso(doc_year, 1, 1)
        return res

    if any(t in low for t in _BEGIN_TOKENS):
        # "Số đầu năm" của báo cáo năm Y = số cuối năm Y−1.
        res.period_end = _iso(doc_year - 1, 12, 31)
        res.as_of_date = _iso(doc_year, 1, 1)
        res.period_role = PeriodRole.PRIOR
        res.period_type = (PeriodType.DURATION
                           if any(h in ctx for h in _DURATION_HINT)
                           else PeriodType.INSTANT)
        res.source = EvidenceSource.DOCUMENT_DEFAULT
        res.rule = "P-RELATIVE-BEGIN"
        if res.period_type is PeriodType.DURATION:
            res.period_start = _iso(doc_year - 1, 1, 1)
        return res

    if any(t in low for t in _DURATION_TOKENS):
        # `Trong năm` = kỳ phát sinh của chính năm báo cáo. Đây là DURATION, và
        # phải có `period_start` — nếu chỉ gán `period_end` thì nó lẫn với số dư
        # thời điểm 31/12, hai đại lượng khác hẳn nhau về kế toán.
        res.period_start = _iso(doc_year, 1, 1)
        res.period_end = _iso(doc_year, 12, 31)
        res.as_of_date = res.period_end
        res.period_role = PeriodRole.CURRENT
        res.period_type = PeriodType.DURATION
        res.source = EvidenceSource.DOCUMENT_DEFAULT
        res.rule = "P-RELATIVE-DURATION"
        return res

    res.rule = "P-UNRESOLVED"
    return res


def resolve_row_period(
    row_path: str,
    metric_label: str = "",
    fiscal_year_end: tuple[int, int] = (12, 31),
) -> PeriodResolution:
    """A5-B1 · giải kỳ từ trục DÒNG. **Chỉ dùng khi cột và bảng đều bó tay.**

    `resolve_period()` đọc nhãn CỘT, `resolve_table_period()` đọc ngữ cảnh
    BẢNG. Cả hai đều mù với một bố cục có thật và phổ biến: bảng biến động vốn
    chủ sở hữu, nơi CỘT mang cấu phần vốn còn DÒNG mang ngày.

        col='Vốn đầu tư chủ sở hữu VND'
        row='18 Vốn chủ sở hữu a › Số dư tại ngày 31/12/2015'

    Đo trên build A4: 185.385 ô có `period_source='none'` ∧ `period_end IS
    NULL`, trong đó 152.455 là `note` và 27.064 là `equity_change` — gần như
    trọn vẹn là bố cục này. Vì không có kỳ, cả 185.385 ô bị loại khỏi
    `execution_candidate` với lý do `period_unresolved`.

    Đây là cùng một hình dạng lỗi với RC2-039 ở A4 — bằng chứng nằm ở trục
    dòng còn bộ phân giải chỉ đọc trục cột — nên cách sửa cũng giống: mở thêm
    trục, KHÔNG hạ tiêu chuẩn bằng chứng.

    Hạng bằng chứng ở đây là NGÀY TUYỆT ĐỐI, đúng hạng mạnh nhất mà
    `resolve_period` dùng cho `P-EXPLICIT-DMY`. Ba tầng yếu hơn CỐ Ý không
    làm ở A5, lý do đo được:

        chỉ có MM/YYYY            331 ô  — quá ít để đáng rủi ro
        chỉ có năm trần        18.057 ô  — năm trong nhãn dòng thường là số
                                           hiệu văn bản, không phải kỳ
        không có tín hiệu ngày 157.465 ô — dòng biến động (`Vốn góp tăng
                                           trong năm`) nằm GIỮA hai dòng mốc
                                           trong bảng trải nhiều năm; gán
                                           `doc_year` sẽ SAI cho các dòng
                                           thuộc năm trước. Cần suy kỳ theo
                                           khoảng giữa hai mốc — để A6, và
                                           cần gold để kiểm.
    """
    res = PeriodResolution()
    text = f"{row_path or ''} {metric_label or ''}".strip()
    if not text:
        res.rule = "P-ROW-EMPTY"
        return res
    res.is_restated = bool(_RESTATED.search(text))

    # Che số hiệu văn bản trước khi dò ngày — nhãn dòng mang số hiệu
    # (`Nghị định 12/2015/NĐ-CP`) thường xuyên hơn nhãn cột.
    masked = _mask_legal_ref(text)

    if m := _DMY.search(masked):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # Cùng quy tắc phân biệt DD/MM với MM/DD như `resolve_period`.
        d, mo = (b, a) if (b > 12 and a <= 12) else (a, b)
    elif m := _DMY_WORDS.search(masked):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        res.rule = "P-ROW-UNRESOLVED"
        return res

    res.as_of_date = _valid_iso(y, mo, d)
    if res.as_of_date is None:
        res.rule = "P-ROW-INVALID-DATE"
        return res

    fy_m, fy_d = fiscal_year_end
    res.source = EvidenceSource.ROW_CONTEXT
    if (d, mo) == (1, 1):
        # `Số dư tại ngày 01/01/YYYY` = số dư ĐẦU kỳ YYYY = cuối kỳ YYYY−1.
        # Giữ nguyên ngữ nghĩa của `P-OPENING-0101`; lệch ở đây thì hai trục
        # sẽ gán hai kỳ khác nhau cho cùng một khái niệm.
        res.period_end = _valid_iso(y - 1, fy_m, fy_d)
        res.period_role = PeriodRole.OPENING
        res.period_type = PeriodType.INSTANT
        res.rule = "P-ROW-OPENING-0101"
    else:
        res.period_end = res.as_of_date
        res.period_role = PeriodRole.CLOSING
        res.period_type = PeriodType.INSTANT
        res.rule = "P-ROW-EXPLICIT-DMY"
    return res


def resolve_table_period(
    table_context: str,
    doc_year: int | None,
    fiscal_year_end: tuple[int, int] = (12, 31),
) -> PeriodResolution:
    """Giải kỳ khai **một lần ở cấp BẢNG**, dùng khi nhãn cột không mang kỳ.

    Bảng thuyết minh dùng cột cho CHIỀU phân tích — `Nguyên giá`, `Hao mòn luỹ
    kế`, `Miền Bắc` — chứ không cho kỳ. Kỳ nằm ở dòng ngữ cảnh phía trên: "Tăng
    giảm tài sản cố định hữu hình tại ngày 31 tháng 12 năm 2018". Nhãn cột
    không mang kỳ vì kỳ **không thuộc về cột**, không phải vì thiếu dữ liệu.

    Bằng chứng ở đây yếu hơn nhãn cột một bậc, nên `source = TABLE_CONTEXT` và
    mọi kết quả phải được gắn cờ `period_from_table` ở nơi gọi. Người dùng
    xuôi dòng phải phân biệt được kỳ ĐỌC ĐƯỢC với kỳ SUY RA.
    """
    ctx = (table_context or "").strip()
    res = PeriodResolution()
    if not ctx:
        res.rule = "PT-NO-CONTEXT"
        return res

    res.is_restated = bool(_RESTATED.search(ctx))
    ctx = _mask_legal_ref(ctx)
    is_duration = bool(_DURATION_PHRASE.search(ctx)) or any(
        h in ctx.lower() for h in _DURATION_HINT)

    def _finish(y: int, mo: int, d: int, rule: str) -> PeriodResolution:
        # Bậc `table` cũng phải validate lịch. Bỏ sót chỗ này là nguồn của 91
        # observation mang ngày không tồn tại, sau khi bậc `column` đã sửa rồi:
        # một luật đúng chỉ áp ở một nhánh thì nhánh còn lại vẫn rò.
        res.as_of_date = _valid_iso(y, mo, d)
        if res.as_of_date is None:
            res.rule = "PT-INVALID-DATE"
            return res
        res.source = EvidenceSource.TABLE_CONTEXT
        res.rule = rule
        if (d, mo) == (1, 1):
            # Cùng ngữ nghĩa với P-OPENING-0101: 01/01/YYYY là số dư cuối YYYY−1.
            res.period_end = _valid_iso(y - 1, 12, 31)
            res.period_role = PeriodRole.OPENING
            res.period_type = PeriodType.INSTANT
            return res
        res.period_end = res.as_of_date
        res.period_role = PeriodRole.CLOSING
        res.period_type = PeriodType.DURATION if is_duration else PeriodType.INSTANT
        if res.period_type is PeriodType.DURATION:
            res.period_start = _iso(y, 1, 1)
        return res

    def _pick(matches: list) -> tuple[int, int, int] | None:
        """Quét từ CUỐI về ĐẦU, nhận ứng viên đầu tiên NẰM TRONG cửa sổ năm.

        Luật cũ lấy thẳng `matches[-1]` với lý do "dòng gần bảng nhất". Lý do đó
        đúng khi ngữ cảnh chỉ có ngày của bảng, nhưng ngữ cảnh thuyết minh
        thường xuyên có thêm ngày ban hành văn bản đứng SAU ngày chốt. Lấy cuối
        không điều kiện là chọn đúng thứ sai. Cửa sổ năm là ràng buộc rẻ và
        kiểm chứng được: giữ nguyên ưu tiên "gần bảng nhất" nhưng chỉ trong
        những ứng viên có thể là kỳ.
        """
        for tup in reversed(matches):
            d, mo, y = (int(x) for x in tup)
            if doc_year is None or (doc_year - _TABLE_YEAR_BACK) <= y <= doc_year:
                return d, mo, y
        return None

    words = _DMY_WORDS.findall(ctx)
    if p := _pick(words):
        return _finish(p[2], p[1], p[0], "PT-CONTEXT-DMY-WORDS")

    slashed = _DMY.findall(ctx)
    if p := _pick(slashed):
        return _finish(p[2], p[1], p[0], "PT-CONTEXT-DMY")

    years = _YEAR.findall(ctx)
    if years:
        y = int(years[-1])
        # Năm trần trong ngữ cảnh là bằng chứng yếu: chỉ nhận khi nó khớp năm
        # thư mục của tài liệu. Lệch năm nghĩa là con số đó đến từ chỗ khác
        # (số hiệu thông tư, năm thành lập) chứ không phải kỳ của bảng.
        if doc_year is not None and y == doc_year:
            # `fiscal_year_end` là (tháng, ngày) — thứ tự này khớp giá trị mặc
            # định (12, 31) và khớp chữ ký `_iso(y, m, d)`.
            return _finish(y, fiscal_year_end[0], fiscal_year_end[1],
                           "PT-CONTEXT-YEAR")

    # Phân biệt "không có ngày nào" với "có ngày nhưng năm quá xa". Hai tình
    # huống này cần hành động khác nhau khi soát chất lượng, nên không gộp mã.
    res.rule = ("PT-YEAR-OUT-OF-WINDOW" if (words or slashed)
                else "PT-UNRESOLVED")
    return res
