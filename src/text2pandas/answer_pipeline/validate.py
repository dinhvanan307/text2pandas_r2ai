"""Answer Validator -- a guardrail, never a generator.

It may only: pass, reject, or abstain, each with a reason code. It must never
edit a number. A value the validator blocked is *not* a rescued answer; it is
an unresolved case, and the metrics report those separately.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .binding import BoundOperand
from .ir import OperationIR, result_dimension
from .units import COUNT, MONEY, PERCENT, RATIO, SHARES, UNKNOWN, Unit

PASS = "PASS"
REJECT = "REJECT"
ABSTAIN = "ABSTAIN"


class VReason:
    OUTPUT_DIMENSION_MISMATCH = "OUTPUT_DIMENSION_MISMATCH"
    UNDERIVABLE_RESULT_DIMENSION = "UNDERIVABLE_RESULT_DIMENSION"
    NON_FINITE = "NON_FINITE"
    DUPLICATE_OPERAND_CELLS = "DUPLICATE_OPERAND_CELLS"
    OPERAND_COUNT_MISMATCH = "OPERAND_COUNT_MISMATCH"
    PERCENT_OUT_OF_PLAUSIBLE_RANGE = "PERCENT_OUT_OF_PLAUSIBLE_RANGE"
    ZERO_DENOMINATOR = "ZERO_DENOMINATOR"


@dataclass
class ValidationResult:
    verdict: str
    reasons: list[str] = field(default_factory=list)
    #: never populated with a corrected number -- validators do not fix
    value: Optional[float] = None

    @property
    def ok(self) -> bool:
        return self.verdict == PASS


def validate(ir: OperationIR, operands: list[BoundOperand],
             value: Optional[float],
             percent_abs_limit: float = 1e4) -> ValidationResult:
    """Check a computed answer against the IR's declared contract."""
    reasons: list[str] = []

    if len(operands) != ir.arity:
        reasons.append(VReason.OPERAND_COUNT_MISMATCH)

    # a multi-operand op whose operands resolved to the same physical cell is
    # a selection failure that produces a plausible-looking 1.0 / 0.0
    if ir.arity > 1:
        keys = {(o.cell.csv_path, o.cell.row_index) for o in operands}
        if len(keys) < len(operands):
            reasons.append(VReason.DUPLICATE_OPERAND_CELLS)

    dims = [o.quantity.unit.dimension for o in operands]
    got = result_dimension(ir.op, dims)
    want = ir.output_unit.dimension
    if got == UNKNOWN:
        reasons.append(VReason.UNDERIVABLE_RESULT_DIMENSION)
    elif got != want:
        # RATIO and PERCENT are the one declared-compatible pair
        if not {got, want} <= {RATIO, PERCENT}:
            reasons.append(VReason.OUTPUT_DIMENSION_MISMATCH)

    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        reasons.append(VReason.NON_FINITE)
    elif want == PERCENT and abs(value) > percent_abs_limit:
        reasons.append(VReason.PERCENT_OUT_OF_PLAUSIBLE_RANGE)

    if not reasons:
        return ValidationResult(PASS, [], value)
    hard = {VReason.OUTPUT_DIMENSION_MISMATCH, VReason.NON_FINITE,
            VReason.DUPLICATE_OPERAND_CELLS, VReason.OPERAND_COUNT_MISMATCH}
    verdict = REJECT if hard & set(reasons) else ABSTAIN
    return ValidationResult(verdict, reasons, None)
