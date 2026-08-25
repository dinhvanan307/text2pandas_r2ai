"""Minimal Unit Contract.

Replaces hard-coded ``/1_000_000`` factors with an explicit, dimension-aware
conversion that **abstains instead of guessing**.

Core invariants
---------------
1. A number never travels without its unit. ``Quantity`` is the only currency.
2. Conversion runs only between *compatible* dimensions. Everything else
   returns ``ABSTAIN`` with a reason code -- never a silent factor.
3. There is no QID anywhere in this module. Behaviour is a function of
   (question text, column header, stored value, raw value) only.

The three scales that must never be confused
--------------------------------------------
``source_scale``   what the column header declares ("Triệu đồng" -> 10^6)
``storage_scale``  what the ingest pipeline already applied to ``value``
                   (``value / parse(value_raw)``); it is NOT constant across
                   the corpus -- measured 3704 cells at 10^6 and 670 cells at
                   10^0 under the *same* "Triệu đồng" header.
``output_scale``   what the question asks for ("bao nhiêu tỷ đồng" -> 10^9)

Hence the factor a pandas query must apply to the stored ``value`` column is

    10 ** (source_scale - output_scale - storage_scale)

and any of the three being unknown makes the result ``ABSTAIN``.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

# ------------------------------------------------------------------ dimensions
MONEY = "MONEY"
PERCENT = "PERCENT"
#: a DIFFERENCE between two percentages. "tăng 2,5%" and "tăng 2,5 điểm phần
#: trăm" are different quantities and must never convert into one another;
#: 23 questions in the corpus ask for percentage points explicitly.
PERCENT_POINT = "PERCENT_POINT"
RATIO = "RATIO"
COUNT = "COUNT"
SHARES = "SHARES"
UNKNOWN = "UNKNOWN"

DIMENSIONS = (MONEY, PERCENT, PERCENT_POINT, RATIO, COUNT, SHARES, UNKNOWN)

#: dimensions whose magnitude is expressed as a power of ten over a base unit
SCALED_DIMENSIONS = frozenset({MONEY})

#: (source, target) pairs a conversion is allowed to cross.
#: PERCENT<->RATIO is the single deliberate cross-dimension pair: a growth rate
#: is computed as a RATIO and routinely asked for as a PERCENT.
#: PERCENT_POINT is deliberately NOT connected to either -- a difference of two
#: percentages is a different quantity from a percentage, and silently scaling
#: between them is exactly the class of error this contract exists to prevent.
_CROSS = {
    (PERCENT, RATIO): 0.01,
    (RATIO, PERCENT): 100.0,
}


class ConversionStatus:
    OK = "OK"
    ABSTAIN = "ABSTAIN"


# -------------------------------------------------------------------- reasons
class Reason:
    UNKNOWN_SOURCE_DIMENSION = "UNKNOWN_SOURCE_DIMENSION"
    UNKNOWN_TARGET_DIMENSION = "UNKNOWN_TARGET_DIMENSION"
    DIMENSION_MISMATCH = "DIMENSION_MISMATCH"
    MISSING_SOURCE_SCALE = "MISSING_SOURCE_SCALE"
    MISSING_TARGET_SCALE = "MISSING_TARGET_SCALE"
    MISSING_STORAGE_SCALE = "MISSING_STORAGE_SCALE"
    NON_FINITE_VALUE = "NON_FINITE_VALUE"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"


@dataclass(frozen=True)
class Unit:
    """A dimension plus, for scaled dimensions, a power-of-ten exponent."""

    dimension: str
    scale_exponent: Optional[int] = None
    currency: Optional[str] = None

    def __post_init__(self):
        if self.dimension not in DIMENSIONS:
            raise ValueError(f"unknown dimension {self.dimension!r}")

    @property
    def is_known(self) -> bool:
        return self.dimension != UNKNOWN

    @property
    def needs_scale(self) -> bool:
        return self.dimension in SCALED_DIMENSIONS

    def describe(self) -> str:
        if self.needs_scale and self.scale_exponent is not None:
            return f"{self.dimension}@1e{self.scale_exponent}"
        return self.dimension


UNKNOWN_UNIT = Unit(UNKNOWN)


@dataclass(frozen=True)
class Quantity:
    """A value expressed in an explicit unit, with where it came from."""

    value: Optional[float]
    unit: Unit
    provenance: Optional[dict] = None

    def with_unit(self, unit: Unit, value: float) -> "Quantity":
        return replace(self, value=value, unit=unit)


@dataclass(frozen=True)
class ConversionResult:
    status: str
    factor: Optional[float] = None
    quantity: Optional[Quantity] = None
    reason: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == ConversionStatus.OK


def _abstain(reason: str) -> ConversionResult:
    return ConversionResult(status=ConversionStatus.ABSTAIN, reason=reason)


def conversion_factor(source: Unit, target: Unit) -> ConversionResult:
    """Factor that turns a magnitude in ``source`` into ``target``.

    Returns ABSTAIN rather than 1.0 whenever the answer is not provable.
    """
    if not source.is_known:
        return _abstain(Reason.UNKNOWN_SOURCE_DIMENSION)
    if not target.is_known:
        return _abstain(Reason.UNKNOWN_TARGET_DIMENSION)

    if source.dimension == target.dimension:
        if source.dimension in SCALED_DIMENSIONS:
            if source.scale_exponent is None:
                return _abstain(Reason.MISSING_SOURCE_SCALE)
            if target.scale_exponent is None:
                return _abstain(Reason.MISSING_TARGET_SCALE)
            if (source.currency and target.currency
                    and source.currency != target.currency):
                return _abstain(Reason.CURRENCY_MISMATCH)
            return ConversionResult(ConversionStatus.OK,
                                    factor=10.0 ** (source.scale_exponent - target.scale_exponent))
        return ConversionResult(ConversionStatus.OK, factor=1.0)

    cross = _CROSS.get((source.dimension, target.dimension))
    if cross is not None:
        return ConversionResult(ConversionStatus.OK, factor=cross)
    return _abstain(Reason.DIMENSION_MISMATCH)


def convert(quantity: Quantity, target: Unit) -> ConversionResult:
    """Convert a Quantity, or abstain."""
    res = conversion_factor(quantity.unit, target)
    if not res.ok:
        return res
    v = quantity.value
    if v is None:
        return _abstain(Reason.NON_FINITE_VALUE)
    try:
        out = float(v) * res.factor
    except (TypeError, ValueError):
        return _abstain(Reason.NON_FINITE_VALUE)
    if out != out or out in (float("inf"), float("-inf")):
        return _abstain(Reason.NON_FINITE_VALUE)
    return ConversionResult(ConversionStatus.OK, factor=res.factor,
                            quantity=Quantity(out, target, quantity.provenance))


def query_factor(source: Unit, target: Unit, storage_exponent: Optional[int]) -> ConversionResult:
    """Factor a pandas query must apply to the raw stored ``value`` column.

    ``storage_exponent`` is the power of ten the ingest step already baked into
    ``value`` relative to ``value_raw``. Unknown storage scale is fatal: it is
    exactly the ambiguity that produced the spurious ``/1e6`` family.
    """
    res = conversion_factor(source, target)
    if not res.ok:
        return res
    if storage_exponent is None:
        return _abstain(Reason.MISSING_STORAGE_SCALE)
    return ConversionResult(ConversionStatus.OK,
                            factor=res.factor / (10.0 ** storage_exponent))


def compatible(a: Unit, b: Unit) -> bool:
    """True when a conversion between the two units is defined."""
    return conversion_factor(a, b).ok


def percent_family(unit: "Unit") -> bool:
    """True for the percent/points/ratio family, whose members share magnitude
    semantics but NOT meaning. Used to decide the unit operands combine in."""
    return unit.dimension in (PERCENT, PERCENT_POINT, RATIO)
