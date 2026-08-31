"""Evaluate Semantic V3 records against one sealed independent-gold release."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SemanticGoldEvaluation:
    records: int
    parser_evaluable: int
    parser_correct: int
    candidate_evaluable: int
    candidate_correct: int
    binding_evaluable: int
    binding_correct: int
    answer_evaluable: int
    answer_correct: int
    cases: tuple[dict[str, Any], ...]

    @property
    def parser_ast_exact(self) -> float | None:
        return _rate(self.parser_correct, self.parser_evaluable)

    @property
    def candidate_recall(self) -> float | None:
        return _rate(self.candidate_correct, self.candidate_evaluable)

    @property
    def binding_exact(self) -> float | None:
        return _rate(self.binding_correct, self.binding_evaluable)

    @property
    def answer_accuracy(self) -> float | None:
        return _rate(self.answer_correct, self.answer_evaluable)

    def to_dict(self) -> dict[str, object]:
        return {
            "records": self.records,
            "parser": {
                "evaluable": self.parser_evaluable,
                "correct": self.parser_correct,
                "ast_exact": self.parser_ast_exact,
            },
            "candidate": {
                "evaluable": self.candidate_evaluable,
                "correct": self.candidate_correct,
                "recall": self.candidate_recall,
            },
            "binding": {
                "evaluable": self.binding_evaluable,
                "correct": self.binding_correct,
                "exact": self.binding_exact,
            },
            "answer": {
                "evaluable": self.answer_evaluable,
                "correct": self.answer_correct,
                "accuracy": self.answer_accuracy,
            },
            "cases": list(self.cases),
        }


def evaluate_semantic_gold(
    records: Sequence[Mapping[str, object]],
    gold_rows: Sequence[Mapping[str, object]],
    *,
    tolerance: float = 0.005,
) -> SemanticGoldEvaluation:
    if tolerance < 0 or tolerance >= 1:
        raise ValueError("tolerance must be in [0, 1)")
    predictions = _index(records, "prediction")
    gold = _index(gold_rows, "gold")
    missing = sorted(set(gold) - set(predictions))
    if missing:
        raise ValueError(f"predictions are missing gold QIDs: {missing[:10]}")

    parser_evaluable = parser_correct = 0
    candidate_evaluable = candidate_correct = 0
    binding_evaluable = binding_correct = 0
    answer_evaluable = answer_correct = 0
    cases: list[dict[str, Any]] = []
    for qid in sorted(gold):
        expected = gold[qid]
        predicted = predictions[qid]
        expected_semantic = _gold_asset(expected, "semantic_parser")
        expected_evidence = _gold_asset(expected, "evidence_binding")
        expected_answer = _gold_asset(expected, "answer")

        parser_match: bool | None = None
        if expected_semantic.get("status") == "OK":
            parser_evaluable += 1
            parser_match = predicted.get("ast") == expected_semantic.get("ast")
            parser_correct += parser_match

        expected_uids = _ordered_gold_uids(expected_evidence)
        candidate_match: bool | None = None
        binding_match: bool | None = None
        if expected_uids is not None:
            candidate_evaluable += 1
            candidate_uids = _candidate_uids(predicted)
            candidate_match = set(expected_uids) <= candidate_uids
            candidate_correct += candidate_match
            binding_evaluable += 1
            selected_uids = _selected_uids(predicted)
            binding_match = selected_uids == expected_uids
            binding_correct += binding_match

        answer_match: bool | None = None
        if expected_answer.get("status") == "OK":
            answer_evaluable += 1
            actual = _number(predicted.get("answer"))
            target = _number(expected_answer.get("value"))
            answer_match = (
                actual is not None
                and target is not None
                and _close(actual, target, tolerance)
            )
            answer_correct += answer_match

        cases.append(
            {
                "qid": qid,
                "status": predicted.get("status"),
                "parser_match": parser_match,
                "candidate_match": candidate_match,
                "binding_match": binding_match,
                "answer_match": answer_match,
            }
        )
    return SemanticGoldEvaluation(
        records=len(gold),
        parser_evaluable=parser_evaluable,
        parser_correct=parser_correct,
        candidate_evaluable=candidate_evaluable,
        candidate_correct=candidate_correct,
        binding_evaluable=binding_evaluable,
        binding_correct=binding_correct,
        answer_evaluable=answer_evaluable,
        answer_correct=answer_correct,
        cases=tuple(cases),
    )


def _candidate_uids(record: Mapping[str, object]) -> set[str]:
    output: set[str] = set()
    trace = record.get("trace")
    if not isinstance(trace, Sequence) or isinstance(trace, (str, bytes)):
        return output
    for event in trace:
        if not isinstance(event, Mapping) or event.get("stage") != "RETRIEVE_OPERANDS":
            continue
        requests = event.get("requests")
        if not isinstance(requests, Mapping):
            continue
        for request in requests.values():
            if not isinstance(request, Mapping):
                continue
            details = request.get("trace")
            if not isinstance(details, Mapping):
                continue
            raw = details.get("candidate_observation_uids")
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
                output.update(str(value) for value in raw)
    return output


def _selected_uids(record: Mapping[str, object]) -> tuple[str, ...]:
    evidence = record.get("evidence")
    if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)):
        return ()
    output: list[str] = []
    for item in evidence:
        if not isinstance(item, Mapping):
            continue
        raw = item.get("observation_uids")
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            output.extend(str(value) for value in raw)
    return tuple(output)


def _ordered_gold_uids(asset: Mapping[str, object]) -> tuple[str, ...] | None:
    if asset.get("status") != "OK":
        return None
    operands = asset.get("ordered_operands")
    if not isinstance(operands, Sequence) or isinstance(operands, (str, bytes)):
        raise TypeError("gold evidence_binding ordered_operands must be a list")
    return tuple(
        str(item.get("observation_uid") or "")
        for item in operands
        if isinstance(item, Mapping)
    )


def _gold_asset(record: Mapping[str, object], field: str) -> Mapping[str, object]:
    value = record.get(field)
    if not isinstance(value, Mapping):
        raise TypeError(f"gold record is missing {field}")
    return value


def _index(
    rows: Sequence[Mapping[str, object]], label: str
) -> dict[int, Mapping[str, object]]:
    output: dict[int, Mapping[str, object]] = {}
    for row in rows:
        qid = int(str(row.get("qid")))
        if qid in output:
            raise ValueError(f"duplicate {label} qid: {qid}")
        output[qid] = row
    return output


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _close(actual: float, expected: float, tolerance: float) -> bool:
    return abs(actual - expected) <= tolerance * max(1.0, abs(expected))


def _rate(correct: int, total: int) -> float | None:
    return correct / total if total else None
