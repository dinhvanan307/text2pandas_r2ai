"""Use case: một câu hỏi -> bảng liên quan + CSV evidence + pandas_query + answer.

Bất biến của module này: **`answer` phải bằng `eval(pandas_query)`** chạy trên
đúng CSV được đóng gói. Mọi phép quy đổi đơn vị nằm TRONG câu lệnh, không nằm
ngoài — nếu không thì Execution Accuracy và Answer Accuracy sẽ lệch nhau.

CSV xuất theo **định dạng dài** (`row_label, col_label, value_raw, value`) chứ
không phải lưới gốc. Lý do: nó biến bài toán "dò tên cột" thành bài toán "khớp
giá trị", vốn dễ hơn hẳn cho cả template lẫn LLM, và làm câu lệnh pandas đọc
được bằng mắt người khi chấm.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from text2pandas.domain.rules.question import QuestionSlots
from text2pandas.domain.values.vn_number import (
    ParseStatus,
    SepConvention,
    detect_convention,
    parse_vn_number,
)
from text2pandas.infrastructure.parsing.html_table import TableGrid, parse_table_html
from text2pandas.infrastructure.retrieval.index import TableHit, tokenize

__all__ = ["AnswerResult", "LongCell", "to_long_format", "answer_question"]

_YEAR = re.compile(r"\b(20[0-2]\d)\b")

# Một bảng hợp lệ trong corpus này không có tới 50k ô số. Vượt ngưỡng nghĩa là
# bảng hỏng hoặc bị OCR gộp nhầm — cắt để CSV bài nộp không phình vô hạn.
MAX_LONG_ROWS = 50_000


@dataclass(slots=True)
class LongCell:
    row_label: str
    row_path: str
    col_label: str
    value_raw: str
    value: Decimal


@dataclass(slots=True)
class AnswerResult:
    qid: int
    answer: float | None
    relevant_docs: list[str]
    relevant_tables: list[str]
    evidence: list[dict[str, str]]
    pandas_query: str
    confidence: float
    csv_rows: list[LongCell] = field(default_factory=list)
    csv_name: str = ""
    has_csv: bool = False
    notes: list[str] = field(default_factory=list)


def _row_label(cells: list[str], upto: int) -> str:
    """Nhãn dòng = ô văn bản đầu tiên bên trái ô giá trị."""
    for c in cells[:upto]:
        s = c.strip()
        if s and not s.replace(".", "").replace(",", "").replace("-", "").isdigit():
            return s
    return ""


def _col_labels(grid: TableGrid) -> list[str]:
    """Nhãn cột = ghép các ô tiêu đề ở những dòng đầu không có giá trị số."""
    labels = [""] * grid.n_cols
    conv = detect_convention([c for r in grid.cells for c in r])
    if conv is SepConvention.UNKNOWN:
        conv = SepConvention.DOT_THOUSANDS
    for row in grid.cells[:3]:
        # Dòng tiêu đề thường CHỨA chữ số ("31/12/2015VND", "Quý 4/2023").
        # Tiêu chí đúng là "parse được thành số", không phải "có chữ số" —
        # nhầm hai thứ này làm mất nhãn cột ở 60% số bảng.
        filled = [c for c in row if c.strip()]
        if not filled:
            continue
        numeric = sum(
            1 for c in filled if parse_vn_number(c, conv).status is ParseStatus.OK
        )
        if numeric > len(filled) // 2:
            break
        for i, c in enumerate(row):
            s = c.strip()
            if s and s not in labels[i]:
                labels[i] = (labels[i] + " " + s).strip()
    for i, lab in enumerate(labels):
        if not lab:
            labels[i] = f"c{i}"
    return labels


def to_long_format(grid: TableGrid) -> list[LongCell]:
    """Lưới -> danh sách ô có nhãn. Bỏ ô không parse được thành số."""
    conv = detect_convention([c for row in grid.cells for c in row])
    if conv is SepConvention.UNKNOWN:
        conv = SepConvention.DOT_THOUSANDS  # quy ước áp đảo: 1.961/1.973 tài liệu
    cols = _col_labels(grid)
    out: list[LongCell] = []
    for row in grid.cells:
        for j, cell in enumerate(row):
            if not cell:
                continue
            p = parse_vn_number(cell, conv)
            if p.status is not ParseStatus.OK or p.value is None:
                continue
            rl = _row_label(row, j)
            if not rl:
                continue
            out.append(LongCell(rl, rl, cols[j] if j < len(cols) else f"c{j}", cell, p.value))
            if len(out) >= MAX_LONG_ROWS:
                return out
    return out


def _score_row(question_tokens: set[str], label: str) -> float:
    lt = set(tokenize(label))
    if not lt:
        return 0.0
    return len(question_tokens & lt) / (len(lt) ** 0.5)


def _pick_cell(
    rows: list[LongCell], slots: QuestionSlots
) -> tuple[LongCell | None, float]:
    """Chọn ô trả lời: khớp nhãn dòng với câu hỏi, ưu tiên cột đúng năm."""
    if not rows:
        return None, 0.0
    qt = set(tokenize(slots.text))
    target_year = str(max(slots.years)) if slots.years else None

    best: LongCell | None = None
    best_score = -1.0
    for cell in rows:
        s = _score_row(qt, cell.row_path)
        if s <= 0:
            continue
        if target_year:
            if target_year in cell.col_label:
                s += 1.0
            elif _YEAR.search(cell.col_label):
                s -= 0.5  # cột của năm khác
        if s > best_score:
            best, best_score = cell, s
    if best is None:
        return None, 0.0
    return best, min(best_score / 3.0, 1.0)


def _select_tables(hits: list[TableHit], max_tables: int = 20) -> list[TableHit]:
    """Chọn tập bảng nộp theo F2.

    F2 = 5h/(4g+N). Thêm một bảng sai làm mẫu số tăng 1; bỏ sót một bảng đúng
    làm mẫu số tăng 4 và tử số giảm. Tỷ lệ thiệt hại ≈ 5,5:1 nghiêng về recall,
    NHƯNG chỉ tới ngưỡng: thêm bảng có xác suất đúng dưới ~0,15 thì lỗ. Ở đây
    dùng ngưỡng điểm tương đối thay cho xác suất đã hiệu chỉnh — sẽ thay bằng
    xác suất thật khi có bộ evidence gold.
    """
    if not hits:
        return []
    top = hits[0].score
    # Ngưỡng nới rất rộng: ở mức F2 hiện tại (~0,03) một bảng chỉ cần xác suất
    # đúng > 0,5% là đã có lợi khi thêm vào. Cắt ở 0,45×top là quá dè dặt —
    # nó vứt đi những bảng có kỳ vọng dương rõ ràng.
    keep = [h for h in hits[:max_tables] if h.score >= 0.12 * top]
    return keep or hits[:1]


def answer_question(
    slots: QuestionSlots,
    hits: list[TableHit],
    html_by_locator: dict[str, str],
    n_tables: int = 20,
    doc_ranking: list[str] | None = None,
    n_docs: int = 5,
) -> AnswerResult:
    chosen = _select_tables(hits, n_tables)
    # `relevant_docs` được chấm bằng F2 RIÊNG, độc lập với `relevant_tables`.
    # Trói nó vào các bảng đã chọn là tự bỏ điểm: truy hồi cấp tài liệu của ta
    # (recall 0,55 · MRR@5 0,75) tốt hơn hẳn cấp bảng (recall 0,13), nên phải
    # để nó tự do. Ngưỡng thêm một tài liệu: p > F2_docs/5 ≈ 0,099.
    docs_out = list(doc_ranking or [])[:n_docs] if doc_ranking else []
    if not chosen:
        return AnswerResult(
            slots.qid, 0.0, docs_out, [], [], "", 0.0,
            notes=["không truy hồi được bảng nào"],
        )

    primary = chosen[0]
    grid = parse_table_html(html_by_locator.get(primary.locator, ""))
    rows = to_long_format(grid) if grid.ok else []
    cell, conf = _pick_cell(rows, slots)

    csv_name = f"{primary.doc_id}_line{primary.line_no}.csv"
    csv_path = f"data/{csv_name}"
    var = "df1"
    notes: list[str] = []
    if cell is None:
        if not rows:
            # Không có ô số nào: nộp bảng để giữ điểm truy hồi, không bịa evidence.
            return AnswerResult(
                slots.qid, 0.0, docs_out or sorted({h.doc_id for h in chosen}),
                [h.locator for h in chosen], [], "", 0.0,
                [], "", ["bảng không chứa ô số parse được"],
            )
        # Không khớp được nhãn: lấy ô đầu làm dự phòng. Giá trị gần như chắc
        # chắn sai, nhưng bất biến answer == eval(query) phải được giữ — nó là
        # tín hiệu chất lượng nội bộ, đánh mất nó là mù cả pipeline.
        cell, conf = rows[0], 0.0
        notes_fallback = ["không khớp được nhãn dòng nào — dùng ô đầu tiên"]
    else:
        notes_fallback = []

    # Quy đổi đơn vị nằm TRONG câu lệnh để giữ bất biến answer == eval(query).
    # Giá trị thật (VND) = ô × 10^table_exp.
    # Đáp án theo đơn vị câu hỏi = giá trị thật / 10^want_exp = ô × 10^(table_exp-want_exp).
    # Bản đầu làm NGƯỢC dấu: bảng không khai đơn vị (10^0) mà câu hỏi hỏi "tỷ đồng"
    # thì nó NHÂN 10^9 thay vì CHIA — sai 10^18 trên 431/1.012 câu.
    table_exp = primary.unit_exponent or 0
    want_exp = slots.unit_exponent
    delta = 0
    if want_exp is not None:
        delta = table_exp - want_exp
        if delta:
            notes.append(f"quy đổi 10^{table_exp} → 10^{want_exp} (×10^{delta})")

    rl = cell.row_path.replace("'", "\\'")
    cl = cell.col_label.replace("'", "\\'")
    base = (
        f"{var}[({var}['row_path'] == '{rl}') & "
        f"({var}['col_label'] == '{cl}')]['value'].values[0]"
    )
    if delta == 0:
        query = f"float({base})"
        value = float(cell.value)
    elif delta > 0:
        query = f"float({base}) * {10 ** delta}"
        value = float(cell.value) * (10 ** delta)
    else:
        query = f"float({base}) / {10 ** (-delta)}"
        value = float(cell.value) / (10 ** (-delta))

    return AnswerResult(
        qid=slots.qid,
        answer=value,
        relevant_docs=docs_out or sorted({h.doc_id for h in chosen}),
        relevant_tables=[h.locator for h in chosen],
        evidence=[{"variable": var, "csv_path": csv_path}],
        pandas_query=query,
        confidence=conf,
        csv_rows=rows,
        csv_name=csv_name,
        notes=notes_fallback + notes,
    )


def write_long_csv(path: Path, rows: list[LongCell]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["row_path", "row_label", "col_label", "value_raw", "value"])
        for r in rows:
            w.writerow([r.row_path, r.row_label, r.col_label, r.value_raw, str(r.value)])
