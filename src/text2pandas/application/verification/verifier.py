"""Fail-closed verifier for one grounded semantic program execution."""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation

from text2pandas.application.binding import BoundExecutionPlan
from text2pandas.application.execution import ExecutionResult
from text2pandas.application.retrieval import ObservationCandidate
from text2pandas.domain.semantic import Basis, Dimension

from .contracts import VerificationPolicy, VerificationResult
from .family_completeness import validate_family_completeness


class ProgramVerifier:
    def __init__(self, policy: VerificationPolicy | None = None) -> None:
        self.policy = policy or VerificationPolicy()

    def verify(
        self,
        bound_plan: BoundExecutionPlan,
        typed: ExecutionResult,
        replayed: float,
    ) -> VerificationResult:
        hard_failures: list[str] = []
        warnings: list[str] = []
        if not typed.ok or typed.answer is None:
            hard_failures.append("TYPED_EXECUTION_NOT_OK")
        elif not answer_is_finite(typed.answer):
            hard_failures.append("ANSWER_NON_FINITE")
        if not math.isfinite(replayed):
            hard_failures.append("REPLAY_NON_FINITE")
        elif typed.answer is not None and not answers_match(typed.answer, replayed):
            hard_failures.append("TYPED_PANDAS_MISMATCH")

        observation_uids: dict[str, tuple[str, str | None, str | None]] = {}
        for request_id, operand in sorted(bound_plan.operands.items()):
            request = operand.request
            candidate = operand.candidate
            semantic_fact = (request.metric_id, request.entity, request.period)
            previous_fact = observation_uids.get(candidate.observation_uid)
            if previous_fact is not None and previous_fact != semantic_fact:
                hard_failures.append(f"DUPLICATE_OBSERVATION:{request_id}")
            observation_uids[candidate.observation_uid] = semantic_fact
            if request.entity and candidate.entity != request.entity:
                hard_failures.append(f"ENTITY_SCOPE_MISMATCH:{request_id}")
            if request.period and not _period_matches(request.period, candidate.period):
                hard_failures.append(f"PERIOD_SCOPE_MISMATCH:{request_id}")
            if request.basis != Basis.UNSPECIFIED and candidate.basis != request.basis:
                hard_failures.append(f"BASIS_SCOPE_MISMATCH:{request_id}")
            if not _dimension_matches(
                request.expected_unit.dimension,
                candidate.unit.dimension,
            ):
                hard_failures.append(f"UNIT_DIMENSION_MISMATCH:{request_id}")
            if candidate.metric_id != request.metric_id:
                hard_failures.append(f"METRIC_ID_MISMATCH:{request_id}")
            if candidate.is_restated:
                warnings.append(f"RESTATED_EVIDENCE:{request_id}")
            if candidate.row_uid is None or candidate.column_uid is None:
                warnings.append(f"PHYSICAL_ID_INCOMPLETE:{request_id}")
            self._verify_readiness(request_id, candidate, hard_failures, warnings)

        family_trace: dict[str, object] = {"family": "disabled"}
        if self.policy.enforce_family_completeness:
            family = validate_family_completeness(bound_plan)
            hard_failures.extend(family.failures)
            family_trace = {
                "family": family.family,
                "expected_members": list(family.expected_members),
                "bound_members": list(family.bound_members),
                "failures": list(family.failures),
            }

        score = max(0.0, 1.0 - 0.04 * len(warnings) - 0.25 * len(hard_failures))
        status = "OK" if not hard_failures else "ABSTAIN"
        reasons = (*hard_failures, *warnings)
        return VerificationResult(
            status,
            score,
            reasons,
            (
                {
                    "stage": "PROGRAM_VERIFY",
                    "status": status,
                    "score": score,
                    "hard_failures": hard_failures,
                    "warnings": warnings,
                    "evidence_count": len(bound_plan.operands),
                    "family_completeness": family_trace,
                },
            ),
        )

    def _verify_readiness(
        self,
        request_id: str,
        candidate: ObservationCandidate,
        hard_failures: list[str],
        warnings: list[str],
    ) -> None:
        if candidate.readiness == "ready" and candidate.collision_class is None:
            return
        if not self.policy.allow_recoverable_collisions:
            hard_failures.append(f"EVIDENCE_NOT_EXECUTION_READY:{request_id}")
            return
        if candidate.readiness != "recoverable":
            hard_failures.append(f"EVIDENCE_READINESS_UNKNOWN:{request_id}")
            return
        if candidate.collision_class not in self.policy.recoverable_collision_classes:
            hard_failures.append(f"COLLISION_CLASS_BLOCKED:{request_id}")
            return
        confidence = candidate.source_confidence
        if confidence is None or confidence < self.policy.minimum_recoverable_confidence:
            hard_failures.append(f"RECOVERABLE_CONFIDENCE_LOW:{request_id}")
            return
        warnings.append(f"RECOVERABLE_EVIDENCE:{request_id}")


def answers_match(typed: Decimal | str, replayed: float) -> bool:
    if not math.isfinite(replayed):
        return False
    try:
        expected = Decimal(str(typed))
        actual = Decimal(str(replayed))
    except (InvalidOperation, ValueError):
        return str(typed) == str(replayed)
    if not expected.is_finite() or not actual.is_finite():
        return False
    tolerance = Decimal("1e-9") * max(Decimal(1), abs(expected))
    return abs(actual - expected) <= tolerance


def answer_is_finite(answer: Decimal | str) -> bool:
    try:
        return Decimal(str(answer)).is_finite()
    except InvalidOperation:
        return bool(str(answer).strip())


def _period_matches(requested: str, actual: str | None) -> bool:
    if actual is None:
        return False
    return actual.startswith(requested) if len(requested) == 4 else actual == requested


def _dimension_matches(expected: Dimension, actual: Dimension) -> bool:
    if expected == Dimension.UNKNOWN:
        return actual != Dimension.UNKNOWN
    return expected == actual or {expected, actual} == {Dimension.PERCENT, Dimension.RATIO}
