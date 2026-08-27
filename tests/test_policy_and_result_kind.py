"""Arithmetic policies, IR serialization and result kinds.

All three were listed as open in doc 172 §4.3 and confirmed open by review 173
§5.7. They are pre-conditions for production integration, so each gets a test
that fails loudly if the guard is ever removed.
"""
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

pd = pytest.importorskip("pandas")

from text2pandas.pipelines.answering import CandidateCell, Unit, answer_question  # noqa: E402
from text2pandas.pipelines.answering.binding import BoundOperand, Selector  # noqa: E402
from text2pandas.pipelines.answering.ir import (  # noqa: E402
    ARGMAX, DENOMINATOR, DIVIDE, GROWTH, MAXIMUM, NEW, NUMERATOR, OLD,
    OperandSlot, OperationIR, SUBTRACT, MINUEND, SUBTRAHEND, SUM, SUMMAND,
    VALUE, LOOKUP,
)
from text2pandas.pipelines.answering.policy import (  # noqa: E402
    CROSS_BASIS_OPERANDS, CROSS_PERIOD_METRIC_DRIFT, GROWTH_BASE_NEGATIVE, GROWTH_BASE_ZERO,
    MISSING_OPERAND_VALUE, SIGNED_EXTREMUM_AMBIGUOUS, ZERO_DENOMINATOR,
    check_operand_policies,
)
from text2pandas.pipelines.answering import result_kind as RK  # noqa: E402
from text2pandas.pipelines.answering.units import (  # noqa: E402
    MONEY, PERCENT, PERCENT_POINT, RATIO, UNKNOWN, Quantity,
)


class InOrder(Selector):
    def pick(self, slot, pool):
        return pool[0] if pool else None


def money_cell(row_path, value, idx, period="2023"):
    return CandidateCell("df1", "t.csv", idx, row_path, f"{period}VND", str(value),
                         float(value), float(value), 0, Unit(MONEY, 0), period)


def frames_from(cells):
    return {"df1": pd.DataFrame([
        {"row_path": c.row_path, "col_label": c.col_label,
         "value_raw": c.value_raw, "value": c.value} for c in cells])}


def operand(role, cell):
    return BoundOperand(role, OperandSlot(role), cell, cell.native_quantity())


# ------------------------------------------------------------------ policies
def test_zero_denominator_is_a_reason_code_not_an_exception():
    """Before the fix this surfaced as EXECUTION_ERROR:ZeroDivisionError."""
    num = money_cell("Nợ xấu", 50, 0)
    den = money_cell("Tổng dư nợ", 0, 1)
    res = answer_question("Tỷ lệ nợ xấu trên tổng dư nợ năm 2023 là bao nhiêu %?",
                          [num, den], frames_from([num, den]), qid=1,
                          requested_unit=Unit(PERCENT), selector=InOrder())
    assert res.status == "ABSTAIN"
    assert res.stage_failed == "POLICY"
    assert res.reason == ZERO_DENOMINATOR
    assert "ZeroDivisionError" not in (res.reason or "")


def test_policy_runs_before_execute():
    num = money_cell("A", 50, 0)
    den = money_cell("B", 0, 1)
    res = answer_question("Tỷ lệ A trên tổng B năm 2023 là bao nhiêu %?",
                          [num, den], frames_from([num, den]), qid=2,
                          requested_unit=Unit(PERCENT), selector=InOrder())
    stages = [t["stage"] for t in res.trace]
    assert "POLICY" in stages
    assert "EXECUTE" not in stages, "execution must not be attempted after a policy abstain"


def test_growth_from_zero_base_abstains():
    ir = OperationIR(GROWTH, (OperandSlot(NEW), OperandSlot(OLD)), Unit(PERCENT))
    ops = [operand(NEW, money_cell("Doanh thu", 100, 0)),
           operand(OLD, money_cell("Doanh thu", 0, 1, "2022"))]
    r = check_operand_policies(ir, ops)
    assert not r.ok and r.reason == GROWTH_BASE_ZERO


