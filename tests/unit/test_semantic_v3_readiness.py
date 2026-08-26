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


def test_every_measured_gate_must_pass_for_promotion() -> None:
    policy = load_promotion_policy()
    decision = evaluate_promotion(
        PromotionMetrics(
            questions=1012,
            semantic_gold_records=300,
            evidence_gold_records=300,
            parser_ast_exact=0.95,
            candidate_recall=0.99,
            binding_exact=0.90,
            answer_accuracy=0.80,
            replay_mismatches=0,
            submission_errors=0,
        ),
        policy,
    )

    assert decision.promotable
