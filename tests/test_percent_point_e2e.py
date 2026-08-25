"""PERCENT_POINT end-to-end + operation-precedence regressions.

ORIGIN (review 173 §5.1, re-audited in doc 174)
-----------------------------------------------
Doc 172 claimed the percentage-point defect was fixed. It was not: only
``result_dimension()`` had been touched, and there was no test that ran a
question through the whole pipeline. The independent audit then found something
worse than the reviewer reported -- the default path did not abstain, it
returned a *silently wrong number*:

    "Chênh lệch tỷ lệ nợ xấu 2023 so với 2022 ... điểm phần trăm?"
    15% vs 10%  ->  150.0        (15/10 * 100, i.e. a DIVIDE)
    expected    ->  5.0 điểm phần trăm

Root cause was not the unit layer at all. ``tỷ lệ`` is the NAME OF A METRIC,
but it lived in the DIVIDE operation lexicon, and DIVIDE was tested before
SUBTRACT. Every difference-of-ratio question was therefore routed to division.

These tests lock all three layers: lexicon, precedence, renderer.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

pd = pytest.importorskip("pandas")

from text2pandas.domain.units.lexicon import scan_question_unit  # noqa: E402
from text2pandas.pipelines.answering import CandidateCell, Unit, answer_question  # noqa: E402
from text2pandas.pipelines.answering.binding import Selector  # noqa: E402
from text2pandas.pipelines.answering.frame import classify_operation  # noqa: E402
from text2pandas.pipelines.answering.ir import DIVIDE, GROWTH, LOOKUP, SUBTRACT  # noqa: E402
from text2pandas.pipelines.answering.units import (  # noqa: E402
    MONEY, PERCENT, PERCENT_POINT, RATIO,
)


class InOrder(Selector):
    def pick(self, slot, pool):
        return pool[0] if pool else None


def pct_cell(col_label, value, row_index, period, row_path="Tỷ lệ nợ xấu"):
    return CandidateCell(
        df_var="df1", csv_path="t.csv", row_index=row_index, row_path=row_path,
        col_label=col_label, value_raw=str(value), value=float(value),
        parsed_raw=float(value), storage_exponent=0, unit=Unit(PERCENT),
        period=period)


def frames_from(cells):
    return {"df1": pd.DataFrame([
        {"row_path": c.row_path, "col_label": c.col_label,
         "value_raw": c.value_raw, "value": c.value} for c in cells])}


# ------------------------------------------------------- layer 1: the lexicon
@pytest.mark.parametrize("q,expected", [
    ("Mức thay đổi là bao nhiêu điểm phần trăm?", PERCENT_POINT),
    ("Tăng bao nhiêu điểm %?", PERCENT_POINT),
    ("Chênh lệch tỷ lệ nợ xấu là bao nhiêu điểm phần trăm?", PERCENT_POINT),
    ("Tỷ lệ nợ xấu năm 2023 là bao nhiêu %?", PERCENT),
    ("Doanh thu năm 2023 là bao nhiêu tỷ đồng?", MONEY),
])
def test_requested_unit_distinguishes_points_from_percent(q, expected):
    assert scan_question_unit(q)[0] == expected


# --------------------------------------------------- layer 2: the precedence
@pytest.mark.parametrize("q,expected", [
    # REGRESSION: a metric noun must not select an operation
    ("Chênh lệch tỷ lệ nợ xấu 2023 so với 2022 là bao nhiêu điểm phần trăm?", SUBTRACT),
    ("Chênh lệch doanh thu 2023 so với 2022 là bao nhiêu tỷ đồng?", SUBTRACT),
    ("Mức thay đổi giữa 2023 và 2022 là bao nhiêu điểm phần trăm?", SUBTRACT),
    # a bare ratio metric is a LOOKUP of a reported figure, not a division
    ("Tỷ lệ nợ xấu năm 2023 là bao nhiêu %?", LOOKUP),
    ("Hệ số thanh toán nhanh năm 2023 là bao nhiêu lần?", LOOKUP),
    # genuine relational constructions still route to DIVIDE
    ("Tỷ lệ nợ xấu trên tổng dư nợ năm 2023 là bao nhiêu %?", DIVIDE),
    ("Lợi nhuận trên mỗi cổ phiếu năm 2023 là bao nhiêu đồng?", DIVIDE),
    ("Doanh thu 2023 gấp bao nhiêu lần 2022?", DIVIDE),
    # growth still wins over difference
    ("Tăng trưởng doanh thu 2023 so với 2022 là bao nhiêu %?", GROWTH),
])
def test_operation_precedence(q, expected):
    assert classify_operation(q).op == expected


def test_metric_noun_alone_never_selects_an_operation():
    """The exact confusion that produced 150.0 instead of 5.0."""
    for noun in ("tỷ lệ", "tỷ trọng", "hệ số", "biên lợi nhuận", "vòng quay"):
        q = f"Chênh lệch {noun} X năm 2023 so với năm 2022 là bao nhiêu điểm phần trăm?"
        assert classify_operation(q).op == SUBTRACT, noun


# ------------------------------------------------------- layer 3: end-to-end
def test_percent_point_subtraction_end_to_end():
    """15% - 10% = 5 percentage points, through every stage."""
    a = pct_cell("2023%", 15, 0, "2023")
    b = pct_cell("2022%", 10, 1, "2022")
    res = answer_question(
        "Chênh lệch tỷ lệ nợ xấu năm 2023 so với năm 2022 là bao nhiêu điểm phần trăm?",
        [a, b], frames_from([a, b]), qid=1,
        requested_unit=Unit(PERCENT_POINT), selector=InOrder())

    assert res.status == "OK", res.reason
    assert res.ir.op == SUBTRACT
    assert res.ir.output_unit.dimension == PERCENT_POINT
    assert [o.role for o in res.operands] == ["minuend", "subtrahend"]
    assert res.answer == pytest.approx(5.0)
    assert res.validation.verdict == "PASS"


def test_operands_are_not_converted_into_percentage_points():
    """A point is the unit of the RESULT. Converting each operand into points
    is meaningless -- and the Unit Contract rightly refuses it, which is why
    the naive implementation abstained."""
    a = pct_cell("2023%", 15, 0, "2023")
    b = pct_cell("2022%", 10, 1, "2022")
    res = answer_question(
        "Chênh lệch tỷ lệ nợ xấu năm 2023 so với năm 2022 là bao nhiêu điểm phần trăm?",
        [a, b], frames_from([a, b]), qid=2,
        requested_unit=Unit(PERCENT_POINT), selector=InOrder())
    factors = next(t["factors"] for t in res.trace if t["stage"] == "RENDER")
    assert all(f == 1.0 for f in factors.values()), factors


def test_full_parse_path_produces_points_not_a_ratio():
    """No forced unit: the parser itself must reach 5.0, not 150.0."""
    from text2pandas.pipelines.answering.adapters import requested_unit_of
    q = "Chênh lệch tỷ lệ nợ xấu năm 2023 so với năm 2022 là bao nhiêu điểm phần trăm?"
    a = pct_cell("2023%", 15, 0, "2023")
    b = pct_cell("2022%", 10, 1, "2022")
    res = answer_question(q, [a, b], frames_from([a, b]), qid=3,
                          requested_unit=requested_unit_of(q), selector=InOrder())
    assert res.status == "OK", res.reason
    assert res.answer == pytest.approx(5.0)
    assert res.answer != pytest.approx(150.0), "regression: divided instead of subtracted"


def test_money_difference_is_unaffected():
    """No-regression: the ordinary money-difference path still works."""
    a = CandidateCell("df1", "t.csv", 0, "Doanh thu", "2023VND", "3000", 3000.0,
                      3000.0, 0, Unit(MONEY, 0), "2023")
    b = CandidateCell("df1", "t.csv", 1, "Doanh thu", "2022VND", "1000", 1000.0,
                      1000.0, 0, Unit(MONEY, 0), "2022")
    res = answer_question(
        "Chênh lệch doanh thu năm 2023 so với năm 2022 là bao nhiêu đồng?",
        [a, b], frames_from([a, b]), qid=4,
        requested_unit=Unit(MONEY, 0), selector=InOrder())
    assert res.status == "OK", res.reason
    assert res.answer == pytest.approx(2000.0)
