from __future__ import annotations

from dataclasses import replace

import pytest

from text2pandas.application.selection import SelectorSpec
from text2pandas.domain.metrics import MetricOntology, MetricSpec, OntologyValidationError
from text2pandas.domain.semantic import Basis, Dimension, PeriodSemantics, UnitSpec
from text2pandas.infrastructure.ontology import load_ontology


def test_reviewed_registry_is_the_single_metric_spec_source() -> None:
    ontology = load_ontology()
    reviewed = [metric for metric in ontology.metrics.values() if metric.review_status == "reviewed"]

    assert len(reviewed) == 28
    assert all(isinstance(metric, MetricSpec) for metric in reviewed)
    assert all(metric.expected_dimension != Dimension.UNKNOWN for metric in reviewed)
    assert all(metric.period_semantics != PeriodSemantics.UNKNOWN for metric in reviewed)
    assert all(metric.preferred_statement_types for metric in reviewed)
    assert all(
        metric.legal_aggregations == ("lookup", "subtract", "growth", "sum", "average")
        for metric in reviewed
    )


def test_required_context_is_preserved_from_reviewed_registry() -> None:
    metric = load_ontology().metrics["common_loan_loss_provision"]

    assert metric.required_context_any == ("du phong rui ro cho vay khach hang",)


def test_selector_spec_projects_metric_policy_and_operand_scope() -> None:
    ontology = load_ontology()
    metric = ontology.metrics["profit_after_tax"]

    spec = SelectorSpec.from_metric(
        metric,
        ontology_fingerprint=ontology.fingerprint,
        entity="VJC",
        period="2024",
        requested_period_role="current",
        requested_basis=Basis.CONSOLIDATED,
        metric_codes=("60",),
        resolution_confidence=0.99,
    )

    assert spec.metric_id == "profit_after_tax"
    assert spec.entity == "VJC"
    assert spec.period == "2024"
    assert spec.expected_dimension == Dimension.MONEY
    assert spec.allowed_statement_types == ("income_statement",)
    assert "cong ty me" in spec.forbidden_contains
    assert spec.metric_codes == ("60",)


def test_selector_spec_rejects_reported_or_unknown_metric_contract() -> None:
    ontology = load_ontology()
    reported = next(
        metric for metric in ontology.metrics.values() if metric.review_status == "reported"
    )

    with pytest.raises(ValueError, match="reviewed metric"):
        SelectorSpec.from_metric(
            reported,
            ontology_fingerprint=ontology.fingerprint,
            entity=None,
            period=None,
            requested_period_role=None,
            requested_basis=Basis.UNSPECIFIED,
        )


@pytest.mark.parametrize(
    ("changes", "issue_code"),
    [
        ({"aliases": ("Lợi nhuận", "loi nhuan")}, "METRIC_ALIAS_DUPLICATE"),
        ({"unit": UnitSpec(Dimension.UNKNOWN)}, "METRIC_DIMENSION"),
        ({"statement_types": ("unsupported_statement",)}, "METRIC_STATEMENT_TYPES"),
        (
            {"aliases": ("loi nhuan",), "forbidden_contains": ("loi nhuan",)},
            "METRIC_ALIASES_FORBIDDEN",
        ),
    ],
)
def test_reviewed_metric_contract_fails_closed(
    changes: dict[str, object], issue_code: str
) -> None:
    base = load_ontology().metrics["gross_profit"]
    metric = replace(base, **changes)

    with pytest.raises(OntologyValidationError) as raised:
        MetricOntology("test", 3, {metric.metric_id: metric}, {})

    assert issue_code in {issue.code for issue in raised.value.issues}
