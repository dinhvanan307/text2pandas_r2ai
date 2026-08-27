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

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional, Sequence

from .binding import BoundOperand
from .ir import (
    ARGMAX,
    ARGMIN,
    AVG,
    DENOMINATOR,
    DIVIDE,
    GROWTH,
    MAXIMUM,
    MINIMUM,
    OLD,
    SUBTRACT,
    SUM,
    OperationIR,
)

ZERO_DENOMINATOR = "ZERO_DENOMINATOR"
GROWTH_BASE_ZERO = "GROWTH_BASE_ZERO"
GROWTH_BASE_NEGATIVE = "GROWTH_BASE_NEGATIVE"
MISSING_OPERAND_VALUE = "MISSING_OPERAND_VALUE"
CROSS_PERIOD_METRIC_DRIFT = "CROSS_PERIOD_METRIC_DRIFT"
CROSS_BASIS_OPERANDS = "CROSS_BASIS_OPERANDS"
SIGNED_EXTREMUM_AMBIGUOUS = "SIGNED_EXTREMUM_AMBIGUOUS"

_SAME_METRIC_OPERATIONS = {
    ARGMAX,
    ARGMIN,
    AVG,
    GROWTH,
    MAXIMUM,
    MINIMUM,
    SUBTRACT,
    SUM,
}
_EXTREMUM_OPERATIONS = {ARGMAX, ARGMIN, MAXIMUM, MINIMUM}
_WORD = re.compile(r"[a-zà-ỹ]+")


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


def _metric_tokens(operand: BoundOperand) -> frozenset[str]:
    leaf = operand.cell.row_path.rsplit("›", 1)[-1]
    normalized = unicodedata.normalize("NFC", leaf).casefold()
    return frozenset(_WORD.findall(normalized))


def same_metric(operands: Sequence[BoundOperand]) -> bool:
    codes = [operand.cell.metric_code for operand in operands]
    if all(codes):
        return len(set(codes)) == 1
    token_sets = [_metric_tokens(operand) for operand in operands]
    if any(not tokens for tokens in token_sets):
        return False
    anchor = token_sets[0]
    for tokens in token_sets[1:]:
        similarity = len(anchor & tokens) / len(anchor | tokens)
        if similarity < 0.65:
            return False
    return True


def same_basis(operands: Sequence[BoundOperand]) -> bool:
    """Whether every operand comes from one accounting scope.

    ``None`` is a real unresolved scope, not a wildcard.  A group of legacy
    documents whose scope is uniformly unknown is coherent; mixing an unknown,
    separate or consolidated fact with another scope is not provably valid.
    """

    return len({operand.cell.basis for operand in operands}) <= 1


def check_operand_policies(ir: OperationIR,
                           operands: Sequence[BoundOperand],
                           allow_negative_growth_base: bool = False) -> PolicyResult:
    """Pre-conditions for the compiled operation. Deterministic, value-only."""
    for o in operands:
        if o.quantity.value is None:
            return _abstain(f"{MISSING_OPERAND_VALUE}:{o.role}")

    if len(operands) > 1 and not same_basis(operands):
        return _abstain(CROSS_BASIS_OPERANDS)

    periods = {operand.slot.period for operand in operands if operand.slot.period}
    if ir.op in _SAME_METRIC_OPERATIONS and len(periods) > 1 and not same_metric(operands):
        return _abstain(CROSS_PERIOD_METRIC_DRIFT)

    if ir.op in _EXTREMUM_OPERATIONS and any(
        operand.quantity.value is not None and operand.quantity.value < 0
        for operand in operands
    ):
        return _abstain(SIGNED_EXTREMUM_AMBIGUOUS)

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
