"""Load and validate the versioned Semantic V4 shadow runtime policy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from text2pandas.application.retrieval import HierarchicalRetrievalPolicy
from text2pandas.application.usecases.semantic_v4 import SemanticV4Config
from text2pandas.application.verification import VerificationPolicy
from text2pandas.infrastructure.checksums import sha256_file


@dataclass(frozen=True, slots=True)
class SemanticV4RuntimePolicy:
    policy_id: str
    status: str
    production_eligible: bool
    operand_pool_k: int
    include_recoverable_collisions: bool
    hierarchy: HierarchicalRetrievalPolicy
    engine: SemanticV4Config
    verification: VerificationPolicy
    config_path: Path
    config_sha256: str


def load_semantic_v4_policy(path: str | Path) -> SemanticV4RuntimePolicy:
    source = Path(path).expanduser().resolve()
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or _int(raw.get("schema_version", 0)) != 1:
        raise ValueError("unsupported Semantic V4 policy schema")
    physical = _mapping(raw, "physical_retrieval")
    hierarchy = _mapping(raw, "hierarchical_retrieval")
    search = _mapping(raw, "program_search")
    verification = _mapping(raw, "verification")
    operand_pool_k = _int(physical.get("operand_pool_k", 64))
    if operand_pool_k < 1:
        raise ValueError("operand_pool_k must be positive")
    include_recoverable = bool(
        physical.get("include_recoverable_collisions", False)
    )
    allow_recoverable = bool(
        verification.get("allow_recoverable_collisions", False)
    )
    if include_recoverable != allow_recoverable:
        raise ValueError("retrieval and verification recoverable-collision flags must match")
    production_eligible = bool(raw.get("production_eligible", False))
    if production_eligible and include_recoverable:
        raise ValueError("recoverable collisions cannot be production eligible without gold")
    hierarchy_policy = HierarchicalRetrievalPolicy(
        top_k=_int(hierarchy.get("top_k", 24)),
        max_per_logical_table=_int(hierarchy.get("max_per_logical_table", 6)),
        exact_leaf_bonus=_float(hierarchy.get("exact_leaf_bonus", 0.8)),
        source_code_bonus=_float(hierarchy.get("source_code_bonus", 0.7)),
        hierarchy_bonus=_float(hierarchy.get("hierarchy_bonus", 0.12)),
        statement_bonus=_float(hierarchy.get("statement_bonus", 0.4)),
        period_role_bonus=_float(hierarchy.get("period_role_bonus", 0.5)),
        component_context_penalty=_float(
            hierarchy.get("component_context_penalty", 2.5)
        ),
        recoverable_penalty=_float(hierarchy.get("recoverable_penalty", 2.5)),
        collision_penalty=_float(hierarchy.get("collision_penalty", 1.0)),
    )
    engine_policy = SemanticV4Config(
        max_parse_candidates=_int(search.get("max_parse_candidates", 8)),
        max_binding_candidates=_int(search.get("max_binding_candidates", 8)),
        minimum_confidence=_float(search.get("minimum_confidence", 0.62)),
        disagreement_margin=_float(search.get("disagreement_margin", 0.2)),
        maximum_relevant_tables=_int(search.get("maximum_relevant_tables", 10)),
    )
    verification_policy = VerificationPolicy(
        allow_recoverable_collisions=allow_recoverable,
        recoverable_collision_classes=_strings(
            verification.get(
                "recoverable_collision_classes",
                ("missing_column_group", "missing_row_parent"),
            )
        ),
        minimum_recoverable_confidence=_float(
            verification.get("minimum_recoverable_confidence", 0.75)
        ),
    )
    return SemanticV4RuntimePolicy(
        policy_id=str(raw["policy_id"]),
        status=str(raw.get("status") or "UNKNOWN"),
        production_eligible=production_eligible,
        operand_pool_k=operand_pool_k,
        include_recoverable_collisions=include_recoverable,
        hierarchy=hierarchy_policy,
        engine=engine_policy,
        verification=verification_policy,
        config_path=source,
        config_sha256=sha256_file(source),
    )


def _mapping(raw: dict[str, object], key: str) -> dict[str, object]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise TypeError(f"Semantic V4 policy section must be a mapping: {key}")
    return value


def _int(value: object) -> int:
    return int(str(value))


def _float(value: object) -> float:
    return float(str(value))


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError("expected a sequence of strings")
    return tuple(str(item) for item in value)
