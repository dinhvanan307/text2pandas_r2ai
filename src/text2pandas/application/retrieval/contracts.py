"""Candidate values returned for one semantic operand request."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from text2pandas.application.planning import ExecutionPlan, OperandRequest
from text2pandas.domain.semantic import Basis, UnitSpec


@dataclass(frozen=True, slots=True)
class ObservationCandidate:
    observation_uid: str
    table_uid: str
    document_id: str
    entity: str
    basis: Basis
    statement_type: str | None
    metric_id: str
    row_path: str
    column_path: str
    period: str | None
    period_role: str | None
    value: Decimal
    value_raw: str
    unit: UnitSpec
    is_restated: bool
    score: float
    score_reasons: tuple[str, ...]
    grid_row: int
    grid_column: int
    row_uid: str | None = None
    source_metric_code: str | None = None
    matched_metric_id: str | None = None
    match_method: str | None = None
    match_features: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "observation_uid": self.observation_uid,
            "table_uid": self.table_uid,
            "document_id": self.document_id,
            "entity": self.entity,
            "basis": self.basis.value,
            "statement_type": self.statement_type,
            "metric_id": self.metric_id,
            "row_path": self.row_path,
            "column_path": self.column_path,
            "period": self.period,
            "period_role": self.period_role,
            "value": str(self.value),
            "value_raw": self.value_raw,
            "unit": self.unit.to_dict(),
            "is_restated": self.is_restated,
            "score": self.score,
            "score_reasons": list(self.score_reasons),
            "grid_row": self.grid_row,
            "grid_column": self.grid_column,
            "row_uid": self.row_uid,
            "source_metric_code": self.source_metric_code,
            "matched_metric_id": self.matched_metric_id or self.metric_id,
            "match_method": self.match_method,
            "match_features": list(self.match_features),
        }


@dataclass(frozen=True, slots=True)
class CandidateBatch:
    request_id: str
    candidates: tuple[ObservationCandidate, ...]
    trace: Mapping[str, object]


class OperandRetriever(Protocol):
    def retrieve(self, request: OperandRequest) -> CandidateBatch: ...


def retrieve_operands(
    plan: ExecutionPlan, retriever: OperandRetriever
) -> dict[str, CandidateBatch]:
    return {request.request_id: retriever.retrieve(request) for request in plan.requests}
