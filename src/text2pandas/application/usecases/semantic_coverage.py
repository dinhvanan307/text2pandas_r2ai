"""Deterministic, data-independent coverage audit for the question corpus.

This report measures whether a question can reach a typed execution route. It
does not claim retrieval, binding, or answer accuracy; those remain materialized
evaluation gates. Keeping that boundary explicit prevents route coverage from
being misreported as end-to-end quality.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from text2pandas.pipelines.answering.adapters import requested_unit_of
from text2pandas.pipelines.answering.count_engine import classify_count_predicate
from text2pandas.pipelines.answering.formula_engine import match_formula
from text2pandas.pipelines.answering.frame import classify_operation, parse_question
from text2pandas.pipelines.answering.ir import DIVIDE, LOOKUP
from text2pandas.pipelines.answering.router import route
from text2pandas.pipelines.retrieval.question_intent import parse_intent

ELIGIBLE = "ELIGIBLE"
GAP = "GAP"
SCOPE = "semantic_route_only_no_retrieval_binding_or_accuracy"


@dataclass(frozen=True, slots=True)
class CoverageRecord:
    qid: int
    operation: str
    formula_id: str | None
    status: str
    reason: str

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "qid": self.qid,
            "operation": self.operation,
            "formula_id": self.formula_id,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class SemanticCoverageReport:
    records: tuple[CoverageRecord, ...]
    questions_sha256: str

    def summary(self) -> dict:
        by_operation = Counter(record.operation for record in self.records)
        by_reason = Counter(record.reason for record in self.records)
        by_status = Counter(record.status for record in self.records)
        total = len(self.records)
        eligible = by_status[ELIGIBLE]
        return {
            "schema_version": 1,
            "scope": SCOPE,
            "questions_sha256": self.questions_sha256,
            "total": total,
            "eligible": eligible,
            "gaps": by_status[GAP],
            "eligible_percent": round(100 * eligible / total, 4) if total else 0.0,
            "by_operation": dict(sorted(by_operation.items())),
            "by_reason": dict(sorted(by_reason.items())),
        }

    def to_dict(self, *, include_records: bool = True) -> dict:
        result = self.summary()
        if include_records:
            result["records"] = [record.to_dict() for record in self.records]
        return result


def analyze_semantic_coverage(
    questions: Sequence[Mapping],
    aliases: Mapping[str, Sequence[str]],
) -> SemanticCoverageReport:
    """Classify every question against the exact canonical runtime routes."""

    normalized: list[tuple[int, str, tuple[str, ...] | None]] = []
    seen: set[int] = set()
    for raw in questions:
        qid = int(raw.get("id", raw.get("qid")))
        question = str(raw["question"])
        if qid in seen:
            raise ValueError(f"duplicate question id: {qid}")
        if not question.strip():
            raise ValueError(f"empty question: {qid}")
        seen.add(qid)
        expected_entities = raw.get("entities")
        expected = (
            tuple(str(value) for value in expected_entities)
            if expected_entities is not None
            else None
        )
        normalized.append((qid, question, expected))
    normalized.sort(key=lambda item: item[0])

    digest = hashlib.sha256()
    records: list[CoverageRecord] = []
    for qid, question, expected_entities in normalized:
        digest.update(
            json.dumps(
                {"id": qid, "question": question},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        digest.update(b"\n")
        records.append(_classify(qid, question, aliases, expected_entities))
    return SemanticCoverageReport(tuple(records), digest.hexdigest())


def _classify(
    qid: int,
    question: str,
    aliases: Mapping[str, Sequence[str]],
    expected_entities: tuple[str, ...] | None = None,
) -> CoverageRecord:
    intent = parse_intent(question, aliases)
    operation = classify_operation(question)
    formula = match_formula(question)
    formula_id = formula.formula_id if formula else None
    if expected_entities is not None and len(expected_entities) != 1:
        return CoverageRecord(
            qid,
            operation.op,
            formula_id,
            GAP,
            f"MULTI_ENTITY_NOT_SUPPORTED:expected={len(expected_entities)}",
        )
    if expected_entities is not None and tuple(intent.targets) != expected_entities:
        return CoverageRecord(
            qid,
            operation.op,
            formula_id,
            GAP,
            "ENTITY_RESOLUTION_MISMATCH:"
            f"expected={len(expected_entities)}:found={len(intent.targets)}",
        )
    if expected_entities is None and len(intent.targets) != 1:
        return CoverageRecord(
            qid,
            operation.op,
            formula_id,
            GAP,
            f"ANSWER_REQUIRES_SINGLE_ENTITY:found={len(intent.targets)}",
        )

    requested_unit = requested_unit_of(question)
    count_predicate, count_reason = classify_count_predicate(question)
    if count_predicate is not None:
        return CoverageRecord(
            qid,
            operation.op,
            None,
            ELIGIBLE,
            "ELIGIBLE_TYPED_COUNT",
        )
    if count_reason is not None:
        return CoverageRecord(qid, operation.op, None, GAP, count_reason)
    if formula is not None:
        if operation.op not in (LOOKUP, DIVIDE):
            reason = f"FORMULA_OUTER_OPERATION_NOT_SUPPORTED:{operation.op}"
        elif len(intent.years) != 1:
            reason = "FORMULA_REQUIRES_ONE_PERIOD"
        elif requested_unit.dimension != formula.output_dimension:
            reason = (
                "FORMULA_OUTPUT_DIMENSION_MISMATCH:"
                f"{formula.output_dimension}:{requested_unit.dimension}"
            )
        else:
            return CoverageRecord(
                qid,
                operation.op,
                formula_id,
                ELIGIBLE,
                "ELIGIBLE_REVIEWED_FORMULA",
            )
        return CoverageRecord(qid, operation.op, formula_id, GAP, reason)

    if operation.op == DIVIDE:
        return CoverageRecord(
            qid,
            operation.op,
            None,
            GAP,
            "DIVIDE_REQUIRES_REVIEWED_FORMULA",
        )

    frame = parse_question(question, qid=qid, requested_unit=requested_unit)
    routed = route(frame)
    if not routed.ok:
        return CoverageRecord(qid, operation.op, None, GAP, routed.reason or "NO_ROUTE")
    return CoverageRecord(
        qid,
        operation.op,
        None,
        ELIGIBLE,
        "ELIGIBLE_TYPED_OPERATION",
    )
