"""RC-05 · Chuẩn hoá văn bản tiếng Việt — MỘT hàm duy nhất cho cả index và query.

Audit A-06 bắt được lỗi: FTS không dấu **sai với chữ `đ`**. Nguyên nhân là
`unicode61 remove_diacritics 2` của SQLite bỏ dấu phụ theo Unicode, nhưng `đ`
(U+0111) **không phải** `d` + dấu phụ — nó là một ký tự riêng. Nên `đầu tư`
bỏ dấu ra `đau tu`, còn người dùng gõ `dau tu`: không khớp.

Hệ quả thực tế là im lặng: truy vấn không lỗi, chỉ **trả về ít kết quả hơn**.
Không ai phát hiện cho tới khi so hai tập candidate.

Module này tồn tại để **không có hai bản logic chuẩn hoá**. Nếu build dùng một
hàm và API dùng một hàm khác, chúng sẽ lệch nhau sau vài lần sửa, và khi lệch
thì chỉ mục nói một đằng còn truy vấn hỏi một nẻo. Mọi nơi cần chuẩn hoá —
dựng `table_cards`, dựng FTS, xử lý câu hỏi người dùng, so khớp nhãn cột — đều
gọi `normalize_search_text()` ở đây.

**Không đụng vào văn bản gốc.** `section_text`, `row_label`, `col_label` giữ
nguyên để hiển thị và trích dẫn. Chuẩn hoá chỉ sinh ra trường tìm kiếm SONG
SONG.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["NORMALIZE_VERSION", "normalize_search_text", "normalize_token",
           "fold_vietnamese", "fts_match_expr", "ACCENT_PAIRS", "FTS_OPERATORS"]

NORMALIZE_VERSION = "1.0"

# Toán tử của FTS5. Một chuỗi người dùng chứa chúng được HIỂU LÀ CÚ PHÁP chứ
# không phải văn bản: `NOT` trong "chi phí NOT tính" đổi hẳn nghĩa truy vấn,
# còn một dấu `"` lẻ làm câu truy vấn không parse được và ném lỗi ngay.
FTS_OPERATORS = frozenset({"AND", "OR", "NOT", "NEAR"})

# Ánh xạ ký tự KHÔNG phải "chữ cái + dấu phụ", nên NFD không tách được.
# `đ`/`Đ` là ca duy nhất trong bảng chữ cái tiếng Việt, và cũng là ca đã làm
# hỏng chỉ mục ở RC1.
_SPECIAL = str.maketrans({
    "đ": "d", "Đ": "d",
    # Một số corpus dùng ký tự nhìn giống nhưng khác code point.
    "ð": "d", "Ð": "d",
    "’": "'", "‘": "'",     # dấu nháy cong → thẳng
    "“": '"', "”": '"',
    " ": " ",                     # no-break space
    "–": "-", "—": "-",      # en/em dash
})

_WS = re.compile(r"\s+")
_ALNUM = re.compile(r"[0-9a-z]")


def fold_vietnamese(text: str) -> str:
    """Bỏ dấu tiếng Việt, kể cả `đ`. KHÔNG hạ chữ thường, KHÔNG đụng khoảng trắng."""
    if not text:
        return ""
    # Thứ tự quan trọng: xử lý `đ` TRƯỚC khi NFD, vì sau NFD nó vẫn là U+0111
    # nguyên vẹn và sẽ sống sót qua bước lọc combining mark.
    t = text.translate(_SPECIAL)
    t = unicodedata.normalize("NFD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return unicodedata.normalize("NFC", t)


def normalize_search_text(text: str) -> str:
    """Dạng chuẩn dùng cho CẢ chỉ mục lẫn truy vấn.

    NFC → casefold → `đ`→`d` → bỏ dấu phụ → gộp khoảng trắng.

    `casefold()` chứ không phải `lower()`: nó xử lý đúng các ca gấp chữ mà
    `lower()` bỏ sót. Với tiếng Việt hai hàm cho cùng kết quả, nhưng corpus có
    lẫn tên riêng nước ngoài.
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFC", text)
    t = t.casefold()
    t = fold_vietnamese(t)
    return _WS.sub(" ", t).strip()


