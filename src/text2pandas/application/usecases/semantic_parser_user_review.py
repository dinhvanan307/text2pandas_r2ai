"""Apply a single user semantic review without promoting it to independent gold."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

REVIEW_INPUT_KIND = "text2pandas.semantic_parser_wave6_user_review_input"
REVIEW_DECISIONS = frozenset({"ACCEPT", "ACCEPT_PENDING_SOURCE", "CORRECT", "REJECT"})
REVIEW_RECORD_FIELDS = frozenset({"qid", "decision", "semantic_structure", "primary_issue"})


class SemanticParserUserReviewError(ValueError):
    """Raised when a user review cannot be applied without ambiguity."""


def apply_user_review(
    queue: Sequence[Mapping[str, object]],
    review_input: Mapping[str, object],
) -> tuple[tuple[dict[str, object], ...], dict[str, object]]:
    """Validate and merge one non-independent user review into a copied queue."""

    if review_input.get("kind") != REVIEW_INPUT_KIND:
        raise SemanticParserUserReviewError("unexpected review input kind")
    if review_input.get("independent_human_gold") is not False:
        raise SemanticParserUserReviewError("single user review must not claim independent gold")
    if review_input.get("source_evidence_default") is not False:
        raise SemanticParserUserReviewError("source evidence must remain unreviewed by default")
    reviewer_scope = str(review_input.get("reviewer_scope") or "")
    if reviewer_scope != "SINGLE_USER_SEMANTIC_REVIEW_NOT_INDEPENDENT_GOLD":
        raise SemanticParserUserReviewError("reviewer scope does not preserve governance")
    reviewer_id = str(review_input.get("reviewer_id") or "").strip()
    if not reviewer_id:
        raise SemanticParserUserReviewError("reviewer_id is required")
    raw_records = review_input.get("records")
    if not isinstance(raw_records, list) or not all(
        isinstance(record, Mapping) for record in raw_records
    ):
        raise SemanticParserUserReviewError("review records must be a list of objects")

    queue_by_qid = _unique_by_qid(queue, "queue")
    review_by_qid = _unique_by_qid(raw_records, "review")
    if set(queue_by_qid) != set(review_by_qid):
        missing = sorted(set(queue_by_qid) - set(review_by_qid))
        extra = sorted(set(review_by_qid) - set(queue_by_qid))
        raise SemanticParserUserReviewError(
            f"review QID mismatch: missing={missing} extra={extra}"
        )

    reviewed: list[dict[str, object]] = []
    cross_tab: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()
    for qid in sorted(queue_by_qid):
        source = review_by_qid[qid]
        if set(source) != REVIEW_RECORD_FIELDS:
            raise SemanticParserUserReviewError(f"review field mismatch for QID {qid}")
        decision = str(source["decision"])
        if decision not in REVIEW_DECISIONS:
            raise SemanticParserUserReviewError(
                f"invalid decision for QID {qid}: {decision}"
            )
        semantic_structure = str(source["semantic_structure"] or "").strip()
        primary_issue = str(source["primary_issue"] or "").strip()
        if not semantic_structure or not primary_issue:
            raise SemanticParserUserReviewError(
                f"semantic structure and issue are required for QID {qid}"
            )

        output = deepcopy(queue_by_qid[qid])
        model_draft = output.get("model_draft")
        if not isinstance(model_draft, Mapping):
            raise SemanticParserUserReviewError(f"missing model draft for QID {qid}")
        structural_status = str(model_draft.get("structural_status") or "")
        output["reviewer_id"] = reviewer_id
        output["review_decision"] = decision
        output["source_evidence_reviewed"] = False
        # The supplied prose is sufficient for triage, but not a complete
        # CompositionFrame/QuestionAST annotation. Never synthesize one here.
        output["corrected_annotation"] = None
        output["review_notes"] = {
            "semantic_structure": semantic_structure,
            "primary_issue": primary_issue,
            "full_annotation_required": decision in {"CORRECT", "REJECT"},
            "source_gate": (
                "PENDING_SOURCE_EVIDENCE"
                if decision == "ACCEPT_PENDING_SOURCE"
                else "NOT_REVIEWED"
            ),
        }
        reviewed.append(output)
        decision_counts[decision] += 1
        cross_tab[f"{structural_status}:{decision}"] += 1

    summary: dict[str, object] = {
        "schema_version": 1,
        "kind": "text2pandas.semantic_parser_wave6_user_review_summary",
        "review_id": review_input.get("review_id"),
        "reviewer_id": reviewer_id,
        "reviewer_scope": reviewer_scope,
        "records": len(reviewed),
        "decision_counts": dict(sorted(decision_counts.items())),
        "model_status_decision_cross_tab": dict(sorted(cross_tab.items())),
        "accepted_model_drafts": cross_tab["OK:ACCEPT"],
        "accepted_proposals_without_model_ast": cross_tab[
            "UNRESOLVED:ACCEPT_PENDING_SOURCE"
        ],
        "corrections_requiring_full_annotation": decision_counts["CORRECT"],
        "source_evidence_reviewed": 0,
        "full_corrected_annotations": 0,
        "independent_human_gold": False,
        "correctness": "NOT_MEASURED",
        "ready_for_runtime": False,
        "ready_for_independent_gold": False,
    }
    return tuple(reviewed), summary


def _unique_by_qid(
    records: Sequence[Mapping[str, object]], label: str
) -> dict[int, dict[str, object]]:
    output: dict[int, dict[str, object]] = {}
    for record in records:
        raw_qid = record.get("qid")
        if isinstance(raw_qid, bool) or not isinstance(raw_qid, int) or raw_qid < 1:
            raise SemanticParserUserReviewError(f"invalid {label} QID: {raw_qid}")
        if raw_qid in output:
            raise SemanticParserUserReviewError(f"duplicate {label} QID: {raw_qid}")
        output[raw_qid] = dict(record)
    return output
