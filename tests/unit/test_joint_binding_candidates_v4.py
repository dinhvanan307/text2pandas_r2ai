from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from text2pandas.application.binding import JointBinder
from text2pandas.application.parsing import OperationKind, QuestionAnnotations, SemanticParser
from text2pandas.application.planning import compile_execution_plan
from text2pandas.application.retrieval import CandidateBatch, ObservationCandidate
from text2pandas.domain.semantic import (
    Basis,
    Dimension,
    ObservationRowRole,
    UnitSpec,
)
from text2pandas.infrastructure.ontology import load_ontology


class _Annotator:
    def annotate(self, question: str) -> QuestionAnnotations:
        return QuestionAnnotations(
            entities=("VCB", "BID"),
            periods=("2024",),
            basis=Basis.CONSOLIDATED,
            requested_unit=UnitSpec(Dimension.PERCENT),
            operation=OperationKind.AVERAGE,
            mode="screen",
        )


def _formula_plan():
    ontology = load_ontology()
    parsed = SemanticParser(ontology, _Annotator()).parse(
        "Biên lợi nhuận ròng bình quân của VCB và BID năm 2024?"
    )
    assert parsed.ast is not None
    return compile_execution_plan(parsed.ast, ontology)


def _candidate(request, uid: str, document: str, score: float) -> ObservationCandidate:
    return ObservationCandidate(
        observation_uid=uid,
        table_uid=f"table:{uid}",
        document_id=document,
        entity=request.entity or "?",
        basis=Basis.CONSOLIDATED,
        statement_type="income_statement",
        metric_id=request.metric_id,
        row_path=request.metric_id,
        column_path="2024",
        period="2024-12-31",
        period_role="current",
        value=Decimal(100),
        value_raw="100",
        unit=UnitSpec(Dimension.MONEY, 6, "VND"),
        is_restated=False,
        score=score,
        score_reasons=("fixture",),
        grid_row=1,
        grid_column=1,
    )


def _two_operand_fixture():
    plan = _formula_plan()
    entity = plan.requests[0].entity
    requests = tuple(request for request in plan.requests if request.entity == entity)
    request_ids = {request.request_id for request in requests}
    scoped = replace(
        plan,
        requests=requests,
        constraints=tuple(
            constraint
            for constraint in plan.constraints
            if set(constraint.request_ids).issubset(request_ids)
        ),
    )
    left, right = requests
    batches = {
        left.request_id: CandidateBatch(
            left.request_id,
            (
                _candidate(left, "left-a", "doc-a", 10.0),
                replace(
                    _candidate(left, "left-b", "doc-b", 8.0),
                    value=Decimal(80),
                ),
            ),
            {},
        ),
        right.request_id: CandidateBatch(
            right.request_id,
            (
                _candidate(right, "right-a", "doc-a", 9.0),
                replace(
                    _candidate(right, "right-b", "doc-b", 7.0),
                    value=Decimal(80),
                ),
            ),
            {},
        ),
    }
    return scoped, batches


def test_binding_search_returns_ranked_semantically_distinct_assignments() -> None:
    plan, batches = _two_operand_fixture()

    result = JointBinder().bind_candidates(plan, batches, limit=4)

    assert result.ok
    assert [candidate.total_score for candidate in result.candidates] == [19.0, 15.0]
    assert result.candidates[0].score_margin == 4.0
    assert result.candidates[1].score_margin is None
    selected_documents = [
        {operand.candidate.document_id for operand in candidate.operands.values()}
        for candidate in result.candidates
    ]
    assert selected_documents == [{"doc-a"}, {"doc-b"}]


def test_binding_search_limit_and_missing_batch_are_explicit() -> None:
    plan, batches = _two_operand_fixture()

    limited = JointBinder().bind_candidates(plan, batches, limit=1)
    missing = JointBinder().bind_candidates(
        plan,
        {next(iter(batches)): next(iter(batches.values()))},
    )

    assert len(limited.candidates) == 1
    assert not missing.ok
    assert missing.reason.startswith("MISSING_CANDIDATE_BATCH:")


def test_canonical_bind_still_fails_closed_on_non_equivalent_tie() -> None:
    plan, batches = _two_operand_fixture()
    tied_batches = {
        request_id: replace(
            batch,
            candidates=tuple(replace(candidate, score=10.0) for candidate in batch.candidates),
        )
        for request_id, batch in batches.items()
    }

    result = JointBinder().bind(plan, tied_batches)

    assert not result.ok
    assert result.reason == "BINDING_TIE"


def test_same_number_different_row_role_remains_semantically_distinct() -> None:
    plan, batches = _two_operand_fixture()
    request = plan.requests[0]
    scoped = replace(plan, requests=(request,), constraints=())
    total = replace(
        _candidate(request, "total", "doc-a", 10.0),
        row_uid="row-total",
        row_hierarchy=("Hàng tồn kho", "Tổng cộng"),
        row_role=ObservationRowRole.TOTAL,
    )
    allowance = replace(
        total,
        observation_uid="allowance",
        row_uid="row-allowance",
        row_hierarchy=("Hàng tồn kho", "Dự phòng"),
        row_role=ObservationRowRole.ALLOWANCE,
    )

    result = JointBinder().bind_candidates(
        scoped,
        {request.request_id: CandidateBatch(request.request_id, (total, allowance), {})},
        limit=3,
    )

    assert result.ok
    assert len(result.candidates) == 2


def test_physical_duplicate_with_same_semantic_identity_is_collapsed() -> None:
    plan, _ = _two_operand_fixture()
    request = plan.requests[0]
    scoped = replace(plan, requests=(request,), constraints=())
    first = replace(
        _candidate(request, "physical-a", "doc-a", 10.0),
        row_uid="row-1",
        column_uid="column-1",
        row_hierarchy=("Doanh thu",),
        column_hierarchy=("Năm nay",),
    )
    duplicate = replace(first, observation_uid="physical-b", table_uid="table:other")

    result = JointBinder().bind_candidates(
        scoped,
        {request.request_id: CandidateBatch(request.request_id, (first, duplicate), {})},
        limit=3,
    )

    assert result.ok
    assert len(result.candidates) == 1
