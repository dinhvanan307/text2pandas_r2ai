"""Ports and transport values at the semantic parser boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from text2pandas.domain.semantic import Basis, QuestionAST, RankDirection, UnitSpec


class OperationKind(StrEnum):
    LOOKUP = "lookup"
    DIVIDE = "divide"
    SUBTRACT = "subtract"
    GROWTH = "growth"
    SUM = "sum"
    AVERAGE = "average"
    COUNT = "count"
    EXTREMUM = "extremum"
    UNSUPPORTED = "unsupported"


class ReturnMode(StrEnum):
    VALUE = "value"
    MEMBER = "member"
    SELECT_AT_ARG = "select_at_arg"
    FILTERED_VALUE = "filtered_value"


@dataclass(frozen=True, slots=True)
class QuestionAnnotations:
    entities: tuple[str, ...]
    periods: tuple[str, ...]
    basis: Basis
    requested_unit: UnitSpec
    operation: OperationKind
    mode: str
    rank_direction: RankDirection | None = None
    return_mode: ReturnMode = ReturnMode.VALUE
    reverse_difference: bool = False
    operation_evidence: str | None = None


class QuestionAnnotator(Protocol):
    def annotate(self, question: str) -> QuestionAnnotations: ...


@dataclass(frozen=True, slots=True)
class ParseResult:
    status: str
    ast: QuestionAST | None = None
    reason: str | None = None
    trace: tuple[dict[str, object], ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status == "OK"

