"""Operand-aware retrieval ports and orchestration."""

from .contracts import CandidateBatch, ObservationCandidate, OperandRetriever, retrieve_operands
from .hierarchical import (
    HIERARCHICAL_RETRIEVAL_VERSION,
    HierarchicalOperandRetriever,
    HierarchicalRetrievalPolicy,
    group_candidates_by_logical_table,
    rank_candidate_tables,
)

__all__ = [
    "HIERARCHICAL_RETRIEVAL_VERSION",
    "CandidateBatch",
    "HierarchicalOperandRetriever",
    "HierarchicalRetrievalPolicy",
    "ObservationCandidate",
    "OperandRetriever",
    "group_candidates_by_logical_table",
    "rank_candidate_tables",
    "retrieve_operands",
]
