"""Typed average of one reported fact across an explicit entity set."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .binding import BoundOperand, CandidateCell, Selector
from .formula_engine import match_formula
from .frame import classify_operation
from .ir import AVG, OperandSlot
from .pipeline import execute
from .policy import same_basis
from .render import cell_expr
from .units import MONEY, SHARES, Unit, compatible, query_factor

_COMPARISON_CUES = (
    "chenh lech",
    "khac biet",
    "cao hon",
    "thap hon",
    "lon hon",
    "nho hon",
)
_FILTER_CUES = (
    "trung vi",
    "lam nguong",
)
_FILTER_PATTERN = re.compile(
    r"\bco\b[^?]{0,120}\b(?:duong|am|cao hon|thap hon|lon hon|nho hon|"
    r"khong thap hon|tu \d)\b"
)
_FINANCIAL_INCOME = "financial_income"
_SHORT_TERM_INTEREST_PAYABLE = "short_term_interest_payable"
_TAXES_PAYABLE = "taxes_payable"
_CURRENT_INCOME_TAX_EXPENSE = "current_income_tax_expense"
_OUTSTANDING_SHARES = "outstanding_common_shares"


@dataclass(slots=True)
class EntityAverageAnswer:
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
            "operation": "ENTITY_AVERAGE",
            "pandas_query": self.query,
            "answer": self.answer,
            "evidence": self.evidence,
            "trace": self.trace,
        }


def is_typed_entity_average(
    question: str,
    entities: Sequence[str],
    years: Sequence[int],
    requested_unit: Unit,
) -> bool:
    """Return whether the question fits the reviewed direct-fact contract.

    Percent and ratio averages remain out of scope: they may require a
    per-entity formula before aggregation. Monetary and share facts already
    carry an unambiguous unit contract and can be averaged directly.
    """

    folded = _fold(question)
    metric_id = _match_metric(folded)
    return (
        len(entities) >= 2
        and len(set(entities)) == len(entities)
        and len(years) == 1
        and classify_operation(question).op == AVG
        and match_formula(question) is None
        and metric_id is not None
        and requested_unit.dimension in {MONEY, SHARES}
        and not any(cue in folded for cue in _COMPARISON_CUES)
        and not any(cue in folded for cue in _FILTER_CUES)
        and _FILTER_PATTERN.search(folded) is None
    )


def answer_entity_average(
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
) -> EntityAverageAnswer | None:
    """Bind the same reported fact once per entity and return its mean."""

    if not is_typed_entity_average(question, entities, years, requested_unit):
        return None
    result = EntityAverageAnswer("OK", qid=qid)
    year = years[0]
    metric_id = _match_metric(_fold(question))
    if metric_id is None:  # Kept defensive if the route contract changes.
        return _fail(result, "ROUTE", "ENTITY_AVERAGE_METRIC_NOT_REVIEWED")
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
            return _fail(result, "BIND", f"ENTITY_AVERAGE_UNBOUND:{entity}")
        operands.append(BoundOperand("entity_value", slot, cell, cell.native_quantity()))

    physical = {(operand.cell.csv_path, operand.cell.row_index) for operand in operands}
    if len(physical) != len(operands):
        return _fail(result, "BIND", "ENTITY_AVERAGE_DUPLICATE_CELLS")
    result.trace.append(
        {
            "stage": "BIND",
            "status": "OK",
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
            return _fail(result, "RENDER", f"ENTITY_AVERAGE_UNIT_ABSTAIN:{conversion.reason}")
        expressions.append(cell_expr(operand, conversion.factor))
    query = f"(({' + '.join(expressions)}) / {len(expressions)})"
    used_frames = {operand.cell.df_var: frames[operand.cell.df_var] for operand in operands}
    answer, error = execute(query, used_frames)
    if error or answer is None:
        return _fail(result, "EXECUTE", error or "ENTITY_AVERAGE_EXECUTION_FAILED")
    if not math.isfinite(answer):
        return _fail(result, "VALIDATE", "ENTITY_AVERAGE_RESULT_INVALID")

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


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    plain = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", plain.replace("đ", "d")).strip()


def _match_metric(folded_question: str) -> str | None:
    if "doanh thu hoat dong tai chinh" in folded_question:
        return _FINANCIAL_INCOME
    if (
        "chi phi lai vay" in folded_question
        and "ngan han" in folded_question
        and "phai tra" in folded_question
    ):
        return _SHORT_TERM_INTEREST_PAYABLE
    if "thue va cac khoan phai nop nha nuoc" in folded_question:
        return _TAXES_PAYABLE
    if (
        "chi phi thue thu nhap doanh nghiep hien hanh" in folded_question
        or "chi phi thue tndn hien hanh" in folded_question
    ):
        return _CURRENT_INCOME_TAX_EXPENSE
    if (
        "so luong co phieu pho thong dang luu hanh" in folded_question
        or "so luong co phieu dang luu hanh" in folded_question
    ):
        return _OUTSTANDING_SHARES
    return None


def _metric_cell_allowed(metric_id: str, cell: CandidateCell) -> bool:
    path = _fold(cell.row_path)
    leaf = _fold(cell.row_path.rsplit("›", 1)[-1])
    if metric_id == _FINANCIAL_INCOME:
        return leaf == "doanh thu hoat dong tai chinh" or (
            leaf in {"cong", "tong cong"}
            and "doanh thu hoat dong tai chinh" in path
        )
    if metric_id == _SHORT_TERM_INTEREST_PAYABLE:
        return (
            "chi phi phai tra" in path
            and "chi phi lai vay" in leaf
            and "dai han" not in path
        )
    if metric_id == _TAXES_PAYABLE:
        return leaf == "thue va cac khoan phai nop nha nuoc"
    if metric_id == _CURRENT_INCOME_TAX_EXPENSE:
        return leaf in {
            "chi phi thue tndn hien hanh",
            "chi phi thue thu nhap hien hanh",
            "chi phi thue thu nhap doanh nghiep hien hanh",
        }
    return (
        metric_id == _OUTSTANDING_SHARES
        and "co phieu" in leaf
        and "luu hanh" in leaf
        and not any(
            value in leaf
            for value in ("binh quan gia quyen", "lai co ban", "pha loang")
        )
    )


def _fail(result: EntityAverageAnswer, stage: str, reason: str) -> EntityAverageAnswer:
    result.status = "ABSTAIN"
    result.stage_failed = stage
    result.reason = reason
    result.trace.append({"stage": stage, "status": "ABSTAIN", "reason": reason})
    return result
