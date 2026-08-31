"""Question-only silver drafts for the Semantic Parser Wave 6 review queue."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any
import unicodedata

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
    declared_complexity = str(response.get("complexity_class") or "")
    if structural_status not in STRUCTURAL_STATUSES:
        raise SemanticParserModelDraftError(f"invalid structural status: {structural_status}")
    if declared_complexity not in COMPLEXITY_CLASSES:
        raise SemanticParserModelDraftError(f"invalid complexity class: {declared_complexity}")
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
    compiler_adjustments: list[str] = []
    raw_mentions = _sequence(frame["metric_mentions"], "metric_mentions")
    frame["metric_mentions"] = _compile_metric_mentions(question, raw_mentions)
    if any(
        isinstance(raw, Mapping) and compiled["mention_text"] != raw.get("mention_text")
        for raw, compiled in zip(raw_mentions, frame["metric_mentions"], strict=True)
    ):
        compiler_adjustments.append("ALIGN_METRIC_MENTIONS_TO_EXACT_SOURCE_SPANS")
    normalized_question = _normalized_text(question)
    explicit_basis = (
        "separate"
        if "cong ty me" in normalized_question
        else "consolidated"
        if "hop nhat" in normalized_question
        else None
    )
    if explicit_basis is not None and frame.get("basis") != explicit_basis:
        raise SemanticParserModelDraftError(
            f"explicit basis mismatch: question={explicit_basis} frame={frame.get('basis')}"
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
        canonical_expression = ast.to_dict()["expression"]
        ast_metric_ids = _expression_metric_ids(canonical_expression)
        mention_metric_ids = {str(mention["metric_id"]) for mention in frame["metric_mentions"]}
        unused_mentions = sorted(mention_metric_ids - ast_metric_ids)
        if unused_mentions:
            raise SemanticParserModelDraftError(
                f"metric mentions are not referenced by expected_ast: {unused_mentions}"
            )
        inferred_complexity = _expression_complexity(canonical_expression)
        complexity = inferred_complexity
        if declared_complexity != inferred_complexity:
            compiler_adjustments.append(
                f"INFER_COMPLEXITY_FROM_AST:{declared_complexity}->{inferred_complexity}"
            )
        output_dimension = str(frame.get("output_dimension") or "")
        if output_dimension != ast.output.unit.dimension.value:
            raise SemanticParserModelDraftError(
                "output dimension mismatch: "
                f"frame={output_dimension} ast={ast.output.unit.dimension.value}"
            )
        inferred_order = _operation_order(canonical_expression)
        if frame["operation_order"] != inferred_order:
            compiler_adjustments.append("INFER_OPERATION_ORDER_FROM_AST")
            frame["operation_order"] = inferred_order
        frame["expected_ast"] = ast.to_dict()
    else:
        complexity = declared_complexity
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
        "compiler_adjustments": compiler_adjustments,
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
        raw_mention = str(raw.get("mention_text") or "")
        span = _source_span(question, raw_mention)
        if span is None:
            raise SemanticParserModelDraftError(
                f"metric mention cannot align to question: {raw_mention!r}"
            )
        start, end = span
        mention_text = question[start:end]
        metric_id = str(raw.get("metric_id") or "")
        if not metric_id:
            raise SemanticParserModelDraftError("metric_id must be non-empty")
        mentions.append(
            {
                **dict(raw),
                "mention_text": mention_text,
                "start": start,
                "end": end,
            }
        )
    return mentions


def _source_span(question: str, mention: str) -> tuple[int, int] | None:
    if not mention:
        return None
    exact = question.find(mention)
    if exact >= 0:
        return exact, exact + len(mention)
    normalized_question, offsets = _normalized_text_with_offsets(question)
    normalized_mention = _normalized_text(mention)
    start = normalized_question.find(normalized_mention)
    if start < 0 or not normalized_mention:
        return None
    end = start + len(normalized_mention)
    return offsets[start], offsets[end - 1] + 1


def _normalized_text(value: str) -> str:
    return _normalized_text_with_offsets(value)[0]


def _normalized_text_with_offsets(value: str) -> tuple[str, list[int]]:
    characters: list[str] = []
    offsets: list[int] = []
    pending_space: int | None = None
    for index, source_character in enumerate(value):
        decomposed = unicodedata.normalize("NFD", source_character.casefold())
        plain = "".join(
            character for character in decomposed if unicodedata.category(character) != "Mn"
        ).replace("đ", "d")
        for character in plain:
            if character.isalnum():
                if pending_space is not None and characters:
                    characters.append(" ")
                    offsets.append(pending_space)
                pending_space = None
                characters.append(character)
                offsets.append(index)
            elif characters:
                pending_space = index
    return "".join(characters), offsets


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


def _expression_metric_ids(expression: Mapping[str, Any]) -> set[str]:
    output: set[str] = set()

    def walk(node: Mapping[str, Any]) -> None:
        if node.get("type") == "metric_ref":
            metric_id = str(node.get("metric_id") or "")
            if metric_id:
                output.add(metric_id)
        for key in ("left", "right", "expression", "by", "rank"):
            child = node.get(key)
            if isinstance(child, Mapping):
                walk(child)
        predicate = node.get("predicate")
        if isinstance(predicate, Mapping):
            walk_predicate(predicate)

    def walk_predicate(predicate: Mapping[str, Any]) -> None:
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
    return output


def _operation_order(expression: Mapping[str, Any]) -> list[str]:
    ordered: list[str] = []

    def add(value: str) -> None:
        if value not in ordered:
            ordered.append(value)

    def walk(node: Mapping[str, Any]) -> None:
        node_type = str(node.get("type"))
        if node_type == "metric_ref":
            add("lookup")
            return
        if node_type == "literal":
            return
        if node_type == "filter":
            predicate = node.get("predicate")
            if isinstance(predicate, Mapping):
                walk_predicate(predicate)
            child = node.get("expression")
            if isinstance(child, Mapping):
                walk(child)
            add("filter")
            return
        if node_type == "select_at_arg":
            rank = node.get("rank")
            child = node.get("expression")
            if isinstance(rank, Mapping):
                walk(rank)
            if isinstance(child, Mapping):
                walk(child)
            add("select_at_arg")
            return
        for key in ("left", "right", "expression", "by"):
            child = node.get(key)
            if isinstance(child, Mapping):
                walk(child)
        stage = {
            "arithmetic": "arithmetic",
            "unary": "arithmetic",
            "rolling_average": "temporal_transform",
            "rolling_growth": "temporal_transform",
            "formula_call": "arithmetic",
            "aggregate": "aggregate",
            "rank": "rank",
        }.get(node_type)
        if stage:
            add(stage)

    def walk_predicate(predicate: Mapping[str, Any]) -> None:
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
        add("predicate")

    walk(expression)
    return ordered


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
