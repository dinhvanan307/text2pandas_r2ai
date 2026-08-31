"""Development-only differential for reviewed semantic parser questions."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import hashlib
import json
from typing import Any

from text2pandas.domain.semantic import QuestionAST, validate_question_ast


class SemanticParserDevelopmentError(ValueError):
    """Raised when a development checkpoint cannot be reproduced safely."""


def build_development_records(
    scope: Sequence[Mapping[str, object]],
    review: Sequence[Mapping[str, object]],
    baseline: Sequence[Mapping[str, object]],
    candidate: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    """Join reviewed development semantics to prediction-only S0/S1 records."""

    development = {
        _qid(row): row for row in scope if str(row.get("split") or "") == "development"
    }
    reviews = _index(review, "review")
    baselines = _index(baseline, "baseline")
    candidates = _index(candidate, "candidate")
    expected = set(development)
    if set(reviews) != {_qid(row) for row in scope}:
        raise SemanticParserDevelopmentError("review QID set must cover the full source scope")
    for label, index in (("baseline", baselines), ("candidate", candidates)):
        missing = expected - set(index)
        if missing:
            raise SemanticParserDevelopmentError(
                f"{label} is missing development QIDs: {sorted(missing)}"
            )

    output: list[dict[str, object]] = []
    for qid in sorted(expected):
        scope_row = development[qid]
        review_row = reviews[qid]
        baseline_row = baselines[qid]
        candidate_row = candidates[qid]
        question = str(scope_row.get("question") or "")
        for label, row in (("baseline", baseline_row), ("candidate", candidate_row)):
            if str(row.get("question") or "") != question:
                raise SemanticParserDevelopmentError(f"{label} question mismatch: {qid}")
        baseline_primary = _primary(baseline_row, qid)
        candidate_primary = _primary(candidate_row, qid)
        ast_payload = candidate_primary.get("ast")
        ast: dict[str, object] | None = None
        ast_sha256: str | None = None
        frame: dict[str, object] | None = None
        if isinstance(ast_payload, Mapping):
            ast = dict(ast_payload)
            parsed = QuestionAST.from_dict(ast)
            issues = validate_question_ast(parsed)
            if issues:
                codes = ",".join(sorted({issue.code for issue in issues}))
                raise SemanticParserDevelopmentError(f"candidate AST invalid: {qid}:{codes}")
            canonical = json.dumps(
                ast,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            ast_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            frame = _composition_frame_candidate(candidate_row, ast)
        output.append(
            {
                "schema_version": 1,
                "kind": "text2pandas.semantic_parser_wave6_development_differential",
                "measurement_scope": "DEVELOPMENT_SUPERVISION_NOT_GOLD",
                "qid": qid,
                "question": question,
                "question_sha256": str(scope_row.get("question_sha256") or ""),
                "family": str(scope_row.get("family") or ""),
                "human_review": {
                    "decision": review_row.get("decision"),
                    "semantic_structure": review_row.get("semantic_structure"),
                    "primary_issue": review_row.get("primary_issue"),
                    "source_evidence_reviewed": False,
                    "independent_gold": False,
                },
                "baseline": _prediction_summary(baseline_primary),
                "candidate": {
                    **_prediction_summary(candidate_primary),
                    "ast_state": (
                        "FULL_QUESTION_AST_CANDIDATE"
                        if ast is not None
                        else "NO_QUESTION_AST"
                    ),
                    "ast_sha256": ast_sha256,
                    "composition_frame_candidate": frame,
                    "expected_ast": ast,
                },
                "correctness": "NOT_MEASURED",
                "promotion_eligible": False,
            }
        )
    return tuple(output)


def summarize_development_records(
    records: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Summarize structural reachability without calling it accuracy."""

    transitions: Counter[str] = Counter()
    blockers: Counter[str] = Counter()
    decisions: Counter[str] = Counter()
    full_ast = 0
    for row in records:
        baseline = _mapping(row.get("baseline"), "baseline")
        candidate = _mapping(row.get("candidate"), "candidate")
        review = _mapping(row.get("human_review"), "human_review")
        before = str(baseline.get("status") or "")
        after = str(candidate.get("status") or "")
        transitions[f"{before}->{after}"] += 1
        decisions[str(review.get("decision") or "UNKNOWN")] += 1
        if candidate.get("ast_state") == "FULL_QUESTION_AST_CANDIDATE":
            full_ast += 1
        else:
            blockers[str(candidate.get("reason") or "UNKNOWN")] += 1
    return {
        "records": len(records),
        "full_question_ast_candidates": full_ast,
        "without_question_ast": len(records) - full_ast,
        "transitions": dict(sorted(transitions.items())),
        "candidate_blockers": dict(blockers.most_common()),
        "review_decisions": dict(sorted(decisions.items())),
        "source_evidence_reviewed": 0,
        "independent_gold": False,
        "correctness": "NOT_MEASURED",
        "promotion_eligible": False,
    }


