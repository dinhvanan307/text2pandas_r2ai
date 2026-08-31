"""Deterministic, prediction-only records for Semantic Parser baselines."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import hashlib
import json

from text2pandas.application.parsing import ParseCandidate, QuestionAnnotations
from text2pandas.application.parsing.parser import SemanticParser
from text2pandas.domain.semantic import expression_to_dict


def build_semantic_parser_record(
    parser: SemanticParser,
    question: str,
    *,
    qid: int,
    max_candidates: int = 8,
) -> dict[str, object]:
    """Run the parser without retrieval and retain only diagnostic predictions."""

    annotations = parser.annotator.annotate(question)
    candidates = parser.parse_candidates(
        question,
        qid=qid,
        max_candidates=max_candidates,
    )
    primary = candidates[0]
    return {
        "schema_version": 1,
        "kind": "text2pandas.semantic_parser_baseline_record",
        "measurement_scope": "PREDICTED_STRUCTURE_ONLY_NOT_GOLD",
        "qid": qid,
        "question": question,
        "question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
        "annotations": _annotations_to_dict(annotations),
        "primary_status": primary.result.status,
        "primary_reason": primary.result.reason,
        "any_candidate_ok": any(candidate.result.ok for candidate in candidates),
        "candidates": [_candidate_to_dict(candidate) for candidate in candidates],
    }


def summarize_semantic_parser_records(
    records: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Summarize parser coverage without interpreting it as correctness."""

    primary_statuses = Counter(str(record["primary_status"]) for record in records)
    primary_reasons = Counter(str(record.get("primary_reason") or "OK") for record in records)
    candidate_statuses: Counter[str] = Counter()
    candidate_reasons: Counter[str] = Counter()
    predicted_complexities: Counter[str] = Counter()
    any_ok = 0
    for record in records:
        if record.get("any_candidate_ok") is True:
            any_ok += 1
        raw_candidates = record.get("candidates")
        if not isinstance(raw_candidates, list):
            raise TypeError("parser baseline candidates must be a list")
        for candidate in raw_candidates:
            if not isinstance(candidate, dict):
                raise TypeError("parser baseline candidate must be an object")
            candidate_statuses[str(candidate["status"])] += 1
            candidate_reasons[str(candidate.get("reason") or "OK")] += 1
            profile = candidate.get("predicted_ast_profile")
            if isinstance(profile, dict):
                predicted_complexities[str(profile["complexity"])] += 1
    return {
        "records": len(records),
        "primary_statuses": dict(sorted(primary_statuses.items())),
        "primary_reasons": dict(primary_reasons.most_common()),
        "any_candidate_ok": any_ok,
        "candidate_statuses": dict(sorted(candidate_statuses.items())),
        "candidate_reasons": dict(candidate_reasons.most_common()),
        "predicted_complexities": dict(sorted(predicted_complexities.items())),
        "correctness": "NOT_MEASURED",
    }


def _annotations_to_dict(annotations: QuestionAnnotations) -> dict[str, object]:
    return {
        "entities": list(annotations.entities),
        "periods": list(annotations.periods),
        "basis": annotations.basis.value,
        "requested_unit": annotations.requested_unit.to_dict(),
        "operation": annotations.operation.value,
        "mode": annotations.mode,
        "rank_direction": (
            None if annotations.rank_direction is None else annotations.rank_direction.value
        ),
        "return_mode": annotations.return_mode.value,
        "reverse_difference": annotations.reverse_difference,
        "absolute_difference": annotations.absolute_difference,
        "operation_evidence": annotations.operation_evidence,
    }


def _candidate_to_dict(candidate: ParseCandidate) -> dict[str, object]:
    result = candidate.result
    ast = result.ast
    return {
        **candidate.to_dict(),
        "source_bindings": [binding.to_dict() for binding in result.source_bindings],
        "predicted_ast_profile": (
            None if ast is None else _profile_expression(expression_to_dict(ast.expression))
        ),
    }


def _profile_expression(expression: Mapping[str, object]) -> dict[str, object]:
    node_types: Counter[str] = Counter()
    layers: set[str] = set()

    def walk(node: Mapping[str, object]) -> int:
        node_type = str(node["type"])
        node_types[node_type] += 1
        if node_type in {"arithmetic", "unary", "rolling_average", "rolling_growth"}:
            layers.add("derived")
        elif node_type == "filter":
            layers.add("filtered")
        elif node_type == "aggregate":
            layers.add("aggregated")
        elif node_type in {"rank", "select_at_arg"}:
            layers.add("ranked")
        child_depths: list[int] = []
        for key in ("left", "right", "expression", "by", "rank"):
            child = node.get(key)
            if isinstance(child, dict) and "type" in child:
                child_depths.append(walk(child))
        predicate = node.get("predicate")
        if isinstance(predicate, dict):
            child_depths.append(walk_predicate(predicate))
        return 1 + max(child_depths, default=0)

    def walk_predicate(predicate: Mapping[str, object]) -> int:
        predicate_type = str(predicate["type"])
        node_types[predicate_type] += 1
        layers.add("predicate")
        child_depths: list[int] = []
        for key in ("left", "right", "expression"):
            child = predicate.get(key)
            if isinstance(child, dict) and "type" in child:
                child_depths.append(walk(child))
        predicates = predicate.get("predicates")
        if isinstance(predicates, list):
            child_depths.extend(
                walk_predicate(child)
                for child in predicates
                if isinstance(child, dict) and "type" in child
            )
        nested = predicate.get("predicate")
        if isinstance(nested, dict) and "type" in nested:
            child_depths.append(walk_predicate(nested))
        return 1 + max(child_depths, default=0)

    depth = walk(expression)
    ordered_layers = tuple(sorted(layers))
    if len(layers) >= 2:
        complexity = "compositional"
    elif "ranked" in layers:
        complexity = "ranked"
    elif "aggregated" in layers:
        complexity = "aggregated"
    elif "filtered" in layers or "predicate" in layers:
        complexity = "filtered"
    elif "derived" in layers:
        complexity = "derived"
    else:
        complexity = "direct"
    canonical = json.dumps(expression, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "complexity": complexity,
        "layers": list(ordered_layers),
        "depth": depth,
        "node_types": dict(sorted(node_types.items())),
        "expression_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }
