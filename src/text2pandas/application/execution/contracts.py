"""Typed values emitted while evaluating a bound semantic AST."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from text2pandas.domain.semantic import Axis, UnitSpec


@dataclass(frozen=True, slots=True, order=True)
class Scope:
    entity: str | None = None
    period: str | None = None

    def member(self, axis: Axis) -> str | None:
        return self.entity if axis == Axis.ENTITY else self.period


@dataclass(frozen=True, slots=True)
class QuantityValue:
    value: Decimal
    unit: UnitSpec


@dataclass(frozen=True, slots=True)
class SeriesValue:
    values: Mapping[Scope, QuantityValue]


@dataclass(frozen=True, slots=True)
class MemberValue:
    axis: Axis
    members: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: str
    answer: Decimal | str | None = None
    unit: UnitSpec | None = None
    reason: str | None = None
    trace: tuple[dict[str, object], ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status == "OK"