def _composition_frame_candidate(
    prediction: Mapping[str, object],
    ast: Mapping[str, object],
) -> dict[str, object]:
    expression = _mapping(ast.get("expression"), "AST expression")
    output = _mapping(ast.get("output"), "AST output")
    unit = _mapping(output.get("unit"), "AST output unit")
    annotations = _mapping(prediction.get("annotations"), "prediction annotations")
    metric_refs = _nodes(expression, "metric_ref")
    predicates = [
        value for value in _all_mappings(expression) if str(value.get("type")) in {
            "comparison",
            "exists",
            "logical",
            "quantified",
        }
    ]
    aggregates = _nodes(expression, "aggregate")
    ranks = _nodes(expression, "rank")
    return {
        "entity_domain": list(annotations.get("entities") or []),
        "period_domain": list(annotations.get("periods") or []),
        "basis": annotations.get("basis"),
        "metric_mentions": [
            {
                "metric_id": value.get("metric_id"),
                "entities": _list_value(value.get("entities")),
                "periods": _list_value(value.get("periods")),
                "basis": value.get("basis"),
                "source_span": "NOT_RECONSTRUCTED_FROM_AST",
            }
            for value in metric_refs
        ],
        "predicate_clauses": predicates,
        "logical_connectors": [
            value.get("operator") for value in _nodes(expression, "logical")
        ],
        "temporal_transforms": [
            value
            for value in _all_mappings(expression)
            if value.get("type") in {"rolling_average", "rolling_growth"}
            or (value.get("type") == "arithmetic" and value.get("operator") == "growth")
        ],
        "projection": _projection(expression),
        "aggregate": aggregates[0] if aggregates else None,
        "rank": ranks[0] if ranks else None,
        "operation_order": _operation_order(expression),
        "expected_ast": ast,
        "output_dimension": unit.get("dimension"),
        "ambiguity": {"status": "NONE", "notes": "PARSER_CANDIDATE_NOT_GOLD"},
    }


def _projection(expression: Mapping[str, object]) -> Mapping[str, object]:
    if expression.get("type") == "aggregate":
        child = _mapping(expression.get("expression"), "aggregate expression")
        if child.get("type") == "filter":
            return _mapping(child.get("expression"), "filter expression")
        return child
    if expression.get("type") == "select_at_arg":
        return _mapping(expression.get("expression"), "selected expression")
    return expression


def _operation_order(expression: Mapping[str, object]) -> list[str]:
    output: list[str] = []

    def visit(node: object) -> None:
        if not isinstance(node, Mapping):
            return
        node_type = str(node.get("type") or "")
        for key in ("left", "right", "by", "rank", "predicate", "expression"):
            visit(node.get(key))
        predicates = node.get("predicates")
        if isinstance(predicates, list):
            for child in predicates:
                visit(child)
        name = str(node.get("operator") or node.get("function") or node_type)
        if node_type:
            output.append("lookup" if node_type == "metric_ref" else name)

    visit(expression)
    return output


def _nodes(root: Mapping[str, object], node_type: str) -> list[Mapping[str, object]]:
    return [value for value in _all_mappings(root) if value.get("type") == node_type]


def _all_mappings(value: object) -> list[Mapping[str, object]]:
    output: list[Mapping[str, object]] = []
    if isinstance(value, Mapping):
        output.append(value)
        for child in value.values():
            output.extend(_all_mappings(child))
    elif isinstance(value, list):
        for child in value:
            output.extend(_all_mappings(child))
    return output


def _prediction_summary(primary: Mapping[str, object]) -> dict[str, object]:
    profile = primary.get("predicted_ast_profile")
    return {
        "status": primary.get("status"),
        "reason": primary.get("reason"),
        "profile": profile if isinstance(profile, Mapping) else None,
    }


def _primary(row: Mapping[str, object], qid: int) -> Mapping[str, object]:
    candidates = row.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise SemanticParserDevelopmentError(f"missing primary candidate: {qid}")
    return _mapping(candidates[0], "primary candidate")


def _index(
    rows: Sequence[Mapping[str, object]], label: str
) -> dict[int, Mapping[str, object]]:
    output: dict[int, Mapping[str, object]] = {}
    for row in rows:
        qid = _qid(row)
        if qid in output:
            raise SemanticParserDevelopmentError(f"duplicate {label} QID: {qid}")
        output[qid] = row
    return output


def _qid(row: Mapping[str, object]) -> int:
    qid = int(str(row.get("qid") or row.get("id") or 0))
    if qid < 1:
        raise SemanticParserDevelopmentError("QID must be positive")
    return qid


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SemanticParserDevelopmentError(f"{label} must be an object")
    return value


def _list_value(value: object) -> list[object]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise SemanticParserDevelopmentError("expected array value")
    return list(value)
