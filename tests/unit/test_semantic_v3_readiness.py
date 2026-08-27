from text2pandas.application.usecases.semantic_v3_readiness import (
    PromotionMetrics,
    evaluate_promotion,
)
from text2pandas.infrastructure.semantic import load_promotion_policy


def test_missing_gold_and_accuracy_can_never_be_interpreted_as_pass() -> None:
    decision = evaluate_promotion(
        PromotionMetrics(questions=1012, replay_mismatches=0),
        load_promotion_policy(),
    )

    assert not decision.promotable
    assert "NOT_MEASURED:PARSER_AST_EXACT" in decision.blockers
    assert "NOT_MEASURED:BINDING_EXACT" in decision.blockers
    assert "NOT_MEASURED:ANSWER_ACCURACY" in decision.blockers
    assert "NOT_MEASURED:RERANKER_F2_DELTA" in decision.blockers
    assert "NOT_MEASURED:EVALUATION_RELEASE_SEALED" in decision.blockers
    assert "NOT_MEASURED:SUBMISSION_REPLAY_RECORDS" in decision.blockers


def test_every_measured_gate_must_pass_for_promotion() -> None:
    policy = load_promotion_policy()
    decision = evaluate_promotion(
        PromotionMetrics(
            questions=1012,
            evaluation_release_id="independent-gold-v1",
            evaluation_release_sealed=True,
            answer_gold_records=300,
            semantic_gold_records=300,
            evidence_gold_records=300,
            parser_ast_exact=0.95,
            candidate_recall=0.99,
            binding_exact=0.90,
            answer_accuracy=0.80,
            reranker_heldout_records=120,
            reranker_f2_delta=0.01,
            reranker_f2_delta_ci95_low=0.0,
            reranker_protected_slice_delta=-0.01,
            submission_replay_records=1012,
            replay_mismatches=0,
            submission_errors=0,
        ),
        policy,
    )

    assert decision.promotable


def test_unsealed_or_mixed_evaluation_release_blocks_promotion() -> None:
    policy = load_promotion_policy()
    metrics = PromotionMetrics(
        questions=1012,
        evaluation_release_id="working-copy",
        evaluation_release_sealed=False,
        answer_gold_records=300,
        semantic_gold_records=300,
        evidence_gold_records=300,
        parser_ast_exact=0.99,
        candidate_recall=1.0,
        binding_exact=0.99,
        answer_accuracy=0.90,
        reranker_heldout_records=120,
        reranker_f2_delta=0.01,
        reranker_f2_delta_ci95_low=0.0,
        reranker_protected_slice_delta=0.0,
        submission_replay_records=1012,
        replay_mismatches=0,
        submission_errors=0,
    )

    decision = evaluate_promotion(metrics, policy)

    assert not decision.promotable
    assert "UNSEALED:EVALUATION_RELEASE" in decision.blockers
