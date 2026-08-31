from __future__ import annotations

from text2pandas.application.parsing import (
    MetricHypothesis,
    MetricResolutionResult,
    OperationKind,
    QuestionAnnotations,
    QuestionMetricMention,
    SemanticParser,
)
from text2pandas.domain.semantic import (
    Basis,
    Dimension,
    MetricRef,
    PeriodSemantics,
    UnitSpec,
)
from text2pandas.infrastructure.ontology import load_ontology


class _Annotator:
    def annotate(self, question: str) -> QuestionAnnotations:
        return QuestionAnnotations(
            entities=("VCB",),
            periods=("2024",),
            basis=Basis.CONSOLIDATED,
            requested_unit=UnitSpec(Dimension.MONEY, 6, "VND"),
            operation=OperationKind.LOOKUP,
            mode="single",
        )


class _AmbiguousResolver:
    fingerprint = "fixture-resolver"

    def resolve(
        self,
        question: str,
        annotations: QuestionAnnotations,
    ) -> MetricResolutionResult:
        mention = QuestionMetricMention(0, 12, "Chỉ tiêu lạ", "chi tieu la")
        hypotheses = tuple(
            MetricHypothesis(
                mention=mention,
                source_metric_id=metric_id,
                source_build_id="fixture-build",
                aliases=("Chỉ tiêu lạ",),
                metric_codes=(metric_id,),
                row_paths=(row_path,),
                statement_types=("note",),
                unit=UnitSpec(Dimension.MONEY, 6, "VND"),
                period_semantics=PeriodSemantics.FLOW,
                preferred_basis=Basis.CONSOLIDATED,
                match_method="fixture",
                score=(5, 4, 3),
                supporting_observations=support,
            )
            for metric_id, row_path, support in (
                ("source:metric-a", "Chi phí › Chỉ tiêu lạ A", 20),
                ("source:metric-b", "Chi phí › Chỉ tiêu lạ B", 10),
            )
        )
        return MetricResolutionResult(
            "ABSTAIN",
            hypotheses=hypotheses,
            reason="METRIC_HYPOTHESES_AMBIGUOUS",
        )


def test_nbest_parser_keeps_canonical_abstention_and_compiles_source_alternatives() -> None:
    parser = SemanticParser(load_ontology(), _Annotator(), _AmbiguousResolver())

    candidates = parser.parse_candidates(
        "Chỉ tiêu lạ của VCB năm 2024?",
        qid=42,
        max_candidates=4,
    )

    assert candidates[0].source == "canonical_v3"
    assert candidates[0].result.reason == "METRIC_HYPOTHESES_AMBIGUOUS"
    assert [candidate.metric_hypothesis_ids for candidate in candidates[1:]] == [
        ("source:metric-a",),
        ("source:metric-b",),
    ]
    expressions = [candidate.result.ast.expression for candidate in candidates[1:]]
    assert all(isinstance(expression, MetricRef) for expression in expressions)
    assert [expression.metric_id for expression in expressions] == [
        "source:metric-a",
        "source:metric-b",
    ]
    assert all(candidate.result.ast.qid == 42 for candidate in candidates[1:])


def test_nbest_candidate_ids_are_content_stable() -> None:
    parser = SemanticParser(load_ontology(), _Annotator(), _AmbiguousResolver())

    first = parser.parse_candidates("Chỉ tiêu lạ của VCB năm 2024?")
    second = parser.parse_candidates("Chỉ tiêu lạ của VCB năm 2024?")

    assert [candidate.candidate_id for candidate in first] == [
        candidate.candidate_id for candidate in second
    ]


def test_nbest_limit_is_enforced() -> None:
    parser = SemanticParser(load_ontology(), _Annotator(), _AmbiguousResolver())

    candidates = parser.parse_candidates("Chỉ tiêu lạ của VCB năm 2024?", max_candidates=2)

    assert len(candidates) == 2
