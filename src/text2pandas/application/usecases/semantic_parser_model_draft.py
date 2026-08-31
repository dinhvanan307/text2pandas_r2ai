"""Question-only silver drafts for the Semantic Parser Wave 6 review queue."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from text2pandas.application.usecases.semantic_parser_review import (
    AMBIGUITY_STATUSES,
    COMPLEXITY_CLASSES,
    COMPOSITION_FRAME_FIELDS,
    STRUCTURAL_STATUSES,
)
from text2pandas.domain.semantic import QuestionAST, validate_question_ast

MODEL_DRAFT_KIND = "text2pandas.semantic_parser_wave6_model_draft"
MODEL_DRAFT_STATUS = "MODEL_DRAFT_PENDING_HUMAN_REVIEW"
RESPONSE_FIELDS = frozenset({"structural_status", "complexity_class", "composition_frame", "notes"})
METRIC_MENTION_FIELDS = frozenset(
    {"mention_text", "metric_id", "semantic_role", "reported_or_derived"}
)


class SemanticParserModelDraftError(ValueError):
    """Raised when a model response cannot become a reviewable draft."""


def compile_model_draft(
    scope_row: Mapping[str, object],
    response: Mapping[str, object],
    generation: Mapping[str, object],
) -> dict[str, object]:
    """Validate and wrap one model response without granting it gold status."""

    extras = set(response) - RESPONSE_FIELDS
    missing = RESPONSE_FIELDS - set(response)
    if extras or missing:
        raise SemanticParserModelDraftError(
            f"response field mismatch: missing={sorted(missing)} extras={sorted(extras)}"
        )
    qid = _positive_int(scope_row.get("qid"), "scope qid")
    question = str(scope_row.get("question") or "")
    structural_status = str(response.get("structural_status") or "")
    complexity = str(response.get("complexity_class") or "")
    if structural_status not in STRUCTURAL_STATUSES:
        raise SemanticParserModelDraftError(f"invalid structural status: {structural_status}")
    if complexity not in COMPLEXITY_CLASSES:
        raise SemanticParserModelDraftError(f"invalid complexity class: {complexity}")
    raw_frame = response.get("composition_frame")
    if not isinstance(raw_frame, Mapping):
        raise SemanticParserModelDraftError("composition_frame must be an object")
    missing_frame = set(COMPOSITION_FRAME_FIELDS) - set(raw_frame)
    extra_frame = set(raw_frame) - set(COMPOSITION_FRAME_FIELDS)
    if missing_frame or extra_frame:
        raise SemanticParserModelDraftError(
            f"composition frame mismatch: missing={sorted(missing_frame)} "
            f"extras={sorted(extra_frame)}"
        )
    frame = deepcopy(dict(raw_frame))
    _validate_frame_lists(frame)
    frame["metric_mentions"] = _compile_metric_mentions(
        question, _sequence(frame["metric_mentions"], "metric_mentions")
    )
    ambiguity = frame.get("ambiguity")
    if not isinstance(ambiguity, Mapping):
        raise SemanticParserModelDraftError("ambiguity must be an object")
    ambiguity_status = str(ambiguity.get("status") or "")
    if ambiguity_status not in AMBIGUITY_STATUSES:
        raise SemanticParserModelDraftError(f"invalid ambiguity status: {ambiguity_status}")

    if structural_status == "OK":
        if ambiguity_status != "NONE":
            raise SemanticParserModelDraftError("OK draft requires ambiguity.status=NONE")
        raw_ast = frame.get("expected_ast")
        if not isinstance(raw_ast, Mapping):
            raise SemanticParserModelDraftError("OK draft requires expected_ast")
        ast_payload = {
            "schema_version": 3,
            "qid": qid,
            "question": question,
            "expression": raw_ast.get("expression"),
            "output": raw_ast.get("output"),
            "diagnostics": [MODEL_DRAFT_STATUS],
        }
        try:
            ast = QuestionAST.from_dict(ast_payload)
        except (KeyError, TypeError, ValueError) as error:
            raise SemanticParserModelDraftError(f"invalid expected_ast: {error}") from error
        issues = validate_question_ast(ast)
        if issues:
            detail = "; ".join(f"{issue.path}:{issue.code}" for issue in issues)
            raise SemanticParserModelDraftError(f"expected_ast validation failed: {detail}")
        inferred_complexity = _expression_complexity(ast.to_dict()["expression"])
        if complexity != inferred_complexity:
            raise SemanticParserModelDraftError(
                f"complexity mismatch: declared={complexity} inferred={inferred_complexity}"
            )
        output_dimension = str(frame.get("output_dimension") or "")
        if output_dimension != ast.output.unit.dimension.value:
            raise SemanticParserModelDraftError(
                "output dimension mismatch: "
                f"frame={output_dimension} ast={ast.output.unit.dimension.value}"
            )
        frame["expected_ast"] = ast.to_dict()
    else:
        if ambiguity_status == "NONE":
            raise SemanticParserModelDraftError(
                "non-OK draft requires AMBIGUOUS or UNRESOLVED ambiguity"
            )
        if frame.get("expected_ast") is not None:
            raise SemanticParserModelDraftError("non-OK draft must not contain expected_ast")

    return {
        "schema_version": 1,
        "kind": MODEL_DRAFT_KIND,
        "review_status": MODEL_DRAFT_STATUS,
        "independent_human_gold": False,
        "qid": qid,
        "question": question,
        "question_sha256": str(scope_row.get("question_sha256") or ""),
        "family": str(scope_row.get("family") or ""),
        "split": str(scope_row.get("split") or ""),
        "structural_status": structural_status,
        "complexity_class": complexity,
        "composition_frame": frame,
        "generation": dict(generation),
        "notes": response.get("notes"),
    }


def generation_failure_draft(
    scope_row: Mapping[str, object],
    generation: Mapping[str, object],
    error: str,
) -> dict[str, object]:
    """Create an explicit unresolved record after bounded generation retries."""

    family = str(scope_row.get("family") or "")
    complexity = "direct" if family == "direct_lookup" else "compositional"
    response = {
        "structural_status": "UNRESOLVED",
        "complexity_class": complexity,
        "composition_frame": {
            "entity_domain": [],
            "period_domain": [],
            "basis": None,
            "metric_mentions": [],
            "predicate_clauses": [],
            "logical_connectors": [],
            "temporal_transforms": [],
            "projection": None,
            "aggregate": None,
            "rank": None,
            "operation_order": [],
            "expected_ast": None,
            "output_dimension": "unknown",
            "ambiguity": {"status": "UNRESOLVED", "notes": error[:4000]},
        },
        "notes": f"Generation failed after bounded retries: {error[:4000]}",
    }
    return compile_model_draft(scope_row, response, generation)


def build_user_review_queue(
    drafts: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    """Wrap silver drafts for explicit user accept/correct/reject decisions."""

    return tuple(
        {
            "schema_version": 1,
            "kind": "text2pandas.semantic_parser_wave6_user_review",
            "qid": _positive_int(draft.get("qid"), "draft qid"),
            "question": str(draft.get("question") or ""),
            "question_sha256": str(draft.get("question_sha256") or ""),
            "family": str(draft.get("family") or ""),
            "split": str(draft.get("split") or ""),
            "model_draft": {
                "structural_status": draft.get("structural_status"),
                "complexity_class": draft.get("complexity_class"),
                "composition_frame": draft.get("composition_frame"),
                "notes": draft.get("notes"),
            },
            "reviewer_id": None,
            "review_decision": None,
            "source_evidence_reviewed": None,
            "corrected_annotation": None,
            "review_notes": None,
        }
        for draft in sorted(drafts, key=lambda row: _positive_int(row.get("qid"), "draft qid"))
    )


def summarize_model_drafts(
    drafts: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Report completion and draft status without claiming semantic correctness."""

    statuses = Counter(str(draft.get("structural_status")) for draft in drafts)
    complexities = Counter(str(draft.get("complexity_class")) for draft in drafts)
    splits = Counter(str(draft.get("split")) for draft in drafts)
    return {
        "records": len(drafts),
        "structural_status_counts": dict(sorted(statuses.items())),
        "complexity_counts": dict(sorted(complexities.items())),
        "split_counts": dict(sorted(splits.items())),
        "human_reviewed": 0,
        "independent_gold": False,
        "correctness": "NOT_MEASURED",
    }


