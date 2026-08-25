"""End-to-end pipeline tests.

RATIO is proven first and in full -- frame, IR, binding, unit contract,
rendered query, execution, validator, evidence -- because it is the smallest
operation that exercises every multi-operand mechanism at once.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

pd = pytest.importorskip("pandas")

from text2pandas.pipelines.answering import (  # noqa: E402
    ARGMAX, MAXIMUM, CandidateCell, DIVIDE, GROWTH, LOOKUP, SUBTRACT, SUM, AVG,
    Unit, answer_question, build_evidence,
)
from text2pandas.pipelines.answering.units import MONEY, PERCENT, RATIO, UNKNOWN  # noqa: E402
from text2pandas.pipelines.answering.binding import BoundOperand, Selector  # noqa: E402
from text2pandas.pipelines.answering.ir import OperandSlot  # noqa: E402


# --------------------------------------------------------------- fixtures
def cell(df_var, row_path, col_label, value_raw, value, parsed_raw,
         storage_exponent, unit, row_index=0, period=None, csv_path="t.csv"):
    return CandidateCell(
        df_var=df_var, csv_path=csv_path, row_index=row_index, row_path=row_path,
        col_label=col_label, value_raw=value_raw, value=value, parsed_raw=parsed_raw,
        storage_exponent=storage_exponent, unit=unit, period=period)


def frames_from(cells):
    """Build the pandas namespace the emitted query will run against."""
    out = {}
    for c in cells:
        out.setdefault(c.df_var, []).append(
            {"row_path": c.row_path, "col_label": c.col_label,
             "value_raw": c.value_raw, "value": c.value})
    return {k: pd.DataFrame(v) for k, v in out.items()}


class InOrder(Selector):
    """Bind each slot to the next unconsumed cell, in pool order.

    ``bind`` removes a chosen cell from the remaining pool, so "next" is always
    ``pool[0]``; keeping an external counter would walk off the end.
    """

    def pick(self, slot, pool):
        return pool[0] if pool else None


# ----------------------------------------------------------------- RATIO E2E
def test_ratio_end_to_end():
    """A DIVIDE question travels every stage and lands on the right number."""
    num = cell("df1", "Nợ xấu", "2023VND", "50.000", 50000.0, 50000.0, 0,
               Unit(MONEY, 0), row_index=0, period="2023")
    den = cell("df1", "Tổng dư nợ", "2023VND", "2.000.000", 2000000.0, 2000000.0, 0,
               Unit(MONEY, 0), row_index=1, period="2023")
    pool = [num, den]

    res = answer_question(
        "Tỷ lệ nợ xấu trên tổng dư nợ năm 2023 của ACB là bao nhiêu %?",
        pool, frames_from(pool), qid=1,
        requested_unit=Unit(PERCENT), selector=InOrder())

    assert res.status == "OK", res.reason
    assert res.ir.op == DIVIDE
    assert [o.role for o in res.operands] == ["numerator", "denominator"]
    assert res.answer == pytest.approx(2.5)          # 50k/2m = 2.5%
    assert res.validation.verdict == "PASS"
    assert len(res.evidence) == 1
    # the emitted query must be real, runnable pandas
    assert "df1[" in res.query and "/" in res.query
    # trace covers every stage that ran
    stages = [t["stage"] for t in res.trace]
    # POLICY sits between RENDER and EXECUTE so a zero denominator becomes a
    # reason code instead of a ZeroDivisionError swallowed by the executor.
    assert stages == ["FRAME", "ROUTE", "BIND", "RENDER", "POLICY", "EXECUTE",
                      "VALIDATE", "EVIDENCE"]


def test_ratio_across_different_source_scales():
    """Numerator in triệu, denominator in đồng: the contract must reconcile
    them before dividing, not after."""
    num = cell("df1", "Lợi nhuận", "Năm nayTriệu đồng", "1.000", 1000.0, 1000.0, 0,
               Unit(MONEY, 6), row_index=0)
    den = cell("df2", "Doanh thu", "2023VND", "10.000.000.000", 10_000_000_000.0,
               10_000_000_000.0, 0, Unit(MONEY, 0), row_index=0, csv_path="u.csv")
    pool = [num, den]
    res = answer_question("Tỷ lệ lợi nhuận trên doanh thu là bao nhiêu %?",
                          pool, frames_from(pool), qid=2,
                          requested_unit=Unit(PERCENT), selector=InOrder())
    assert res.status == "OK", res.reason
    # 1000 triệu = 1e9 ; 1e9 / 1e10 = 0.1 -> 10%
    assert res.answer == pytest.approx(10.0)
    assert len(res.evidence) == 2, "both dataframes must appear in evidence"


def test_ratio_abstains_on_unknown_storage_scale():
    num = cell("df1", "A", "2023VND", "5", 5.0, 5.0, None, Unit(MONEY, 0))
    den = cell("df1", "B", "2023VND", "10", 10.0, 10.0, 0, Unit(MONEY, 0), row_index=1)
    pool = [num, den]
    res = answer_question("Tỷ lệ A trên B là bao nhiêu %?", pool, frames_from(pool),
                          qid=3, requested_unit=Unit(PERCENT), selector=InOrder())
    assert res.status == "ABSTAIN"
    assert res.stage_failed == "RENDER"
    assert "MISSING_STORAGE_SCALE" in res.reason


def test_ratio_rejects_when_both_operands_are_the_same_cell():
    """Two distinct candidate objects pointing at one physical cell must not
    quietly produce 1.0 -- that is a selection failure wearing a valid answer."""
    a = cell("df1", "A", "2023VND", "5", 5.0, 5.0, 0, Unit(MONEY, 0), row_index=0)
    b = cell("df1", "A", "2023VND", "5", 5.0, 5.0, 0, Unit(MONEY, 0), row_index=0)
    res = answer_question("Tỷ lệ A trên A là bao nhiêu %?", [a, b], frames_from([a]),
                          qid=4, requested_unit=Unit(PERCENT), selector=InOrder())
    assert res.status == "REJECT"
    assert "DUPLICATE_OPERAND_CELLS" in res.reason


# ------------------------------------------------------------ other operations
def test_subtract_end_to_end():
    a = cell("df1", "Doanh thu", "2023VND", "3.000", 3000.0, 3000.0, 0,
             Unit(MONEY, 0), row_index=0, period="2023")
    b = cell("df1", "Doanh thu", "2022VND", "1.000", 1000.0, 1000.0, 0,
             Unit(MONEY, 0), row_index=1, period="2022")
    pool = [a, b]
    res = answer_question(
        "Chênh lệch doanh thu năm 2023 so với năm 2022 là bao nhiêu đồng?",
        pool, frames_from(pool), qid=5, requested_unit=Unit(MONEY, 0),
        selector=InOrder())
    assert res.status == "OK", res.reason
    assert res.ir.op == SUBTRACT
    assert [o.role for o in res.operands] == ["minuend", "subtrahend"]
    assert res.answer == pytest.approx(2000.0)


def test_growth_end_to_end():
    new = cell("df1", "Doanh thu", "2023VND", "1.200", 1200.0, 1200.0, 0,
               Unit(MONEY, 0), row_index=0, period="2023")
    old = cell("df1", "Doanh thu", "2022VND", "1.000", 1000.0, 1000.0, 0,
               Unit(MONEY, 0), row_index=1, period="2022")
    pool = [new, old]
    res = answer_question(
        "Tăng trưởng doanh thu năm 2023 so với năm 2022 là bao nhiêu %?",
        pool, frames_from(pool), qid=6, requested_unit=Unit(PERCENT),
        selector=InOrder())
    assert res.status == "OK", res.reason
    assert res.ir.op == GROWTH
    assert [o.role for o in res.operands] == ["new", "old"]
    assert res.answer == pytest.approx(20.0)


def test_sum_and_avg_end_to_end():
    cells = [cell("df1", "Doanh thu", f"{y}VND", "100", 100.0 * (i + 1),
                  100.0 * (i + 1), 0, Unit(MONEY, 0), row_index=i, period=str(y))
             for i, y in enumerate((2021, 2022, 2023))]
    res = answer_question(
        "Tổng cộng doanh thu năm 2021, năm 2022 và năm 2023 là bao nhiêu đồng?",
        cells, frames_from(cells), qid=7, requested_unit=Unit(MONEY, 0),
        selector=InOrder())
    assert res.status == "OK", res.reason
    assert res.ir.op == SUM
    assert res.answer == pytest.approx(600.0)

    res2 = answer_question(
        "Doanh thu trung bình năm 2021, năm 2022 và năm 2023 là bao nhiêu đồng?",
        cells, frames_from(cells), qid=8, requested_unit=Unit(MONEY, 0),
        selector=InOrder())
    assert res2.status == "OK", res2.reason
    assert res2.ir.op == AVG
    assert res2.answer == pytest.approx(200.0)


# ---------------------------------------------------------------- guardrails
def test_lookup_applies_contract_factor_not_a_hardcoded_million():
    """The spurious-/1e6 family, reproduced from data with no QID knowledge.

    Header says "Triệu đồng", ingest did NOT normalise (storage_exponent 0),
    question asks for triệu đồng -> the correct factor is 1.0.
    """
    c = cell("df1", "Tổng quỹ lương", "Năm nayTriệu đồng", "1.855.837",
             1855837.0, 1855837.0, 0, Unit(MONEY, 6))
    res = answer_question("Tổng quỹ lương năm 2022 của công ty mẹ EIB là bao nhiêu triệu đồng?",
                          [c], frames_from([c]), qid=42, requested_unit=Unit(MONEY, 6))
    assert res.status == "OK", res.reason
    assert res.answer == pytest.approx(1_855_837.0)
    assert "1000000" not in res.query


def test_lookup_divides_when_ingest_did_normalise():
    """Same header, same question -- but ingest already scaled to VND, so the
    very same contract now yields 1e-6. One rule, two outcomes, from data."""
    c = cell("df1", "Tổng quỹ lương", "Năm nayTriệu đồng", "1.855.837",
             1_855_837_000_000.0, 1855837.0, 6, Unit(MONEY, 6))
    res = answer_question("Tổng quỹ lương năm 2022 của công ty mẹ EIB là bao nhiêu triệu đồng?",
                          [c], frames_from([c]), qid=99, requested_unit=Unit(MONEY, 6))
    assert res.status == "OK", res.reason
    assert res.answer == pytest.approx(1_855_837.0)


def test_percent_question_answered_with_money_is_rejected():
    c = cell("df1", "Doanh thu", "2023VND", "1.000", 1000.0, 1000.0, 0, Unit(MONEY, 0))
    res = answer_question("Doanh thu năm 2023 là bao nhiêu %?", [c],
                          frames_from([c]), qid=10, requested_unit=Unit(PERCENT))
    assert res.status in ("ABSTAIN", "REJECT")
    assert res.answer is None


def test_unknown_requested_unit_abstains_at_route():
    c = cell("df1", "Doanh thu", "2023VND", "1.000", 1000.0, 1000.0, 0, Unit(MONEY, 0))
    res = answer_question("Doanh thu năm 2023 thế nào?", [c], frames_from([c]),
                          qid=11, requested_unit=Unit(UNKNOWN))
    assert res.status == "ABSTAIN"
    assert res.stage_failed == "ROUTE"
    assert res.reason == "UNKNOWN_REQUESTED_UNIT"


def test_cross_entity_extremum_abstains_instead_of_becoming_a_lookup():
    c = cell("df1", "Doanh thu", "2023VND", "1.000", 1000.0, 1000.0, 0, Unit(MONEY, 0))
    res = answer_question("Công ty nào có doanh thu cao nhất năm 2023, bao nhiêu tỷ đồng?",
                          [c], frames_from([c]), qid=12, requested_unit=Unit(MONEY, 9))
    assert res.status == "ABSTAIN"
    assert res.reason == "EXTREMUM_NEEDS_TWO_PERIODS"


def test_period_argmax_returns_the_year_from_executed_evidence():
    cells = [
        cell(
            "df1",
            "Doanh thu",
            f"{year}VND",
            str(value),
            value,
            value,
            0,
            Unit(MONEY, 0),
            row_index=index,
            period=str(year),
        )
        for index, (year, value) in enumerate(((2021, 100.0), (2022, 300.0), (2023, 200.0)))
    ]
    result = answer_question(
        "Năm nào doanh thu cao nhất trong các năm 2021, 2022 và 2023?",
        cells,
        frames_from(cells),
        qid=14,
        requested_unit=Unit(UNKNOWN),
        selector=InOrder(),
    )

    assert result.status == "OK", result.reason
    assert result.ir.op == ARGMAX
    assert result.ir.result_kind == "PERIOD_YEAR"
    assert result.answer == 2022.0
    assert "max(" in result.query


def test_period_maximum_returns_value_in_requested_unit():
    cells = [
        cell(
            "df1",
            "Doanh thu",
            f"{year}Triệu đồng",
            str(value),
            value,
            value,
            0,
            Unit(MONEY, 6),
            row_index=index,
            period=str(year),
        )
        for index, (year, value) in enumerate(((2021, 100.0), (2022, 300.0), (2023, 200.0)))
    ]
    result = answer_question(
        "Doanh thu cao nhất trong các năm 2021, 2022 và 2023 là bao nhiêu triệu đồng?",
        cells,
        frames_from(cells),
        qid=15,
        requested_unit=Unit(MONEY, 6),
        selector=InOrder(),
    )

    assert result.status == "OK", result.reason
    assert result.ir.op == MAXIMUM
    assert result.answer == 300.0


def test_select_at_arg_abstains_until_two_metrics_are_bound():
    result = answer_question(
        "Tại năm có chi phí XDCB cao nhất, số dư nợ đủ tiêu chuẩn là bao nhiêu triệu đồng?",
        [],
        {},
        qid=16,
        requested_unit=Unit(MONEY, 6),
    )

    assert result.status == "ABSTAIN"
    assert result.reason == "EXTREMUM_SELECT_AT_ARG_REQUIRES_TWO_METRICS"


def test_filtered_and_derived_extrema_abstain_instead_of_ignoring_semantics():
    filtered = answer_question(
        "Trong các năm có biên lợi nhuận trên 10%, doanh thu thấp nhất là bao nhiêu tỷ đồng?",
        [],
        {},
        requested_unit=Unit(MONEY, 9),
    )
    derived = answer_question(
        "Năm nào có mức tăng doanh thu cao nhất trong các năm 2021, 2022 và 2023?",
        [],
        {},
        requested_unit=Unit(UNKNOWN),
    )

    assert filtered.reason == "EXTREMUM_FILTERS_NOT_SUPPORTED"
    assert derived.reason == "EXTREMUM_DERIVED_RANKING_NOT_SUPPORTED"


def test_validator_never_edits_the_number():
    """A rejected case yields no answer at all -- it is not silently corrected."""
    c = cell("df1", "Doanh thu", "2023VND", "1.000", 1000.0, 1000.0, 0, Unit(MONEY, 0))
    res = answer_question("Doanh thu năm 2023 là bao nhiêu %?", [c],
                          frames_from([c]), qid=13, requested_unit=Unit(PERCENT))
    assert res.answer is None
    assert res.validation is None or res.validation.value is None


# ------------------------------------------------------------------ evidence
def _operand(role, c):
    return BoundOperand(role=role, slot=OperandSlot(role), cell=c,
                        quantity=c.native_quantity())


def test_evidence_lists_every_dataframe_the_query_uses():
    a = cell("df1", "A", "2023VND", "1", 1.0, 1.0, 0, Unit(MONEY, 0), csv_path="a.csv")
    b = cell("df2", "B", "2023VND", "2", 2.0, 2.0, 0, Unit(MONEY, 0), csv_path="b.csv")
    ev = build_evidence([_operand("numerator", a), _operand("denominator", b)])
    assert [e["variable"] for e in ev] == ["df1", "df2"]
    assert [e["csv_path"] for e in ev] == ["a.csv", "b.csv"]


def test_evidence_deduplicates_repeated_dataframe():
    a = cell("df1", "A", "2023VND", "1", 1.0, 1.0, 0, Unit(MONEY, 0))
    b = cell("df1", "B", "2023VND", "2", 2.0, 2.0, 0, Unit(MONEY, 0), row_index=1)
    ev = build_evidence([_operand("numerator", a), _operand("denominator", b)])
    assert len(ev) == 1
