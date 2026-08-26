"""Suy LOẠI BÁO CÁO và MÃ CHỈ TIÊU VAS từ câu hỏi — tín hiệu cộng điểm ở S2.

VÌ SAO ĐÁNG LÀM
---------------
119.061/146.246 bảng là `note`; chỉ 9.420 bảng mang `metric_codes` (mã số chỉ
tiêu VAS của bốn báo cáo lõi). Phần lớn câu hỏi tỷ số tài chính cần đúng nhóm
9.420 bảng đó. BM25 trên nhãn dòng không phân biệt được "Doanh thu thuần" ở
Báo cáo KQKD với "Doanh thu thuần" nhắc lại trong một thuyết minh — mã chỉ tiêu
thì phân biệt được.

VÌ SAO LÀ ĐIỂM CỘNG, KHÔNG PHẢI BỘ LỌC
--------------------------------------
Có câu hỏi cần đúng thuyết minh ("giá trị mua hàng từ Coats Phong Phú" là
thuyết minh bên liên quan). Suy loại báo cáo từ câu hỏi mà sai một lần là mất
trắng câu đó. Nguyên tắc đã dùng ở `filter_s1` và ở `Intent.targets` giữ
nguyên: fail-closed thuộc tầng TRẢ LỜI, tầng sinh ứng viên phải giữ recall.
"""
from __future__ import annotations

import re
import unicodedata

__all__ = ["statement_hint", "metric_codes_hint", "CODE_OF"]


def _fold(s: str) -> str:
    d = unicodedata.normalize("NFD", s)
    d = "".join(c for c in d if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", d.replace("đ", "d").replace("Đ", "D").lower())


# Cụm → loại báo cáo. Cụm dài đặt trước; khớp đầu tiên thắng.
_STMT = (
    ("cash_flow", (
        "luu chuyen tien", "dong tien thuan", "dong tien tu hoat dong",
        "dong tien hoat dong", "cfo", "tien thu tu", "tien chi tra",
        "khau hao", "dong tien tu do")),
    ("income_statement", (
        "doanh thu thuan", "doanh thu ban hang", "gia von hang ban",
        "gia von", "loi nhuan gop", "loi nhuan sau thue", "loi nhuan truoc thue",
        "loi nhuan thuan", "bien loi nhuan", "chi phi ban hang",
        "chi phi quan ly", "chi phi lai vay", "lai co ban tren co phieu",
        "eps", "doanh thu tai chinh", "chi phi tai chinh", "loi nhuan")),
    ("balance_sheet", (
        "tong tai san", "tai san ngan han", "tai san dai han", "no phai tra",
        "no ngan han", "no dai han", "von chu so huu", "hang ton kho",
        "phai thu", "phai tra", "tien va cac khoan tuong duong tien",
        "vay va no thue tai chinh", "von dieu le", "loi nhuan sau thue chua phan phoi")),
)

# Cụm → mã số chỉ tiêu VAS. Chỉ những chỉ tiêu XUẤT HIỆN NHIỀU trong đề và có
# mã ổn định giữa các doanh nghiệp. Mã ngân hàng khác mã doanh nghiệp thường,
# nên đây là tín hiệu CỘNG, không phải điều kiện.
CODE_OF: dict[str, tuple[str, ...]] = {
    "doanh thu thuan": ("10",),
    "doanh thu ban hang": ("01",),
    "gia von hang ban": ("11",),
    "loi nhuan gop": ("20",),
    "chi phi tai chinh": ("22",),
    "chi phi lai vay": ("23",),
    "chi phi ban hang": ("25",),
    "chi phi quan ly": ("26",),
    "loi nhuan thuan tu hoat dong kinh doanh": ("30",),
    "loi nhuan truoc thue": ("50",),
    "loi nhuan sau thue": ("60",),
    "lai co ban tren co phieu": ("70",),
    "tai san co dinh huu hinh": ("221",),
    "tai san co dinh vo hinh": ("227",),
    "tai san co dinh": ("220",),
    "tai san ngan han": ("100",),
    "hang ton kho": ("140",),
    "tai san dai han": ("200",),
    "tong tai san": ("270",),
    "no phai tra": ("300",),
    "no ngan han": ("310",),
    "no dai han": ("330",),
    "von chu so huu": ("400",),
    "von dieu le": ("411",),
    "loi nhuan sau thue chua phan phoi": ("421",),
}


def statement_hint(question: str) -> str | None:
    """Loại báo cáo mà câu hỏi NHIỀU KHẢ NĂNG cần. `None` = không đoán."""
    q = _fold(question)
    for stmt, cues in _STMT:
        if any(c in q for c in cues):
            return stmt
    return None


def metric_codes_hint(question: str) -> frozenset[str]:
    """Mã chỉ tiêu VAS suy được từ câu hỏi. Rỗng = không có tín hiệu."""
    q = _fold(question)
    matched = [
        (phrase, match.start(), match.end())
        for phrase in CODE_OF
        for match in re.finditer(re.escape(phrase), q)
    ]
    # Only keep maximal phrases.  Otherwise "tổng tài sản cố định hữu hình"
    # also fires the shorter "tổng tài sản" hint (270), which dominates the
    # binder and selects the balance-sheet total instead of code 221.  The
    # same rule disambiguates retained earnings (421) from net income (60).
    maximal = {
        phrase
        for phrase, start, end in matched
        if not any(
            (other_end - other_start) > (end - start)
            and start < other_end
            and other_start < end
            for _other, other_start, other_end in matched
        )
    }
    out: set[str] = set()
    for phrase in maximal:
        out.update(CODE_OF[phrase])
    return frozenset(out)