def test_growth_from_negative_base_abstains_by_default():
    """(new-old)/abs(old) off a negative base inverts the sign of improvement;
    abstain rather than silently pick a convention."""
    ir = OperationIR(GROWTH, (OperandSlot(NEW), OperandSlot(OLD)), Unit(PERCENT))
    ops = [operand(NEW, money_cell("LNST", 100, 0)),
           operand(OLD, money_cell("LNST", -50, 1, "2022"))]
    r = check_operand_policies(ir, ops)
    assert not r.ok and r.reason == GROWTH_BASE_NEGATIVE


def test_growth_from_negative_base_allowed_when_explicitly_opted_in():
    ir = OperationIR(GROWTH, (OperandSlot(NEW), OperandSlot(OLD)), Unit(PERCENT))
    ops = [operand(NEW, money_cell("LNST", 100, 0)),
           operand(OLD, money_cell("LNST", -50, 1, "2022"))]
    assert check_operand_policies(ir, ops, allow_negative_growth_base=True).ok


def test_positive_growth_passes_policy():
    ir = OperationIR(GROWTH, (OperandSlot(NEW), OperandSlot(OLD)), Unit(PERCENT))
    ops = [operand(NEW, money_cell("Doanh thu", 120, 0)),
           operand(OLD, money_cell("Doanh thu", 100, 1, "2022"))]
    assert check_operand_policies(ir, ops).ok


def test_nonzero_denominator_passes_policy():
    ir = OperationIR(DIVIDE, (OperandSlot(NUMERATOR), OperandSlot(DENOMINATOR)),
                     Unit(RATIO))
    ops = [operand(NUMERATOR, money_cell("A", 5, 0)),
           operand(DENOMINATOR, money_cell("B", 10, 1))]
    assert check_operand_policies(ir, ops).ok


def test_subtract_has_no_zero_restriction():
    ir = OperationIR(SUBTRACT, (OperandSlot(MINUEND), OperandSlot(SUBTRAHEND)),
                     Unit(MONEY, 0))
    ops = [operand(MINUEND, money_cell("A", 0, 0)),
           operand(SUBTRAHEND, money_cell("B", 0, 1))]
    assert check_operand_policies(ir, ops).ok


def test_cross_period_operation_rejects_metric_drift():
    slots = (OperandSlot(VALUE, period="2022"), OperandSlot(VALUE, period="2023"))
    ir = OperationIR(MAXIMUM, slots, Unit(MONEY, 0))
    cells = [money_cell("Doanh thu thuần", 100, 0, "2022"),
             money_cell("Chi phí lãi vay", 200, 1, "2023")]
    ops = [BoundOperand(VALUE, slot, cell, cell.native_quantity())
           for slot, cell in zip(slots, cells, strict=True)]

    result = check_operand_policies(ir, ops)

    assert not result.ok and result.reason == CROSS_PERIOD_METRIC_DRIFT


def test_multi_operand_operation_rejects_mixed_accounting_basis():
    slots = (OperandSlot(VALUE, period="2022"), OperandSlot(VALUE, period="2023"))
    ir = OperationIR(MAXIMUM, slots, Unit(MONEY, 0))
    cells = [
        replace(money_cell("Doanh thu thuần", 100, 0, "2022"), basis="separate"),
        replace(money_cell("Doanh thu thuần", 200, 1, "2023"), basis="consolidated"),
    ]
    ops = [
        BoundOperand(VALUE, slot, cell, cell.native_quantity())
        for slot, cell in zip(slots, cells, strict=True)
    ]

    result = check_operand_policies(ir, ops)

    assert not result.ok and result.reason == CROSS_BASIS_OPERANDS


def test_signed_extremum_abstains_until_sign_semantics_are_declared():
    slots = (OperandSlot(VALUE, period="2022"), OperandSlot(VALUE, period="2023"))
    ir = OperationIR(ARGMAX, slots, Unit(MONEY, 0))
    cells = [money_cell("Giá vốn hàng bán", -100, 0, "2022"),
             money_cell("Giá vốn hàng bán", -200, 1, "2023")]
    ops = [BoundOperand(VALUE, slot, cell, cell.native_quantity())
           for slot, cell in zip(slots, cells, strict=True)]

    result = check_operand_policies(ir, ops)

    assert not result.ok and result.reason == SIGNED_EXTREMUM_AMBIGUOUS


