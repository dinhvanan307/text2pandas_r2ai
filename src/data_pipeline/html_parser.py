"""DP-005 — D2 Raw Table Extraction: span-aware, tách source cell và grid cell.

Khác biệt cốt lõi so với bản prototype: **một ô số có `colspan=2` chỉ sinh
MỘT observation**, không phải hai. Bản cũ duyệt lưới đặc nên nhân đôi giá trị
theo span — lỗi im lặng tạo ra observation trùng.

    source_cell     ô THẬT trong HTML (một thẻ <td>)
    grid_cell       vị trí LOGIC được ô đó phủ
    is_span_anchor  vị trí gốc; chỉ anchor mới sinh observation

Lưới đặc chỉ được materialise dưới hạn mức cấu hình. Bảng lớn nhất trong
corpus là 1.008×1.954 ≈ 2 triệu ô — không có hạn mức thì tiến trình bị OOM
giết mà không để lại log. Bảng vượt hạn mức **vẫn giữ source cells và status**
(DI-02), chỉ không dựng lưới.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import html as lxml_html

from data_pipeline.cleaning import clean_text
from data_pipeline.models import (
    CellRole,
    GridCell,
    ParseStatus,
    SourceCell,
    make_uid,
)

__all__ = ["ParsedTable", "parse_table", "PARSER_VERSION", "DEFAULT_GRID_BUDGET"]

PARSER_VERSION = "1.0"
DEFAULT_GRID_BUDGET = 120_000
_MAX_SPAN = 200
_WS = re.compile(r"\s+")


@dataclass(slots=True)
class ParsedTable:
    table_uid: str
    parse_status: ParseStatus
    source_cells: list[SourceCell] = field(default_factory=list)
    grid_cells: list[GridCell] = field(default_factory=list)
    n_grid_rows: int = 0
    n_grid_cols: int = 0
    n_img_stripped: int = 0
    diagnostics: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.parse_status is ParseStatus.OK

    def anchors(self) -> list[SourceCell]:
        return self.source_cells

    def grid_index(self) -> dict[tuple[int, int], GridCell]:
        return {(g.grid_row_idx, g.grid_col_idx): g for g in self.grid_cells}

    def by_uid(self) -> dict[str, SourceCell]:
        return {c.source_cell_uid: c for c in self.source_cells}

    def row_texts(self, row: int) -> list[str]:
        """Text clean theo cột của một hàng lưới, đã điền span."""
        idx = self.grid_index()
        cells = self.by_uid()
        out = []
        for c in range(self.n_grid_cols):
            g = idx.get((row, c))
            out.append(cells[g.source_cell_uid].text_clean if g else "")
        return out


def _to_int(value: str | None, default: int = 1) -> int:
    if not value:
        return default
    try:
        n = int(value.strip())
    except (TypeError, ValueError):
        return default
    return n if 1 <= n <= _MAX_SPAN else default


def parse_table(
    table_uid: str, raw_html: str, grid_budget: int = DEFAULT_GRID_BUDGET
) -> ParsedTable:
    """HTML -> source cells + grid mapping. Không suy diễn tài chính ở đây."""
    out = ParsedTable(table_uid=table_uid, parse_status=ParseStatus.OK)
    out.n_img_stripped = len(re.findall(r"<img", raw_html, re.I))

    try:
        root = lxml_html.fragment_fromstring(raw_html, create_parent="div")
    except Exception as exc:  # noqa: BLE001 — bắt mọi lỗi parse, không nuốt
        out.parse_status = ParseStatus.TABLE_PARSE_FAILED
        out.diagnostics.append(f"lxml: {exc!r}")
        return out

    trs = root.xpath(".//tr")
    if not trs:
        out.parse_status = ParseStatus.TABLE_PARSE_FAILED
        out.diagnostics.append("không có <tr>")
        return out

    occupied: set[tuple[int, int]] = set()
    max_col = 0
    n_rows = 0

    for src_row, tr in enumerate(trs):
        col_cursor = 0
        for src_col, td in enumerate(tr.xpath("./td|./th")):
            while (src_row, col_cursor) in occupied:
                col_cursor += 1
            rowspan = _to_int(td.get("rowspan"))
            colspan = _to_int(td.get("colspan"))
            text_source = _WS.sub(" ", td.text_content().replace("\n", " "))
            cleaned = clean_text(text_source)

            uid = make_uid(table_uid, src_row, src_col)
            out.source_cells.append(
                SourceCell(
                    source_cell_uid=uid, table_uid=table_uid,
                    source_row_idx=src_row, source_col_idx=src_col,
                    grid_row_idx=src_row, grid_col_idx=col_cursor,
                    rowspan=rowspan, colspan=colspan,
                    text_source=text_source, text_clean=cleaned.text_clean,
                    clean_rules=cleaned.rules, clean_status=cleaned.status,
                )
            )
            for dr in range(rowspan):
                for dc in range(colspan):
                    pos = (src_row + dr, col_cursor + dc)
                    occupied.add(pos)
                    out.grid_cells.append(
                        GridCell(
                            table_uid=table_uid,
                            grid_row_idx=pos[0], grid_col_idx=pos[1],
                            source_cell_uid=uid,
                            is_span_anchor=(dr == 0 and dc == 0),
                            cell_role=CellRole.UNKNOWN,
                        )
                    )
            max_col = max(max_col, col_cursor + colspan)
            n_rows = max(n_rows, src_row + rowspan)
            col_cursor += colspan

    out.n_grid_rows = n_rows
    out.n_grid_cols = max_col

    if n_rows * max_col > grid_budget:
        # Giữ source cells và status; chỉ bỏ lưới. Không silent drop (DI-02).
        out.grid_cells = []
        out.parse_status = ParseStatus.TABLE_TOO_LARGE
        out.diagnostics.append(
            f"vượt hạn mức lưới: {n_rows}×{max_col}={n_rows*max_col:,} > {grid_budget:,}"
        )
        return out

    seen: set[tuple[int, int]] = set()
    for g in out.grid_cells:
        key = (g.grid_row_idx, g.grid_col_idx)
        if key in seen:
            out.diagnostics.append(f"span chồng lấn tại {key}")
        seen.add(key)

    n_anchor = sum(1 for g in out.grid_cells if g.is_span_anchor)
    if n_anchor != len(out.source_cells):
        out.diagnostics.append(
            f"bất biến sai: {n_anchor} anchor ≠ {len(out.source_cells)} source cell"
        )
    return out
