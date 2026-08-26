"""Decimal arithmetic and unit algebra shared by executor and compiler."""

from __future__ import annotations

from decimal import Decimal

from text2pandas.domain.semantic import ArithmeticOperator, Dimension, UnaryOperator, UnitSpec

from .contracts import QuantityValue


class QuantityError(ValueError):
    pass


def convert_quantity(quantity: QuantityValue, target: UnitSpec) -> QuantityValue:
    source = quantity.unit
    if source.dimension == target.dimension:
        if source.dimension in (Dimension.MONEY, Dimension.SHARES):
            if source.scale_exponent is None or target.scale_exponent is None:
                raise QuantityError("SCALE_UNKNOWN")
            if source.currency and target.currency and source.currency != target.currency:
                raise QuantityError("CURRENCY_MISMATCH")
            factor = _power(source.scale_exponent - target.scale_exponent)
            return QuantityValue(quantity.value * factor, target)
        return QuantityValue(quantity.value, target)
    if source.dimension == Dimension.RATIO and target.dimension == Dimension.PERCENT:
        return QuantityValue(quantity.value * Decimal(100), target)
    if source.dimension == Dimension.PERCENT and target.dimension == Dimension.RATIO:
        return QuantityValue(quantity.value / Decimal(100), target)
    raise QuantityError(f"DIMENSION_MISMATCH:{source.dimension}:{target.dimension}")


def unary_quantity(operator: UnaryOperator, value: QuantityValue) -> QuantityValue:
    if operator == UnaryOperator.ABSOLUTE:
        return QuantityValue(abs(value.value), value.unit)
    if operator == UnaryOperator.NEGATE:
        return QuantityValue(-value.value, value.unit)
    raise QuantityError(f"UNSUPPORTED_UNARY:{operator}")


def arithmetic_quantity(
    operator: ArithmeticOperator, left: QuantityValue, right: QuantityValue
) -> QuantityValue:
    if operator in (ArithmeticOperator.ADD, ArithmeticOperator.SUBTRACT):
        left_base, right_base = _common_additive_units(left, right)
        value = (
            left_base.value + right_base.value
            if operator == ArithmeticOperator.ADD
            else left_base.value - right_base.value
        )
        unit = left_base.unit
        if operator == ArithmeticOperator.SUBTRACT and unit.dimension == Dimension.PERCENT:
            unit = UnitSpec(Dimension.PERCENT_POINT)
        return QuantityValue(value, unit)
    if operator == ArithmeticOperator.GROWTH:
        left_base, right_base = _common_additive_units(left, right)
        if right_base.value == 0:
            raise QuantityError("ZERO_DENOMINATOR")
        return QuantityValue(
            (left_base.value - right_base.value) / abs(right_base.value),
            UnitSpec(Dimension.RATIO),
        )
    if operator == ArithmeticOperator.DIVIDE:
        left_base, right_base = _common_additive_units(left, right)
        if right_base.value == 0:
            raise QuantityError("ZERO_DENOMINATOR")
        return QuantityValue(left_base.value / right_base.value, UnitSpec(Dimension.RATIO))
    if operator == ArithmeticOperator.MULTIPLY:
        if left.unit.dimension == Dimension.RATIO:
            return QuantityValue(left.value * right.value, right.unit)
        if right.unit.dimension == Dimension.RATIO:
            return QuantityValue(left.value * right.value, left.unit)
        raise QuantityError(
            f"MULTIPLY_DIMENSION_UNSUPPORTED:{left.unit.dimension}:{right.unit.dimension}"
        )
    raise QuantityError(f"UNSUPPORTED_ARITHMETIC:{operator}")


def comparable(quantity: QuantityValue) -> QuantityValue:
    if quantity.unit.dimension in (Dimension.MONEY, Dimension.SHARES):
        target = UnitSpec(quantity.unit.dimension, 0, quantity.unit.currency)
        return convert_quantity(quantity, target)
    if quantity.unit.dimension == Dimension.PERCENT:
        return convert_quantity(quantity, UnitSpec(Dimension.RATIO))
    return quantity


def _common_additive_units(
    left: QuantityValue, right: QuantityValue
) -> tuple[QuantityValue, QuantityValue]:
    if left.unit.dimension != right.unit.dimension:
        raise QuantityError(f"DIMENSION_MISMATCH:{left.unit.dimension}:{right.unit.dimension}")
    if left.unit.dimension in (Dimension.MONEY, Dimension.SHARES):
        currency = left.unit.currency or right.unit.currency
        target = UnitSpec(left.unit.dimension, 0, currency)
        return convert_quantity(left, target), convert_quantity(right, target)
    return left, right


def _power(exponent: int) -> Decimal:
    return Decimal(10) ** exponent
