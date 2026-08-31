from pathlib import Path

import pytest

from text2pandas.infrastructure.semantic import load_semantic_v4_policy

ROOT = Path(__file__).resolve().parents[2]


def test_v4_runtime_policy_is_shadow_locked_and_consistent() -> None:
    policy = load_semantic_v4_policy(ROOT / "configs/semantic/search_v4.yaml")

    assert policy.policy_id == "semantic-v4-search-v1"
    assert not policy.production_eligible
    assert not policy.include_recoverable_collisions
    assert not policy.enforce_observation_roles
    assert not policy.verification.allow_recoverable_collisions
    assert policy.operand_pool_k >= policy.hierarchy.top_k
    assert policy.engine.maximum_relevant_tables == 10
    assert not policy.engine.infer_observation_roles
    assert len(policy.config_sha256) == 64


def test_wave4_policy_limits_rebinding_and_requires_consensus() -> None:
    policy = load_semantic_v4_policy(ROOT / "configs/semantic/search_v4_wave4.yaml")

    assert policy.policy_id == "semantic-v4-wave4-search-v2"
    assert policy.engine.max_binding_candidates == 3
    assert policy.engine.require_answer_consensus
    assert not policy.production_eligible


def test_wave5_policy_enables_role_inference_and_hard_filtering() -> None:
    policy = load_semantic_v4_policy(ROOT / "configs/semantic/search_v4_wave5_riska.yaml")

    assert not policy.production_eligible
    assert policy.enforce_observation_roles
    assert policy.engine.infer_observation_roles
    assert policy.engine.strict_observation_equivalence
    assert policy.engine.enforce_rank_semantic_gates
    assert policy.engine.require_selection_key_consensus
    assert policy.verification.enforce_family_completeness
    assert policy.verification.enforced_families == (
        "direct_lookup",
        "direct_ratio",
        "two_period_difference",
        "single_metric_sum",
        "single_metric_average",
    )
    assert policy.engine.max_binding_candidates == 3
    assert policy.engine.require_answer_consensus


@pytest.mark.parametrize(
    ("name", "roles", "strict_binding", "families"),
    (
        ("s1_contract", False, False, ()),
        ("s2_selector", True, False, ()),
        ("s3_binding", True, True, ()),
        ("s4_direct", True, True, ("direct_lookup", "direct_ratio")),
        (
            "s5_difference_sum",
            True,
            True,
            (
                "direct_lookup",
                "direct_ratio",
                "two_period_difference",
                "single_metric_sum",
            ),
        ),
        (
            "s6_average",
            True,
            True,
            (
                "direct_lookup",
                "direct_ratio",
                "two_period_difference",
                "single_metric_sum",
                "single_metric_average",
            ),
        ),
    ),
)
def test_wave5_checkpoint_policies_are_monotonic_and_extrema_stay_off(
    name: str,
    roles: bool,
    strict_binding: bool,
    families: tuple[str, ...],
) -> None:
    policy = load_semantic_v4_policy(ROOT / f"configs/semantic/search_v4_wave5_{name}.yaml")

    assert policy.enforce_observation_roles is roles
    assert policy.engine.infer_observation_roles is roles
    assert policy.engine.strict_observation_equivalence is strict_binding
    assert policy.verification.enforce_family_completeness is bool(families)
    assert policy.verification.enforced_families == families
    assert not policy.engine.enforce_rank_semantic_gates
    assert not policy.engine.require_selection_key_consensus
    assert not policy.production_eligible


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
