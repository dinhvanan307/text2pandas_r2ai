from __future__ import annotations

from text2pandas.application.planning import compile_execution_plan
from text2pandas.domain.semantic import (
    Basis,
    Dimension,
    MetricRef,
    ObservationColumnRole,
    ObservationRoleSpec,
    ObservationRowRole,
    ObservationSignMode,
    OutputSpec,
    QuestionAST,
    ResultKind,
    UnitSpec,
)
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.retrieval.observation_roles import (
    load_observation_role_policy,
)


def _role(*, row_role: ObservationRowRole) -> ObservationRoleSpec:
    return ObservationRoleSpec(
        source_metric_id="source:inventory-cost",
        accepted_source_metric_codes=("141",),
        exact_row_labels=("Hàng tồn kho › Giá gốc",),
        required_row_path_tokens=("giá gốc",),
        forbidden_row_path_tokens=("dự phòng",),
        allowed_row_roles=(row_role,),
        allowed_column_roles=(ObservationColumnRole.CLOSING,),
        allowed_period_roles=("closing",),
        sign_mode=ObservationSignMode.AS_REPORTED,
        allowed_scale_sources=("column_path",),
        entity_membership=("HNG",),
    )


def _ast(role: ObservationRoleSpec) -> QuestionAST:
    return QuestionAST(
        expression=MetricRef(
            "inventory",
            entities=("HNG",),
            periods=("2024",),
            basis=Basis.CONSOLIDATED,
            expected_unit=UnitSpec(Dimension.MONEY, 0, "VND"),
            observation_role=role,
        ),
        output=OutputSpec(ResultKind.SCALAR, UnitSpec(Dimension.MONEY, 0, "VND")),
        question="Hàng tồn kho giá gốc cuối năm 2024 của HNG?",
        qid=1,
    )


def test_observation_role_round_trips_through_ast_and_plan() -> None:
    role = _role(row_role=ObservationRowRole.COST)
    ast = _ast(role)
    restored = QuestionAST.from_dict(ast.to_dict())
    plan = compile_execution_plan(restored, load_ontology())

    assert restored == ast
    assert plan.requests[0].observation_role == role
    assert plan.requests[0].to_dict()["observation_role"] == role.to_dict()


def test_observation_role_changes_plan_fingerprint() -> None:
    ontology = load_ontology()
    cost = compile_execution_plan(
        _ast(_role(row_role=ObservationRowRole.COST)), ontology
    )
    allowance = compile_execution_plan(
        _ast(_role(row_role=ObservationRowRole.ALLOWANCE)), ontology
    )

    assert cost.fingerprint != allowance.fingerprint


def test_versioned_policy_classifies_rows_columns_and_safe_scales() -> None:
    policy = load_observation_role_policy()

    assert policy.classify_row("Hàng tồn kho › Giá gốc") == ObservationRowRole.COST
    assert policy.classify_row("Hàng tồn kho › Dự phòng") == ObservationRowRole.ALLOWANCE
    assert policy.classify_row("Tài sản › Tiền") == ObservationRowRole.CHILD
    assert policy.classify_column("Số cuối năm", None) == ObservationColumnRole.CLOSING
    assert policy.classify_column("", "prior") == ObservationColumnRole.PRIOR
    assert "none" not in policy.strict_money_scale_sources
    assert len(policy.fingerprint) == 64
