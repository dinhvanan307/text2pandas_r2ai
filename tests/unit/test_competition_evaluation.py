from __future__ import annotations

import pytest

from text2pandas.application.usecases.competition_evaluation import (
    AnswerGold,
    Prediction,
    ReplayResult,
    RetrievalGold,
    compare_scores,
    normalize_table_ref,
    score_competition,
    score_ranked_case,
)


def test_ranked_metrics_match_published_per_query_formula() -> None:
    score = score_ranked_case(1, ("a", "x"), frozenset({"a", "b"}))

    assert score.precision == 0.5
    assert score.recall == 0.5
    assert score.f2 == 0.5
    assert score.mrr5 == 1.0


def test_macro_f2_is_mean_of_query_f2_not_f2_of_macro_precision_recall() -> None:
    predictions = [
        Prediction(1, ("d1|1",), ("d1",), None),
        Prediction(2, ("wrong|1", "wrong|2"), ("wrong",), None),
    ]
    gold = [
        RetrievalGold(1, frozenset({"d1|1"}), frozenset({"d1"})),
        RetrievalGold(2, frozenset({"d2|1", "d2|2"}), frozenset({"d2"})),
    ]

    report = score_competition(predictions, gold, [], [])

    assert report["metrics"]["tables_f2_macro"] == 0.5
    assert report["metrics"]["tables_precision"] == 0.5
    assert report["metrics"]["tables_recall"] == 0.5


def test_mrr_is_zero_when_first_hit_is_after_rank_five() -> None:
    score = score_ranked_case(
        1, ("x1", "x2", "x3", "x4", "x5", "gold"), frozenset({"gold"})
    )

    assert score.mrr5 == 0.0


def test_duplicate_prediction_cannot_inflate_recall() -> None:
    score = score_ranked_case(1, ("gold", "gold"), frozenset({"gold", "other"}))

    assert score.precision == 0.5
    assert score.recall == 0.5


def test_answer_and_execution_are_scored_independently() -> None:
    predictions = [Prediction(1, (), (), 100.0), Prediction(2, (), (), 999.0)]
    gold = [AnswerGold(1, 100.0), AnswerGold(2, 200.0)]
    replay = [ReplayResult(1, "NO_EXECUTABLE_QUERY", None), ReplayResult(2, "OK", 200.0)]

    report = score_competition(predictions, [], gold, replay)

    assert report["metrics"]["answer_accuracy"] == 0.5
    assert report["metrics"]["execution_accuracy"] == 0.5
    assert report["cases"]["answer"][0]["answer_correct"] is True
    assert report["cases"]["answer"][0]["execution_correct"] is False


def test_answer_tolerance_has_absolute_floor_for_zero() -> None:
    report = score_competition(
        [Prediction(1, (), (), 0.004)],
        [],
        [AnswerGold(1, 0.0)],
        [ReplayResult(1, "OK", 0.006)],
        tolerance=0.005,
    )

    assert report["metrics"]["answer_accuracy"] == 1.0
    assert report["metrics"]["execution_accuracy"] == 0.0


def test_missing_prediction_remains_in_macro_denominator_as_zero() -> None:
    report = score_competition(
        [],
        [RetrievalGold(9, frozenset({"d|1"}), frozenset({"d"}))],
        [AnswerGold(9, 10.0)],
        [],
    )

    assert report["metrics"]["tables_f2_macro"] == 0.0
    assert report["metrics"]["docs_f2_macro"] == 0.0
    assert report["metrics"]["answer_accuracy"] == 0.0
    assert report["metrics"]["execution_accuracy"] == 0.0


def test_table_reference_normalizes_internal_line_prefix() -> None:
    assert normalize_table_ref("doc_extracted|line:42") == "doc|42"


def test_comparison_fails_closed_on_any_metric_regression() -> None:
    baseline = score_competition(
        [Prediction(1, ("d|1",), ("d",), 10.0)],
        [RetrievalGold(1, frozenset({"d|1"}), frozenset({"d"}))],
        [AnswerGold(1, 10.0)],
        [ReplayResult(1, "OK", 10.0)],
    )
    candidate = score_competition(
        [Prediction(1, (), (), 10.0)],
        [RetrievalGold(1, frozenset({"d|1"}), frozenset({"d"}))],
        [AnswerGold(1, 10.0)],
        [ReplayResult(1, "OK", 10.0)],
    )

    comparison = compare_scores(candidate, baseline)

    assert comparison["all_ten_metrics_non_regressing"] is False
    assert comparison["metric_deltas"]["tables_f2_macro"] == pytest.approx(-1.0)
