"""Operand binding: turn declared slots into real, unit-carrying cells.

A ``BoundOperand`` is the unit of evidence. Nothing downstream may reference a
number that did not come through here, which is what makes multi-operand
evidence completeness checkable instead of aspirational.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Optional, Sequence

from .ir import OperandSlot, OperationIR
from .units import UNKNOWN, Quantity, Unit


@dataclass(frozen=True)
class CandidateCell:
    """A cell offered by retrieval/selection, with everything needed to type it."""

    df_var: str
    csv_path: str
    row_index: int
    row_path: str
    col_label: str
    value_raw: str
    value: float                      # the stored number (post-ingest)
    parsed_raw: Optional[float]       # value_raw parsed back to a number
    storage_exponent: Optional[int]   # log10(value / parsed_raw)
    unit: Unit                        # declared by the column header
    period: Optional[str] = None
    table_uid: Optional[str] = None
    document_id: Optional[str] = None
    entity: Optional[str] = None
    basis: Optional[str] = None
    statement_type: Optional[str] = None
    metric_code: Optional[str] = None
    period_role: Optional[str] = None
    is_restated: bool = False
    table_rank: int = 0
    section_text: str = ""
    table_context: str = ""

    def native_quantity(self) -> Quantity:
        """The cell expressed in the unit its *header* declares.

        Uses ``parsed_raw`` -- the printed number -- not ``value``, because
        ``value`` carries an ingest scaling that is not constant corpus-wide.
        """
        return Quantity(self.parsed_raw, self.unit, provenance=self.provenance())

    def provenance(self) -> dict:
        return {
            "csv_path": self.csv_path,
            "row_index": self.row_index,
            "row_path": self.row_path,
            "col_label": self.col_label,
            "value_raw": self.value_raw,
            "stored_value": self.value,
            "storage_exponent": self.storage_exponent,
            "declared_unit": self.unit.describe(),
            "table_uid": self.table_uid,
            "document_id": self.document_id,
            "entity": self.entity,
            "basis": self.basis,
            "statement_type": self.statement_type,
            "metric_code": self.metric_code,
            "period_role": self.period_role,
            "is_restated": self.is_restated,
            "section_text": self.section_text,
        }


@dataclass(frozen=True)
class BoundOperand:
    role: str
    slot: OperandSlot
    cell: CandidateCell
    quantity: Quantity

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "source": self.cell.csv_path,
            "df_var": self.cell.df_var,
            "cell": {"row_path": self.cell.row_path, "col_label": self.cell.col_label,
                     "row_index": self.cell.row_index},
            "value": self.quantity.value,
            "period": self.slot.period or self.cell.period,
            "dimension": self.quantity.unit.dimension,
            "unit": self.quantity.unit.describe(),
            "provenance": self.cell.provenance(),
        }


@dataclass
class BindingResult:
    status: str                       # OK | ABSTAIN
    operands: list[BoundOperand] = field(default_factory=list)
    reason: Optional[str] = None
    unbound_roles: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "OK"


class Selector:
    """Chooses a cell for a slot from the candidate pool.

    Deliberately dumb and deterministic: score by explicit, inspectable
    features, break ties by pool order. Improving this is a *selection*
    workstream; keeping it separate means selection defects do not masquerade
    as unit or operation defects.
    """

    def score(self, slot: OperandSlot, cell: CandidateCell) -> tuple:
        period_hit = 0
        if slot.period and (cell.period or cell.col_label):
            hay = f"{cell.period or ''} {cell.col_label}"
            period_hit = 1 if slot.period[:4] in hay else 0
        metric_hit = 0
        if slot.metric_id:
            metric_hit = 1 if slot.metric_id.lower() in cell.row_path.lower() else 0
        unit_known = 1 if cell.unit.dimension != UNKNOWN else 0
        scale_known = 1 if cell.storage_exponent is not None else 0
        return (period_hit, metric_hit, unit_known, scale_known)

    def pick(self, slot: OperandSlot, pool: Sequence[CandidateCell]) -> Optional[CandidateCell]:
        ranked = self.rank(slot, pool)
        return ranked[0] if ranked else None

    def rank(self, slot: OperandSlot, pool: Sequence[CandidateCell]) -> list[CandidateCell]:
        """Rank candidates while preserving legacy pool-order tie behavior."""

        return sorted(pool, key=lambda cell: self.score(slot, cell), reverse=True)

    def failure_reason(
        self, slot: OperandSlot, pool: Sequence[CandidateCell]
    ) -> Optional[str]:
        _ = slot, pool
        return None


def bind(ir: OperationIR, pool: Sequence[CandidateCell],
         selector: Optional[Selector] = None,
         allow_reuse: bool = False) -> BindingResult:
    """Bind every slot of ``ir`` to a distinct cell from ``pool``.

    Distinctness matters: a DIVIDE whose numerator and denominator resolve to
    the same cell is a selection failure that would otherwise silently return
    1.0 and look plausible.
    """
    selector = selector or Selector()
    remaining = list(pool)
    bound: list[BoundOperand] = []
    unbound: list[str] = []

    for slot in ir.slots:
        cell = selector.pick(slot, remaining)
        if cell is None:
            unbound.append(slot.role)
            continue
        if not allow_reuse:
            remaining = [c for c in remaining if c is not cell]
        q = cell.native_quantity()
        if q.value is None:
            unbound.append(slot.role)
            continue
        bound.append(BoundOperand(slot.role, slot, cell, q))

    if unbound:
        selector_reason = next(
            (
                selector.failure_reason(slot, pool)
                for slot in ir.slots
                if slot.role in unbound and selector.failure_reason(slot, pool)
            ),
            None,
        )
        return BindingResult(
            "ABSTAIN",
            bound,
            reason=selector_reason or "UNBOUND_OPERANDS",
            unbound_roles=unbound,
        )
    return BindingResult("OK", bound)


def bind_ranked(
    ir: OperationIR,
    pool: Sequence[CandidateCell],
    *,
    selector: Selector,
    max_bindings: int = 3,
) -> tuple[BindingResult, ...]:
    """Return at most three deterministic, distinct candidate bindings.

    This function only enumerates bindings. Render, policy, execution and the
    existing validator remain authoritative and decide whether the caller may
    advance to the next binding.
    """

    if not 1 <= max_bindings <= 3:
        raise ValueError("P0 max_bindings must be between 1 and 3")
    ranked_by_slot = [selector.rank(slot, pool) for slot in ir.slots]
    for slot, ranked in zip(ir.slots, ranked_by_slot, strict=True):
        if not ranked:
            return (
                BindingResult(
                    "ABSTAIN",
                    reason=selector.failure_reason(slot, pool) or "UNBOUND_OPERANDS",
                    unbound_roles=[slot.role],
                ),
            )
    limits = [range(min(len(ranked), max_bindings)) for ranked in ranked_by_slot]
    combinations = sorted(product(*limits), key=lambda indices: (sum(indices), indices))
    results: list[BindingResult] = []
    for indices in combinations:
        cells = [ranked_by_slot[index][rank] for index, rank in enumerate(indices)]
        physical = {(cell.csv_path, cell.row_index) for cell in cells}
        if len(physical) != len(cells):
            continue
        operands: list[BoundOperand] = []
        invalid = False
        for slot, cell in zip(ir.slots, cells, strict=True):
            quantity = cell.native_quantity()
            if quantity.value is None:
                invalid = True
                break
            operands.append(BoundOperand(slot.role, slot, cell, quantity))
        if invalid:
            continue
        results.append(BindingResult("OK", operands))
        if len(results) == max_bindings:
            break
    if results:
        return tuple(results)
    return (BindingResult("ABSTAIN", reason="NO_DISTINCT_BINDING"),)
