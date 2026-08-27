from dataclasses import replace

import pytest

from text2pandas.application.usecases.gold_readiness import GoldAsset, Independence
from text2pandas.infrastructure.semantic import load_gold_registry


def test_tracked_gold_registry_is_integral_but_not_promotion_eligible() -> None:
    registry = load_gold_registry()

    assert not registry.promotion_eligible
    assert registry.by_name("answer").usable_records == 31
    assert registry.by_name("semantic_parser").promotion_eligible_records == 0
    assert registry.by_name("evidence_binding").usable_records == 0


def test_non_independent_gold_cannot_be_declared_promotion_eligible() -> None:
    asset = load_gold_registry().by_name("semantic_parser")

    with pytest.raises(ValueError, match="non-independent gold"):
        replace(asset, promotion_eligible_records=1)


def test_unsealed_gold_cannot_be_declared_promotion_eligible() -> None:
    with pytest.raises(ValueError, match="unsealed gold"):
        GoldAsset(
            name="answer",
            path="gold.jsonl",
            sha256="0" * 64,
            records=1,
            usable_records=1,
            promotion_eligible_records=1,
            independence=Independence.VERIFIED,
            sealed=False,
        )
