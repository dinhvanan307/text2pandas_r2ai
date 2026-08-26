"""Explicit promotion gate for replacing the canonical V2 runtime."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    policy_id: str
    required_full_questions: int
    minimum_semantic_gold_records: int
    minimum_evidence_gold_records: int
    minimum_parser_ast_exact: float
    minimum_candidate_recall: float
    minimum_binding_exact: float
    minimum_answer_accuracy: float
    maximum_replay_mismatches: int
    maximum_submission_errors: int


@dataclass(frozen=True, slots=True)
class PromotionMetrics:
    questions: int
    semantic_gold_records: int | None = None
    evidence_gold_records: int | None = None
    parser_ast_exact: float | None = None
    candidate_recall: float | None = None
    binding_exact: float | None = None
    answer_accuracy: float | None = None
    replay_mismatches: int | None = None
    submission_errors: int | None = None


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    status: str
    policy_id: str
    blockers: tuple[str, ...]

    @property
    def promotable(self) -> bool:
        return self.status == "PROMOTABLE"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "policy_id": self.policy_id,
            "blockers": list(self.blockers),
        }


def evaluate_promotion(
    metrics: PromotionMetrics, policy: PromotionPolicy
) -> PromotionDecision:
    blockers: list[str] = []
    if metrics.questions != policy.required_full_questions:
        blockers.append(
            f"QUESTION_COVERAGE:{metrics.questions}:{policy.required_full_questions}"
        )
    _minimum(
        blockers,
        "SEMANTIC_GOLD_RECORDS",
        metrics.semantic_gold_records,
        policy.minimum_semantic_gold_records,
    )
    _minimum(
        blockers,
        "EVIDENCE_GOLD_RECORDS",
        metrics.evidence_gold_records,
        policy.minimum_evidence_gold_records,
    )
    _minimum(
        blockers,
        "PARSER_AST_EXACT",
        metrics.parser_ast_exact,
        policy.minimum_parser_ast_exact,
    )
    _minimum(
        blockers,
        "CANDIDATE_RECALL",
        metrics.candidate_recall,
        policy.minimum_candidate_recall,
    )
    _minimum(
        blockers,
        "BINDING_EXACT",
        metrics.binding_exact,
        policy.minimum_binding_exact,
    )
    _minimum(
        blockers,
        "ANSWER_ACCURACY",
        metrics.answer_accuracy,
        policy.minimum_answer_accuracy,
    )
    _maximum(
        blockers,
        "REPLAY_MISMATCHES",
        metrics.replay_mismatches,
        policy.maximum_replay_mismatches,
    )
    _maximum(
        blockers,
        "SUBMISSION_ERRORS",
        metrics.submission_errors,
        policy.maximum_submission_errors,
    )
    return PromotionDecision(
        "BLOCKED" if blockers else "PROMOTABLE",
        policy.policy_id,
        tuple(blockers),
    )


def _minimum(
    blockers: list[str],
    name: str,
    actual: float | None,
    required: float,
) -> None:
    if actual is None:
        blockers.append(f"NOT_MEASURED:{name}")
    elif actual < required:
        blockers.append(f"BELOW_MINIMUM:{name}:{actual}:{required}")


def _maximum(
    blockers: list[str],
    name: str,
    actual: float | None,
    allowed: float,
) -> None:
    if actual is None:
        blockers.append(f"NOT_MEASURED:{name}")
    elif actual > allowed:
        blockers.append(f"ABOVE_MAXIMUM:{name}:{actual}:{allowed}")
