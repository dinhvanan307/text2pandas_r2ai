"""Adapters between the A6 CSV shape and the pipeline's typed contracts.

Kept out of the core so the core has no I/O and no corpus assumptions.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Iterable, Optional

from .binding import CandidateCell
from .period import resolve_period
from .units import UNKNOWN, Unit

# the unit lexicon lives with the measurement tooling; import it by path so the
# package has no hard dependency on the tools tree being installed
_TOOLS = Path(__file__).resolve().parents[3] / "tools" / "measure_v4"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from unitlex import (  # noqa: E402
    parse_raw_number, scan_question_unit, scan_unit, snap_power_of_ten,
    storage_ratio,
)


def unit_of_column(col_label: str, row_path: str = "") -> tuple[Unit, str]:
    """Declared unit of a cell, from its column header, then its row label.

    Returns ``(unit, source)`` so provenance records where the unit came from.
    """
    dim, exp, _tok = scan_unit(col_label)
    if dim != UNKNOWN:
        return Unit(dim, exp), "col_label"
    dim, exp, _tok = scan_unit(row_path)
    if dim != UNKNOWN:
        return Unit(dim, exp), "row_path"
    return Unit(UNKNOWN), "none"


def requested_unit_of(question: str) -> Unit:
    dim, exp, _tok = scan_question_unit(question)
    return Unit(dim, exp)


def load_cells(csv_path: str, df_var: str, root: Optional[Path] = None) -> list[CandidateCell]:
    """Read one A6 CSV into typed candidate cells."""
    full = Path(root or ".") / csv_path
    out: list[CandidateCell] = []
    with open(full, newline="", encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            raw, _st = parse_raw_number(row.get("value_raw"))
            ratio, rst = storage_ratio(row.get("value"), row.get("value_raw"))
            sexp = snap_power_of_ten(ratio) if rst == "OK" else None
            unit, _src = unit_of_column(row.get("col_label", ""), row.get("row_path", ""))
            try:
                value = float(row.get("value"))
            except (TypeError, ValueError):
                value = float("nan")
            out.append(CandidateCell(
                df_var=df_var,
                csv_path=csv_path,
                row_index=i,
                row_path=row.get("row_path", ""),
                col_label=row.get("col_label", ""),
                value_raw=row.get("value_raw", ""),
                value=value,
                parsed_raw=raw,
                storage_exponent=sexp,
                unit=unit,
                period=_period_of(row.get("col_label", ""), csv_path),
            ))
    return out


def _period_of(col_label: str, csv_path: str = "") -> Optional[str]:
    """Absolute year of a cell.

    Delegates to :mod:`period`, which combines the column header with the
    anchor year in the filename. Reading the header alone loses the majority of
    cells, because this corpus writes periods relatively ("Năm nay" /
    "Năm trước") and keeps the absolute year in the file name.
    """
    return resolve_period(col_label, csv_path).year


def load_frames(evidence: Iterable[dict], root: Optional[Path] = None) -> dict:
    """Build the ``{var: DataFrame}`` namespace an emitted query executes in."""
    import pandas as pd

    frames = {}
    for e in evidence:
        var, path = e.get("variable"), e.get("csv_path")
        if not var or not path:
            continue
        frames[var] = pd.read_csv(Path(root or ".") / path)
    return frames
