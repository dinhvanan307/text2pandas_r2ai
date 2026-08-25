"""Table Card — biểu diễn văn bản của một bảng, dùng để index.

Đây là thứ thay cho "chunking" trong bài toán này. Chunk cắt tài liệu thành
đoạn nhân tạo rồi phải ánh xạ ngược về bảng; Table Card giữ nguyên đơn vị mà
BTC chấm điểm (một bảng tại một số dòng) và chỉ thay đổi *nội dung đem đi
index*.

Khác biệt cốt lõi so với index cũ: **không có con số nào**. Đo trên index cũ,
44% token là số — chúng không bao giờ khớp câu hỏi, nhưng làm BM25 phạt độ dài
các bảng tài chính và đẩy bảng danh sách nhân sự ngắn gọn lên trên.

Thành phần của card, theo thứ tự trọng số giảm dần:
  1. tiêu đề/thuyết minh ngay trên bảng — chứa đúng cụm từ câu hỏi hay dùng
  2. nhãn dòng                          — tên chỉ tiêu
  3. nhãn cột                           — kỳ, đơn vị
  4. loại báo cáo + mã CK + năm         — để lọc và để khớp thô
"""

from __future__ import annotations

import re

__all__ = ["build_card", "CARD_WEIGHTS"]

# Lặp lại một trường n lần là cách tăng trọng số trong BM25 mà không cần đổi
# công thức chấm. Rẻ, minh bạch, và chỉnh được bằng một con số.
CARD_WEIGHTS = {"context": 3, "row_labels": 2, "col_labels": 1, "meta": 1}

_NUMERIC = re.compile(r"^[\d.,()%\-/\s]+$")
_LONG_NUM = re.compile(r"\d[\d.,]{3,}")

_TYPE_WORDS = {
    "balance_sheet": "bảng cân đối kế toán tài sản nguồn vốn",
    "income_statement": "kết quả hoạt động kinh doanh doanh thu lợi nhuận chi phí",
    "cash_flow": "lưu chuyển tiền tệ dòng tiền",
    "equity_change": "thay đổi vốn chủ sở hữu",
    "note": "thuyết minh báo cáo tài chính",
    "subsidiary": "công ty con công ty liên kết tỷ lệ sở hữu",
    "personnel": "nhân sự hội đồng quản trị ban giám đốc",
    "toc": "mục lục",
    "other": "",
}


def _clean_label(text: str) -> str:
    """Bỏ nhãn thuần số và cắt các cụm số dài khỏi nhãn hỗn hợp."""
    s = text.strip()
    if not s or _NUMERIC.match(s):
        return ""
    s = _LONG_NUM.sub(" ", s)
    return " ".join(s.split())


def build_card(
    statement_type: str,
    ticker: str,
    doc_year: int | None,
    basis: str | None,
    years: list[int],
    context: str,
    row_labels: list[str],
    col_labels: list[str],
    unit_raw: str,
) -> str:
    """Sinh nội dung đem đi index cho một bảng. Không chứa giá trị số."""
    ctx = _clean_label(context)
    rows = [x for x in (_clean_label(r) for r in row_labels) if x]
    cols = [x for x in (_clean_label(c) for c in col_labels) if x]

    meta = " ".join(
        filter(None, [
            ticker,
            str(doc_year) if doc_year else "",
            " ".join(str(y) for y in years),
            {"separate": "riêng công ty mẹ", "consolidated": "hợp nhất"}.get(basis or "", ""),
            _TYPE_WORDS.get(statement_type, ""),
            _clean_label(unit_raw),
        ])
    )

    parts: list[str] = []
    parts += [ctx] * CARD_WEIGHTS["context"]
    parts += [" ".join(rows)] * CARD_WEIGHTS["row_labels"]
    parts += [" ".join(cols)] * CARD_WEIGHTS["col_labels"]
    parts += [meta] * CARD_WEIGHTS["meta"]
    return " ".join(p for p in parts if p.strip())
