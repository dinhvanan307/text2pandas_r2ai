"""Compile a QuestionSemanticFrame into an OperationIR.

Separate module, separate contract, separate failure class. The router owns
exactly two decisions: which operation, and what the output unit must be.
It never touches data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .frame import EXTREMUM, QuestionSemanticFrame, UNSUPPORTED
from .ir import (AVG, DENOMINATOR, DIVIDE, GROWTH, LOOKUP, MINUEND, NEW, NUMERATOR,
                 OLD, OperandSlot, OperationIR, SUBTRACT, SUBTRAHEND, SUM, SUMMAND,
                 VALUE)
from .units import PERCENT, PERCENT_POINT, RATIO, UNKNOWN, Unit


@dataclass(frozen=True)
class RouteResult:
    ir: Optional[OperationIR]
    status: str                 # OK | ABSTAIN
    reason: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == "OK"


def _abstain(reason: str) -> RouteResult:
    return RouteResult(None, "ABSTAIN", reason)


def _period(frame: QuestionSemanticFrame, i: int) -> Optional[str]:
    return frame.periods[i] if i < len(frame.periods) else None


def route(frame: QuestionSemanticFrame) -> RouteResult:
    """Frame -> IR, or an explicit abstention with a reason code."""
    op = frame.operation.op
    if not frame.operation.supported:
        return _abstain(f"UNSUPPORTED_OPERATION:{op}")

    out_unit = frame.requested_unit
    if out_unit.dimension == UNKNOWN:
        return _abstain("UNKNOWN_REQUESTED_UNIT")

    common = dict(metric_id=frame.metric_id, basis=frame.basis, entity=frame.entity)

    if op == LOOKUP:
        slots = (OperandSlot(VALUE, period=_period(frame, 0), **common),)
        return RouteResult(OperationIR(LOOKUP, slots, out_unit), "OK")

    if op == DIVIDE:
        # a ratio question must ask for a ratio-like answer
        if out_unit.dimension not in (RATIO, PERCENT):
            return _abstain(f"DIVIDE_OUTPUT_NOT_RATIO_LIKE:{out_unit.dimension}")
        slots = (OperandSlot(NUMERATOR, period=_period(frame, 0), **common),
                 OperandSlot(DENOMINATOR, period=_period(frame, 0), **common))
        return RouteResult(OperationIR(DIVIDE, slots, out_unit), "OK")

    if op == GROWTH:
        if out_unit.dimension not in (RATIO, PERCENT):
            return _abstain(f"GROWTH_OUTPUT_NOT_RATIO_LIKE:{out_unit.dimension}")
        if len(frame.periods) < 2:
            return _abstain("GROWTH_NEEDS_TWO_PERIODS")
        # newest period first: periods are emitted in source order, so sort
        newest, oldest = _order_periods(frame.periods)
        slots = (OperandSlot(NEW, period=newest, **common),
                 OperandSlot(OLD, period=oldest, **common))
        return RouteResult(OperationIR(GROWTH, slots, out_unit), "OK")

    if op == SUBTRACT:
        if len(frame.periods) < 2:
            return _abstain("SUBTRACT_NEEDS_TWO_PERIODS")
        newest, oldest = _order_periods(frame.periods)
        slots = (OperandSlot(MINUEND, period=newest, **common),
                 OperandSlot(SUBTRAHEND, period=oldest, **common))
        return RouteResult(OperationIR(SUBTRACT, slots, out_unit), "OK")

    if op in (SUM, AVG):
        if len(frame.periods) < 2:
            return _abstain(f"{op}_NEEDS_TWO_OPERANDS")
        slots = tuple(OperandSlot(SUMMAND, period=p, **common) for p in frame.periods)
        return RouteResult(OperationIR(op, slots, out_unit), "OK")

    return _abstain(f"NO_ROUTE:{op}")


def _order_periods(periods: tuple[str, ...]) -> tuple[str, str]:
    """Return (newest, oldest). Lexicographic order works for ISO dates and
    bare years alike, which is why periods are normalised in the frame."""
    ordered = sorted(periods, reverse=True)
    return ordered[0], ordered[-1]
