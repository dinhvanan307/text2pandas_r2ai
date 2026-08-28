"""Gold-aware attribution across canonical table-retrieval transitions.

The production pipeline never imports gold.  This module consumes immutable
stage traces after a run and assigns one mutually exclusive loss label.  It is
kept under evalkit so diagnostic labels cannot influence retrieval behavior.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable

__all__ = ["StageLoss", "classify_stage_loss"]


class StageLoss(str, Enum):
    S1_LOSS = "S1_LOSS"
    S2_RANK_LOSS = "S2_RANK_LOSS"
    OUTPUT_N_LOSS = "OUTPUT_N_LOSS"
    BINDING_LOSS = "BINDING_LOSS"
    SERIALIZATION_LOSS = "SERIALIZATION_LOSS"
    NO_LOSS = "NO_LOSS"
    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:
        return self.value


def classify_stage_loss(
    *,
    gold_table_ids: Iterable[str],
    s1_table_ids: Iterable[str],
    s2_table_ids: Iterable[str],
    s3_table_ids: Iterable[str],
    output_table_ids: Iterable[str],
    binding_table_ids: Iterable[str] | None,
    final_table_ids: Iterable[str],
) -> StageLoss:
    """Return the first transition that removes every gold table.

    `binding_table_ids=None` means binding was not applied (for example a
    fail-closed answer whose final refs remain retrieval refs).  An empty
    iterable means binding ran but selected no table.
    """

    gold = frozenset(gold_table_ids)
    if not gold:
        return StageLoss.UNKNOWN
    final = frozenset(final_table_ids)
    if gold & final:
        return StageLoss.NO_LOSS
    if binding_table_ids is not None:
        bound = frozenset(binding_table_ids)
        if gold & bound:
            return StageLoss.SERIALIZATION_LOSS
    output = frozenset(output_table_ids)
    if gold & output:
        if binding_table_ids is not None:
            return StageLoss.BINDING_LOSS
        return StageLoss.SERIALIZATION_LOSS
    s3 = frozenset(s3_table_ids)
    if gold & s3:
        return StageLoss.OUTPUT_N_LOSS
    s2 = frozenset(s2_table_ids)
    if gold & s2:
        return StageLoss.S2_RANK_LOSS
    s1 = frozenset(s1_table_ids)
    if gold & s1:
        return StageLoss.S2_RANK_LOSS
    return StageLoss.S1_LOSS
