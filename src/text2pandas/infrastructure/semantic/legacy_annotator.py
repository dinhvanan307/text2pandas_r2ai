"""Adapter from the measured Vietnamese lexical recognisers to V3 contracts.

This module is intentionally the only V3 component importing the V2 parser.
It preserves the already measured entity/unit/cue behaviour while semantic
composition moves to `application.parsing.SemanticParser`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from text2pandas.application.parsing.contracts import (
    OperationKind,
    QuestionAnnotations,
    ReturnMode,
)
from text2pandas.domain.semantic import Basis, Dimension, RankDirection, UnitSpec
from text2pandas.domain.units.lexicon import scan_question_unit
from text2pandas.pipelines.answering.frame import (
    RETURN_FILTERED_VALUE,
    RETURN_PERIOD,
    RETURN_SELECT_AT_ARG,
    classify_operation,
)
from text2pandas.pipelines.retrieval.question_intent import parse_intent

_OPERATION = {
    "LOOKUP": OperationKind.LOOKUP,
    "DIVIDE": OperationKind.DIVIDE,
    "SUBTRACT": OperationKind.SUBTRACT,
    "GROWTH": OperationKind.GROWTH,
    "SUM": OperationKind.SUM,
    "AVG": OperationKind.AVERAGE,
    "COUNT": OperationKind.COUNT,
    "EXTREMUM": OperationKind.EXTREMUM,
}

_DIMENSION = {
    "MONEY": Dimension.MONEY,
    "PERCENT": Dimension.PERCENT,
    "PERCENT_POINT": Dimension.PERCENT_POINT,
    "RATIO": Dimension.RATIO,
    "COUNT": Dimension.COUNT,
    "SHARES": Dimension.SHARES,
    "UNKNOWN": Dimension.UNKNOWN,
}


class LegacyVietnameseAnnotator:
    def __init__(self, companies: Mapping[str, str | Sequence[str]]):
        self.companies = companies

    def annotate(self, question: str) -> QuestionAnnotations:
        intent = parse_intent(question, self.companies)
        operation = classify_operation(question)
        dimension, scale, _token = scan_question_unit(question)
        if intent.explicit_scope == "công ty mẹ":
            basis = Basis.SEPARATE
        elif intent.explicit_scope == "hợp nhất":
            basis = Basis.CONSOLIDATED
        else:
            basis = Basis.UNSPECIFIED
        return_modes = {
            RETURN_PERIOD: ReturnMode.MEMBER,
            RETURN_SELECT_AT_ARG: ReturnMode.SELECT_AT_ARG,
            RETURN_FILTERED_VALUE: ReturnMode.FILTERED_VALUE,
        }
        return_mode = (
            return_modes.get(operation.return_mode, ReturnMode.VALUE)
            if operation.return_mode
            else ReturnMode.VALUE
        )
        rank_direction = None
        if operation.rank_direction == "MAX":
            rank_direction = RankDirection.DESCENDING
        elif operation.rank_direction == "MIN":
            rank_direction = RankDirection.ASCENDING
        return QuestionAnnotations(
            entities=intent.targets,
            periods=tuple(str(value) for value in intent.years),
            basis=basis,
            requested_unit=UnitSpec(_DIMENSION[dimension], scale),
            operation=_OPERATION.get(operation.op, OperationKind.UNSUPPORTED),
            mode=intent.mode,
            rank_direction=rank_direction,
            return_mode=return_mode,
            reverse_difference=operation.reverse_difference,
            operation_evidence=operation.matched,
        )
