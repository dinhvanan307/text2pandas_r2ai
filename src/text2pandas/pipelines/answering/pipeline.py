"""End-to-end orchestration.

    question + candidate cells
        -> QuestionSemanticFrame
        -> OperationIR
        -> BoundOperand[]
        -> Unit Contract
        -> pandas query
        -> execution
        -> Answer Validator
        -> Evidence

Every stage returns a status and a reason code, and the trace records all of
them, so "why is this answer wrong" is answered by reading one record instead
of guessing from the final number.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from text2pandas.infrastructure.sandbox.query import (
    QuerySafetyError,
    execute_query,
    validate_query,
)

from .binding import BindingResult, BoundOperand, CandidateCell, Selector, bind
from .frame import QuestionSemanticFrame, parse_question
from .ir import OperationIR
from .render import RenderResult, render
from .router import route
from .units import Unit
from .validate import PASS, ValidationResult, validate
from .policy import check_operand_policies

STAGES = ("FRAME", "ROUTE", "BIND", "RENDER", "POLICY", "EXECUTE",
          "VALIDATE", "EVIDENCE")


@dataclass
class PipelineResult:
    qid: Optional[int]
    status: str                                   # OK | ABSTAIN | REJECT
    stage_failed: Optional[str] = None
    reason: Optional[str] = None
    frame: Optional[QuestionSemanticFrame] = None
    ir: Optional[OperationIR] = None
    operands: list[BoundOperand] = field(default_factory=list)
    query: Optional[str] = None
    answer: Optional[float] = None
    validation: Optional[ValidationResult] = None
    evidence: list[dict] = field(default_factory=list)
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
            "frame": self.frame.to_dict() if self.frame else None,
            "operation": self.ir.op if self.ir else None,
            "output_unit": self.ir.output_unit.describe() if self.ir else None,
            "operands": [o.to_dict() for o in self.operands],
            "pandas_query": self.query,
            "answer": self.answer,
            "validation": {
                "verdict": self.validation.verdict,
                "reasons": self.validation.reasons,
            } if self.validation else None,
            "evidence": self.evidence,
            "trace": self.trace,
        }


def build_evidence(operands: Sequence[BoundOperand]) -> list[dict]:
    """Evidence must name every dataframe the query references -- all of them.

    Order is first-reference order and duplicates collapse, so evidence is a
    deterministic function of the bound operands.
    """
    seen: dict[str, dict] = {}
    for o in operands:
        key = o.cell.df_var
        if key not in seen:
            seen[key] = {"variable": o.cell.df_var, "csv_path": o.cell.csv_path}
    return list(seen.values())


def execute(query: str, frames: dict) -> tuple[Optional[float], Optional[str]]:
    """Evaluate the emitted expression against the supplied dataframes.

    The namespace contains only the dataframes and a tiny numeric allowlist --
    no builtins, no imports.
    """
    try:
        contract = validate_query(query, set(frames), require_all_evidence=False)
        used_frames = {name: frames[name] for name in contract.dataframe_variables}
        value = execute_query(query, used_frames)
    except QuerySafetyError as exc:
        return None, f"EXECUTION_ERROR:{type(exc).__name__}:{exc}"
    except Exception as exc:  # pragma: no cover - defensive runtime boundary
        return None, f"EXECUTION_ERROR:{type(exc).__name__}:{exc}"
    return value, None


def answer_question(question: str,
                    pool: Sequence[CandidateCell],
                    frames: dict,
                    qid: Optional[int] = None,
                    metric_id: Optional[str] = None,
                    requested_unit: Optional[Unit] = None,
                    selector: Optional[Selector] = None,
                    resolved_entity: Optional[str] = None) -> PipelineResult:
    """Run every stage. Abstains loudly instead of guessing at any point."""
    res = PipelineResult(qid=qid, status="OK")

    # -- FRAME
    frame = parse_question(question, qid=qid, metric_id=metric_id,
                           requested_unit=requested_unit,
                           resolved_entity=resolved_entity)
    res.frame = frame
    res.trace.append({"stage": "FRAME", "status": "OK",
                      "operation": frame.operation.op,
                      "missing": list(frame.missing)})

    # -- ROUTE
    rr = route(frame)
    res.trace.append({"stage": "ROUTE", "status": rr.status, "reason": rr.reason})
    if not rr.ok:
        res.status, res.stage_failed, res.reason = "ABSTAIN", "ROUTE", rr.reason
        return res
    res.ir = rr.ir

    # -- BIND
    br = bind(rr.ir, pool, selector=selector)
    res.operands = br.operands
    res.trace.append({"stage": "BIND", "status": br.status, "reason": br.reason,
                      "bound": [o.role for o in br.operands],
                      "unbound": br.unbound_roles})
    if not br.ok:
        res.status, res.stage_failed, res.reason = "ABSTAIN", "BIND", br.reason
        return res

    # -- RENDER (Unit Contract lives here)
    rd = render(rr.ir, br.operands)
    res.trace.append({"stage": "RENDER", "status": rd.status, "reason": rd.reason,
                      "factors": rd.per_operand_factor})
    if not rd.ok:
        res.status, res.stage_failed, res.reason = "ABSTAIN", "RENDER", rd.reason
        return res
    res.query = rd.query

    # -- POLICY (before EXECUTE: a zero denominator must be a declared reason
    #    code, not a ZeroDivisionError caught by a generic except)
    pol = check_operand_policies(rr.ir, br.operands)
    res.trace.append({"stage": "POLICY", "status": pol.status, "reason": pol.reason})
    if not pol.ok:
        res.status, res.stage_failed, res.reason = "ABSTAIN", "POLICY", pol.reason
        return res

    # -- EXECUTE
    value, err = execute(rd.query, frames)
    res.trace.append({"stage": "EXECUTE", "status": "OK" if err is None else "ERROR",
                      "reason": err})
    if err is not None:
        res.status, res.stage_failed, res.reason = "ABSTAIN", "EXECUTE", err
        return res

    # -- VALIDATE
    vr = validate(rr.ir, br.operands, value)
    res.validation = vr
    res.trace.append({"stage": "VALIDATE", "status": vr.verdict, "reason": ";".join(vr.reasons)})
    if not vr.ok:
        res.status = "REJECT" if vr.verdict == "REJECT" else "ABSTAIN"
        res.stage_failed, res.reason = "VALIDATE", ";".join(vr.reasons)
        return res
    res.answer = value

    # -- EVIDENCE
    res.evidence = build_evidence(br.operands)
    res.trace.append({"stage": "EVIDENCE", "status": "OK",
                      "n_dataframes": len(res.evidence)})
    return res