# ------------------------------------------------------- IR round-trip
@pytest.mark.parametrize("ir", [
    OperationIR(LOOKUP, (OperandSlot(VALUE, metric_id="revenue", period="2023",
                                     basis="separate", entity="ACB"),), Unit(MONEY, 9)),
    OperationIR(DIVIDE, (OperandSlot(NUMERATOR, metric_id="bad_debt"),
                         OperandSlot(DENOMINATOR, metric_id="total_loans")), Unit(PERCENT)),
    OperationIR(SUBTRACT, (OperandSlot(MINUEND, period="2023"),
                           OperandSlot(SUBTRAHEND, period="2022")), Unit(PERCENT_POINT)),
    OperationIR(SUM, tuple(OperandSlot(SUMMAND, period=str(y)) for y in (2021, 2022, 2023)),
                Unit(MONEY, 0)),
    OperationIR(ARGMAX, (OperandSlot(VALUE, period="2022"),
                         OperandSlot(VALUE, period="2023")),
                Unit(UNKNOWN), result_kind=RK.PERIOD_YEAR),
])
def test_ir_serialization_round_trip(ir):
    back = OperationIR.from_dict(ir.to_dict())
    assert back == ir
    assert back.to_dict() == ir.to_dict()


def test_round_trip_preserves_per_operand_metric_ids():
    """The field that makes 'nợ xấu / tổng dư nợ' representable at all."""
    ir = OperationIR(DIVIDE, (OperandSlot(NUMERATOR, metric_id="bad_debt"),
                              OperandSlot(DENOMINATOR, metric_id="total_loans")),
                     Unit(PERCENT))
    back = OperationIR.from_dict(ir.to_dict())
    assert back.slot(NUMERATOR).metric_id == "bad_debt"
    assert back.slot(DENOMINATOR).metric_id == "total_loans"


def test_round_trip_survives_json():
    import json
    ir = OperationIR(GROWTH, (OperandSlot(NEW, period="2023"),
                              OperandSlot(OLD, period="2022")), Unit(PERCENT))
    assert OperationIR.from_dict(json.loads(json.dumps(ir.to_dict()))) == ir


# ------------------------------------------------------------- result kinds
def test_period_year_serialises_as_float():
    assert RK.serialize(2017, RK.PERIOD_YEAR) == 2017.0
    assert isinstance(RK.serialize(2017, RK.PERIOD_YEAR), float)


@pytest.mark.parametrize("value,ok,reason", [
    (2017, True, None),
    (2.0001342522819e13, False, "PERIOD_YEAR_OUT_OF_RANGE"),
    (2017.5, False, "PERIOD_YEAR_NOT_INTEGRAL"),
    (None, False, "VALUE_IS_NONE"),
])
def test_period_year_range_check(value, ok, reason):
    """A 'năm nào' question answered with 2e13 is provably wrong with no gold."""
    got_ok, got_reason = RK.is_plausible(value, RK.PERIOD_YEAR)
    assert got_ok is ok
    assert got_reason == reason


def test_period_year_must_be_in_the_requested_set():
    assert RK.is_plausible(2017, RK.PERIOD_YEAR, ["2016", "2019", "2020"])[1] == \
        "PERIOD_YEAR_NOT_IN_REQUESTED_SET"
    assert RK.is_plausible(2017, RK.PERIOD_YEAR, ["2016", "2017"])[0] is True


@pytest.mark.parametrize("dim,kind", [
    (MONEY, RK.MONEY_AMOUNT),
    (PERCENT, RK.PERCENT_VALUE),
    (PERCENT_POINT, RK.PERCENT_POINT_VALUE),
    (RATIO, RK.RATIO_FRACTION),
])
def test_result_kind_from_unit(dim, kind):
    assert RK.from_unit(Unit(dim, 0 if dim == MONEY else None)) == kind


def test_all_declared_result_kinds_are_reachable():
    assert set(RK.RESULT_KINDS) >= {
        RK.MONEY_AMOUNT, RK.PERCENT_VALUE, RK.PERCENT_POINT_VALUE,
        RK.RATIO_FRACTION, RK.COUNT_VALUE, RK.SHARES_VALUE, RK.PERIOD_YEAR}
