"""Fail-closed orchestration for the shadow Semantic Query Engine v3."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from text2pandas.application.binding import BoundExecutionPlan, JointBinder
from text2pandas.application.execution import PandasProgram, TypedExecutor, compile_pandas
from text2pandas.application.parsing import SemanticParser
from text2pandas.application.planning import PlanningError, compile_execution_plan
from text2pandas.application.retrieval import OperandRetriever, retrieve_operands


class ReplayPort(Protocol):
    def replay(self, program: PandasProgram, bound_plan: BoundExecutionPlan) -> float: ...


@dataclass(frozen=True, slots=True)
class SemanticV3Result:
    qid: int | None
    status: str
    stage_failed: str | None = None
    reason: str | None = None
    answer: Decimal | str | None = None
    query: str | None = None
    relevant_tables: tuple[str, ...] = ()
    relevant_documents: tuple[str, ...] = ()
    evidence: tuple[Mapping[str, object], ...] = ()
    ast: Mapping[str, object] | None = None
    plan_fingerprint: str | None = None
    ontology_fingerprint: str | None = None
    binding_score: float | None = None
    binding_margin: float | None = None
    trace: tuple[dict[str, object], ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status == "OK"

    def to_dict(self) -> dict[str, object]:
        return {
            "semantic_schema_version": 3,
            "qid": self.qid,
            "status": self.status,
            "stage_failed": self.stage_failed,
            "reason": self.reason,
            "answer": str(self.answer) if isinstance(self.answer, Decimal) else self.answer,
            "pandas_query": self.query,
            "relevant_tables": list(self.relevant_tables),
            "relevant_documents": list(self.relevant_documents),
            "evidence": [dict(item) for item in self.evidence],
            "ast": dict(self.ast) if self.ast else None,
            "plan_fingerprint": self.plan_fingerprint,
            "ontology_fingerprint": self.ontology_fingerprint,
            "binding_score": self.binding_score,
            "binding_margin": self.binding_margin,
            "trace": list(self.trace),
        }


class SemanticV3Engine:
    def __init__(
        self,
        parser: SemanticParser,
        retriever: OperandRetriever,
        replay: ReplayPort,
        *,
        binder: JointBinder | None = None,
        executor: TypedExecutor | None = None,
    ):
        self.parser = parser
        self.retriever = retriever
        self.replay = replay
        self.binder = binder or JointBinder()
        self.executor = executor or TypedExecutor()

    def answer(self, question: str, *, qid: int | None = None) -> SemanticV3Result:
        trace: list[dict[str, object]] = []
        parsed = self.parser.parse(question, qid=qid)
        trace.extend(parsed.trace)
        if not parsed.ok or parsed.ast is None:
            return _failed(qid, "PARSE", parsed.reason or "PARSE_FAILED", trace)
        try:
            plan = compile_execution_plan(parsed.ast, self.parser.ontology)
        except PlanningError as error:
            return _failed(qid, "PLAN", str(error), trace, ast=parsed.ast.to_dict())
        trace.append(
            {
                "stage": "PLAN",
                "requests": len(plan.requests),
                "constraints": len(plan.constraints),
                "plan_fingerprint": plan.fingerprint,
            }
        )
        batches = retrieve_operands(plan, self.retriever)
        trace.append(
            {
                "stage": "RETRIEVE_OPERANDS",
                "requests": {
                    request_id: {
                        "candidates": len(batch.candidates),
                        "trace": dict(batch.trace),
                    }
                    for request_id, batch in batches.items()
                },
            }
        )
        binding = self.binder.bind(plan, batches)
        trace.extend(binding.trace)
        if not binding.ok or binding.bound_plan is None:
            return _failed(
                qid,
                "BIND",
                binding.reason or "BIND_FAILED",
                trace,
                ast=parsed.ast.to_dict(),
                plan_fingerprint=plan.fingerprint,
                ontology_fingerprint=plan.ontology_fingerprint,
            )
        typed = self.executor.execute(binding.bound_plan)
        trace.extend(typed.trace)
        if not typed.ok or typed.answer is None:
            return _failed(
                qid,
                "TYPED_EXECUTE",
                typed.reason or "TYPED_EXECUTE_FAILED",
                trace,
                ast=parsed.ast.to_dict(),
                plan_fingerprint=plan.fingerprint,
                ontology_fingerprint=plan.ontology_fingerprint,
            )
        compiled = compile_pandas(binding.bound_plan)
        trace.extend(compiled.trace)
        if not compiled.ok or compiled.program is None:
            return _failed(
                qid,
                "PANDAS_COMPILE",
                compiled.reason or "PANDAS_COMPILE_FAILED",
                trace,
                ast=parsed.ast.to_dict(),
                plan_fingerprint=plan.fingerprint,
                ontology_fingerprint=plan.ontology_fingerprint,
            )
        try:
            replayed = self.replay.replay(compiled.program, binding.bound_plan)
        except Exception as error:  # noqa: BLE001 - infrastructure boundary
            return _failed(
                qid,
                "PANDAS_REPLAY",
                f"{type(error).__name__}:{error}",
                trace,
                ast=parsed.ast.to_dict(),
                plan_fingerprint=plan.fingerprint,
                ontology_fingerprint=plan.ontology_fingerprint,
            )
        if not _matches(typed.answer, replayed):
            return _failed(
                qid,
                "DIFFERENTIAL_VALIDATE",
                f"TYPED_PANDAS_MISMATCH:{typed.answer}:{replayed}",
                trace,
                ast=parsed.ast.to_dict(),
                plan_fingerprint=plan.fingerprint,
                ontology_fingerprint=plan.ontology_fingerprint,
            )
        trace.append({"stage": "PANDAS_REPLAY", "status": "MATCH", "value": replayed})
        tables = tuple(evidence.table_uid for evidence in compiled.program.evidence)
        documents = tuple(dict.fromkeys(evidence.document_id for evidence in compiled.program.evidence))
        evidence = tuple(
            {
                "variable": item.variable,
                "table_uid": item.table_uid,
                "document_id": item.document_id,
                "observation_uids": list(item.observation_uids),
            }
            for item in compiled.program.evidence
        )
        return SemanticV3Result(
            qid=qid,
            status="OK",
            answer=typed.answer,
            query=compiled.program.query,
            relevant_tables=tables,
            relevant_documents=documents,
            evidence=evidence,
            ast=parsed.ast.to_dict(),
            plan_fingerprint=plan.fingerprint,
            ontology_fingerprint=plan.ontology_fingerprint,
            binding_score=binding.bound_plan.total_score,
            binding_margin=binding.bound_plan.score_margin,
            trace=tuple(trace),
        )


def classify_differential(
    legacy: Mapping[str, object] | None, v3: SemanticV3Result
) -> str:
    if legacy is None:
        return "V3_ONLY_MEASUREMENT"
    legacy_ok = legacy.get("status") == "OK" and legacy.get("answer") is not None
    if legacy_ok and v3.ok and v3.answer is not None:
        try:
            matched = _matches(Decimal(str(legacy["answer"])), float(v3.answer))
        except (ValueError, TypeError):
            matched = str(legacy.get("answer")) == str(v3.answer)
        return "BOTH_OK_MATCH" if matched else "BOTH_OK_VALUE_DIFFERENCE"
    if legacy_ok:
        return "LEGACY_ONLY_OK"
    if v3.ok:
        return "V3_ONLY_OK"
    legacy_stage = str(legacy.get("reason") or "UNKNOWN").split(":", 1)[0]
    return "BOTH_ABSTAIN_SAME_STAGE" if legacy_stage == v3.stage_failed else "BOTH_ABSTAIN_DIFFERENT_STAGE"


def _matches(typed: Decimal | str, replayed: float) -> bool:
    if isinstance(typed, str):
        try:
            return Decimal(typed) == Decimal(str(replayed))
        except ArithmeticError:
            return False
    actual = Decimal(str(replayed))
    tolerance = Decimal("1e-9") * max(Decimal(1), abs(typed))
    return abs(actual - typed) <= tolerance


def _failed(
    qid: int | None,
    stage: str,
    reason: str,
    trace: list[dict[str, object]],
    *,
    ast: Mapping[str, object] | None = None,
    plan_fingerprint: str | None = None,
    ontology_fingerprint: str | None = None,
) -> SemanticV3Result:
    return SemanticV3Result(
        qid=qid,
        status="ABSTAIN",
        stage_failed=stage,
        reason=reason,
        ast=ast,
        plan_fingerprint=plan_fingerprint,
        ontology_fingerprint=ontology_fingerprint,
        trace=tuple(trace),
    )
