"""Deterministic normalization for financial fact labels and row hierarchies."""

from __future__ import annotations

import re
from functools import lru_cache

from text2pandas.domain.metrics import normalize_phrase

_HIERARCHY_SEPARATOR = re.compile(r"\s*(?:›|>|→|»)\s*")
_LEADING_ENUMERATOR = re.compile(
    r"^(?:(?:[ivxlcdm]+|\d+(?:\.\d+)*|[a-z])\s*[.):\-]+\s*)+"
)
_FORMULA_SUFFIX = re.compile(
    r"\s*\((?:ma\s+so\s*)?\d[\d\s=+\-*/.,:]*\)\s*$"
)
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


@lru_cache(maxsize=262_144)
def normalize_fact_label(value: str) -> str:
    """Normalize one row label without retaining layout punctuation.

    A6 preserves punctuation because it is useful for evidence display. Metric
    matching needs a second, deterministic representation where enumerators and
    accounting formula suffixes cannot break an otherwise exact label match.
    Semantic parentheticals are retained; only numeric/formula suffixes such as
    ``(100 = 110 + 120)`` are removed.
    """

    normalized = normalize_phrase(value)
    normalized = _LEADING_ENUMERATOR.sub("", normalized)
    normalized = _FORMULA_SUFFIX.sub("", normalized)
    normalized = _NON_ALNUM.sub(" ", normalized)
    return " ".join(normalized.split())


@lru_cache(maxsize=262_144)
def fact_label_segments(value: str) -> tuple[str, ...]:
    """Return normalized non-empty hierarchy segments from an A6 row path."""

    return tuple(
        normalized
        for part in _HIERARCHY_SEPARATOR.split(value)
        if (normalized := normalize_fact_label(part))
    )
