"""OperationIR -- the typed contract between "what was asked" and "what to compute".

Deliberately separate from :mod:`frame`. The boundary exists so a failure can
be attributed: a wrong ``QuestionSemanticFrame`` is a *parsing* defect, a wrong
``OperationIR`` is a *compilation* defect, a wrong ``BoundOperand`` is a
*retrieval/selection* defect. Merging them would collapse three distinct
root causes into one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .units import (MONEY, PERCENT, PERCENT_POINT, RATIO, COUNT, SHARES,
                    UNKNOWN, Unit)

# ------------------------------------------------------------------ operations
LOOKUP = "LOOKUP"
DIVIDE = "DIVIDE"
SUBTRACT = "SUBTRACT"
GROWTH = "GROWTH"
SUM = "SUM"
AVG = "AVG"
MAXIMUM = "MAXIMUM"
MINIMUM = "MINIMUM"
ARGMAX = "ARGMAX"
ARGMIN = "ARGMIN"

OPERATIONS = (LOOKUP, DIVIDE, SUBTRACT, GROWTH, SUM, AVG, MAXIMUM, MINIMUM, ARGMAX, ARGMIN)

# --------------------------------------------------------------- operand roles
VALUE = "value"
NUMERATOR = "numerator"
DENOMINATOR = "denominator"
MINUEND = "minuend"
SUBTRAHEND = "subtrahend"
NEW = "new"
OLD = "old"
SUMMAND = "summand"

#: ordered, required roles per operation. ``variadic`` marks a role that may
#: repeat. Order is semantic: (numerator, denominator) is not commutative.
ROLE_SPEC: dict[str, tuple[tuple[str, ...], bool]] = {
    LOOKUP: ((VALUE,), False),
    DIVIDE: ((NUMERATOR, DENOMINATOR), False),
    SUBTRACT: ((MINUEND, SUBTRAHEND), False),
    GROWTH: ((NEW, OLD), False),
    SUM: ((SUMMAND,), True),
    AVG: ((SUMMAND,), True),
    MAXIMUM: ((VALUE,), True),
    MINIMUM: ((VALUE,), True),
    ARGMAX: ((VALUE,), True),
    ARGMIN: ((VALUE,), True),
}

#: minimum operand count per operation
MIN_ARITY = {
    LOOKUP: 1,
    DIVIDE: 2,
    SUBTRACT: 2,
    GROWTH: 2,
    SUM: 2,
    AVG: 2,
    MAXIMUM: 2,
    MINIMUM: 2,
    ARGMAX: 2,
    ARGMIN: 2,
}


class IRError(ValueError):
    pass


@dataclass(frozen=True)
class OperandSlot:
    """A declared, not-yet-bound operand."""

    role: str
    metric_id: Optional[str] = None
    period: Optional[str] = None
    basis: Optional[str] = None
    entity: Optional[str] = None

    def key(self) -> tuple:
        return (self.role, self.metric_id, self.period, self.basis, self.entity)

    def to_dict(self) -> dict:
        return {"role": self.role, "metric_id": self.metric_id,
                "period": self.period, "basis": self.basis, "entity": self.entity}

    @classmethod
    def from_dict(cls, d: dict) -> "OperandSlot":
        return cls(role=d["role"], metric_id=d.get("metric_id"),
                   period=d.get("period"), basis=d.get("basis"),
                   entity=d.get("entity"))


@dataclass(frozen=True)
class OperationIR:
    """A compiled, executable intent."""

    op: str
    slots: tuple[OperandSlot, ...]
    output_unit: Unit
    #: policy flags kept explicit so they show up in traces
    abstain_on_missing_operand: bool = True
    notes: tuple[str, ...] = field(default_factory=tuple)
    result_kind: Optional[str] = None

    def __post_init__(self):
        if self.op not in OPERATIONS:
            raise IRError(f"unknown operation {self.op!r}")
        roles, variadic = ROLE_SPEC[self.op]
        got = [s.role for s in self.slots]
        if variadic:
            if set(got) != set(roles):
                raise IRError(f"{self.op} accepts only roles {roles}, got {sorted(set(got))}")
            if len(got) < MIN_ARITY[self.op]:
                raise IRError(f"{self.op} needs >= {MIN_ARITY[self.op]} operands, got {len(got)}")
        else:
            if tuple(got) != roles:
                raise IRError(f"{self.op} requires ordered roles {roles}, got {tuple(got)}")

    @property
    def arity(self) -> int:
        return len(self.slots)

    def to_dict(self) -> dict:
        """Serialise. Round-trips through :meth:`from_dict` exactly -- an IR you
        cannot persist and reload is an IR you cannot debug from a trace."""
        return {
            "op": self.op,
            "slots": [s.to_dict() for s in self.slots],
            "output_unit": {"dimension": self.output_unit.dimension,
                            "scale_exponent": self.output_unit.scale_exponent,
                            "currency": self.output_unit.currency},
            "abstain_on_missing_operand": self.abstain_on_missing_operand,
            "notes": list(self.notes),
            "result_kind": self.result_kind,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OperationIR":
        u = d["output_unit"]
        return cls(
            op=d["op"],
            slots=tuple(OperandSlot.from_dict(x) for x in d["slots"]),
            output_unit=Unit(u["dimension"], u.get("scale_exponent"), u.get("currency")),
            abstain_on_missing_operand=d.get("abstain_on_missing_operand", True),
            notes=tuple(d.get("notes", ())),
            result_kind=d.get("result_kind"),
        )

    def slot(self, role: str) -> OperandSlot:
        for s in self.slots:
            if s.role == role:
                return s
        raise IRError(f"no slot {role!r} in {self.op}")


def result_dimension(op: str, operand_dimensions: list[str]) -> str:
    """Dimension an operation yields, or UNKNOWN when it is not derivable.

    This is what makes ``Answer Validator`` able to reject "percent question
    answered with money" without inspecting any gold.
    """
    dims = list(operand_dimensions)
    if not dims or any(d == UNKNOWN for d in dims):
        return UNKNOWN
    if op in (LOOKUP, MAXIMUM, MINIMUM):
        return dims[0]
    if op == SUBTRACT:
        if len(set(dims)) != 1:
            return UNKNOWN
        # a difference of two percentages is measured in percentage POINTS
        return PERCENT_POINT if dims[0] == PERCENT else dims[0]
    if op in (SUM, AVG):
        return dims[0] if len(set(dims)) == 1 else UNKNOWN
    if op == DIVIDE:
        # like/like cancels to a pure ratio; unlike dimensions are not defined
        return RATIO if len(set(dims)) == 1 else UNKNOWN
    if op == GROWTH:
        return RATIO if len(set(dims)) == 1 else UNKNOWN
    if op in (ARGMAX, ARGMIN):
        return UNKNOWN
    return UNKNOWN