def _compile_metric_mentions(
    question: str, raw_mentions: Sequence[object]
) -> list[dict[str, object]]:
    mentions: list[dict[str, object]] = []
    for index, raw in enumerate(raw_mentions):
        if not isinstance(raw, Mapping):
            raise SemanticParserModelDraftError(f"metric_mentions[{index}] must be an object")
        missing = METRIC_MENTION_FIELDS - set(raw)
        extras = set(raw) - METRIC_MENTION_FIELDS
        if missing or extras:
            raise SemanticParserModelDraftError(
                f"metric mention mismatch at {index}: missing={sorted(missing)} "
                f"extras={sorted(extras)}"
            )
        mention_text = str(raw.get("mention_text") or "")
        start = question.find(mention_text)
        if not mention_text or start < 0:
            raise SemanticParserModelDraftError(
                f"metric mention is not an exact question substring: {mention_text!r}"
            )
        metric_id = str(raw.get("metric_id") or "")
        if not metric_id:
            raise SemanticParserModelDraftError("metric_id must be non-empty")
        mentions.append(
            {
                **dict(raw),
                "start": start,
                "end": start + len(mention_text),
            }
        )
    return mentions


def _validate_frame_lists(frame: Mapping[str, object]) -> None:
    for field in (
        "entity_domain",
        "period_domain",
        "metric_mentions",
        "predicate_clauses",
        "logical_connectors",
        "temporal_transforms",
        "operation_order",
    ):
        _sequence(frame.get(field), field)


