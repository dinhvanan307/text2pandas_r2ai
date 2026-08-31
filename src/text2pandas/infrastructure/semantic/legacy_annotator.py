"""Adapter from the measured Vietnamese lexical recognisers to V3 contracts.

This module is intentionally the only V3 component importing the V2 parser.
It preserves the already measured entity/unit/cue behaviour while semantic
composition moves to `application.parsing.SemanticParser`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from text2pandas.application.parsing.contracts import (
    OperationKind,
    QuestionAnnotations,
    ReturnMode,
)
from text2pandas.domain.metrics import normalize_phrase
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


_EXPLICIT_TOTAL = re.compile(
    r"(?:^|[,:.]\s*|\bnam\s+(?:19|20)\d{2},\s*)(?:tinh\s+)?tong\s+"
)
_LEGAL_ENTITY_PREFIX = re.compile(r"^tong\s+cong\s+ty\b")
_FILTERED_ENTITY_SELECTION = re.compile(
    r"\bcua\s+(?:cong\s+ty|doanh\s+nghiep)\s+co\b|\btrong\s+so\b"
)
_EXPLICIT_PERIOD_DOMAIN = re.compile(
    r"\b(?:trong|qua|cho|tai)\s+cac\s+nam\b|\btrong\s+giai\s+doan\b"
)
_EXPLICIT_FILTERED_ENTITY_TOTAL = re.compile(
    r"\btong\s+[^,?]{1,80}\s+cua\s+"
    r"(?:cac\s+cong\s+ty|cac\s+doanh\s+nghiep|nhom)\b"
)
_TRAILING_FILTERED_TOTAL = re.compile(
    r"[,;]\s*tong\s+[^,?]{1,100}\s+(?:nam\s+(?:19|20)\d{2}\s+)?"
    r"la\s+bao\s+nhieu\b"
)
_PERCENTAGE_MOVEMENT = re.compile(r"\bty le bien dong\b")


def _aggregate_override(
    question: str,
    *,
    entity_count: int,
    period_count: int,
    operation: OperationKind,
) -> tuple[OperationKind, str | None]:
    """Recover explicit total domains that the legacy cue router cannot see.

    ``Tổng`` is overloaded in financial Vietnamese: it can be part of a legal
    entity name, a reported line label, or an instruction to aggregate.  V3 only
    upgrades it to ``SUM`` when the question also declares a multi-entity or
    multi-period domain.  Filter/select questions remain fail-closed instead of
    being flattened into an unconditional sum.
    """

    normalized = normalize_phrase(question)
    if entity_count >= 2 and _TRAILING_FILTERED_TOTAL.search(normalized):
        return OperationKind.SUM, "aggregate_domain:filtered_multi_entity_total"
    if entity_count >= 2 and _EXPLICIT_FILTERED_ENTITY_TOTAL.search(normalized):
        return OperationKind.SUM, "aggregate_domain:filtered_multi_entity_total"
    if operation != OperationKind.LOOKUP:
        return operation, None
    if not _EXPLICIT_TOTAL.search(normalized) or _LEGAL_ENTITY_PREFIX.search(normalized):
        return operation, None
    if _FILTERED_ENTITY_SELECTION.search(normalized):
        return operation, None
    if entity_count >= 2:
        return OperationKind.SUM, "aggregate_domain:multi_entity_total"
    if period_count >= 2 and _EXPLICIT_PERIOD_DOMAIN.search(normalized):
        return OperationKind.SUM, "aggregate_domain:multi_period_total"
    return operation, None


class LegacyVietnameseAnnotator:
    def __init__(self, companies: Mapping[str, str | Sequence[str]]):
        self.companies = companies

    def annotate(self, question: str) -> QuestionAnnotations:
        intent = parse_intent(question, self.companies)
        operation = classify_operation(question)
        operation_kind = _OPERATION.get(operation.op, OperationKind.UNSUPPORTED)
        operation_kind, aggregate_evidence = _aggregate_override(
            question,
            entity_count=len(intent.tickers),
            period_count=len(intent.years),
            operation=operation_kind,
        )
        aggregate_all_entities = aggregate_evidence in {
            "aggregate_domain:multi_entity_total",
            "aggregate_domain:filtered_multi_entity_total",
        }
        average_all_entities = (
            operation_kind == OperationKind.AVERAGE
            and len(intent.targets) < len(intent.tickers)
        )
        if aggregate_all_entities:
            entities = tuple(sorted(intent.tickers))
        elif average_all_entities:
            entities = intent.ordered_tickers
        else:
            entities = intent.targets
        dimension, scale, _token = scan_question_unit(question)
        if (
            operation_kind == OperationKind.SUBTRACT
            and len(intent.targets) == 1
            and len(intent.years) == 2
            and dimension in {"PERCENT", "RATIO"}
            and _PERCENTAGE_MOVEMENT.search(normalize_phrase(question)) is not None
        ):
            operation_kind = OperationKind.GROWTH
            aggregate_evidence = "semantic_operation:percentage_movement"
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
            entities=entities,
            periods=tuple(str(value) for value in intent.years),
            basis=basis,
            requested_unit=UnitSpec(_DIMENSION[dimension], scale),
            operation=operation_kind,
            mode="screen"
            if aggregate_all_entities or average_all_entities
            else intent.mode,
            rank_direction=rank_direction,
            return_mode=return_mode,
            reverse_difference=operation.reverse_difference,
            absolute_difference=operation.absolute_difference,
            operation_evidence=aggregate_evidence or operation.matched,
        )
