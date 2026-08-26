"""Immutable planning contracts between semantic parsing and retrieval."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from text2pandas.domain.semantic import Basis, PeriodSemantics, QuestionAST, UnitSpec


class ConstraintKind(StrEnum):
    SAME_DOCUMENT = "same_document"
    SAME_CURRENCY = "same_currency"
    DISTINCT_OBSERVATIONS = "distinct_observations"


@dataclass(frozen=True, slots=True)
class OperandRequest:
    request_id: str
    metric_id: str
    entity: str | None
    period: str | None
    basis: Basis
    preferred_basis: Basis
    statement_types: tuple[str, ...]
    expected_unit: UnitSpec
    period_semantics: PeriodSemantics
    qualifiers: tuple[str, ...]
    consumers: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "metric_id": self.metric_id,
            "entity": self.entity,
            "period": self.period,
            "basis": self.basis.value,
            "preferred_basis": self.preferred_basis.value,
            "statement_types": list(self.statement_types),
            "expected_unit": self.expected_unit.to_dict(),
            "period_semantics": self.period_semantics.value,
            "qualifiers": list(self.qualifiers),
            "consumers": list(self.consumers),
        }


@dataclass(frozen=True, slots=True)
class BindingConstraint:
    kind: ConstraintKind
    request_ids: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "request_ids": list(self.request_ids),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    ast: QuestionAST
    requests: tuple[OperandRequest, ...]
    constraints: tuple[BindingConstraint, ...]
    ontology_fingerprint: str

    @property
    def requests_by_id(self) -> Mapping[str, OperandRequest]:
        return {request.request_id: request for request in self.requests}

    @property
    def fingerprint(self) -> str:
        payload = {
            "ast": self.ast.to_dict(),
            "requests": [request.to_dict() for request in self.requests],
            "constraints": [constraint.to_dict() for constraint in self.constraints],
            "ontology_fingerprint": self.ontology_fingerprint,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

