from __future__ import annotations

import pytest

from text2pandas.pipelines.retrieval.evalkit.attribution import (
    StageLoss,
    classify_stage_loss,
)


@pytest.mark.parametrize(
    "expected,empty_from",
    [
        (StageLoss.S1_LOSS, "s1_table_ids"),
        (StageLoss.S2_RANK_LOSS, "s2_table_ids"),
        (StageLoss.S2_RANK_LOSS, "s3_table_ids"),
        (StageLoss.OUTPUT_N_LOSS, "output_table_ids"),
        (StageLoss.BINDING_LOSS, "binding_table_ids"),
        (StageLoss.SERIALIZATION_LOSS, "final_table_ids"),
    ],
)
def test_stage_loss_is_mutually_exclusive(expected: StageLoss, empty_from: str) -> None:
    ordered = [
        "s1_table_ids",
        "s2_table_ids",
        "s3_table_ids",
        "output_table_ids",
        "binding_table_ids",
        "final_table_ids",
    ]
    values = {
        "gold_table_ids": ["gold"],
        "s1_table_ids": ["gold"],
        "s2_table_ids": ["gold"],
        "s3_table_ids": ["gold"],
        "output_table_ids": ["gold"],
        "binding_table_ids": ["gold"],
        "final_table_ids": ["gold"],
    }
    start = ordered.index(empty_from)
    for key in ordered[start:]:
        values[key] = []
    assert classify_stage_loss(**values) is expected


def test_missing_gold_is_unknown() -> None:
    assert classify_stage_loss(
        gold_table_ids=[],
        s1_table_ids=[],
        s2_table_ids=[],
        s3_table_ids=[],
        output_table_ids=[],
        binding_table_ids=None,
        final_table_ids=[],
    ) is StageLoss.UNKNOWN


def test_final_recovery_is_no_loss() -> None:
    assert classify_stage_loss(
        gold_table_ids=["gold"],
        s1_table_ids=["gold"],
        s2_table_ids=["gold"],
        s3_table_ids=["gold"],
        output_table_ids=[],
        binding_table_ids=["gold"],
        final_table_ids=["gold"],
    ) is StageLoss.NO_LOSS


def test_binding_not_applied_does_not_create_false_binding_loss() -> None:
    assert classify_stage_loss(
        gold_table_ids=["gold"],
        s1_table_ids=["gold"],
        s2_table_ids=["gold"],
        s3_table_ids=["gold"],
        output_table_ids=["gold"],
        binding_table_ids=None,
        final_table_ids=["gold"],
    ) is StageLoss.NO_LOSS
