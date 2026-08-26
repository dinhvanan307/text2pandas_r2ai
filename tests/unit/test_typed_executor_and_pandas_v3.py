from __future__ import annotations

from decimal import Decimal

import pandas as pd

from text2pandas.application.binding import JointBinder
from text2pandas.application.execution import TypedExecutor, compile_pandas
from text2pandas.application.parsing import (
    OperationKind,
    QuestionAnnotations,
    ReturnMode,
    SemanticParser,
)
from text2pandas.application.planning import compile_execution_plan
from text2pandas.application.retrieval import CandidateBatch, ObservationCandidate
from text2pandas.domain.semantic import Basis, Dimension, RankDirection, UnitSpec
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.sandbox.query import execute_query


class StaticAnnotator:
    def __init__(self, annotations):
        self.annotations = annotations

    def annotate(self, question):
        return self.annotations


def _bound_formula():
    ontology = load_ontology()
    annotations = QuestionAnnotations(
        entities=("VCB",),
        periods=("2024",),
        basis=Basis.CONSOLIDATED,
        requested_unit=UnitSpec(Dimension.PERCENT),
        operation=OperationKind.DIVIDE,
        mode="single",
    )
    parsed = SemanticParser(ontology, StaticAnnotator(annotations)).parse(
        "Biên lợi nhuận ròng của VCB năm 2024 là bao nhiêu phần trăm?"
    )
    assert parsed.ok
    plan = compile_execution_plan(parsed.ast, ontology)
    values = {"profit_after_tax": Decimal(20), "net_revenue": Decimal(100)}
    batches = {}
    for request in plan.requests:
        candidate = ObservationCandidate(
            observation_uid=f"obs:{request.metric_id}",
            table_uid="table:income",
            document_id="VCB-2024",
            entity="VCB",
            basis=Basis.CONSOLIDATED,
            statement_type="income_statement",
            metric_id=request.metric_id,
            row_path=request.metric_id,
            column_path="2024",
            period="2024-12-31",
            period_role="current",
            value=values[request.metric_id],
            value_raw=str(values[request.metric_id]),
            unit=UnitSpec(Dimension.MONEY, 6, "VND"),
            is_restated=False,
            score=10.0,
            score_reasons=("fixture",),
            grid_row=1,
            grid_column=1,
        )
        batches[request.request_id] = CandidateBatch(request.request_id, (candidate,), {})
    binding = JointBinder().bind(plan, batches)
    assert binding.ok
    return binding.bound_plan


def test_typed_formula_and_pandas_program_replay_to_same_percent() -> None:
    bound = _bound_formula()

    typed = TypedExecutor().execute(bound)
    compiled = compile_pandas(bound)

    assert typed.ok and typed.answer == Decimal(20)
    assert compiled.ok
    frame = pd.DataFrame(
        {
            "observation_uid": ["obs:profit_after_tax", "obs:net_revenue"],
            "value": [20.0, 100.0],
        }
    )
    replayed = execute_query(compiled.program.query, {"df1": frame})
    assert replayed == 20.0
    assert compiled.program.evidence[0].observation_uids == (
        "obs:net_revenue",
        "obs:profit_after_tax",
    )


