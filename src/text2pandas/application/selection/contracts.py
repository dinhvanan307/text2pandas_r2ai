"""Immutable per-operand selector contract for P0 answer correctness."""

from __future__ import annotations

from dataclasses import dataclass

from text2pandas.domain.metrics import MetricSpec
from text2pandas.domain.semantic import Basis, Dimension, PeriodSemantics


@dataclass(frozen=True, slots=True)
class ResolvedMetricMention:
    start: int
    end: int
    surface: str
    normalized_surface: str
    candidate_metric_ids: tuple[str, ...]
    selected_metric_id: str | None
    match_method: str
    confidence: float
    metric_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "start": self.start,
            "end": self.end,
            "surface": self.surface,
            "normalized_surface": self.normalized_surface,
            "candidate_metric_ids": list(self.candidate_metric_ids),
            "selected_metric_id": self.selected_metric_id,
            "match_method": self.match_method,
            "confidence": self.confidence,
            "metric_codes": list(self.metric_codes),
        }


@dataclass(frozen=True, slots=True)
class MetricResolution:
    status: str
    selected_metric_id: str | None
    mentions: tuple[ResolvedMetricMention, ...]
    candidates: tuple[str, ...]
    confidence: float
    resolution_method: str
    reason: str | None
    ontology_fingerprint: str
    resolver_fingerprint: str
    operation_eligible: bool
    trace: tuple[dict[str, object], ...] = ()

    @property
    def resolved(self) -> bool:
        return self.status == "RESOLVED" and self.selected_metric_id is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "selected_metric_id": self.selected_metric_id,
            "mentions": [mention.to_dict() for mention in self.mentions],
            "candidates": list(self.candidates),
            "confidence": self.confidence,
            "resolution_method": self.resolution_method,
            "reason": self.reason,
            "ontology_fingerprint": self.ontology_fingerprint,
            "resolver_fingerprint": self.resolver_fingerprint,
            "operation_eligible": self.operation_eligible,
            "trace": list(self.trace),
        }


@dataclass(frozen=True, slots=True)
class SelectorSpec:
    """All semantic constraints needed to select one physical observation.

    One instance belongs to exactly one operand.  Metric policy is projected
    from the reviewed ontology; question scope and source evidence are added by
    the resolver/builder.  The contract intentionally contains no answer,
    retrieval rank, Pandas query, or gold field.
    """

    metric_id: str
    aliases: tuple[str, ...]
    expected_dimension: Dimension
    allowed_statement_types: tuple[str, ...]
    preferred_basis: Basis
    period_semantics: PeriodSemantics
    forbidden_prefixes: tuple[str, ...]
    forbidden_contains: tuple[str, ...]
    required_context_any: tuple[str, ...]
    entity: str | None
    period: str | None
    requested_period_role: str | None
    requested_basis: Basis
    metric_codes: tuple[str, ...]
    resolution_confidence: float
    resolution_method: str
    ontology_fingerprint: str
    operand_role: str = "value"

    def __post_init__(self) -> None:
        if not self.metric_id:
            raise ValueError("SelectorSpec requires metric_id")
        if not self.aliases:
            raise ValueError("SelectorSpec requires aliases")
        if self.expected_dimension == Dimension.UNKNOWN:
            raise ValueError("SelectorSpec rejects UNKNOWN expected_dimension")
        if self.period_semantics == PeriodSemantics.UNKNOWN:
            raise ValueError("SelectorSpec rejects UNKNOWN period_semantics")
        if not self.allowed_statement_types:
            raise ValueError("SelectorSpec requires allowed_statement_types")
        if not 0.0 <= self.resolution_confidence <= 1.0:
            raise ValueError("resolution_confidence must be between 0 and 1")
        if not self.resolution_method:
            raise ValueError("SelectorSpec requires resolution_method")
        if not self.ontology_fingerprint:
            raise ValueError("SelectorSpec requires ontology_fingerprint")

    @classmethod
    def from_metric(
        cls,
        metric: MetricSpec,
        *,
        ontology_fingerprint: str,
        entity: str | None,
        period: str | None,
        requested_period_role: str | None,
        requested_basis: Basis,
        metric_codes: tuple[str, ...] = (),
        resolution_confidence: float = 1.0,
        resolution_method: str = "EXACT_ALIAS",
        operand_role: str = "value",
    ) -> "SelectorSpec":
        if metric.review_status != "reviewed":
            raise ValueError("P0 SelectorSpec requires a reviewed metric")
        return cls(
            metric_id=metric.metric_id,
            aliases=metric.aliases,
            expected_dimension=metric.expected_dimension,
            allowed_statement_types=metric.preferred_statement_types,
            preferred_basis=metric.preferred_basis,
            period_semantics=metric.period_semantics,
            forbidden_prefixes=metric.forbidden_prefixes,
            forbidden_contains=metric.forbidden_contains,
            required_context_any=metric.required_context_any,
            entity=entity,
            period=period,
            requested_period_role=requested_period_role,
            requested_basis=requested_basis,
            metric_codes=metric_codes,
            resolution_confidence=resolution_confidence,
            resolution_method=resolution_method,
            ontology_fingerprint=ontology_fingerprint,
            operand_role=operand_role,
        )
