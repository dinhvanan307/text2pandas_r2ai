"""Evidence-first table output policy shared by Semantic V4 packaging."""

from __future__ import annotations


def compose_relevant_tables(
    evidence_table_uids: tuple[str, ...],
    candidate_table_uids: tuple[str, ...],
    *,
    expected_operands: int,
    max_tables: int = 10,
) -> tuple[str, ...]:
    """Keep exact evidence first, then add a bounded retrieval safety net."""
    if max_tables < 1:
        return ()
    evidence = tuple(dict.fromkeys(evidence_table_uids))
    adaptive_limit = min(max_tables, max(len(evidence), 2 * max(1, expected_operands) + 2))
    combined = tuple(dict.fromkeys((*evidence, *candidate_table_uids)))
    return combined[:adaptive_limit]
