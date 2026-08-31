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

from .binding import BindingResult, BoundOperand, CandidateCell, Selector, bind, bind_ranked
from .frame import QuestionSemanticFrame, parse_question
from .ir import OperationIR
from .render import render
from .router import route
from .units import Unit
from .validate import ValidationResult, validate, validate_operand_identity
from .policy import CROSS_BASIS_OPERANDS, CROSS_PERIOD_METRIC_DRIFT, check_operand_policies

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
                    resolved_entity: Optional[str] = None,
                    max_bind_attempts: int = 1) -> PipelineResult:
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

    active_selector = selector or Selector()
    bindings = (
        (bind(rr.ir, pool, selector=active_selector),)
        if max_bind_attempts == 1
        else bind_ranked(
            rr.ir,
            pool,
            selector=active_selector,
            max_bindings=max_bind_attempts,
        )
    )
    for attempt, br in enumerate(bindings, start=1):
        res.operands = br.operands
        res.query = None
        res.answer = None
        res.validation = None
        bind_trace = {
            "stage": "BIND",
            "status": br.status,
            "reason": br.reason,
            "bound": [operand.role for operand in br.operands],
            "unbound": br.unbound_roles,
        }
        if max_bind_attempts > 1:
            bind_trace["attempt"] = attempt
            bind_trace["max_attempts"] = max_bind_attempts
        res.trace.append(bind_trace)
        if not br.ok:
            res.status, res.stage_failed, res.reason = "ABSTAIN", "BIND", br.reason
            return res

        identity = validate_operand_identity(rr.ir, br.operands)
        if not identity.ok:
            reason = ";".join(identity.reasons)
            res.validation = identity
            res.trace.append(
                {"stage": "VALIDATE", "status": identity.verdict, "reason": reason}
            )
            res.status, res.stage_failed, res.reason = "REJECT", "VALIDATE", reason
            return res

        # -- RENDER (Unit Contract lives here)
        rd = render(rr.ir, br.operands)
        res.trace.append({"stage": "RENDER", "status": rd.status, "reason": rd.reason,
                          "factors": rd.per_operand_factor})
        if not rd.ok:
            if _try_next_binding(res, bindings, attempt, "RENDER", rd.reason):
                continue
            res.status, res.stage_failed, res.reason = "ABSTAIN", "RENDER", rd.reason
            return res
        res.query = rd.query

        # -- POLICY (before EXECUTE: a zero denominator must be a declared reason
        #    code, not a ZeroDivisionError caught by a generic except)
        pol = check_operand_policies(rr.ir, br.operands)
        res.trace.append({"stage": "POLICY", "status": pol.status, "reason": pol.reason})
        if not pol.ok:
            if _try_next_binding(res, bindings, attempt, "POLICY", pol.reason):
                continue
            res.status, res.stage_failed, res.reason = "ABSTAIN", "POLICY", pol.reason
            return res

        # -- EXECUTE
        assert rd.query is not None
        value, err = execute(rd.query, frames)
        res.trace.append({"stage": "EXECUTE", "status": "OK" if err is None else "ERROR",
                          "reason": err})
        if err is not None:
            res.status, res.stage_failed, res.reason = "ABSTAIN", "EXECUTE", err
            return res

        # -- VALIDATE
        vr = validate(rr.ir, br.operands, value)
        res.validation = vr
        res.trace.append({"stage": "VALIDATE", "status": vr.verdict,
                          "reason": ";".join(vr.reasons)})
        if not vr.ok:
            reason = ";".join(vr.reasons)
            if _try_next_binding(res, bindings, attempt, "VALIDATE", reason):
                continue
            res.status = "REJECT" if vr.verdict == "REJECT" else "ABSTAIN"
            res.stage_failed, res.reason = "VALIDATE", reason
            return res
        res.answer = value

        # -- EVIDENCE
        res.evidence = build_evidence(br.operands)
        res.trace.append({"stage": "EVIDENCE", "status": "OK",
                          "n_dataframes": len(res.evidence)})
        return res
    return res


def _try_next_binding(
    result: PipelineResult,
    bindings: Sequence[BindingResult],
    attempt: int,
    stage: str,
    reason: str | None,
) -> bool:
    if attempt >= len(bindings) or not _rebindable(stage, reason):
        return False
    result.trace.append(
        {
            "stage": "REBIND",
            "from_attempt": attempt,
            "next_attempt": attempt + 1,
            "trigger_stage": stage,
            "trigger_reason": reason,
        }
    )
    return True


def _rebindable(stage: str, reason: str | None) -> bool:
    if stage in {"RENDER", "VALIDATE"}:
        return True
    return stage == "POLICY" and reason in {
        CROSS_BASIS_OPERANDS,
        CROSS_PERIOD_METRIC_DRIFT,
    }
