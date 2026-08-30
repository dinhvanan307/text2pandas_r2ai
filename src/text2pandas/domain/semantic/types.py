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


class ObservationRowRole(StrEnum):
    TOTAL = "total"
    CHILD = "child"
    ALLOWANCE = "allowance"
    COST = "cost"
    NET = "net"
    UNKNOWN = "unknown"


class ObservationColumnRole(StrEnum):
    CLOSING = "closing"
    OPENING = "opening"
    CURRENT = "current"
    PRIOR = "prior"
    AS_OF = "as_of"
    UNKNOWN = "unknown"


class ObservationSignMode(StrEnum):
    AS_REPORTED = "as_reported"
    POSITIVE_MAGNITUDE = "positive_magnitude"
    SIGNED_DIFFERENCE = "signed_difference"


@dataclass(frozen=True, slots=True)
class ObservationRoleSpec:
    """Hard semantic requirements for selecting one physical observation."""

    source_metric_id: str | None = None
    accepted_source_metric_codes: tuple[str, ...] = ()
    exact_row_labels: tuple[str, ...] = ()
    required_row_path_tokens: tuple[str, ...] = ()
    forbidden_row_path_tokens: tuple[str, ...] = ()
    allowed_row_roles: tuple[ObservationRowRole, ...] = ()
    allowed_column_roles: tuple[ObservationColumnRole, ...] = ()
    allowed_period_roles: tuple[str, ...] = ()
    sign_mode: ObservationSignMode = ObservationSignMode.AS_REPORTED
    allowed_scale_sources: tuple[str, ...] = ()
    entity_membership: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_metric_id": self.source_metric_id,
            "accepted_source_metric_codes": list(self.accepted_source_metric_codes),
            "exact_row_labels": list(self.exact_row_labels),
            "required_row_path_tokens": list(self.required_row_path_tokens),
            "forbidden_row_path_tokens": list(self.forbidden_row_path_tokens),
            "allowed_row_roles": [value.value for value in self.allowed_row_roles],
            "allowed_column_roles": [
                value.value for value in self.allowed_column_roles
            ],
            "allowed_period_roles": list(self.allowed_period_roles),
            "sign_mode": self.sign_mode.value,
            "allowed_scale_sources": list(self.allowed_scale_sources),
            "entity_membership": list(self.entity_membership),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ObservationRoleSpec:
        return cls(
            source_metric_id=_optional_str(raw.get("source_metric_id")),
            accepted_source_metric_codes=tuple(
                str(value) for value in raw.get("accepted_source_metric_codes", ())
            ),
            exact_row_labels=tuple(str(value) for value in raw.get("exact_row_labels", ())),
            required_row_path_tokens=tuple(
                str(value) for value in raw.get("required_row_path_tokens", ())
            ),
            forbidden_row_path_tokens=tuple(
                str(value) for value in raw.get("forbidden_row_path_tokens", ())
            ),
            allowed_row_roles=tuple(
                ObservationRowRole(str(value))
                for value in raw.get("allowed_row_roles", ())
            ),
            allowed_column_roles=tuple(
                ObservationColumnRole(str(value))
                for value in raw.get("allowed_column_roles", ())
            ),
            allowed_period_roles=tuple(
                str(value) for value in raw.get("allowed_period_roles", ())
            ),
            sign_mode=ObservationSignMode(
                str(raw.get("sign_mode", ObservationSignMode.AS_REPORTED.value))
            ),
            allowed_scale_sources=tuple(
                str(value) for value in raw.get("allowed_scale_sources", ())
            ),
            entity_membership=tuple(
                str(value) for value in raw.get("entity_membership", ())
            ),
        )


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