def normalize_token(text: str) -> str:
    """Như trên nhưng bỏ luôn dấu câu — dùng khi so khớp NHÃN, không phải FTS.

    FTS5 tự tách token nên không cần bước này; so khớp nhãn cột thì cần, vì
    OCR hay chèn dấu chấm và gạch nối vào giữa (`Mã.số`, `Mã-số`).
    """
    return _WS.sub(" ", re.sub(r"[^0-9a-z]+", " ",
                               normalize_search_text(text))).strip()


def fts_match_expr(text: str, *, phrase: bool = False) -> str:
    """Dựng biểu thức `MATCH` an toàn từ văn bản người dùng gõ vào.

    RC-05 · Nội dung `table_cards_fts` được lưu ở DẠNG CHUẨN. Truy vấn vì thế
    cũng phải ở dạng chuẩn — nếu không, `MATCH 'đồng'` cho tokenizer ra `đong`
    (vì `remove_diacritics 2` không gập được `đ`) và khớp KHÔNG CÁI GÌ.

    Đó là hành vi có chủ đích: **hỏng thì hỏng to**. RC1 làm ngược lại — cùng
    câu hỏi đó trả về 997 thẻ trong khi đúng ra là 104.792, một kết quả trông
    hợp lý nên không ai nghi ngờ suốt cả vòng đời gói.

    Hàm này cũng vô hiệu hoá toán tử FTS5 lẫn trong văn bản. Không làm thì
    `"chi phí NOT tính"` bị hiểu thành một phép loại trừ, và một dấu nháy lẻ
    làm câu truy vấn ném lỗi cú pháp.

    >>> fts_match_expr("Đầu tư")
    '"dau" "tu"'
    >>> fts_match_expr("Đầu tư", phrase=True)
    '"dau tu"'
    """
    norm = normalize_search_text(text)
    if not norm:
        return ""
    if phrase:
        return '"' + norm.replace('"', "") + '"'
    # Mỗi token bọc nháy kép: FTS5 coi chuỗi trong nháy là văn bản thuần, nên
    # `AND`/`OR`/`NOT`/`NEAR` lọt vào cũng chỉ là một từ để tìm.
    #
    # Token KHÔNG có ký tự chữ-số bị loại: tokenizer `unicode61` sẽ nuốt hết
    # dấu câu và cho ra token RỖNG, tức một vế `MATCH` không tìm gì nhưng vẫn
    # tham gia phép AND ngầm. Chuỗi toàn dấu câu vì thế phải cho ra biểu thức
    # rỗng để nơi gọi biết mà bỏ hẳn truy vấn, thay vì chạy một câu vô nghĩa.
    toks = [t for t in norm.split() if _ALNUM.search(t)]
    return " ".join('"' + t.replace('"', "") + '"' for t in toks)


# Bộ hồi quy tối thiểu theo RC-05. Mỗi cặp phải cho **cùng một** dạng chuẩn.
# Đây là hợp đồng: thêm cặp thì thêm ở đây, đừng viết test rời rạc.
ACCENT_PAIRS: tuple[tuple[str, str], ...] = (
    ("tiền", "tien"),
    ("tương", "tuong"),
    ("đương", "duong"),
    ("đầu tư", "dau tu"),
    ("dòng tiền", "dong tien"),
    ("đồng", "dong"),
    ("đường", "duong"),
    # Bổ sung: các ca `đ` ở giữa từ và `đ` viết hoa, vốn là chỗ lỗi nấp.
    ("Đầu Tư", "dau tu"),
    ("hàng tồn kho", "hang ton kho"),
    ("lưu chuyển tiền tệ", "luu chuyen tien te"),
)
