"""Chuẩn hoá chuỗi để khớp thực thể.

CHÉP NGUYÊN VĂN NGỮ NGHĨA từ `_codebase/src/vifinqa/retrieval/metadata_filter.py`
của BTC. Đây không phải lựa chọn kỹ thuật của ta — BTC là bên chấm, nên hàm
chuẩn hoá của ta phải khớp hàm của họ tới từng ký tự. Lệch một quy tắc là lệch
tập ứng viên, và ta sẽ tối ưu trên một bài toán khác bài toán được chấm.

Nguồn: `_ascii_compact`, `_company_aliases`, `_ticker_mentioned`.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["ascii_compact", "company_aliases", "ticker_mentioned",
           "LEGAL_PREFIXES"]

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")

# Tiền tố pháp lý cắt được khi khớp tên. Giữ ĐÚNG thứ tự của BTC: vòng lặp của
# họ `break` ở tiền tố khớp ĐẦU TIÊN, nên thứ tự quyết định kết quả với tên bắt
# đầu bằng "congtycophan" (khớp trước "ctcp").
LEGAL_PREFIXES = ("congtycophan", "ctcp", "congtytnhh", "tnhh")

# Ngưỡng của BTC: phần đuôi sau khi cắt tiền tố phải dài ≥ 6 ký tự mới được
# nhận làm alias. Ngắn hơn thì quá dễ khớp nhầm.
_MIN_SUFFIX = 6


def ascii_compact(text: str) -> str:
    """NFD → bỏ dấu → `đ`→`d` → lower → bỏ mọi ký tự không alnum."""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    stripped = stripped.replace("đ", "d").replace("Đ", "D").lower()
    return _NON_ALNUM_RE.sub("", stripped)


def company_aliases(name: str) -> tuple[str, ...]:
    """Dạng nén của tên, cộng dạng đã cắt tiền tố pháp lý nếu đủ dài."""
    compact = ascii_compact(name)
    aliases = [compact] if compact else []
    for prefix in LEGAL_PREFIXES:
        if compact.startswith(prefix):
            suffix = compact[len(prefix):]
            if len(suffix) >= _MIN_SUFFIX:
                aliases.append(suffix)
            break
    return tuple(aliases)


def ticker_mentioned(query: str, ticker: str) -> bool:
    """Mã xuất hiện như một token viết hoa, không dính chữ/số hai bên.

    Dùng `query.upper()` như BTC: câu hỏi viết `vjc` thường cũng được tính.
    """
    return bool(re.search(rf"(?<![A-Z0-9]){re.escape(ticker.upper())}(?![A-Z0-9])",
                          query.upper()))
