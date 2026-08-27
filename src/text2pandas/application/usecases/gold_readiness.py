"""Pure governance contract for promotion-grade evaluation gold."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Independence(StrEnum):
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    VERIFIED = "VERIFIED"


@dataclass(frozen=True, slots=True)
class GoldAsset:
    name: str
    path: str
    sha256: str
    records: int
    usable_records: int
    promotion_eligible_records: int
    independence: Independence
    sealed: bool
    blocker: str | None = None

    def __post_init__(self) -> None:
        counts = (self.records, self.usable_records, self.promotion_eligible_records)
        if any(value < 0 for value in counts):
            raise ValueError(f"gold counts must be non-negative: {self.name}")
        if self.usable_records > self.records:
            raise ValueError(f"usable gold exceeds total records: {self.name}")
        if self.promotion_eligible_records > self.usable_records:
            raise ValueError(f"eligible gold exceeds usable records: {self.name}")
        if self.promotion_eligible_records and self.independence != Independence.VERIFIED:
            raise ValueError(f"non-independent gold cannot be promotion eligible: {self.name}")
        if self.promotion_eligible_records and not self.sealed:
            raise ValueError(f"unsealed gold cannot be promotion eligible: {self.name}")


@dataclass(frozen=True, slots=True)
class GoldRegistry:
    registry_id: str
    assets: tuple[GoldAsset, ...]

    def by_name(self, name: str) -> GoldAsset:
        matches = [asset for asset in self.assets if asset.name == name]
        if len(matches) != 1:
            raise KeyError(f"gold asset must exist exactly once: {name}")
        return matches[0]

    @property
    def promotion_eligible(self) -> bool:
        required = {"answer", "semantic_parser", "evidence_binding"}
        available = {asset.name for asset in self.assets if asset.promotion_eligible_records}
        return required <= available

    def to_dict(self) -> dict[str, object]:
        return {
            "registry_id": self.registry_id,
            "promotion_eligible": self.promotion_eligible,
            "assets": {
                asset.name: {
                    "path": asset.path,
                    "records": asset.records,
                    "usable_records": asset.usable_records,
                    "promotion_eligible_records": asset.promotion_eligible_records,
                    "independence": asset.independence.value,
                    "sealed": asset.sealed,
                    "blocker": asset.blocker,
                }
                for asset in self.assets
            },
        }

