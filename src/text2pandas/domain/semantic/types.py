"""Small immutable semantic value objects shared by parser and execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Dimension(StrEnum):
    MONEY = "money"
    PERCENT = "percent"
    PERCENT_POINT = "percent_point"
    RATIO = "ratio"
    COUNT = "count"
    SHARES = "shares"
    PERIOD = "period"
    ENTITY = "entity"
    UNKNOWN = "unknown"


class ResultKind(StrEnum):
    SCALAR = "scalar"
    ENTITY = "entity"
    PERIOD = "period"
    BOOLEAN = "boolean"
    SET = "set"


class Axis(StrEnum):
    ENTITY = "entity"
    PERIOD = "period"


class Basis(StrEnum):
    CONSOLIDATED = "consolidated"
    SEPARATE = "separate"
    UNSPECIFIED = "unspecified"


class PeriodSemantics(StrEnum):
    POINT_IN_TIME = "point_in_time"
    FLOW = "flow"
    INSTANT = "instant"
    UNKNOWN = "unknown"


class ArithmeticOperator(StrEnum):
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    GROWTH = "growth"


class UnaryOperator(StrEnum):
    ABSOLUTE = "absolute"
    NEGATE = "negate"


class AggregateFunction(StrEnum):
    SUM = "sum"
    AVERAGE = "average"
    COUNT = "count"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    MEDIAN = "median"


class RankDirection(StrEnum):
    ASCENDING = "ascending"
    DESCENDING = "descending"


class ComparisonOperator(StrEnum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GE = "ge"
    LT = "lt"
    LE = "le"


class LogicalOperator(StrEnum):
    AND = "and"
    OR = "or"


class PredicateQuantifier(StrEnum):
    ALL = "all"
    ANY = "any"


@dataclass(frozen=True, slots=True)
class UnitSpec:
    dimension: Dimension
    scale_exponent: int | None = None
    currency: str | None = None

    def __post_init__(self) -> None:
        if self.dimension not in (Dimension.MONEY, Dimension.SHARES) and self.scale_exponent:
            raise ValueError(f"{self.dimension} cannot have a scale exponent")
        if self.dimension != Dimension.MONEY and self.currency is not None:
            raise ValueError(f"{self.dimension} cannot have a currency")

    @property
    def is_known(self) -> bool:
        return self.dimension != Dimension.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "scale_exponent": self.scale_exponent,
            "currency": self.currency,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> UnitSpec:
        return cls(
            dimension=Dimension(str(raw["dimension"])),
            scale_exponent=_optional_int(raw.get("scale_exponent")),
            currency=_optional_str(raw.get("currency")),
        )


@dataclass(frozen=True, slots=True)
class OutputSpec:
    result_kind: ResultKind
    unit: UnitSpec
    rounding_digits: int | None = None

    def __post_init__(self) -> None:
        if self.rounding_digits is not None and self.rounding_digits < 0:
            raise ValueError("rounding_digits must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_kind": self.result_kind.value,
            "unit": self.unit.to_dict(),
            "rounding_digits": self.rounding_digits,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> OutputSpec:
        return cls(
            result_kind=ResultKind(str(raw["result_kind"])),
            unit=UnitSpec.from_dict(_mapping(raw["unit"])),
            rounding_digits=_optional_int(raw.get("rounding_digits")),
        )


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"expected mapping, got {type(value).__name__}")
    return value


def _optional_int(value: object) -> int | None:
    return None if value is None else int(str(value))


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)
