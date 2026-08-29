"""Projection from physical A6 observations to canonical logical facts."""

from __future__ import annotations

import hashlib

from text2pandas.application.retrieval import ObservationCandidate
from text2pandas.domain.facts import FactReadiness, FinancialFact, split_hierarchy


def project_candidate(candidate: ObservationCandidate) -> FinancialFact:
    readiness = FactReadiness(candidate.readiness)
    logical_table_uid = candidate.logical_table_uid or candidate.table_uid
    fact_payload = "\x1f".join(
        (
            candidate.observation_uid,
            logical_table_uid,
            candidate.metric_id,
            candidate.period or "",
        )
    )
    return FinancialFact(
        fact_uid="fact:" + hashlib.sha256(fact_payload.encode("utf-8")).hexdigest()[:24],
        observation_uid=candidate.observation_uid,
        table_uid=candidate.table_uid,
        logical_table_uid=logical_table_uid,
        document_id=candidate.document_id,
        entity=candidate.entity,
        basis=candidate.basis,
        statement_type=candidate.statement_type,
        metric_id=candidate.metric_id,
        source_metric_code=candidate.source_metric_code,
        row_uid=candidate.row_uid,
        column_uid=candidate.column_uid,
        row_hierarchy=candidate.row_hierarchy or split_hierarchy(candidate.row_path),
        column_hierarchy=candidate.column_hierarchy or split_hierarchy(candidate.column_path),
        period=candidate.period,
        period_role=candidate.period_role,
        value=candidate.value,
        value_raw=candidate.value_raw,
        unit=candidate.unit,
        is_restated=candidate.is_restated,
        readiness=readiness,
        collision_class=candidate.collision_class,
        source_confidence=candidate.source_confidence,
    )
