from __future__ import annotations

from text2pandas.domain.metrics import expression_metric_ids
from text2pandas.domain.semantic import Arithmetic, ArithmeticOperator
from text2pandas.infrastructure.ontology import load_ontology, normalize_phrase


def test_reviewed_sources_load_as_one_validated_ontology() -> None:
    ontology = load_ontology()

    assert ontology.schema_version == 3
    assert sum(metric.review_status == "reviewed" for metric in ontology.metrics.values()) == 24
    assert sum(metric.review_status == "reported" for metric in ontology.metrics.values()) > 300
    assert len(ontology.formulas) == 24
    assert ontology.validate() == ()
    assert len(ontology.fingerprint) == 64


def test_reported_catalog_is_versioned_but_not_promoted_to_reviewed_semantics() -> None:
    ontology = load_ontology()
    metric = ontology.match_metric(normalize_phrase("Chi phí dịch vụ mua ngoài năm 2024"))

    assert metric is not None
    assert metric.review_status == "reported"
    assert metric.legal_aggregations == ("lookup",)


def test_formula_leaves_are_derived_from_the_semantic_expression() -> None:
    ontology = load_ontology()
    quick_ratio = ontology.formulas["quick_ratio"]

    assert expression_metric_ids(quick_ratio.expression) == frozenset(quick_ratio.leaves)
    assert isinstance(quick_ratio.expression, Arithmetic)
    assert quick_ratio.expression.operator == ArithmeticOperator.DIVIDE


def test_longest_specific_alias_wins_for_metric_and_formula() -> None:
    ontology = load_ontology()

    metric = ontology.match_metric(normalize_phrase("Tài sản cố định hữu hình năm 2024"))
    formula = ontology.match_formula(
        normalize_phrase("Tỷ trọng tài sản cố định hữu hình trên tổng tài sản")
    )

    assert metric is not None and metric.metric_id == "tangible_fixed_assets"
    assert formula is not None and formula.formula_id == "tangible_fixed_assets_to_assets"
