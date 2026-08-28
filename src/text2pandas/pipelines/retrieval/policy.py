"""Single source of truth for retrieval output-size policy."""

from __future__ import annotations

MAX_RELEVANT_TABLES = 10


def submission_table_limit(
    n_targets: int,
    n_years: int,
    *,
    maximum: int = MAX_RELEVANT_TABLES,
) -> int:
    """Estimate submitted table count from the explicit entity/year scope."""

    return max(1, min(max(1, n_targets) * max(1, n_years), maximum))


def adaptive_submission_table_limit(
    base_n: int,
    scores: list[float] | tuple[float, ...],
    *,
    score_margin: float,
    maximum: int = MAX_RELEVANT_TABLES,
) -> int:
    """Extend a scope-derived floor while candidates remain near rank one.

    The score margin uses only signals already produced by S2.  It never
    shrinks the scope-derived floor, never exceeds ``maximum``, and cannot add
    a table that was not ranked by the production retriever.
    """

    if score_margin < 0:
        raise ValueError("score_margin must be non-negative")
    if not scores:
        return 0
    limit = min(maximum, len(scores))
    n = min(max(1, base_n), limit)
    threshold = scores[0] - score_margin
    while n < limit and scores[n] >= threshold:
        n += 1
    return n
