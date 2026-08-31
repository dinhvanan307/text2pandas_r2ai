"""Physical retrieval adapters."""

from .fact_graph import project_candidate
from .fact_label import fact_label_segments, normalize_fact_label
from .operand import FACT_RETRIEVAL_POLICY_VERSION, SqliteOperandRetriever

__all__ = [
    "FACT_RETRIEVAL_POLICY_VERSION",
    "SqliteOperandRetriever",
    "fact_label_segments",
    "normalize_fact_label",
    "project_candidate",
]
