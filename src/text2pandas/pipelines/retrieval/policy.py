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
