"""Corpus-grounded N-best semantic program synthesis and verification."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
import json
from typing import Protocol

from text2pandas.application.binding import BoundExecutionPlan, JointBinder
from text2pandas.application.evidence_output import compose_relevant_tables
from text2pandas.application.execution import PandasProgram, TypedExecutor, compile_pandas
from text2pandas.application.parsing import ParseCandidate, SemanticParser
from text2pandas.application.planning import PlanningError, compile_execution_plan
from text2pandas.application.retrieval import (
    CandidateBatch,
    OperandRetriever,
    rank_candidate_tables,
    retrieve_operands,
)
from text2pandas.application.verification import ProgramVerifier, answers_match

SEMANTIC_V4_VERSION = "corpus-grounded-program-synthesis-v1"
CONFIDENCE_STATUS = "UNCALIBRATED_NO_SEALED_GOLD"


class ReplayPort(Protocol):
    def replay(self, program: PandasProgram, bound_plan: BoundExecutionPlan) -> float: ...


@dataclass(frozen=True, slots=True)
class SemanticV4Config:
    max_parse_candidates: int = 8
    max_binding_candidates: int = 8
    minimum_confidence: float = 0.62
    disagreement_margin: float = 0.2
    require_answer_consensus: bool = False
    maximum_relevant_tables: int = 10
    infer_observation_roles: bool = False
    require_selection_key_consensus: bool = False

    def __post_init__(self) -> None:
        if self.max_parse_candidates < 1 or self.max_binding_candidates < 1:
            raise ValueError("candidate limits must be positive")
        if not 0.0 <= self.minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be in [0, 1]")
        if self.disagreement_margin < 0.0:
            raise ValueError("disagreement_margin must be non-negative")
        if self.maximum_relevant_tables < 1:
            raise ValueError("maximum_relevant_tables must be positive")


@dataclass(frozen=True, slots=True)
class ProgramAlternative:
    parse_candidate_id: str
    answer: Decimal | str
    query: str
    joint_score: float
    binding_score: float
    binding_margin: float | None
    verifier_score: float
    relevant_tables: tuple[str, ...]
    relevant_documents: tuple[str, ...]
    evidence: tuple[Mapping[str, object], ...]
    ast: Mapping[str, object]
    plan_fingerprint: str
    ontology_fingerprint: str
    trace: tuple[dict[str, object], ...]
    selection_signatures: tuple[str, ...] = ()

    def summary(self) -> dict[str, object]:
        return {
            "parse_candidate_id": self.parse_candidate_id,
            "answer": str(self.answer) if isinstance(self.answer, Decimal) else self.answer,
            "joint_score": self.joint_score,
            "binding_score": self.binding_score,
            "binding_margin": self.binding_margin,
            "verifier_score": self.verifier_score,
            "relevant_tables": list(self.relevant_tables),
            "plan_fingerprint": self.plan_fingerprint,
            "selection_signatures": list(self.selection_signatures),
        }


@dataclass(frozen=True, slots=True)
class SemanticV4Result:
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
    confidence: float | None = None
    confidence_status: str = CONFIDENCE_STATUS
    consensus_size: int = 0
    successful_candidates: int = 0
    selected_parse_candidate_id: str | None = None
    candidate_tables: tuple[str, ...] = ()
    alternatives: tuple[Mapping[str, object], ...] = ()
    failure_counts: Mapping[str, int] = field(default_factory=dict)
    trace: tuple[dict[str, object], ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status == "OK"

    def to_dict(self) -> dict[str, object]:
        return {
            "semantic_schema_version": 4,
            "semantic_engine_version": SEMANTIC_V4_VERSION,
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
            "confidence": self.confidence,
            "confidence_status": self.confidence_status,
            "consensus_size": self.consensus_size,
            "successful_candidates": self.successful_candidates,
            "selected_parse_candidate_id": self.selected_parse_candidate_id,
            "candidate_tables": list(self.candidate_tables),
            "alternatives": [dict(item) for item in self.alternatives],
            "failure_counts": dict(self.failure_counts),
            "trace": list(self.trace),
        }


class SemanticV4Engine:
    def __init__(
        self,
        parser: SemanticParser,
        retriever: OperandRetriever,
        replay: ReplayPort,
        *,
        binder: JointBinder | None = None,
        executor: TypedExecutor | None = None,
        verifier: ProgramVerifier | None = None,
        config: SemanticV4Config | None = None,
    ) -> None:
        self.parser = parser
        self.retriever = retriever
        self.replay = replay
        self.binder = binder or JointBinder()
        self.executor = executor or TypedExecutor()
        self.verifier = verifier or ProgramVerifier()
        self.config = config or SemanticV4Config()

    def answer(self, question: str, *, qid: int | None = None) -> SemanticV4Result:
        parse_candidates = self.parser.parse_candidates(
            question,
            qid=qid,
            max_candidates=self.config.max_parse_candidates,
        )
        failures: Counter[str] = Counter()
        alternatives: list[ProgramAlternative] = []
        all_batches: dict[str, CandidateBatch] = {}
        search_trace: list[dict[str, object]] = [
            {
                "stage": "V4_PARSE_CANDIDATES",
                "count": len(parse_candidates),
                "candidate_ids": [value.candidate_id for value in parse_candidates],
            }
        ]
        maximum_operands = 1
        for parsed in parse_candidates:
            result = parsed.result
            if not result.ok or result.ast is None:
                failures[f"PARSE:{result.reason or 'PARSE_FAILED'}"] += 1
                continue
            try:
                plan = compile_execution_plan(
                    result.ast,
                    self.parser.ontology,
                    infer_observation_roles=self.config.infer_observation_roles,
                )
            except PlanningError as error:
                failures[f"PLAN:{error}"] += 1
                continue
            maximum_operands = max(maximum_operands, len(plan.requests))
            batches = retrieve_operands(plan, self.retriever)
            for request_id, batch in batches.items():
                all_batches[f"{parsed.candidate_id}:{request_id}"] = batch
            binding = self.binder.bind_candidates(
                plan,
                batches,
                limit=self.config.max_binding_candidates,
            )
            if not binding.ok:
                failures[f"BIND:{binding.reason or 'BIND_FAILED'}"] += 1
                continue
            for bound_plan in binding.candidates:
                alternative, failure = self._execute_candidate(parsed, bound_plan)
                if alternative is None:
                    failures[failure or "EXECUTE:UNKNOWN"] += 1
                else:
                    alternatives.append(alternative)

        candidate_tables = rank_candidate_tables(
            all_batches,
            limit=self.config.maximum_relevant_tables,
        )
        if not alternatives:
            return SemanticV4Result(
                qid=qid,
                status="ABSTAIN",
                stage_failed="JOINT_SEARCH",
                reason="NO_VERIFIED_PROGRAM",
                relevant_tables=candidate_tables,
                candidate_tables=candidate_tables,
                failure_counts=dict(sorted(failures.items())),
                trace=tuple(search_trace),
            )
        groups = _answer_groups(alternatives)
        ranked_groups = sorted(groups, key=_group_sort_key)
        winning_group = ranked_groups[0]
        selected = max(winning_group, key=_alternative_sort_key)
        if (
            self.config.require_selection_key_consensus
            and _selection_signatures_disagree(alternatives)
        ):
            return self._abstain_after_search(
                qid,
                "SELECTED_KEY_DISAGREEMENT",
                alternatives,
                candidate_tables,
                failures,
                search_trace,
            )
        if self.config.require_answer_consensus and len(ranked_groups) > 1:
            return self._abstain_after_search(
                qid,
                "SEMANTIC_CANDIDATE_DISAGREEMENT",
                alternatives,
                candidate_tables,
                failures,
                search_trace,
            )
        competing_score = (
            max(value.joint_score for value in ranked_groups[1])
            if len(ranked_groups) > 1
            else None
        )
        if (
            competing_score is not None
            and selected.joint_score - competing_score < self.config.disagreement_margin
        ):
            return self._abstain_after_search(
                qid,
                "ANSWER_DISAGREEMENT",
                alternatives,
                candidate_tables,
                failures,
                search_trace,
            )
        confidence = _confidence(selected, len(winning_group), len(alternatives))
        if confidence < self.config.minimum_confidence:
            return self._abstain_after_search(
                qid,
                "CONFIDENCE_BELOW_SHADOW_THRESHOLD",
                alternatives,
                candidate_tables,
                failures,
                search_trace,
                confidence=confidence,
                consensus_size=len(winning_group),
            )
        relevant_tables = compose_relevant_tables(
            selected.relevant_tables,
            candidate_tables,
            expected_operands=maximum_operands,
            max_tables=self.config.maximum_relevant_tables,
        )
        search_trace.append(
            {
                "stage": "V4_SELECT_PROGRAM",
                "successful_candidates": len(alternatives),
                "answer_groups": len(groups),
                "consensus_size": len(winning_group),
                "confidence": confidence,
                "confidence_status": CONFIDENCE_STATUS,
            }
        )
        return SemanticV4Result(
            qid=qid,
            status="OK",
            answer=selected.answer,
            query=selected.query,
            relevant_tables=relevant_tables,
            relevant_documents=selected.relevant_documents,
            evidence=selected.evidence,
            ast=selected.ast,
            plan_fingerprint=selected.plan_fingerprint,
            ontology_fingerprint=selected.ontology_fingerprint,
            binding_score=selected.binding_score,
            binding_margin=selected.binding_margin,
            confidence=confidence,
            consensus_size=len(winning_group),
            successful_candidates=len(alternatives),
            selected_parse_candidate_id=selected.parse_candidate_id,
            candidate_tables=candidate_tables,
            alternatives=tuple(value.summary() for value in _top_alternatives(alternatives)),
            failure_counts=dict(sorted(failures.items())),
            trace=(*search_trace, *selected.trace),
        )

    def _execute_candidate(
        self,
        parsed: ParseCandidate,
        bound_plan: BoundExecutionPlan,
    ) -> tuple[ProgramAlternative | None, str | None]:
        typed = self.executor.execute(bound_plan)
        if not typed.ok or typed.answer is None:
            return None, f"TYPED_EXECUTE:{typed.reason or 'FAILED'}"
        compiled = compile_pandas(bound_plan)
        if not compiled.ok or compiled.program is None:
            return None, f"PANDAS_COMPILE:{compiled.reason or 'FAILED'}"
        try:
            replayed = self.replay.replay(compiled.program, bound_plan)
        except Exception as error:  # noqa: BLE001 - infrastructure boundary
            return None, f"PANDAS_REPLAY:{type(error).__name__}:{error}"
        verified = self.verifier.verify(bound_plan, typed, replayed)
        if not verified.ok:
            return None, "VERIFY:" + ",".join(verified.reasons)
        evidence_tables = tuple(item.table_uid for item in compiled.program.evidence)
        documents = tuple(
            dict.fromkeys(item.document_id for item in compiled.program.evidence)
        )
        evidence = tuple(
            {
                "variable": item.variable,
                "table_uid": item.table_uid,
                "document_id": item.document_id,
                "observation_uids": list(item.observation_uids),
            }
            for item in compiled.program.evidence
        )
        average_binding = bound_plan.total_score / max(1, len(bound_plan.operands))
        margin_bonus = min(1.0, max(0.0, (bound_plan.score_margin or 0.0) / 2.0))
        joint_score = (
            2.0 * parsed.semantic_score
            + 2.0 * verified.score
            + min(1.0, max(0.0, average_binding / 35.0))
            + 0.5 * margin_bonus
        )
        return (
            ProgramAlternative(
                parsed.candidate_id,
                typed.answer,
                compiled.program.query,
                joint_score,
                bound_plan.total_score,
                bound_plan.score_margin,
                verified.score,
                evidence_tables,
                documents,
                evidence,
                bound_plan.plan.ast.to_dict(),
                bound_plan.plan.fingerprint,
                bound_plan.plan.ontology_fingerprint,
                (*parsed.result.trace, *typed.trace, *compiled.trace, *verified.trace),
                _canonical_selection_signatures(typed.trace),
            ),
            None,
        )

    def _abstain_after_search(
        self,
        qid: int | None,
        reason: str,
        alternatives: list[ProgramAlternative],
        candidate_tables: tuple[str, ...],
        failures: Counter[str],
        trace: list[dict[str, object]],
        *,
        confidence: float | None = None,
        consensus_size: int = 0,
    ) -> SemanticV4Result:
        return SemanticV4Result(
            qid=qid,
            status="ABSTAIN",
            stage_failed="VERIFY_AND_SELECT",
            reason=reason,
            relevant_tables=candidate_tables,
            confidence=confidence,
            consensus_size=consensus_size,
            successful_candidates=len(alternatives),
            candidate_tables=candidate_tables,
            alternatives=tuple(value.summary() for value in _top_alternatives(alternatives)),
            failure_counts=dict(sorted(failures.items())),
            trace=tuple(trace),
        )


def _answer_groups(
    alternatives: list[ProgramAlternative],
) -> list[list[ProgramAlternative]]:
    groups: list[list[ProgramAlternative]] = []
    for alternative in sorted(alternatives, key=_alternative_sort_key, reverse=True):
        for group in groups:
            if _answers_equivalent(group[0].answer, alternative.answer):
                group.append(alternative)
                break
        else:
            groups.append([alternative])
    return groups


def _answers_equivalent(left: Decimal | str, right: Decimal | str) -> bool:
    if isinstance(left, Decimal) and isinstance(right, Decimal):
        return answers_match(left, float(right))
    return str(left) == str(right)


def _canonical_selection_signatures(
    trace: tuple[dict[str, object], ...],
) -> tuple[str, ...]:
    output: list[str] = []
    for item in trace:
        raw = item.get("selection_signatures")
        if not isinstance(raw, list):
            continue
        for signature in raw:
            if isinstance(signature, Mapping):
                output.append(
                    json.dumps(
                        dict(signature),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
    return tuple(sorted(output))


def _selection_signatures_disagree(
    alternatives: list[ProgramAlternative],
) -> bool:
    signatures = {alternative.selection_signatures for alternative in alternatives}
    return any(signatures) and len(signatures) != 1


def _alternative_sort_key(value: ProgramAlternative) -> tuple[float, float, str]:
    return value.joint_score, value.binding_score, value.parse_candidate_id


def _group_sort_key(
    group: list[ProgramAlternative],
) -> tuple[float, float, str]:
    best = max(group, key=_alternative_sort_key)
    return -best.joint_score, -len(group), str(best.answer)


def _confidence(
    selected: ProgramAlternative,
    consensus_size: int,
    successful_candidates: int,
) -> float:
    agreement = consensus_size / max(1, successful_candidates)
    margin = (
        0.75
        if selected.binding_margin is None
        else min(1.0, max(0.0, selected.binding_margin / 2.0))
    )
    semantic = min(1.0, max(0.0, (selected.joint_score - 2.0) / 3.5))
    return min(
        1.0,
        max(
            0.0,
            0.35 * agreement + 0.25 * selected.verifier_score + 0.2 * margin + 0.2 * semantic,
        ),
    )


def _top_alternatives(
    alternatives: list[ProgramAlternative],
    limit: int = 12,
) -> tuple[ProgramAlternative, ...]:
    return tuple(sorted(alternatives, key=_alternative_sort_key, reverse=True)[:limit])