def test_select_at_arg_executes_rank_metric_then_returns_a_different_metric() -> None:
    ontology = load_ontology()
    annotations = QuestionAnnotations(
        entities=("VCB", "BID"),
        periods=("2024",),
        basis=Basis.CONSOLIDATED,
        requested_unit=UnitSpec(Dimension.MONEY, 6, "VND"),
        operation=OperationKind.EXTREMUM,
        mode="screen",
        rank_direction=RankDirection.DESCENDING,
        return_mode=ReturnMode.SELECT_AT_ARG,
    )
    parsed = SemanticParser(ontology, StaticAnnotator(annotations)).parse(
        "Công ty có tổng tài sản lớn nhất có lợi nhuận sau thuế bao nhiêu triệu đồng?"
    )
    assert parsed.ok
    plan = compile_execution_plan(parsed.ast, ontology)
    values = {
        ("total_assets", "VCB"): Decimal(100),
        ("total_assets", "BID"): Decimal(200),
        ("profit_after_tax", "VCB"): Decimal(10),
        ("profit_after_tax", "BID"): Decimal(30),
    }
    batches = {}
    for request in plan.requests:
        uid = f"obs:{request.metric_id}:{request.entity}"
        candidate = ObservationCandidate(
            observation_uid=uid,
            table_uid=f"table:{request.entity}",
            document_id=f"{request.entity}-2024",
            entity=request.entity,
            basis=Basis.CONSOLIDATED,
            statement_type="balance_sheet",
            metric_id=request.metric_id,
            row_path=request.metric_id,
            column_path="2024",
            period="2024-12-31",
            period_role="current",
            value=values[(request.metric_id, request.entity)],
            value_raw=str(values[(request.metric_id, request.entity)]),
            unit=UnitSpec(Dimension.MONEY, 6, "VND"),
            is_restated=False,
            score=10.0,
            score_reasons=("fixture",),
            grid_row=1,
            grid_column=1,
        )
        batches[request.request_id] = CandidateBatch(request.request_id, (candidate,), {})
    binding = JointBinder().bind(plan, batches)
    assert binding.ok

    typed = TypedExecutor().execute(binding.bound_plan)
    compiled = compile_pandas(binding.bound_plan)

    assert typed.ok and typed.answer == Decimal(30)
    assert compiled.ok
    frames = {}
    for evidence in compiled.program.evidence:
        rows = [
            operand.candidate
            for operand in binding.bound_plan.operands.values()
            if operand.candidate.table_uid == evidence.table_uid
        ]
        frames[evidence.variable] = pd.DataFrame(
            {
                "observation_uid": [row.observation_uid for row in rows],
                "value": [float(row.value) for row in rows],
            }
        )
    assert execute_query(compiled.program.query, frames) == 30.0


def test_filtered_minimum_executes_and_compiles_the_same_qualifying_periods() -> None:
    ontology = load_ontology()
    annotations = QuestionAnnotations(
        entities=("ASM",),
        periods=("2016", "2017", "2018"),
        basis=Basis.CONSOLIDATED,
        requested_unit=UnitSpec(Dimension.MONEY, 6, "VND"),
        operation=OperationKind.EXTREMUM,
        mode="single",
        rank_direction=RankDirection.ASCENDING,
        return_mode=ReturnMode.FILTERED_VALUE,
    )
    parsed = SemanticParser(ontology, StaticAnnotator(annotations)).parse(
        "Trong các năm 2016, 2017 và 2018 của ASM, xét các năm có tỷ lệ lợi "
        "nhuận sau thuế trên doanh thu thuần lớn hơn 10%, doanh thu thuần thấp "
        "nhất là bao nhiêu triệu đồng?"
    )
    assert parsed.ok
    plan = compile_execution_plan(parsed.ast, ontology)
    values = {
        ("profit_after_tax", "2016"): Decimal(5),
        ("net_revenue", "2016"): Decimal(100),
        ("profit_after_tax", "2017"): Decimal(30),
        ("net_revenue", "2017"): Decimal(200),
        ("profit_after_tax", "2018"): Decimal(18),
        ("net_revenue", "2018"): Decimal(150),
    }
    batches = {}
    for request in plan.requests:
        uid = f"obs:{request.metric_id}:{request.period}"
        candidate = ObservationCandidate(
            observation_uid=uid,
            table_uid=f"table:{request.period}",
            document_id=f"ASM-{request.period}",
            entity="ASM",
            basis=Basis.CONSOLIDATED,
            statement_type="income_statement",
            metric_id=request.metric_id,
            row_path=request.metric_id,
            column_path=request.period or "",
            period=f"{request.period}-12-31",
            period_role="current",
            value=values[(request.metric_id, request.period)],
            value_raw=str(values[(request.metric_id, request.period)]),
            unit=UnitSpec(Dimension.MONEY, 6, "VND"),
            is_restated=False,
            score=10.0,
            score_reasons=("fixture",),
            grid_row=1,
            grid_column=1,
        )
        batches[request.request_id] = CandidateBatch(request.request_id, (candidate,), {})
    binding = JointBinder().bind(plan, batches)
    assert binding.ok

    typed = TypedExecutor().execute(binding.bound_plan)
    compiled = compile_pandas(binding.bound_plan)

    assert typed.ok and typed.answer == Decimal(150)
    assert compiled.ok
    frames = {}
    for evidence in compiled.program.evidence:
        rows = [
            operand.candidate
            for operand in binding.bound_plan.operands.values()
            if operand.candidate.table_uid == evidence.table_uid
        ]
        frames[evidence.variable] = pd.DataFrame(
            {
                "observation_uid": [row.observation_uid for row in rows],
                "value": [float(row.value) for row in rows],
            }
        )
    assert execute_query(compiled.program.query, frames) == 150.0
