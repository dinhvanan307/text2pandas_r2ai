"""Typed same-period difference between exactly two entities."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .binding import BoundOperand, CandidateCell, Selector
from .formula_engine import match_formula
from .frame import SUBTRACT, classify_operation
from .ir import OperandSlot
from .pipeline import execute
from .policy import same_basis, same_metric
from .render import cell_expr
from .units import COUNT, UNKNOWN, Unit, compatible, query_factor

_ENTITY_METRICS = {
    "outstanding_common_shares": {
        "question_aliases": ("so luong co phieu pho thong dang luu hanh",),
        "required_all": ("co phieu", "luu hanh"),
        "forbidden": ("binh quan gia quyen", "lai co ban", "pha loang"),
    },
    "profit_after_tax": {
        "question_aliases": ("loi nhuan thuan sau thue",),
        "required_any": ("loi nhuan sau thue", "loi nhuan thuan sau thue"),
        "forbidden": (
            "chua phan phoi",
            "truoc thue",
            "dieu chinh",
            "co dong",
            "cong ty me",
            "khong kiem soat",
        ),
    },
}


@dataclass(slots=True)
class EntityDifferenceAnswer:
    status: str
    qid: int | None = None
    stage_failed: str | None = None
    reason: str | None = None
    query: str | None = None
    answer: float | None = None
    evidence: list[dict[str, str]] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "OK"

    def to_dict(self) -> dict:
        return {
            "qid": self.qid,
            "status": self.status,
            "stage_failed": self.stage_failed,
            "reason": self.reason,
            "operation": "ENTITY_DIFFERENCE",
            "pandas_query": self.query,
            "answer": self.answer,
            "evidence": self.evidence,
            "trace": self.trace,
        }


def is_typed_entity_difference(
    question: str,
    entities: Sequence[str],
    years: Sequence[int],
    requested_unit: Unit,
    *,
    mode: str,
) -> bool:
    """Return whether the question fits the narrow reviewed route contract."""

    return (
        len(entities) == 2
        and len(set(entities)) == 2
        and len(years) == 1
        and classify_operation(question).op == SUBTRACT
        and match_formula(question) is None
        and requested_unit.dimension not in {UNKNOWN, COUNT}
    )


def answer_entity_difference(
    question: str,
    pool: Sequence[CandidateCell],
    frames: Mapping[str, object],
    *,
    entities: Sequence[str],
    years: Sequence[int],
    basis: str | None,
    requested_unit: Unit,
    selector: Selector,
    mode: str,
    qid: int | None = None,
) -> EntityDifferenceAnswer | None:
    """Bind the same metric once per entity and execute the semantic direction.

    Entity order is semantic: Vietnamese questions of the form ``A so với B``
    ask for ``A - B``; ``A kém/thấp/bé hơn B`` asks for ``B - A``.  Absolute
    value is only applied when the question explicitly says ``chênh lệch tuyệt
    đối``; applying it to ordinary differences would discard their direction.
    """

    if not is_typed_entity_difference(
        question,
        entities,
        years,
        requested_unit,
        mode=mode,
    ):
        return None
    result = EntityDifferenceAnswer("OK", qid=qid)
    year = years[0]
    metric_id = _match_metric(question)
    operands: list[BoundOperand] = []
    for entity in entities:
        entity_pool = [
            cell
            for cell in pool
            if cell.entity == entity
            and cell.period
            and cell.period[:4] == str(year)
            and (not basis or cell.basis == basis)
            and compatible(cell.unit, requested_unit)
            and _metric_cell_allowed(metric_id, cell)
        ]
        slot = OperandSlot("entity_value", period=str(year), basis=basis, entity=entity)
        cell = selector.pick(slot, entity_pool)
        if cell is None:
            return _fail(result, "BIND", f"ENTITY_DIFFERENCE_UNBOUND:{entity}")
        operands.append(BoundOperand("entity_value", slot, cell, cell.native_quantity()))

    physical = {(operand.cell.csv_path, operand.cell.row_index) for operand in operands}
    if len(physical) != 2:
        return _fail(result, "BIND", "ENTITY_DIFFERENCE_DUPLICATE_CELLS")
    operation = classify_operation(question)
    calculation_operands = list(reversed(operands)) if operation.reverse_difference else operands
    result.trace.append(
        {
            "stage": "BIND",
            "status": "OK",
            "semantic_entity_order": [operand.slot.entity for operand in operands],
            "calculation_entity_order": [operand.slot.entity for operand in calculation_operands],
            "reverse_difference": operation.reverse_difference,
            "absolute_difference": operation.absolute_difference,
            "operands": {
                operand.slot.entity: {
                    "row_path": operand.cell.row_path,
                    "csv_path": operand.cell.csv_path,
                    "period": operand.cell.period,
                    "basis": operand.cell.basis,
                }
                for operand in operands
            },
        }
    )
    if not same_basis(operands):
        return _fail(result, "POLICY", "CROSS_BASIS_OPERANDS")
    if metric_id is None and not same_metric(operands):
        return _fail(result, "POLICY", "ENTITY_DIFFERENCE_METRIC_DRIFT")

    expressions: list[str] = []
    for operand in calculation_operands:
        conversion = query_factor(
            operand.quantity.unit,
            requested_unit,
            operand.cell.storage_exponent,
        )
        if not conversion.ok or conversion.factor is None:
            return _fail(
                result,
                "RENDER",
                f"ENTITY_DIFFERENCE_UNIT_ABSTAIN:{conversion.reason}",
            )
        expressions.append(cell_expr(operand, conversion.factor))
    query = f"({expressions[0]} - {expressions[1]})"
    if operation.absolute_difference:
        query = f"abs({query})"
    used_frames = {operand.cell.df_var: frames[operand.cell.df_var] for operand in operands}
    answer, error = execute(query, used_frames)
    if error or answer is None:
        return _fail(result, "EXECUTE", error or "ENTITY_DIFFERENCE_EXECUTION_FAILED")
    if not math.isfinite(answer):
        return _fail(result, "VALIDATE", "ENTITY_DIFFERENCE_RESULT_INVALID")

    result.query = query
    result.answer = answer
    for operand in operands:
        result.evidence.append(
            {"variable": operand.cell.df_var, "csv_path": operand.cell.csv_path}
        )
    result.trace.extend(
        [
            {"stage": "RENDER", "status": "OK", "query": query},
            {"stage": "EXECUTE", "status": "OK", "answer": answer},
            {"stage": "VALIDATE", "status": "PASS"},
        ]
    )
    return result


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    plain = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", plain.replace("đ", "d")).strip()


def _match_metric(question: str) -> str | None:
    folded = _fold(question)
    for metric_id, policy in _ENTITY_METRICS.items():
        if any(alias in folded for alias in policy["question_aliases"]):
            return metric_id
    return None


def _metric_cell_allowed(metric_id: str | None, cell: CandidateCell) -> bool:
    if metric_id is None:
        return True
    policy = _ENTITY_METRICS[metric_id]
    leaf = _fold(cell.row_path.rsplit("›", 1)[-1])
    if any(value in leaf for value in policy["forbidden"]):
        return False
    required_all = policy.get("required_all", ())
    required_any = policy.get("required_any", ())
    return all(value in leaf for value in required_all) and (
        not required_any or any(value in leaf for value in required_any)
    )


def _fail(
    result: EntityDifferenceAnswer,
    stage: str,
    reason: str,
) -> EntityDifferenceAnswer:
    result.status = "ABSTAIN"
    result.stage_failed = stage
    result.reason = reason
    result.trace.append({"stage": stage, "status": "ABSTAIN", "reason": reason})
    return result
