from __future__ import annotations

from text2pandas.domain.metrics import expression_metric_ids
from text2pandas.domain.semantic import Arithmetic, ArithmeticOperator
from text2pandas.infrastructure.ontology import load_ontology, normalize_phrase


def test_reviewed_sources_load_as_one_validated_ontology() -> None:
    ontology = load_ontology()

    assert ontology.schema_version == 3
    assert len(ontology.metrics) == 24
    assert len(ontology.formulas) == 24
    assert ontology.validate() == ()
    assert len(ontology.fingerprint) == 64


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

