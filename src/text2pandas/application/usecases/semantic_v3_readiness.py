"""Explicit promotion gate for replacing the canonical V2 runtime."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    policy_id: str
    required_full_questions: int
    minimum_answer_gold_records: int
    minimum_semantic_gold_records: int
    minimum_evidence_gold_records: int
    minimum_parser_ast_exact: float
    minimum_candidate_recall: float
    minimum_binding_exact: float
    minimum_answer_accuracy: float
    minimum_reranker_heldout_records: int
    minimum_reranker_f2_delta: float
    minimum_reranker_f2_delta_ci95_low: float
    minimum_reranker_protected_slice_delta: float
    minimum_submission_replay_records: int
    maximum_replay_mismatches: int
    maximum_submission_errors: int
    require_sealed_evaluation_release: bool


@dataclass(frozen=True, slots=True)
class PromotionMetrics:
    questions: int
    evaluation_release_id: str | None = None
    evaluation_release_sealed: bool | None = None
    answer_gold_records: int | None = None
    semantic_gold_records: int | None = None
    evidence_gold_records: int | None = None
    parser_ast_exact: float | None = None
    candidate_recall: float | None = None
    binding_exact: float | None = None
    answer_accuracy: float | None = None
    reranker_heldout_records: int | None = None
    reranker_f2_delta: float | None = None
    reranker_f2_delta_ci95_low: float | None = None
    reranker_protected_slice_delta: float | None = None
    submission_replay_records: int | None = None
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
    if policy.require_sealed_evaluation_release:
        if metrics.evaluation_release_sealed is None:
            blockers.append("NOT_MEASURED:EVALUATION_RELEASE_SEALED")
        elif not metrics.evaluation_release_sealed:
            blockers.append("UNSEALED:EVALUATION_RELEASE")
        if not metrics.evaluation_release_id:
            blockers.append("NOT_MEASURED:EVALUATION_RELEASE_ID")
    _minimum(
        blockers,
        "ANSWER_GOLD_RECORDS",
        metrics.answer_gold_records,
        policy.minimum_answer_gold_records,
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
    _minimum(
        blockers,
        "RERANKER_HELDOUT_RECORDS",
        metrics.reranker_heldout_records,
        policy.minimum_reranker_heldout_records,
    )
    _minimum(
        blockers,
        "RERANKER_F2_DELTA",
        metrics.reranker_f2_delta,
        policy.minimum_reranker_f2_delta,
    )
    _minimum(
        blockers,
        "RERANKER_F2_DELTA_CI95_LOW",
        metrics.reranker_f2_delta_ci95_low,
        policy.minimum_reranker_f2_delta_ci95_low,
    )
    _minimum(
        blockers,
        "RERANKER_PROTECTED_SLICE_DELTA",
        metrics.reranker_protected_slice_delta,
        policy.minimum_reranker_protected_slice_delta,
    )
    _minimum(
        blockers,
        "SUBMISSION_REPLAY_RECORDS",
        metrics.submission_replay_records,
        policy.minimum_submission_replay_records,
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
