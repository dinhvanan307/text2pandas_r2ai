"""Load and integrity-check the governed gold registry."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

import yaml

from text2pandas.application.usecases.gold_readiness import (
    GoldAsset,
    GoldRegistry,
    Independence,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT = _REPO_ROOT / "configs" / "evaluation" / "gold_registry_v1.yaml"


def load_gold_registry(path: str | Path = _DEFAULT) -> GoldRegistry:
    registry_path = Path(path)
    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping) or int(raw.get("schema_version", 0)) != 1:
        raise ValueError("gold registry schema_version must equal 1")
    raw_assets = raw.get("assets")
    if not isinstance(raw_assets, Mapping):
        raise TypeError("gold registry assets must be a mapping")
    assets: list[GoldAsset] = []
    for name, value in raw_assets.items():
        if not isinstance(value, Mapping):
            raise TypeError(f"gold asset must be a mapping: {name}")
        relative_path = str(value["path"])
        asset_path = _REPO_ROOT / relative_path
        if not asset_path.is_file():
            raise FileNotFoundError(f"missing gold asset: {relative_path}")
        actual_sha = hashlib.sha256(asset_path.read_bytes()).hexdigest()
        expected_sha = str(value["sha256"])
        if actual_sha != expected_sha:
            raise ValueError(f"gold checksum mismatch: {name}:{actual_sha}:{expected_sha}")
        actual_records = sum(
            1 for line in asset_path.read_text(encoding="utf-8").splitlines() if line.strip()
        )
        expected_records = int(value["records"])
        if actual_records != expected_records:
            raise ValueError(
                f"gold record count mismatch: {name}:{actual_records}:{expected_records}"
            )
        assets.append(
            GoldAsset(
                name=str(name),
                path=relative_path,
                sha256=expected_sha,
                records=expected_records,
                usable_records=int(value["usable_records"]),
                promotion_eligible_records=int(value["promotion_eligible_records"]),
                independence=Independence(str(value["independence"])),
                sealed=bool(value["sealed"]),
                blocker=None if value.get("blocker") is None else str(value["blocker"]),
            )
        )
    registry = GoldRegistry(str(raw["registry_id"]), tuple(assets))
    for required in ("answer", "semantic_parser", "evidence_binding"):
        registry.by_name(required)
    return registry

