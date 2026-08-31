from __future__ import annotations

from dataclasses import dataclass

from text2pandas.application.parsing import (
    MetricHypothesis,
    MetricResolutionResult,
    OperationKind,
    QuestionAnnotations,
    QuestionMetricMention,
)
from text2pandas.application.selection import ReviewedMetricResolver
from text2pandas.domain.semantic import Basis, Dimension, PeriodSemantics, UnitSpec
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.semantic import load_metric_resolver_policy


def _annotations(operation: OperationKind = OperationKind.LOOKUP) -> QuestionAnnotations:
    return QuestionAnnotations(
        entities=("AAA",),
        periods=("2024",),
        basis=Basis.CONSOLIDATED,
        requested_unit=UnitSpec(Dimension.MONEY),
        operation=operation,
        mode="lookup",
    )


@dataclass
class _Fallback:
    result: MetricResolutionResult

    @property
    def fingerprint(self) -> str:
        return "fixture-fallback"

    def resolve(
        self, question: str, annotations: QuestionAnnotations
    ) -> MetricResolutionResult:
        _ = question, annotations
        return self.result


def _source_hypothesis(
    *,
    surface: str = "CFO",
    aliases: tuple[str, ...] = ("Lưu chuyển tiền thuần từ hoạt động kinh doanh",),
    statement_types: tuple[str, ...] = ("cash_flow",),
) -> MetricHypothesis:
    return MetricHypothesis(
        mention=QuestionMetricMention(0, len(surface), surface, surface.casefold()),
        source_metric_id="source-fixture",
        source_build_id="fixture-build",
        aliases=aliases,
        metric_codes=("20",),
        row_paths=aliases,
        statement_types=statement_types,
        unit=UnitSpec(Dimension.MONEY),
        period_semantics=PeriodSemantics.UNKNOWN,
        preferred_basis=Basis.CONSOLIDATED,
        match_method="a6_scoped_contiguous_ngram",
        score=(4, 1000, 4),
        supporting_observations=10,
    )


def _resolver(fallback: _Fallback | None = None) -> ReviewedMetricResolver:
    return ReviewedMetricResolver(
        load_ontology(),
        load_metric_resolver_policy(),
        fallback,
    )


def test_every_reviewed_metric_has_a_positive_exact_resolution() -> None:
    ontology = load_ontology()
    resolver = _resolver()

    for metric in ontology.metrics.values():
        if metric.review_status != "reviewed":
            continue
        question = f"{metric.aliases[0]} cua AAA nam 2024"
        result = resolver.resolve(question, _annotations())
        assert result.resolved, (metric.metric_id, result.to_dict())
        assert result.selected_metric_id == metric.metric_id


def test_accented_and_unaccented_questions_resolve_to_same_metric() -> None:
    resolver = _resolver()

    accented = resolver.resolve("Lợi nhuận gộp của AAA năm 2024", _annotations())
    plain = resolver.resolve("loi nhuan gop cua AAA nam 2024", _annotations())

    assert accented.selected_metric_id == plain.selected_metric_id == "gross_profit"
    assert accented.resolution_method == "NORMALIZED_ALIAS"
    assert plain.resolution_method == "EXACT_ALIAS"
    assert accented.mentions[0].surface == "Lợi nhuận gộp"


def test_longest_alias_owns_nested_parent_match() -> None:
    result = _resolver().resolve(
        "Tài sản cố định hữu hình của AAA năm 2024", _annotations()
    )

    assert result.resolved
    assert result.selected_metric_id == "tangible_fixed_assets"


def test_forbidden_parent_child_and_qualifier_fail_closed() -> None:
    resolver = _resolver()

    liabilities = resolver.resolve("Nợ phải trả người bán của AAA năm 2024", _annotations())
    parent_pat = resolver.resolve(
        "Lợi nhuận sau thuế của cổ đông công ty mẹ AAA năm 2024", _annotations()
    )

    assert liabilities.status == "UNRESOLVED"
    assert liabilities.reason == "FORBIDDEN_QUALIFIER"
    assert parent_pat.status == "UNRESOLVED"
    assert parent_pat.reason == "FORBIDDEN_QUALIFIER"


def test_generic_and_multiple_metric_questions_are_ambiguous() -> None:
    resolver = _resolver()

    generic = resolver.resolve("Doanh thu của AAA năm 2024", _annotations())
    multiple = resolver.resolve(
        "Doanh thu thuần và lợi nhuận gộp của AAA năm 2024", _annotations()
    )

    assert generic.status == "AMBIGUOUS"
    assert generic.reason == "GENERIC_METRIC_PHRASE"
    assert multiple.status == "AMBIGUOUS"
    assert multiple.reason == "MULTIPLE_REVIEWED_METRICS"
    assert multiple.candidates == ("gross_profit", "net_revenue")


def test_source_fallback_maps_only_to_one_reviewed_metric_and_keeps_codes() -> None:
    hypothesis = _source_hypothesis()
    resolver = _resolver(_Fallback(MetricResolutionResult("RESOLVED", selected=(hypothesis,))))

    result = resolver.resolve("CFO của AAA năm 2024", _annotations())

    assert result.resolved
    assert result.selected_metric_id == "cash_flow_from_operations"
    assert result.resolution_method == "SOURCE_LABEL"
    assert result.mentions[0].metric_codes == ("20",)


def test_source_fallback_cannot_promote_unreviewed_source_label() -> None:
    hypothesis = _source_hypothesis(
        surface="Phí dịch vụ",
        aliases=("Chi phí dịch vụ mua ngoài",),
        statement_types=("note",),
    )
    resolver = _resolver(_Fallback(MetricResolutionResult("RESOLVED", selected=(hypothesis,))))

    result = resolver.resolve("Phí dịch vụ của AAA năm 2024", _annotations())

    assert result.status == "UNRESOLVED"
    assert result.reason == "SOURCE_LABEL_OUTSIDE_REVIEWED_METRICS"


def test_source_ambiguity_and_unsupported_operation_are_not_forced() -> None:
    ambiguous = _resolver(
        _Fallback(
            MetricResolutionResult("ABSTAIN", reason="METRIC_HYPOTHESES_AMBIGUOUS")
        )
    ).resolve("Chỉ tiêu dịch vụ của AAA năm 2024", _annotations())
    unsupported = _resolver().resolve(
        "Lợi nhuận gộp chia cho chỉ tiêu khác", _annotations(OperationKind.DIVIDE)
    )

    assert ambiguous.status == "AMBIGUOUS"
    assert unsupported.resolved
    assert unsupported.operation_eligible is False
    assert unsupported.reason == "OPERATION_NOT_ELIGIBLE"
