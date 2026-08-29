"""Load the versioned Semantic V3 hybrid-composition policy."""

from __future__ import annotations

from pathlib import Path

import yaml

from text2pandas.application.usecases.hybrid_v3 import (
    HybridPolicy,
    HybridRoutePolicy,
)


def load_hybrid_policy(path: str | Path) -> HybridPolicy:
    source = Path(path)
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if int(raw.get("schema_version", 0)) != 1:
        raise ValueError("unsupported hybrid policy schema")
    default = _route(raw.get("default_route") or {})
    routes = {
        str(name): _route(values or {})
        for name, values in (raw.get("routes") or {}).items()
    }
    refs_mode = str(raw.get("relevant_refs_mode") or "semantic_evidence")
    if refs_mode not in {"semantic_evidence", "semantic_plus_legacy"}:
        raise ValueError(f"invalid relevant_refs_mode: {refs_mode}")
    maximum = int(raw.get("maximum_relevant_tables", 10))
    if maximum < 1 or maximum > 10:
        raise ValueError("maximum_relevant_tables must be in [1, 10]")
    return HybridPolicy(
        policy_id=str(raw["policy_id"]),
        status=str(raw.get("status") or "UNKNOWN"),
        production_eligible=bool(raw.get("production_eligible", False)),
        relevant_refs_mode=refs_mode,
        maximum_relevant_tables=maximum,
        default_route=default,
        routes=routes,
    )


def _route(raw: dict[str, object]) -> HybridRoutePolicy:
    margin = raw.get("minimum_binding_margin")
    return HybridRoutePolicy(
        recover_legacy_abstention=bool(raw.get("recover_legacy_abstention", False)),
        replace_legacy_value=bool(raw.get("replace_legacy_value", False)),
        minimum_binding_margin=None if margin is None else float(str(margin)),
    )