def _expression_complexity(expression: Mapping[str, Any]) -> str:
    layers: set[str] = set()

    def walk(node: Mapping[str, Any]) -> None:
        node_type = str(node.get("type"))
        if node_type in {
            "arithmetic",
            "unary",
            "rolling_average",
            "rolling_growth",
            "formula_call",
        }:
            layers.add("derived")
        elif node_type == "filter":
            layers.add("filtered")
        elif node_type == "aggregate":
            layers.add("aggregated")
        elif node_type in {"rank", "select_at_arg"}:
            layers.add("ranked")
        for key in ("left", "right", "expression", "by", "rank"):
            child = node.get(key)
            if isinstance(child, Mapping):
                walk(child)
        predicate = node.get("predicate")
        if isinstance(predicate, Mapping):
            walk_predicate(predicate)

    def walk_predicate(predicate: Mapping[str, Any]) -> None:
        layers.add("predicate")
        for key in ("left", "right", "expression"):
            child = predicate.get(key)
            if isinstance(child, Mapping):
                walk(child)
        children = predicate.get("predicates")
        if isinstance(children, list):
            for child in children:
                if isinstance(child, Mapping):
                    walk_predicate(child)
        nested = predicate.get("predicate")
        if isinstance(nested, Mapping):
            walk_predicate(nested)

    walk(expression)
    if len(layers) >= 2:
        return "compositional"
    if "ranked" in layers:
        return "ranked"
    if "aggregated" in layers:
        return "aggregated"
    if "filtered" in layers or "predicate" in layers:
        return "filtered"
    if "derived" in layers:
        return "derived"
    return "direct"


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise SemanticParserModelDraftError(f"{label} must be a list")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{label} must be a positive integer")
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as error:
        raise TypeError(f"{label} must be a positive integer") from error
    if parsed < 1:
        raise ValueError(f"{label} must be a positive integer")
    return parsed
