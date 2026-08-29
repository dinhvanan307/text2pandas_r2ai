"""Deterministic hierarchy-aware reranking over physical fact candidates."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace

from text2pandas.application.planning import OperandRequest
from text2pandas.domain.semantic import PeriodSemantics

from .contracts import CandidateBatch, ObservationCandidate, OperandRetriever

HIERARCHICAL_RETRIEVAL_VERSION = "hierarchical-fact-retrieval-v1"


@dataclass(frozen=True, slots=True)
class HierarchicalRetrievalPolicy:
    top_k: int = 24
    max_per_logical_table: int = 6
    exact_leaf_bonus: float = 0.8
    source_code_bonus: float = 0.7
    hierarchy_bonus: float = 0.12
    statement_bonus: float = 0.4
    period_role_bonus: float = 0.5
    recoverable_penalty: float = 2.5
    collision_penalty: float = 1.0

    def __post_init__(self) -> None:
        if self.top_k < 1:
            raise ValueError("top_k must be positive")
        if self.max_per_logical_table < 1:
            raise ValueError("max_per_logical_table must be positive")


class HierarchicalOperandRetriever:
    """Rerank and deduplicate candidates returned by a physical retriever."""

    def __init__(
        self,
        base: OperandRetriever,
        policy: HierarchicalRetrievalPolicy | None = None,
    ) -> None:
        self.base = base
        self.policy = policy or HierarchicalRetrievalPolicy()

    def retrieve(self, request: OperandRequest) -> CandidateBatch:
        batch = self.base.retrieve(request)
        reranked = tuple(self._rerank(request, candidate) for candidate in batch.candidates)
        ordered = sorted(reranked, key=lambda item: (-item.score, item.observation_uid))
        unique: list[ObservationCandidate] = []
        seen_facts: set[tuple[object, ...]] = set()
        logical_counts: Counter[str] = Counter()
        duplicate_count = 0
        diversity_rejected = 0
        for candidate in ordered:
            fact_key = _semantic_fact_key(candidate)
            if fact_key in seen_facts:
                duplicate_count += 1
                continue
            logical_uid = candidate.logical_table_uid or candidate.table_uid
            if logical_counts[logical_uid] >= self.policy.max_per_logical_table:
                diversity_rejected += 1
                continue
            seen_facts.add(fact_key)
            logical_counts[logical_uid] += 1
            unique.append(candidate)
            if len(unique) >= self.policy.top_k:
                break
        trace = {
            **batch.trace,
            "hierarchical_retrieval": HIERARCHICAL_RETRIEVAL_VERSION,
            "hierarchical_input_count": len(batch.candidates),
            "hierarchical_returned_count": len(unique),
            "logical_table_count": len(logical_counts),
            "semantic_duplicates_removed": duplicate_count,
            "logical_diversity_rejected": diversity_rejected,
            "candidate_table_uids": list(
                dict.fromkeys(candidate.table_uid for candidate in unique)
            ),
            "candidate_logical_table_uids": list(
                dict.fromkeys(
                    candidate.logical_table_uid or candidate.table_uid for candidate in unique
                )
            ),
        }
        return CandidateBatch(batch.request_id, tuple(unique), trace)

    def _rerank(
        self,
        request: OperandRequest,
        candidate: ObservationCandidate,
    ) -> ObservationCandidate:
        adjustment = 0.0
        reasons: list[str] = []
        if candidate.match_method == "row_leaf_raw_exact":
            adjustment += self.policy.exact_leaf_bonus
            reasons.append("hierarchy:raw_exact")
        if candidate.source_metric_code and candidate.source_metric_code == request.metric_id:
            adjustment += self.policy.source_code_bonus
            reasons.append("hierarchy:source_code")
        hierarchy_depth = max(
            len(candidate.row_hierarchy),
            len(candidate.column_hierarchy),
        )
        if hierarchy_depth > 1:
            adjustment += min(4, hierarchy_depth - 1) * self.policy.hierarchy_bonus
            reasons.append("hierarchy:context_depth")
        if candidate.statement_type and candidate.statement_type in request.statement_types:
            adjustment += self.policy.statement_bonus
            reasons.append("hierarchy:statement")
        if _period_role_matches(request.period_semantics, candidate.period_role):
            adjustment += self.policy.period_role_bonus
            reasons.append("hierarchy:period_role")
        if candidate.readiness == "recoverable":
            adjustment -= self.policy.recoverable_penalty
            reasons.append("hierarchy:recoverable_penalty")
        if candidate.collision_class:
            adjustment -= self.policy.collision_penalty
            reasons.append("hierarchy:collision_penalty")
        if candidate.source_confidence is not None:
            adjustment += max(-0.5, min(0.5, candidate.source_confidence - 0.5))
            reasons.append("hierarchy:source_confidence")
        return replace(
            candidate,
            score=candidate.score + adjustment,
            score_reasons=(*candidate.score_reasons, *reasons),
        )


def rank_candidate_tables(
    batches: Mapping[str, CandidateBatch],
    *,
    limit: int = 10,
) -> tuple[str, ...]:
    """Aggregate operand evidence into a stable physical table ranking."""
    if limit < 1:
        return ()
    best_score: dict[str, float] = {}
    support: Counter[str] = Counter()
    first_seen: dict[str, int] = {}
    serial = 0
    for request_id in sorted(batches):
        per_request_seen: set[str] = set()
        for candidate in batches[request_id].candidates:
            table_uid = candidate.table_uid
            if table_uid not in first_seen:
                first_seen[table_uid] = serial
                serial += 1
            best_score[table_uid] = max(best_score.get(table_uid, float("-inf")), candidate.score)
            if table_uid not in per_request_seen:
                support[table_uid] += 1
                per_request_seen.add(table_uid)
    return tuple(
        sorted(
            best_score,
            key=lambda uid: (-support[uid], -best_score[uid], first_seen[uid], uid),
        )[:limit]
    )


def group_candidates_by_logical_table(
    candidates: tuple[ObservationCandidate, ...],
) -> Mapping[str, tuple[ObservationCandidate, ...]]:
    grouped: defaultdict[str, list[ObservationCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.logical_table_uid or candidate.table_uid].append(candidate)
    return {key: tuple(values) for key, values in sorted(grouped.items())}


def _semantic_fact_key(candidate: ObservationCandidate) -> tuple[object, ...]:
    return (
        candidate.document_id,
        candidate.entity,
        candidate.basis,
        candidate.statement_type,
        candidate.matched_metric_id or candidate.metric_id,
        candidate.row_hierarchy or (candidate.row_path,),
        candidate.column_hierarchy or (candidate.column_path,),
        candidate.period,
        candidate.period_role,
        candidate.value,
        candidate.unit,
    )


def _period_role_matches(semantics: PeriodSemantics, role: str | None) -> bool:
    if semantics == PeriodSemantics.POINT_IN_TIME:
        return role in {"closing", "opening", "prior"}
    if semantics == PeriodSemantics.FLOW:
        return role in {"current", "prior"}
    return False
