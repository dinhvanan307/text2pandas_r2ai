"""Load the versioned P0 metric resolver/selector policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from text2pandas.application.selection import MetricResolverPolicy, MetricSelectorPolicy
from text2pandas.domain.metrics import normalize_phrase
from text2pandas.infrastructure.checksums import sha256_file

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_POLICY = _REPO_ROOT / "configs" / "answer_v2" / "metric_selector_p0.yaml"


def load_metric_resolver_policy(
    path: str | Path = _DEFAULT_POLICY,
) -> MetricResolverPolicy:
    policy_path = Path(path)
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or int(raw.get("schema_version", 0)) != 1:
        raise ValueError("P0 metric selector policy schema_version must equal 1")
    resolution = _mapping(raw.get("resolution"), "resolution")
    exact = float(resolution["exact_confidence"])
    normalized = float(resolution["normalized_confidence"])
    source = float(resolution["source_confidence"])
    if not 0.0 <= source <= normalized <= exact <= 1.0:
        raise ValueError("P0 resolver confidences must satisfy source <= normalized <= exact <= 1")
    ambiguous = tuple(
        normalize_phrase(str(value)) for value in raw.get("ambiguous_phrases", ())
    )
    operations = tuple(str(value) for value in raw.get("supported_operations", ()))
    if not ambiguous or not operations:
        raise ValueError("P0 resolver policy requires ambiguity and operation policies")
    return MetricResolverPolicy(
        policy_id=str(raw["policy_id"]),
        exact_confidence=exact,
        normalized_confidence=normalized,
        source_confidence=source,
        ambiguous_phrases=ambiguous,
        supported_operations=operations,
        config_sha256=sha256_file(policy_path),
    )


def load_metric_selector_policy(
    path: str | Path = _DEFAULT_POLICY,
) -> MetricSelectorPolicy:
    policy_path = Path(path)
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or int(raw.get("schema_version", 0)) != 1:
        raise ValueError("P0 metric selector policy schema_version must equal 1")
    selection = _mapping(raw.get("selection"), "selection")
    return MetricSelectorPolicy(
        min_guarded_confidence=float(selection["min_guarded_confidence"]),
        max_rebind_candidates=int(selection["max_rebind_candidates"]),
        ambiguity_margin=float(selection["ambiguity_margin"]),
        config_sha256=sha256_file(policy_path),
    )


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be a mapping")
    return value
