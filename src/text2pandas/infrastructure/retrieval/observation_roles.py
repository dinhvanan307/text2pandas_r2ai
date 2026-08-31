"""Versioned, source-agnostic observation row and column role classification."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from text2pandas.domain.facts import split_hierarchy
from text2pandas.domain.semantic import ObservationColumnRole, ObservationRowRole

from .fact_label import normalize_fact_label

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OBSERVATION_ROLE_POLICY = (
    _REPO_ROOT / "configs/semantic/observation_roles_v1.yaml"
)


@dataclass(frozen=True, slots=True)
class ObservationRolePolicy:
    policy_id: str
    row_role_priority: tuple[ObservationRowRole, ...]
    row_role_tokens: Mapping[ObservationRowRole, tuple[str, ...]]
    column_role_tokens: Mapping[ObservationColumnRole, tuple[str, ...]]
    strict_money_scale_sources: tuple[str, ...]
    fingerprint: str

    def classify_row(self, row_path: str) -> ObservationRowRole:
        hierarchy = split_hierarchy(row_path)
        leaf = normalize_fact_label(hierarchy[-1] if hierarchy else row_path)
        for role in self.row_role_priority:
            if any(_contains(leaf, token) for token in self.row_role_tokens.get(role, ())):
                return role
        if len(hierarchy) > 1:
            return ObservationRowRole.CHILD
        return ObservationRowRole.UNKNOWN

    def classify_column(
        self, column_path: str, period_role: str | None
    ) -> ObservationColumnRole:
        direct = str(period_role or "").strip().lower()
        if direct in {
            ObservationColumnRole.CLOSING.value,
            ObservationColumnRole.OPENING.value,
            ObservationColumnRole.CURRENT.value,
            ObservationColumnRole.PRIOR.value,
        }:
            return ObservationColumnRole(direct)
        normalized = normalize_fact_label(column_path)
        for role in (
            ObservationColumnRole.CLOSING,
            ObservationColumnRole.OPENING,
            ObservationColumnRole.CURRENT,
            ObservationColumnRole.PRIOR,
            ObservationColumnRole.AS_OF,
        ):
            if any(
                _contains(normalized, token)
                for token in self.column_role_tokens.get(role, ())
            ):
                return role
        return ObservationColumnRole.UNKNOWN


def load_observation_role_policy(
    path: str | Path = DEFAULT_OBSERVATION_ROLE_POLICY,
) -> ObservationRolePolicy:
    source = Path(path).expanduser().resolve()
    raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or int(str(raw.get("schema_version", 0))) != 1:
        raise ValueError("unsupported observation-role policy schema")
    raw_row_roles = _mapping(raw.get("row_roles"), "row_roles")
    raw_column_roles = _mapping(raw.get("column_roles"), "column_roles")
    priority = tuple(
        ObservationRowRole(str(value))
        for value in _sequence(raw.get("row_role_priority"), "row_role_priority")
    )
    row_tokens = {
        ObservationRowRole(str(role)): _normalized_tokens(values, f"row_roles.{role}")
        for role, values in raw_row_roles.items()
    }
    column_tokens = {
        ObservationColumnRole(str(role)): _normalized_tokens(
            values, f"column_roles.{role}"
        )
        for role, values in raw_column_roles.items()
    }
    safe_scales = tuple(
        str(value)
        for value in _sequence(
            raw.get("strict_money_scale_sources"), "strict_money_scale_sources"
        )
    )
    canonical = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return ObservationRolePolicy(
        policy_id=str(raw.get("policy_id") or ""),
        row_role_priority=priority,
        row_role_tokens=row_tokens,
        column_role_tokens=column_tokens,
        strict_money_scale_sources=safe_scales,
        fingerprint=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def _normalized_tokens(value: object, label: str) -> tuple[str, ...]:
    return tuple(normalize_fact_label(str(item)) for item in _sequence(value, label))


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{label} must be a sequence")
    return value


def _contains(value: str, token: str) -> bool:
    return token == value or f" {token} " in f" {value} "
