from __future__ import annotations

import pytest

from text2pandas.pipelines.retrieval.policy import adaptive_submission_table_limit


def test_score_margin_extends_scope_floor_without_exceeding_cap() -> None:
    assert (
        adaptive_submission_table_limit(
            1,
            (1.00, 0.75, 0.51, 0.49, 0.10),
            score_margin=0.50,
            maximum=4,
        )
        == 3
    )


def test_score_margin_never_shrinks_scope_floor() -> None:
    assert (
        adaptive_submission_table_limit(
            3,
            (1.00, 0.20, 0.10, 0.05),
            score_margin=0.01,
            maximum=10,
        )
        == 3
    )


def test_score_margin_rejects_negative_values() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        adaptive_submission_table_limit(1, (1.0,), score_margin=-0.1)
