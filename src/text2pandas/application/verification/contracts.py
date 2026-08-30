"""Contracts for evidence and differential verification."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class VerificationPolicy:
    allow_recoverable_collisions: bool = False
    recoverable_collision_classes: tuple[str, ...] = (
        "missing_column_group",
        "missing_row_parent",
    )
    minimum_recoverable_confidence: float = 0.75
    enforce_family_completeness: bool = False
    enforced_families: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.minimum_recoverable_confidence <= 1.0:
            raise ValueError("minimum_recoverable_confidence must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: str
    score: float
    reasons: tuple[str, ...] = ()
    trace: tuple[dict[str, object], ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status == "OK"
