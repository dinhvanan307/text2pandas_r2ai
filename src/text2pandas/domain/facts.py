"""Canonical logical facts used by the corpus-grounded semantic engine.

The A6 database stores physical observations.  A financial fact is the stable,
logical identity used by retrieval and verification after physical table
fragments have been normalised.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from text2pandas.domain.semantic import Basis, UnitSpec


class FactReadiness(StrEnum):
    READY = "ready"
    RECOVERABLE = "recoverable"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class FinancialFact:
    """Immutable logical projection of one executable source observation."""

    fact_uid: str
    observation_uid: str
    table_uid: str
    logical_table_uid: str
    document_id: str
    entity: str
    basis: Basis
    statement_type: str | None
    metric_id: str
    source_metric_code: str | None
    row_uid: str | None
    column_uid: str | None
    row_hierarchy: tuple[str, ...]
    column_hierarchy: tuple[str, ...]
    period: str | None
    period_role: str | None
    value: Decimal
    value_raw: str
    unit: UnitSpec
    is_restated: bool
    readiness: FactReadiness
    collision_class: str | None
    source_confidence: float | None

    def semantic_key(self) -> tuple[object, ...]:
        """Identity for deduplication without collapsing distinct disclosures."""
        return (
            self.document_id,
            self.entity,
            self.basis,
            self.statement_type,
            self.metric_id,
            self.row_hierarchy,
            self.column_hierarchy,
            self.period,
            self.period_role,
            self.value,
            self.unit,
        )


def make_logical_table_uid(
    *,
    document_id: str,
    statement_type: str | None,
    section_text: str | None,
    physical_table_uid: str,
) -> str:
    """Build a deterministic identity across continuation table fragments.

    Empty/generic sections deliberately retain the physical table identity so
    unrelated tables in a document are never merged speculatively.
    """
    section = _normalise_section(section_text or "")
    if not section or section in {"bang", "table", "thuyet minh", "notes"}:
        section = f"physical:{physical_table_uid}"
    payload = "\x1f".join(
        (
            _normalise(document_id),
            _normalise(statement_type or "unknown"),
            section,
        )
    )
    return "logical-table:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def split_hierarchy(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in re.split(r"\s*[›>]\s*", value) if part.strip())


def _normalise_section(value: str) -> str:
    normalised = _normalise(value)
    normalised = re.sub(
        r"\b(?:tiep theo|continued|continuation|trang|page)\b(?:\s+\d+)?",
        " ",
        normalised,
    )
    return re.sub(r"\s+", " ", normalised).strip()


def _normalise(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold().replace("đ", "d"))
    ascii_value = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", ascii_value).strip()
