"""Ports and transport values at the semantic parser boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from text2pandas.domain.semantic import (
    Basis,
    MetricBindingHint,
    PeriodSemantics,
    QuestionAST,
    RankDirection,
    UnitSpec,
)


class OperationKind(StrEnum):
    LOOKUP = "lookup"
    DIVIDE = "divide"
    SUBTRACT = "subtract"
    GROWTH = "growth"
    SUM = "sum"
    AVERAGE = "average"
    COUNT = "count"
    EXTREMUM = "extremum"
    UNSUPPORTED = "unsupported"


class ReturnMode(StrEnum):
    VALUE = "value"
    MEMBER = "member"
    SELECT_AT_ARG = "select_at_arg"
    FILTERED_VALUE = "filtered_value"


@dataclass(frozen=True, slots=True)
class QuestionAnnotations:
    entities: tuple[str, ...]
    periods: tuple[str, ...]
    basis: Basis
    requested_unit: UnitSpec
    operation: OperationKind
    mode: str
    rank_direction: RankDirection | None = None
    return_mode: ReturnMode = ReturnMode.VALUE
    reverse_difference: bool = False
    absolute_difference: bool = False
    operation_evidence: str | None = None


class QuestionAnnotator(Protocol):
    def annotate(self, question: str) -> QuestionAnnotations: ...


@dataclass(frozen=True, slots=True)
class QuestionMetricMention:
    start: int
    end: int
    surface: str
    normalized_surface: str


@dataclass(frozen=True, slots=True)
class MetricHypothesis:
    mention: QuestionMetricMention
    source_metric_id: str
    source_build_id: str
    aliases: tuple[str, ...]
    metric_codes: tuple[str, ...]
    row_paths: tuple[str, ...]
    statement_types: tuple[str, ...]
    unit: UnitSpec
    period_semantics: PeriodSemantics
    preferred_basis: Basis
    match_method: str
    score: tuple[int, int, int]
    supporting_observations: int

    def to_dict(self) -> dict[str, object]:
        return {
            "mention": {
                "start": self.mention.start,
                "end": self.mention.end,
                "surface": self.mention.surface,
                "normalized_surface": self.mention.normalized_surface,
            },
            "source_metric_id": self.source_metric_id,
            "source_build_id": self.source_build_id,
            "aliases": list(self.aliases),
            "metric_codes": list(self.metric_codes),
            "row_paths": list(self.row_paths),
            "statement_types": list(self.statement_types),
            "unit": self.unit.to_dict(),
            "period_semantics": self.period_semantics.value,
            "preferred_basis": self.preferred_basis.value,
            "match_method": self.match_method,
            "score": list(self.score),
            "supporting_observations": self.supporting_observations,
        }


@dataclass(frozen=True, slots=True)
class MetricResolutionResult:
    status: str
    selected: tuple[MetricHypothesis, ...] = ()
    hypotheses: tuple[MetricHypothesis, ...] = ()
    reason: str | None = None
    trace: tuple[dict[str, object], ...] = field(default_factory=tuple)


class MetricMentionResolver(Protocol):
    @property
    def fingerprint(self) -> str: ...

    def resolve(
        self, question: str, annotations: QuestionAnnotations
    ) -> MetricResolutionResult: ...


@dataclass(frozen=True, slots=True)
class ParseResult:
    status: str
    ast: QuestionAST | None = None
    reason: str | None = None
    trace: tuple[dict[str, object], ...] = field(default_factory=tuple)
    source_bindings: tuple[MetricBindingHint, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status == "OK"


@dataclass(frozen=True, slots=True)
class ParseCandidate:
    """One deterministic semantic-program hypothesis and its provenance."""

    candidate_id: str
    result: ParseResult
    source: str
    semantic_score: float
    metric_hypothesis_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "status": self.result.status,
            "reason": self.result.reason,
            "ast": None if self.result.ast is None else self.result.ast.to_dict(),
            "source": self.source,
            "semantic_score": self.semantic_score,
            "metric_hypothesis_ids": list(self.metric_hypothesis_ids),
            "trace": list(self.result.trace),
        }
