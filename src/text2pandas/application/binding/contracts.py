"""Immutable output of global operand assignment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from text2pandas.application.planning import ExecutionPlan, OperandRequest
from text2pandas.application.retrieval import ObservationCandidate


@dataclass(frozen=True, slots=True)
class BoundOperand:
    request: OperandRequest
    candidate: ObservationCandidate


@dataclass(frozen=True, slots=True)
class BoundExecutionPlan:
    plan: ExecutionPlan
    operands: Mapping[str, BoundOperand]
    total_score: float
    score_margin: float | None


@dataclass(frozen=True, slots=True)
class BindingResult:
    status: str
    bound_plan: BoundExecutionPlan | None = None
    reason: str | None = None
    trace: tuple[dict[str, object], ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status == "OK"

