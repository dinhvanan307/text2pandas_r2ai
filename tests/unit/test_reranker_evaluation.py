from text2pandas.application.usecases.reranker_evaluation import (
    RerankOutcome,
    evaluate_reranker_ab,
)


def test_paired_heldout_gate_passes_clear_uplift() -> None:
    rows = [
        RerankOutcome(i, "single" if i % 2 else "screen", 1, 10,
                      (), (1,))
        for i in range(120)
    ]
    report = evaluate_reranker_ab(rows, bootstrap_samples=200, seed=7)
    assert report["status"] == "PASS"
    assert report["paired_f2_delta"] > 0
    assert report["paired_f2_delta_ci95"][0] > 0


def test_paired_heldout_gate_rejects_protected_regression() -> None:
    rows = [RerankOutcome(i, "single", 1, 10, (1,), ()) for i in range(100)]
    report = evaluate_reranker_ab(rows, bootstrap_samples=100, seed=7)
    assert report["status"] == "FAIL"
    assert not report["gates"]["protected_slice_delta_gte_minus_0_01"]
