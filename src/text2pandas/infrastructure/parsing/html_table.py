"""HTML table -> lưới ô chữ nhật, giữ nguyên văn bản gốc từng ô.

Corpus đã đo: chỉ tồn tại 3 thẻ (`table`, `tr`, `td`) và 2 thuộc tính
(`colspan` 133.322 lần, `rowspan` 81.799 lần). Không có `th`, không có
thuộc tính nào khác. Bộ parse này cố ý hẹp đúng bằng thực tế đó.

Nhiễu đã biết trong ô:
  - `<img src="data:image/jpeg;base64,...">` — 119 thẻ, tổng ~1 MB
  - thực thể HTML hỏng (`&IR;`, `&2;`) — KHÔNG được "sửa", chỉ giữ nguyên
  - chữ dính nhau do OCR (`Lợi nhuậnĐiều chỉnh`) — 68.532 ô; KHÔNG tách,
    vì tách sai thì hỏng vĩnh viễn còn khớp mờ chỉ hỏng một truy vấn
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from lxml import html as lxml_html

__all__ = ["TableGrid", "parse_table_html", "MAX_CELLS"]

# Chốt chặn bộ nhớ. Lưới được khai triển thành ma trận ĐẶC, nên một bảng
# 1.008 hàng × 1.954 cột sinh ~2 triệu chuỗi và giết tiến trình 3 GB RAM mà
# không để lại lỗi nào trong log. Bảng vượt ngưỡng vẫn được truy hồi (điểm F2
# giữ nguyên), chỉ không rút được giá trị — đánh đổi đúng chiều.
MAX_CELLS = 120_000

_IMG = re.compile(r"<img[^>]*>", re.I)
_WS = re.compile(r"[ \t ]+")


@dataclass(slots=True)
class TableGrid:
    """Lưới đã khai triển span. `cells[r][c]` luôn tồn tại (có thể là "")."""

    cells: list[list[str]]
    n_rows: int
    n_cols: int
    had_spans: bool
    n_img_stripped: int
    parse_error: str | None = None
    spans: list[tuple[int, int, int, int]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.parse_error is None and self.n_rows > 0

    def flat_text(self) -> str:
        return " ".join(c for row in self.cells for c in row if c)

    def column(self, idx: int) -> list[str]:
        return [row[idx] if idx < len(row) else "" for row in self.cells]


def _cell_text(el: Any) -> str:
    """Văn bản của một ô, đã gộp con, chưa chuẩn hoá ngữ nghĩa."""
    txt = el.text_content()
    txt = _WS.sub(" ", txt.replace("\n", " "))
    return txt.strip()


def _to_int(value: str | None, default: int = 1) -> int:
    if not value:
        return default
    try:
        n = int(value.strip())
    except (TypeError, ValueError):
        return default
    # Chặn span vô lý: một ô khai colspan=9999 sẽ làm nổ bộ nhớ.
    return n if 1 <= n <= 200 else default


def parse_table_html(raw_html: str) -> TableGrid:
    """Parse một chuỗi `<table>...</table>` thành lưới chữ nhật.

    rowspan/colspan được khai triển: giá trị của ô gốc được **lặp lại** vào
    mọi ô mà nó phủ. Vị trí span gốc vẫn được giữ trong `spans` để truy vết.
    """
    n_img = len(_IMG.findall(raw_html))
    cleaned = _IMG.sub("", raw_html) if n_img else raw_html

    try:
        root = lxml_html.fragment_fromstring(cleaned, create_parent="div")
    except Exception as exc:  # noqa: BLE001 — muốn bắt mọi lỗi parse
        return TableGrid([], 0, 0, False, n_img, parse_error=f"lxml: {exc!r}")

    rows = root.xpath(".//tr")
    if not rows:
        return TableGrid([], 0, 0, False, n_img, parse_error="no <tr>")

    grid: dict[tuple[int, int], str] = {}
    occupied: set[tuple[int, int]] = set()
    spans: list[tuple[int, int, int, int]] = []
    had_spans = False
    max_col = 0

    for r, tr in enumerate(rows):
        c = 0
        for td in tr.xpath("./td|./th"):
            while (r, c) in occupied:
                c += 1
            text = _cell_text(td)
            cs = _to_int(td.get("colspan"))
            rs = _to_int(td.get("rowspan"))
            if cs > 1 or rs > 1:
                had_spans = True
                spans.append((r, c, rs, cs))
            for dr in range(rs):
                for dc in range(cs):
                    occupied.add((r + dr, c + dc))
                    grid[(r + dr, c + dc)] = text
            max_col = max(max_col, c + cs)
            c += cs

    n_rows = (max(k[0] for k in grid) + 1) if grid else 0
    n_cols = max_col
    if n_rows * n_cols > MAX_CELLS:
        return TableGrid(
            [], n_rows, n_cols, had_spans, n_img,
            parse_error=f"too_large: {n_rows}x{n_cols}={n_rows*n_cols:,} ô > {MAX_CELLS:,}",
        )
    cells = [[grid.get((r, c), "") for c in range(n_cols)] for r in range(n_rows)]
    return TableGrid(cells, n_rows, n_cols, had_spans, n_img, None, spans)
