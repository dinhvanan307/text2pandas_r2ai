"""Dựng đường dẫn phân cấp cho từng dòng bảng.

Vì sao cần: 40,7% số ô trong Silver mang nhãn xuất hiện ở hơn 200 bảng khác
nhau. `TỔNG CỘNG` có mặt ở 10.538 bảng, `Cộng` ở 9.631, `Số dư cuối năm` ở
6.678. Một nhãn như thế **không định danh được chỉ tiêu nào** — biết ô tên
"Cộng" vẫn không biết nó cộng cái gì.

Đường dẫn phân cấp phục hồi thông tin đó từ hai nguồn đã có sẵn:

  1. `context` — mấy dòng ngay trên bảng, thường chứa số hiệu và tên thuyết minh
     ("5.1. Tiền và các khoản tương đương tiền")
  2. **dòng tiêu đề bên trong bảng** — những dòng có chữ nhưng không có ô số.
     Chúng hiện đang bị loại khỏi `cells` vì không mang giá trị, nhưng chính
     chúng là cha của các dòng dữ liệu.

Kết quả:  `Cộng`  →  `5.1 Tiền và các khoản tương đương tiền › Cộng`

Quy ước đánh số của BCTC Việt Nam cho biết cấp của mỗi dòng:

    A. B.        cấp 0   phần lớn (TÀI SẢN / NGUỒN VỐN)
    I. II. III.  cấp 1   mục
    1. 2. 3.     cấp 2   khoản
    1.1  a)  -   cấp 3   khoản con
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = ["RowPath", "extract_section", "build_row_paths", "normalize_label"]

SEP = " › "
MAX_DEPTH = 4
MAX_LEN = 220

# ── tiền tố đánh số → cấp ───────────────────────────────────────────────────
# Số La Mã phải đứng TRƯỚC chữ cái đơn: 'I', 'V', 'X' vừa là chữ cái hoa vừa là
# số La Mã. Nếu để mẫu chữ cái bắt trước thì 'I.' thành cấp 0 ngang hàng 'A.',
# làm sập một tầng phân cấp.
_LEVEL_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"^(I{1,3}|IV|VI{0,3}|IX|XI{0,3}|V|X)\s*[.)]\s+"), 1),  # I. II. IV.
    (re.compile(r"^([A-HJ-UWYZ])\s*[.)]\s+"), 0),                 # A. B. (trừ I,V,X)
    (re.compile(r"^(\d{1,2})\s*[.)]\s+(?!\d)"), 2),               # 1.  2)
    (re.compile(r"^(\d{1,2}\.\d{1,2})\s*[.)]?\s+"), 3),           # 1.1
    (re.compile(r"^([a-z])\s*[)]\s+"), 3),                        # a)  b)
    (re.compile(r"^[-–—▪•+]\s+"), 3),                             # -  ▪
)

# Tiêu đề thuyết minh ở cuối context: "5.1. Tiền và các khoản tương đương tiền"
_SECTION = re.compile(
    r"(\d{1,2}(?:\.\d{1,2}){0,2})\s*[.)]?\s+([A-ZÀ-Ỹ][^.]{4,90}?)\s*$"
)
_SECTION_ANY = re.compile(r"(\d{1,2}(?:\.\d{1,2}){0,2})\s*[.)]\s+([A-ZÀ-Ỹ][^.]{4,90})")

_NUMBERING = re.compile(r"^\s*(?:[A-Za-z]\s*[.)]|\d{1,2}(?:\.\d{1,2})*\s*[.)]?|[-–—▪•+])\s+")
_PURE_NUM = re.compile(r"^[\d.,()%\-\s]+$")
_WS = re.compile(r"\s+")

# Dòng chỉ mang nghĩa tổng hợp — bắt buộc phải có cha mới hiểu được.
GENERIC_LABELS = {
    "cộng", "tổng cộng", "tổng", "cong", "tong cong",
    "số dư cuối năm", "số dư đầu năm", "số cuối năm", "số đầu năm",
    "số dư cuối kỳ", "số dư đầu kỳ", "khác", "cộng dồn", "tổng số",
}


@dataclass(frozen=True, slots=True)
class RowPath:
    parts: tuple[str, ...]
    is_generic: bool

    def text(self) -> str:
        s = SEP.join(self.parts)
        return s[:MAX_LEN]

    @property
    def leaf(self) -> str:
        return self.parts[-1] if self.parts else ""


def normalize_label(label: str) -> str:
    """Bỏ tiền tố đánh số và chuẩn hoá khoảng trắng. Không đụng tới nội dung."""
    s = unicodedata.normalize("NFC", label).strip()
    s = _NUMBERING.sub("", s)
    return _WS.sub(" ", s).strip(" .:–—-")


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn").replace("đ", "d")


def is_generic(label: str) -> bool:
    return _fold(normalize_label(label)) in {_fold(g) for g in GENERIC_LABELS}


def _level_of(label: str) -> int | None:
    for pat, lvl in _LEVEL_PATTERNS:
        if pat.match(label):
            return lvl
    return None


def extract_section(context: str) -> str:
    """Rút tên mục/thuyết minh gần bảng nhất từ đoạn văn bản phía trên.

    Ưu tiên khớp ở CUỐI chuỗi — dòng gần bảng nhất là dòng mô tả đúng bảng đó.
    Không khớp được thì trả chuỗi rỗng, không đoán.
    """
    if not context:
        return ""
    ctx = _WS.sub(" ", context).strip()
    if m := _SECTION.search(ctx):
        return f"{m.group(1)} {m.group(2).strip()}"
    hits = _SECTION_ANY.findall(ctx)
    if hits:
        num, title = hits[-1]
        return f"{num} {title.strip()}"
    return ""


def build_row_paths(
    rows: list[list[str]],
    is_numeric_row: list[bool],
    section: str,
    skip_rows: int = 0,
) -> list[RowPath]:
    """Trả về đường dẫn cho từng dòng của lưới.

    `is_numeric_row[i]` = dòng i có ít nhất một ô parse được thành số.
    `skip_rows` = số dòng đầu đã được dùng làm tiêu đề CỘT. Chúng không có ô số
    nên nếu không loại sẽ bị coi là tiêu đề DÒNG và nhét ngày tháng vào đường
    dẫn của mọi dòng bên dưới.
    Dòng KHÔNG có ô số được coi là tiêu đề và trở thành tổ tiên của các dòng
    phía dưới — đây chính là thông tin đang bị mất khi chỉ lưu ô có giá trị.
    """
    out: list[RowPath] = []
    stack: list[tuple[int, str]] = []  # (cấp, nhãn đã chuẩn hoá)
    last_level = -1

    for i, row in enumerate(rows):
        if i < skip_rows:
            out.append(RowPath((), False))
            continue
        raw = ""
        for cell in row:
            s = cell.strip()
            if s and not _PURE_NUM.match(s):
                raw = s
                break
        if not raw:
            out.append(RowPath((), False))
            continue

        lvl = _level_of(raw)
        if lvl is None:
            # Không có tiền tố: là con của dòng có tiền tố gần nhất.
            lvl = last_level + 1 if stack else 0
        else:
            last_level = lvl

        while stack and stack[-1][0] >= lvl:
            stack.pop()

        label = normalize_label(raw) or raw.strip()
        parts = [p for _, p in stack]
        if section:
            parts = [section, *parts]
        parts = parts[-(MAX_DEPTH - 1):] + [label]

        out.append(RowPath(tuple(parts), is_generic(raw)))

        # Dòng tiêu đề (không có ô số nào) trở thành cha cho các dòng sau.
        if not is_numeric_row[i]:
            stack.append((lvl, label))

    return out
