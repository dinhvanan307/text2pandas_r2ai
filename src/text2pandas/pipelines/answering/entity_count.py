"""Typed positive-evidence COUNT across an explicit entity set."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .binding import BoundOperand, CandidateCell, Selector
from .count_engine import GT, CountPredicate, parse_positive_evidence_predicate
from .frame import COUNT_OP, classify_operation
from .ir import OperandSlot
from .pipeline import execute
from .policy import same_metric
from .render import cell_expr
from .units import compatible, query_factor

_OUTSTANDING_SHARES = "outstanding_common_shares"
_RELATED_SHORT_TERM_DEBT = "related_party_short_term_debt"
_OPERATING_LEASE_WITHIN_YEAR = "operating_lease_within_one_year"
_INTEREST_EXPENSE = "interest_expense"
_COMPOUND_PREDICATE = re.compile(r"(đ[ồo]ng\s*th[ờo]i|v[ừu]a[^?]{0,180}v[ừu]a)")


@dataclass(slots=True)
class EntityCountAnswer:
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
            "operation": "COUNT_ENTITIES",
            "pandas_query": self.query,
            "answer": self.answer,
            "evidence": self.evidence,
            "trace": self.trace,
        }


def classify_entity_count(
    question: str,
    entities: Sequence[str],
    years: Sequence[int],
    *,
    mode: str,
) -> tuple[CountPredicate | None, str | None]:
    if (
        mode != "screen"
        or len(entities) < 2
        or len(set(entities)) != len(entities)
        or len(years) != 1
        or classify_operation(question).op != COUNT_OP
        or _COMPOUND_PREDICATE.search(question.casefold())
    ):
        return None, None
    return parse_positive_evidence_predicate(question)


def answer_entity_count(
    question: str,
    pool: Sequence[CandidateCell],
    frames: Mapping[str, object],
    *,
    entities: Sequence[str],
    years: Sequence[int],
    basis: str | None,
    selector: Selector,
    mode: str,
    qid: int | None = None,
) -> EntityCountAnswer | None:
    predicate, reason = classify_entity_count(question, entities, years, mode=mode)
    if predicate is None and reason is None:
        return None
    result = EntityCountAnswer("OK", qid=qid)
    if predicate is None:
        return _fail(result, "ROUTE", reason or "COUNT_PREDICATE_NOT_SUPPORTED")

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
            and (
                predicate.threshold_unit is None
                or compatible(cell.unit, predicate.threshold_unit)
            )
            and _metric_cell_allowed(metric_id, cell)
        ]
        slot = OperandSlot("entity_value", period=str(year), basis=basis, entity=entity)
        cell = selector.pick(slot, entity_pool)
        if cell is None:
            return _fail(result, "BIND", f"ENTITY_COUNT_UNBOUND:{entity}")
        operands.append(BoundOperand("entity_value", slot, cell, cell.native_quantity()))

    physical = {(operand.cell.csv_path, operand.cell.row_index) for operand in operands}
    if len(physical) != len(operands):
        return _fail(result, "BIND", "ENTITY_COUNT_DUPLICATE_CELLS")
    result.trace.append(
        {
            "stage": "BIND",
            "status": "OK",
            "operands": {
                operand.slot.entity: {
                    "row_path": operand.cell.row_path,
                    "csv_path": operand.cell.csv_path,
                    "period": operand.cell.period,
                }
                for operand in operands
            },
        }
    )
    if metric_id is None and not same_metric(operands):
        return _fail(result, "POLICY", "ENTITY_COUNT_METRIC_DRIFT")

    expressions: list[str] = []
    symbol = ">" if predicate.operator == GT else "<"
    for operand in operands:
        target = predicate.threshold_unit or operand.quantity.unit
        conversion = query_factor(
            operand.quantity.unit,
            target,
            operand.cell.storage_exponent,
        )
        if not conversion.ok or conversion.factor is None:
            return _fail(result, "RENDER", f"ENTITY_COUNT_UNIT_ABSTAIN:{conversion.reason}")
        value = cell_expr(operand, conversion.factor)
        expressions.append(f"float({value} {symbol} {predicate.threshold!r})")
    query = "(" + " + ".join(expressions) + ")"
    used_frames = {operand.cell.df_var: frames[operand.cell.df_var] for operand in operands}
    answer, error = execute(query, used_frames)
    if error or answer is None:
        return _fail(result, "EXECUTE", error or "ENTITY_COUNT_EXECUTION_FAILED")
    if not math.isfinite(answer) or answer < 0 or answer > len(entities) or answer != int(answer):
        return _fail(result, "VALIDATE", "ENTITY_COUNT_RESULT_INVALID")

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
    if (
        "so luong co phieu dang luu hanh" in folded
        or "so luong co phieu pho thong dang luu hanh" in folded
    ):
        return _OUTSTANDING_SHARES
    if "no ngan han voi ben lien quan" in folded:
        return _RELATED_SHORT_TERM_DEBT
    if "cam ket thue hoat dong den han trong 1 nam" in folded:
        return _OPERATING_LEASE_WITHIN_YEAR
    if "chi phi lai vay" in folded:
        return _INTEREST_EXPENSE
    return None


def _metric_cell_allowed(metric_id: str | None, cell: CandidateCell) -> bool:
    if metric_id is None:
        return True
    path = _fold(cell.row_path)
    leaf = _fold(cell.row_path.rsplit("›", 1)[-1])
    if metric_id == _OUTSTANDING_SHARES:
        return (
            "co phieu" in leaf
            and "luu hanh" in leaf
            and not any(
                value in leaf
                for value in ("binh quan gia quyen", "lai co ban", "pha loang")
            )
        )
    if metric_id == _RELATED_SHORT_TERM_DEBT:
        return "no ngan han" in path and "lien quan" in path
    if metric_id == _INTEREST_EXPENSE:
        return "chi phi lai vay" in leaf and "von hoa" not in leaf
    return (
        metric_id == _OPERATING_LEASE_WITHIN_YEAR
        and "cam ket thue hoat dong" in path
        and any(value in leaf for value in ("trong 1 nam", "den han trong 1 nam"))
    )


def _fail(result: EntityCountAnswer, stage: str, reason: str) -> EntityCountAnswer:
    result.status = "ABSTAIN"
    result.stage_failed = stage
    result.reason = reason
    result.trace.append({"stage": stage, "status": "ABSTAIN", "reason": reason})
    return result
