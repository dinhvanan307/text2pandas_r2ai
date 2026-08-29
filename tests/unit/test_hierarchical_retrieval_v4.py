from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from text2pandas.application.planning import OperandRequest
from text2pandas.application.retrieval import (
    CandidateBatch,
    HierarchicalOperandRetriever,
    HierarchicalRetrievalPolicy,
    ObservationCandidate,
    rank_candidate_tables,
)
from text2pandas.domain.semantic import Basis, Dimension, PeriodSemantics, UnitSpec


class _StaticRetriever:
    def __init__(self, candidates: tuple[ObservationCandidate, ...]) -> None:
        self.candidates = candidates

    def retrieve(self, request: OperandRequest) -> CandidateBatch:
        return CandidateBatch(request.request_id, self.candidates, {"base": "fixture"})


def _request(request_id: str = "operand:assets") -> OperandRequest:
    return OperandRequest(
        request_id=request_id,
        metric_id="total_assets",
        entity="VCB",
        period="2024",
        basis=Basis.CONSOLIDATED,
        preferred_basis=Basis.CONSOLIDATED,
        statement_types=("balance_sheet",),
        expected_unit=UnitSpec(Dimension.MONEY),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
        qualifiers=(),
        consumers=("$.expression",),
    )


def _candidate(uid: str, table_uid: str, score: float) -> ObservationCandidate:
    return ObservationCandidate(
        observation_uid=uid,
        table_uid=table_uid,
        logical_table_uid="logical:" + table_uid,
        document_id="VCB-2024",
        entity="VCB",
        basis=Basis.CONSOLIDATED,
        statement_type="balance_sheet",
        metric_id="total_assets",
        row_path="Tài sản › Tổng cộng",
        row_hierarchy=("Tài sản", "Tổng cộng"),
        column_path="2024 › Cuối năm",
        column_hierarchy=("2024", "Cuối năm"),
        period="2024-12-31",
        period_role="closing",
        value=Decimal(1000),
        value_raw="1.000",
        unit=UnitSpec(Dimension.MONEY, 6, "VND"),
        is_restated=False,
        score=score,
        score_reasons=("metric:exact",),
        grid_row=10,
        grid_column=2,
        match_method="row_leaf_raw_exact",
        source_metric_code="total_assets",
    )


def test_hierarchical_retriever_deduplicates_logical_facts_and_penalises_collisions() -> None:
    best = _candidate("best", "table-a", 20.0)
    duplicate_fragment = replace(
        best,
        observation_uid="duplicate",
        table_uid="table-a-fragment",
        logical_table_uid="logical:table-a",
        score=19.0,
    )
    collision = replace(
        best,
        observation_uid="collision",
        table_uid="table-b",
        logical_table_uid="logical:table-b",
        score=21.0,
        readiness="recoverable",
        collision_class="missing_row_parent",
        source_confidence=0.6,
        value=Decimal(900),
    )
    retriever = HierarchicalOperandRetriever(
        _StaticRetriever((collision, duplicate_fragment, best)),
        HierarchicalRetrievalPolicy(top_k=5),
    )

    batch = retriever.retrieve(_request())

    assert [candidate.observation_uid for candidate in batch.candidates] == [
        "best",
        "collision",
    ]
    assert batch.trace["semantic_duplicates_removed"] == 1
    assert batch.trace["logical_table_count"] == 2
    assert batch.trace["hierarchical_retrieval"] == "hierarchical-fact-retrieval-v1"


def test_candidate_table_ranking_rewards_cross_operand_support() -> None:
    shared_low = _candidate("shared-low", "shared", 10.0)
    unique_high = _candidate("unique-high", "unique", 20.0)
    shared_second = replace(shared_low, observation_uid="shared-second", score=9.0)
    batches = {
        "operand:a": CandidateBatch("operand:a", (unique_high, shared_low), {}),
        "operand:b": CandidateBatch("operand:b", (shared_second,), {}),
    }

    assert rank_candidate_tables(batches) == ("shared", "unique")


def test_logical_table_diversity_is_bounded_by_policy() -> None:
    candidates = tuple(
        replace(
            _candidate(f"obs-{index}", "same", 20.0 - index),
            value=Decimal(1000 + index),
        )
        for index in range(5)
    )
    retriever = HierarchicalOperandRetriever(
        _StaticRetriever(candidates),
        HierarchicalRetrievalPolicy(top_k=5, max_per_logical_table=2),
    )

    batch = retriever.retrieve(_request())

    assert len(batch.candidates) == 2
    assert batch.trace["logical_diversity_rejected"] == 3
