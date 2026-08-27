"""Typed sum of one reviewed reported fact across explicit entities."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .binding import BoundOperand, CandidateCell, Selector
from .formula_engine import match_formula
from .ir import OperandSlot
from .pipeline import execute
from .policy import same_basis
from .render import cell_expr
from .units import MONEY, Unit, compatible, query_factor

_SUM_CUE = re.compile(
    r"\b(?:tinh\s+)?tong\s+(?:gia tri\s+)?(?:chi phi|doanh thu|so du|luu chuyen)\b"
)
_FILTER_CUES = ("trung vi", "lam nguong", "co ty le", "co he so")

_FINANCIAL_EXPENSE = "financial_expense"
_SELLING_EXPENSE = "selling_expense"
_FINANCIAL_INCOME = "financial_income"
_CFO = "cash_flow_from_operations"


@dataclass(slots=True)
class EntitySumAnswer:
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
            "operation": "ENTITY_SUM",
            "pandas_query": self.query,
            "answer": self.answer,
            "evidence": self.evidence,
            "trace": self.trace,
        }


def is_typed_entity_sum(
    question: str,
    entities: Sequence[str],
    years: Sequence[int],
    requested_unit: Unit,
) -> bool:
    folded = _fold(question)
    return (
        len(entities) >= 2
        and len(set(entities)) == len(entities)
        and len(years) == 1
        and requested_unit.dimension == MONEY
        and match_formula(question) is None
        and _SUM_CUE.search(folded) is not None
        and not any(cue in folded for cue in _FILTER_CUES)
        and _match_metric(folded) is not None
    )


def answer_entity_sum(
    question: str,
    pool: Sequence[CandidateCell],
    frames: Mapping[str, object],
    *,
    entities: Sequence[str],
    years: Sequence[int],
    basis: str | None,
    requested_unit: Unit,
    selector: Selector,
    qid: int | None = None,
) -> EntitySumAnswer | None:
    if not is_typed_entity_sum(question, entities, years, requested_unit):
        return None
    result = EntitySumAnswer("OK", qid=qid)
    metric_id = _match_metric(_fold(question))
    if metric_id is None:  # Defensive if the route contract changes.
        return _fail(result, "ROUTE", "ENTITY_SUM_METRIC_NOT_REVIEWED")

    year = years[0]
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
            return _fail(result, "BIND", f"ENTITY_SUM_UNBOUND:{entity}")
        operands.append(BoundOperand("entity_value", slot, cell, cell.native_quantity()))

    physical = {(operand.cell.csv_path, operand.cell.row_index) for operand in operands}
    if len(physical) != len(operands):
        return _fail(result, "BIND", "ENTITY_SUM_DUPLICATE_CELLS")
    result.trace.append(
        {
            "stage": "BIND",
            "status": "OK",
            "metric_id": metric_id,
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

    expressions: list[str] = []
    for operand in operands:
        conversion = query_factor(
            operand.quantity.unit,
            requested_unit,
            operand.cell.storage_exponent,
        )
        if not conversion.ok or conversion.factor is None:
            return _fail(result, "RENDER", f"ENTITY_SUM_UNIT_ABSTAIN:{conversion.reason}")
        expression = cell_expr(operand, conversion.factor)
        if metric_id in {_FINANCIAL_EXPENSE, _SELLING_EXPENSE}:
            expression = f"abs({expression})"
        expressions.append(expression)
    query = f"({' + '.join(expressions)})"
    used_frames = {operand.cell.df_var: frames[operand.cell.df_var] for operand in operands}
    answer, error = execute(query, used_frames)
    if error or answer is None:
        return _fail(result, "EXECUTE", error or "ENTITY_SUM_EXECUTION_FAILED")
    if not math.isfinite(answer):
        return _fail(result, "VALIDATE", "ENTITY_SUM_RESULT_INVALID")

    result.query = query
    result.answer = answer
    result.evidence = [
        {"variable": operand.cell.df_var, "csv_path": operand.cell.csv_path}
        for operand in operands
    ]
    result.trace.extend(
        [
            {"stage": "RENDER", "status": "OK", "query": query},
            {"stage": "EXECUTE", "status": "OK", "answer": answer},
            {"stage": "VALIDATE", "status": "PASS"},
        ]
    )
    return result


def _match_metric(folded_question: str) -> str | None:
    if "chi phi tai chinh" in folded_question:
        return _FINANCIAL_EXPENSE
    if "chi phi ban hang" in folded_question:
        return _SELLING_EXPENSE
    if "doanh thu hoat dong tai chinh" in folded_question:
        return _FINANCIAL_INCOME
    if "luu chuyen tien thuan tu hoat dong kinh doanh" in folded_question:
        return _CFO
    return None


def _metric_cell_allowed(metric_id: str, cell: CandidateCell) -> bool:
    path = _fold(cell.row_path)
    leaf = _fold(cell.row_path.rsplit("›", 1)[-1])
    if metric_id == _FINANCIAL_EXPENSE:
        return leaf == "chi phi tai chinh" or (
            leaf in {"cong", "tong cong"} and "chi phi tai chinh" in path
        )
    if metric_id == _SELLING_EXPENSE:
        return leaf == "chi phi ban hang"
    if metric_id == _FINANCIAL_INCOME:
        return leaf == "doanh thu hoat dong tai chinh" or (
            leaf in {"cong", "tong cong"} and "doanh thu hoat dong tai chinh" in path
        )
    return metric_id == _CFO and leaf in {
        "luu chuyen tien thuan tu hoat dong kinh doanh",
        "luu chuyen tien thuan tu hoat dong kinh doanh trong ky",
    }


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    plain = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", plain.replace("đ", "d")).strip()


def _fail(result: EntitySumAnswer, stage: str, reason: str) -> EntitySumAnswer:
    result.status = "ABSTAIN"
    result.stage_failed = stage
    result.reason = reason
    result.trace.append({"stage": stage, "status": "ABSTAIN", "reason": reason})
    return result
