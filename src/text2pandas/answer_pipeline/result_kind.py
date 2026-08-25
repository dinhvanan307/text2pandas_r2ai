"""What KIND of thing an answer is.

Distinct from ``Unit``. A unit says how a magnitude is scaled; a result kind
says what the number *denotes*. They diverge in exactly the place that bit us:
a question asking "năm nào ... cao nhất" wants a YEAR, and answering it with a
money amount is wrong no matter how correct the unit conversion was.

The competition serialises every answer as ``float``, so ``PERIOD_YEAR`` is
carried internally as an int year and serialised as ``2017.0``.
"""
from __future__ import annotations

from .units import (COUNT, MONEY, PERCENT, PERCENT_POINT, RATIO, SHARES,
                    UNKNOWN, Unit)

MONEY_AMOUNT = "MONEY"
PERCENT_VALUE = "PERCENT_VALUE"
PERCENT_POINT_VALUE = "PERCENT_POINT"
RATIO_FRACTION = "RATIO_FRACTION"
COUNT_VALUE = "COUNT"
SHARES_VALUE = "SHARES"
PERIOD_YEAR = "PERIOD_YEAR"
UNKNOWN_KIND = "UNKNOWN"

RESULT_KINDS = (MONEY_AMOUNT, PERCENT_VALUE, PERCENT_POINT_VALUE, RATIO_FRACTION,
                COUNT_VALUE, SHARES_VALUE, PERIOD_YEAR, UNKNOWN_KIND)

_FROM_DIMENSION = {
    MONEY: MONEY_AMOUNT,
    PERCENT: PERCENT_VALUE,
    PERCENT_POINT: PERCENT_POINT_VALUE,
    RATIO: RATIO_FRACTION,
    COUNT: COUNT_VALUE,
    SHARES: SHARES_VALUE,
    UNKNOWN: UNKNOWN_KIND,
}

#: plausible calendar range for a PERIOD_YEAR answer in this corpus
MIN_YEAR, MAX_YEAR = 1990, 2100


def from_unit(unit: Unit) -> str:
    """Result kind implied by a unit. PERIOD_YEAR has no unit and never
    arises this way -- it must be declared by the operation."""
    return _FROM_DIMENSION.get(unit.dimension, UNKNOWN_KIND)


def serialize(value, kind: str):
    """Competition wire format: always a float."""
    if value is None:
        return None
    if kind == PERIOD_YEAR:
        return float(int(round(float(value))))
    return float(value)


def is_plausible(value, kind: str, allowed_years=None) -> tuple[bool, str | None]:
    """Range check a value against its declared kind.

    Returns ``(ok, reason)``. This is what makes "năm nào" answered with
    2.0e13 a *provable* type error, with no semantic gold needed.
    """
    if value is None:
        return False, "VALUE_IS_NONE"
    v = float(value)
    if kind == PERIOD_YEAR:
        if v != int(v):
            return False, "PERIOD_YEAR_NOT_INTEGRAL"
        if not (MIN_YEAR <= v <= MAX_YEAR):
            return False, "PERIOD_YEAR_OUT_OF_RANGE"
        if allowed_years and str(int(v)) not in set(allowed_years):
            return False, "PERIOD_YEAR_NOT_IN_REQUESTED_SET"
    if kind == COUNT_VALUE and (v < 0 or v != int(v)):
        return False, "COUNT_NOT_NON_NEGATIVE_INTEGER"
    if kind == SHARES_VALUE and v < 0:
        return False, "SHARES_NEGATIVE"
    return True, None
