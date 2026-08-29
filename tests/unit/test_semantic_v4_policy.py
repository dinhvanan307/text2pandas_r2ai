from pathlib import Path

import pytest

from text2pandas.infrastructure.semantic import load_semantic_v4_policy

ROOT = Path(__file__).resolve().parents[2]


def test_v4_runtime_policy_is_shadow_locked_and_consistent() -> None:
    policy = load_semantic_v4_policy(ROOT / "configs/semantic/search_v4.yaml")

    assert policy.policy_id == "semantic-v4-search-v1"
    assert not policy.production_eligible
    assert not policy.include_recoverable_collisions
    assert not policy.verification.allow_recoverable_collisions
    assert policy.operand_pool_k >= policy.hierarchy.top_k
    assert policy.engine.maximum_relevant_tables == 10
    assert len(policy.config_sha256) == 64


def test_v4_policy_rejects_retrieval_verifier_collision_mismatch(tmp_path: Path) -> None:
    source = (ROOT / "configs/semantic/search_v4.yaml").read_text(encoding="utf-8")
    path = tmp_path / "invalid.yaml"
    path.write_text(
        source.replace(
            "include_recoverable_collisions: false",
            "include_recoverable_collisions: true",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="flags must match"):
        load_semantic_v4_policy(path)
