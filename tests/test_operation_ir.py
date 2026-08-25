"""OperationIR + operand-role tests, including the ordering that makes
numerator/denominator and new/old non-commutative."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from text2pandas.answer_pipeline.ir import (  # noqa: E402
    AVG, DENOMINATOR, DIVIDE, GROWTH, IRError, LOOKUP, MINUEND, MIN_ARITY, NEW,
    NUMERATOR, OLD, OperandSlot, OperationIR, ROLE_SPEC, SUBTRACT, SUBTRAHEND,
    SUM, SUMMAND, VALUE, result_dimension,
)
from text2pandas.answer_pipeline.units import (  # noqa: E402
    COUNT, MONEY, PERCENT, RATIO, SHARES, UNKNOWN, Unit,
)


def test_every_operation_declares_roles_and_arity():
    for op in ROLE_SPEC:
        assert op in MIN_ARITY
        roles, variadic = ROLE_SPEC[op]
        assert roles, op
        assert isinstance(variadic, bool)


def test_lookup_ir():
    ir = OperationIR(LOOKUP, (OperandSlot(VALUE),), Unit(MONEY, 6))
    assert ir.arity == 1


def test_divide_requires_ordered_roles():
    ok = OperationIR(DIVIDE, (OperandSlot(NUMERATOR), OperandSlot(DENOMINATOR)), Unit(RATIO))
    assert ok.slot(NUMERATOR).role == NUMERATOR
    with pytest.raises(IRError):
        OperationIR(DIVIDE, (OperandSlot(DENOMINATOR), OperandSlot(NUMERATOR)), Unit(RATIO))


def test_growth_requires_new_then_old():
    OperationIR(GROWTH, (OperandSlot(NEW), OperandSlot(OLD)), Unit(PERCENT))
    with pytest.raises(IRError):
        OperationIR(GROWTH, (OperandSlot(OLD), OperandSlot(NEW)), Unit(PERCENT))


def test_subtract_requires_minuend_then_subtrahend():
    OperationIR(SUBTRACT, (OperandSlot(MINUEND), OperandSlot(SUBTRAHEND)), Unit(MONEY, 9))
    with pytest.raises(IRError):
        OperationIR(SUBTRACT, (OperandSlot(SUBTRAHEND), OperandSlot(MINUEND)), Unit(MONEY, 9))


def test_sum_is_variadic_with_minimum_arity():
    ir = OperationIR(SUM, tuple(OperandSlot(SUMMAND, period=str(y)) for y in (2021, 2022, 2023)),
                     Unit(MONEY, 9))
    assert ir.arity == 3
    with pytest.raises(IRError):
        OperationIR(SUM, (OperandSlot(SUMMAND),), Unit(MONEY, 9))


def test_avg_rejects_foreign_roles():
    with pytest.raises(IRError):
        OperationIR(AVG, (OperandSlot(SUMMAND), OperandSlot(NUMERATOR)), Unit(MONEY, 9))


def test_unknown_operation_rejected():
    with pytest.raises(IRError):
        OperationIR("MULTI", (OperandSlot(VALUE),), Unit(MONEY, 0))


# ------------------------------------------------------------ result dimension
@pytest.mark.parametrize("op,dims,expected", [
    (LOOKUP, [MONEY], MONEY),
    (DIVIDE, [MONEY, MONEY], RATIO),
    (GROWTH, [MONEY, MONEY], RATIO),
    (SUBTRACT, [MONEY, MONEY], MONEY),
    (SUM, [MONEY, MONEY, MONEY], MONEY),
    (AVG, [PERCENT, PERCENT], PERCENT),
    # unlike dimensions are not defined -- never silently coerced
    (DIVIDE, [MONEY, SHARES], UNKNOWN),
    (SUBTRACT, [MONEY, COUNT], UNKNOWN),
    (SUM, [MONEY, UNKNOWN], UNKNOWN),
    (LOOKUP, [UNKNOWN], UNKNOWN),
])
def test_result_dimension(op, dims, expected):
    assert result_dimension(op, dims) == expected
