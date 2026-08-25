"""Period resolution for A6 cells.

The corpus does NOT put an absolute year in most column headers. It encodes the
period *relatively* -- "Năm nay" / "Năm trước" / "Số cuối năm" / "Số đầu năm" --
and puts the absolute year in the **filename**:

    a6_EIB_financial_statements_2021_consolidated_line1377.csv
                                 ^^^^ the anchor year

So resolving a cell's period needs both halves. Reading only the column header
(as an earlier version of the adapter did) silently returns ``None`` for the
majority of cells, which then starves every multi-period operation and shows up
downstream as "operands not available" -- a measurement artifact, not a fact
about the data.

Conventions implemented (all reversible, all tested):

    "Năm nay",  "Kỳ này",  "Số cuối năm", "Cuối kỳ"   -> anchor
    "Năm trước","Kỳ trước","Số đầu năm",  "Đầu kỳ"    -> anchor - 1

``Số đầu năm`` is the opening balance of the anchor year, which equals the
closing balance of the prior year; for period *matching* purposes it is treated
as the prior year, and ``basis`` records which reading was used.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

_FILE_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_ABS_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")

CURRENT = "CURRENT"
PRIOR = "PRIOR"
ABSOLUTE = "ABSOLUTE"
UNRESOLVED = "UNRESOLVED"

_CURRENT_PAT = re.compile(
    r"(n[ăa]m\s*nay|k[ỳy]\s*n[àa]y|s[ốo]\s*cu[ốo]i\s*n[ăa]m|cu[ốo]i\s*k[ỳy]"
    r"|cu[ốo]i\s*n[ăa]m\s*nay|current\s*year|this\s*year)")
_PRIOR_PAT = re.compile(
    r"(n[ăa]m\s*tr[ưu][ớo]c|k[ỳy]\s*tr[ưu][ớo]c|s[ốo]\s*đ[ầa]u\s*n[ăa]m|đ[ầa]u\s*k[ỳy]"
    r"|đ[ầa]u\s*n[ăa]m|prior\s*year|previous\s*year)")


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s or "").lower()


@dataclass(frozen=True)
class Period:
    """A resolved period, with how it was resolved."""

    year: Optional[str]
    kind: str                  # ABSOLUTE | CURRENT | PRIOR | UNRESOLVED
    anchor_year: Optional[str] = None
    source: Optional[str] = None   # col_label | filename+col_label | none

    @property
    def resolved(self) -> bool:
        return self.year is not None

    def __str__(self) -> str:
        return self.year or "UNRESOLVED"


def anchor_year_from_path(csv_path: str) -> Optional[str]:
    """The statement year named in the file name.

    Takes the LAST year-looking token, because ticker/line fragments can carry
    digits and the statement year is the trailing one in this corpus naming.
    """
    if not csv_path:
        return None
    stem = csv_path.rsplit("/", 1)[-1]
    stem = re.sub(r"_line\d+", "", stem)
    hits = _FILE_YEAR.findall(stem)
    return hits[-1] if hits else None


def resolve_period(col_label: str, csv_path: str = "") -> Period:
    """Absolute period of a cell, from its header plus the file's anchor year."""
    label = col_label or ""
    # 1. an explicit year in the header always wins
    m = _ABS_YEAR.search(label)
    if m:
        return Period(m.group(1), ABSOLUTE, source="col_label")

    anchor = anchor_year_from_path(csv_path)
    t = _norm(label)
    if anchor:
        if _CURRENT_PAT.search(t):
            return Period(anchor, CURRENT, anchor_year=anchor, source="filename+col_label")
        if _PRIOR_PAT.search(t):
            return Period(str(int(anchor) - 1), PRIOR, anchor_year=anchor,
                          source="filename+col_label")
    return Period(None, UNRESOLVED, anchor_year=anchor, source="none")
