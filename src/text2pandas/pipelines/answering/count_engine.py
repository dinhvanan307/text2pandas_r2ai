"""Typed COUNT over explicit periods for one entity.

Only positive-evidence predicates are supported. Counting the *absence* of a
row requires proving corpus completeness for every requested period, so an
"item exists in how many years" question remains fail-closed.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Sequence

from text2pandas.domain.units.lexicon import scan_unit

from .binding import BoundOperand, CandidateCell, Selector
from .frame import COUNT_OP, classify_operation
from .ir import OperandSlot
from .pipeline import execute
from .policy import same_metric
from .render import cell_expr
from .units import COUNT, MONEY, SHARES, Unit, query_factor

GT = "GT"
LT = "LT"

_COUNT_PERIOD = re.compile(r"(?:bao\s+nhi[êe]u\s+n[ăa]m|s[ốo]\s+n[ăa]m)")
_EXISTENCE = re.compile(r"t[ồo]n\s+t[ạa]i\s+kho[ảa]n\s+m[ụu]c")
_NEGATIVE = re.compile(r"\b[âa]m\b")
_POSITIVE = re.compile(r"\bd[ưu][ơo]ng\b")
_THRESHOLD = re.compile(
    r"(?P<direction>(?:nhi[ềe]u|l[ớo]n|cao|[íi]t|nh[ỏo]|th[ấa]p)\s+h[ơo]n"
    r"|v[ưu][ợo]t)\s+"
    r"(?P<number>\d+(?:[.,]\d+)?)"
    r"(?P<unit>\s*(?:tr[ăa]m\s+t[ỷy]|ngh[ìi]n\s+t[ỷy]|t[ỷy]|tri[ệe]u|ngh[ìi]n)?"
    r"\s*(?:đ[ồo]ng|vnd|vnđ|c[ổo]\s*phi[ếe]u|c[ổo]\s*ph[ầa]n)?)"
)


@dataclass(frozen=True, slots=True)
class CountPredicate:
    operator: str
    threshold: float
    threshold_unit: Unit | None = None
    metric_id: str | None = None


_COUNT_METRICS = {
    "bonus_welfare_fund_appropriation": {
        "question_aliases": ("trich lap quy khen thuong",),
        "cell_aliases": ("trich lap tu loi nhuan chua phan phoi", "trich lap quy"),
        "forbidden": ("du phong",),
    }
}


@dataclass(slots=True)
class CountAnswer:
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
            "operation": "COUNT_PERIODS",
            "pandas_query": self.query,
            "answer": self.answer,
            "evidence": self.evidence,
            "trace": self.trace,
        }


def classify_count_predicate(question: str) -> tuple[CountPredicate | None, str | None]:
    """Return a reviewed predicate or an explicit static abstention reason."""

    text = unicodedata.normalize("NFC", question or "").casefold()
    folded = _fold(text)
    if classify_operation(text).op != COUNT_OP or not _COUNT_PERIOD.search(text):
        return None, None
    return parse_positive_evidence_predicate(text, folded=folded)


def parse_positive_evidence_predicate(
    question: str,
    *,
    folded: str | None = None,
) -> tuple[CountPredicate | None, str | None]:
    """Parse a threshold/sign predicate shared by period and entity COUNT."""

    text = unicodedata.normalize("NFC", question or "").casefold()
    folded = folded or _fold(text)
    if _EXISTENCE.search(text):
        return None, "COUNT_EXISTENCE_REQUIRES_NEGATIVE_EVIDENCE"
    match = _THRESHOLD.search(text)
    if match:
        threshold = float(match.group("number").replace(",", "."))
        direction = match.group("direction")
        operator = GT if direction[0] in {"n", "l", "c", "v"} else LT
        unit_text = match.group("unit").strip()
        threshold_unit = None
        if unit_text:
            dimension, scale, _ = scan_unit(unit_text)
            if dimension not in {MONEY, SHARES}:
                return None, "COUNT_THRESHOLD_UNIT_NOT_SUPPORTED"
            threshold_unit = Unit(
                dimension,
                scale,
                "VND" if dimension == MONEY else None,
            )
        return CountPredicate(
            operator,
            threshold,
            threshold_unit,
            metric_id=_match_metric(folded),
        ), None
    if _NEGATIVE.search(text):
        return CountPredicate(LT, 0.0, metric_id=_match_metric(folded)), None
    if _POSITIVE.search(text):
        return CountPredicate(GT, 0.0, metric_id=_match_metric(folded)), None
    return None, "COUNT_PREDICATE_NOT_SUPPORTED"


def answer_count_periods(
    question: str,
    pool: Sequence[CandidateCell],
    frames: dict[str, object],
    *,
    entity: str,
    years: Sequence[int],
    basis: str | None,
    selector: Selector,
    qid: int | None = None,
) -> CountAnswer | None:
    predicate, reason = classify_count_predicate(question)
    if predicate is None and reason is None:
        return None
    result = CountAnswer("OK", qid=qid)
    if predicate is None:
        return _fail(result, "ROUTE", reason or "COUNT_PREDICATE_NOT_SUPPORTED")
    if not years:
        return _fail(result, "ROUTE", "COUNT_REQUIRES_PERIODS")

    operands: list[BoundOperand] = []
    expressions: list[str] = []
    for year in years:
        period_pool = [
            cell
            for cell in pool
            if cell.entity == entity
            and cell.period
            and cell.period[:4] == str(year)
            and (not basis or cell.basis == basis)
            and _metric_cell_allowed(predicate.metric_id, cell)
        ]
        slot = OperandSlot("value", period=str(year), basis=basis, entity=entity)
        cell = selector.pick(slot, period_pool)
        if cell is None:
            return _fail(result, "BIND", f"COUNT_UNBOUND_PERIOD:{year}")
        operand = BoundOperand("value", slot, cell, cell.native_quantity())
        operands.append(operand)

    physical = {(operand.cell.csv_path, operand.cell.row_index) for operand in operands}
    if len(physical) != len(operands):
        return _fail(result, "BIND", "COUNT_DUPLICATE_PERIOD_CELLS")
    result.trace.append(
        {
            "stage": "BIND",
            "status": "OK",
            "operands": [
                {
                    "period": operand.slot.period,
                    "row_path": operand.cell.row_path,
                    "csv_path": operand.cell.csv_path,
                    "row_index": operand.cell.row_index,
                }
                for operand in operands
            ],
        }
    )
    if predicate.metric_id is None and not same_metric(operands):
        return _fail(result, "POLICY", "COUNT_CROSS_PERIOD_METRIC_DRIFT")

    for operand in operands:
        target = predicate.threshold_unit or operand.quantity.unit
        factor = query_factor(
            operand.quantity.unit,
            target,
            operand.cell.storage_exponent,
        )
        if not factor.ok or factor.factor is None:
            return _fail(result, "RENDER", f"COUNT_UNIT_ABSTAIN:{factor.reason}")
        value = cell_expr(operand, factor.factor)
        symbol = ">" if predicate.operator == GT else "<"
        expressions.append(f"float({value} {symbol} {predicate.threshold!r})")

    query = "(" + " + ".join(expressions) + ")"
    used_frames = {operand.cell.df_var: frames[operand.cell.df_var] for operand in operands}
    answer, error = execute(query, used_frames)
    if error or answer is None:
        return _fail(result, "EXECUTE", error or "COUNT_EXECUTION_FAILED")
    if not math.isfinite(answer) or answer < 0 or answer > len(years) or answer != int(answer):
        return _fail(result, "VALIDATE", "COUNT_RESULT_INVALID")

    result.query = query
    result.answer = answer
    seen: set[str] = set()
    for operand in operands:
        if operand.cell.df_var not in seen:
            seen.add(operand.cell.df_var)
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


def _fail(result: CountAnswer, stage: str, reason: str) -> CountAnswer:
    result.status = "ABSTAIN"
    result.stage_failed = stage
    result.reason = reason
    result.trace.append({"stage": stage, "status": "ABSTAIN", "reason": reason})
    return result


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    plain = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", plain.replace("đ", "d")).strip()


def _match_metric(question: str) -> str | None:
    for metric_id, policy in _COUNT_METRICS.items():
        if any(alias in question for alias in policy["question_aliases"]):
            return metric_id
    return None


def _metric_cell_allowed(metric_id: str | None, cell: CandidateCell) -> bool:
    if metric_id is None:
        return True
    policy = _COUNT_METRICS[metric_id]
    leaf = _fold(cell.row_path.rsplit("›", 1)[-1])
    if any(value in leaf for value in policy["forbidden"]):
        return False
    return any(leaf.startswith(alias) for alias in policy["cell_aliases"])
