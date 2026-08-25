"""Arithmetic policies checked BEFORE execution.

A division by zero must surface as a declared reason code, not as a
``ZeroDivisionError`` swallowed by a generic ``except`` in the executor. Same
for a growth rate off a non-positive base: ``(new-old)/abs(old)`` is not
meaningful when ``old <= 0``, and silently returning a number there is how a
system starts producing confident nonsense.

Every policy here is a *pre-condition on the bound operands*. It never edits a
value and never picks a different operand -- it only says "this computation is
not defined", with a reason.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from .binding import BoundOperand
from .ir import DENOMINATOR, DIVIDE, GROWTH, OLD, OperationIR

ZERO_DENOMINATOR = "ZERO_DENOMINATOR"
GROWTH_BASE_ZERO = "GROWTH_BASE_ZERO"
GROWTH_BASE_NEGATIVE = "GROWTH_BASE_NEGATIVE"
MISSING_OPERAND_VALUE = "MISSING_OPERAND_VALUE"


@dataclass(frozen=True)
class PolicyResult:
    status: str                       # OK | ABSTAIN
    reason: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == "OK"


def _abstain(reason: str) -> PolicyResult:
    return PolicyResult("ABSTAIN", reason)


def _value(operands: Sequence[BoundOperand], role: str):
    for o in operands:
        if o.role == role:
            return o.quantity.value
    return None


def check_operand_policies(ir: OperationIR,
                           operands: Sequence[BoundOperand],
                           allow_negative_growth_base: bool = False) -> PolicyResult:
    """Pre-conditions for the compiled operation. Deterministic, value-only."""
    for o in operands:
        if o.quantity.value is None:
            return _abstain(f"{MISSING_OPERAND_VALUE}:{o.role}")

    if ir.op == DIVIDE:
        den = _value(operands, DENOMINATOR)
        if den == 0:
            return _abstain(ZERO_DENOMINATOR)

    if ir.op == GROWTH:
        old = _value(operands, OLD)
        if old == 0:
            # growth from zero is undefined, not "infinite"
            return _abstain(GROWTH_BASE_ZERO)
        if old is not None and old < 0 and not allow_negative_growth_base:
            # (new-old)/abs(old) off a negative base flips the sign of the
            # improvement; the financial reading is ambiguous, so abstain
            # rather than guess a convention.
            return _abstain(GROWTH_BASE_NEGATIVE)

    return PolicyResult("OK")
