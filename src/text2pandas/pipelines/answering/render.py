"""Render bound operands + IR into an executable pandas expression.

Every scaling constant in the emitted string comes from the Unit Contract.
There is no literal ``1000000`` written anywhere in this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .binding import BoundOperand
from .ir import (
    ARGMAX,
    ARGMIN,
    AVG,
    DENOMINATOR,
    DIVIDE,
    GROWTH,
    LOOKUP,
    MAXIMUM,
    MINIMUM,
    MINUEND,
    NEW,
    NUMERATOR,
    OLD,
    OperationIR,
    SUBTRACT,
    SUBTRAHEND,
    SUM,
)
from .units import (ConversionStatus, PERCENT, PERCENT_POINT, RATIO, Quantity,
                    Unit, UNKNOWN, conversion_factor, query_factor)


@dataclass(frozen=True)
class RenderResult:
    status: str                    # OK | ABSTAIN
    query: Optional[str] = None
    reason: Optional[str] = None
    per_operand_factor: Optional[dict] = None
    output_factor: Optional[float] = None

    @property
    def ok(self) -> bool:
        return self.status == "OK"


def _abstain(reason: str) -> RenderResult:
    return RenderResult("ABSTAIN", reason=reason)


def _pyrepr(s: str) -> str:
    return repr(s)


def cell_expr(op: BoundOperand, factor: float) -> str:
    """`float(dfN[(dfN['row_path']==...)&(dfN['col_label']==...)]['value'].values[0])`
    multiplied by an explicit, contract-derived factor."""
    c = op.cell
    base = (f"float({c.df_var}[({c.df_var}['row_path'] == {_pyrepr(c.row_path)}) & "
            f"({c.df_var}['col_label'] == {_pyrepr(c.col_label)})]['value'].values[0])")
    if factor == 1.0:
        return base
    return f"({base} * {factor!r})"


def render(ir: OperationIR, operands: list[BoundOperand]) -> RenderResult:
    """Emit a query whose numeric result is already in ``ir.output_unit``."""
    by_role: dict[str, list[BoundOperand]] = {}
    for o in operands:
        by_role.setdefault(o.role, []).append(o)

    # ---- decide the unit each operand must be expressed in before combining
    if ir.op == LOOKUP:
        target_each = ir.output_unit
    else:
        # all operands are brought to a single common unit so the operation is
        # dimensionally sound; for like/like DIVIDE and GROWTH the common unit
        # cancels, for SUBTRACT/SUM/AVG it must equal the output unit.
        dims = {o.quantity.unit.dimension for o in operands}
        if len(dims) != 1 or UNKNOWN in dims:
            return _abstain(f"OPERAND_DIMENSIONS_NOT_UNIFORM:{sorted(dims)}")
        if ir.op in (DIVIDE, GROWTH, ARGMAX, ARGMIN):
            target_each = operands[0].quantity.unit    # any common unit cancels
        elif ir.op == SUBTRACT and ir.output_unit.dimension == PERCENT_POINT:
            # A percentage POINT is the unit of the RESULT, never of an operand.
            # Converting each operand into PERCENT_POINT is meaningless and the
            # contract rightly refuses it; instead normalise both operands into
            # a common PERCENT representation and tag the DIFFERENCE as points.
            target_each = Unit(PERCENT)
        else:
            target_each = ir.output_unit

    factors: dict[str, float] = {}
    exprs: dict[str, list[str]] = {}
    for o in operands:
        qf = query_factor(o.quantity.unit, target_each, o.cell.storage_exponent)
        if not qf.ok:
            return _abstain(f"UNIT_CONTRACT_ABSTAIN:{o.role}:{qf.reason}")
        factors[f"{o.role}#{len(exprs.get(o.role, []))}"] = qf.factor
        exprs.setdefault(o.role, []).append(cell_expr(o, qf.factor))

    # ---- combine
    if ir.op == LOOKUP:
        body = exprs[NUMERATOR][0] if NUMERATOR in exprs else exprs["value"][0]
        return RenderResult("OK", body, per_operand_factor=factors, output_factor=1.0)

    if ir.op in (DIVIDE, GROWTH):
        if ir.op == DIVIDE:
            body = f"({exprs[NUMERATOR][0]} / {exprs[DENOMINATOR][0]})"
        else:
            new, old = exprs[NEW][0], exprs[OLD][0]
            body = f"(({new} - {old}) / abs({old}))"
        # result is a pure RATIO; convert to the requested ratio-like unit
        conv = conversion_factor(Unit(RATIO), ir.output_unit)
        if not conv.ok:
            return _abstain(f"OUTPUT_UNIT_ABSTAIN:{conv.reason}")
        if conv.factor != 1.0:
            body = f"({body} * {conv.factor!r})"
        return RenderResult("OK", body, per_operand_factor=factors, output_factor=conv.factor)

    if ir.op == SUBTRACT:
        body = f"({exprs[MINUEND][0]} - {exprs[SUBTRAHEND][0]})"
        # operands were normalised to `target_each`; the difference carries the
        # result unit directly (PERCENT - PERCENT = PERCENT_POINT, 1:1 in value)
        return RenderResult("OK", body, per_operand_factor=factors, output_factor=1.0)

    if ir.op in (SUM, AVG):
        parts = exprs["summand"]
        body = "(" + " + ".join(parts) + ")"
        if ir.op == AVG:
            body = f"({body} / {len(parts)})"
        return RenderResult("OK", body, per_operand_factor=factors, output_factor=1.0)

    if ir.op in (MAXIMUM, MINIMUM):
        function = "max" if ir.op == MAXIMUM else "min"
        body = f"{function}({', '.join(exprs['value'])})"
        return RenderResult("OK", body, per_operand_factor=factors, output_factor=1.0)

    if ir.op in (ARGMAX, ARGMIN):
        values = exprs["value"]
        periods = [operand.slot.period for operand in operands]
        if any(period is None or not period[:4].isdigit() for period in periods):
            return _abstain("ARG_EXTREMUM_REQUIRES_YEAR_PERIODS")
        function = "max" if ir.op == ARGMAX else "min"
        ranked = f"{function}({', '.join(values)})"
        # Stable first-operand tie break. Every branch remains an expression and
        # references the same evidence values, so replay proves the ranking.
        body = f"float({int(periods[-1][:4])})"
        for value, period in reversed(list(zip(values[:-1], periods[:-1], strict=True))):
            body = f"float({int(period[:4])} if {value} == {ranked} else {body})"
        return RenderResult("OK", body, per_operand_factor=factors, output_factor=1.0)

    return _abstain(f"NO_RENDERER:{ir.op}")
