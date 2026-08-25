#!/usr/bin/env python3
"""Per-file / per-cell storage-scale scan + mixed-scale file detection.

Definitions (explicit, so aggregates are reproducible):
  parsed_raw      = parse_raw_number(value_raw)
  storage_ratio   = value / parsed_raw            (only when parsed_raw != 0)
  storage_exp     = k such that storage_ratio == 10^k within rel tol 1e-6
  column_dim/exp  = scan_unit(col_label)          (MONEY exponent over VND)
  canonical_vnd   = parsed_raw * 10^column_exp    (MONEY only)

MIXED_SCALE_FILE definitions (both emitted, never conflated):
  narrow : file has >=2 distinct storage_exp among MONEY-dimension cells
  broad  : file has >=2 distinct storage_exp among all numeric cells
Cells excluded from both: raw unparseable, zero raw, value unparseable.
"""
from __future__ import annotations
import csv, json, argparse, sys, collections, hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from text2pandas.domain.units.lexicon import (parse_raw_number, storage_ratio, snap_power_of_ten,
                     scan_unit, MONEY)


def scan_file(path: Path):
    cells = []
    with open(path, newline="", encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            raw, st = parse_raw_number(row.get("value_raw"))
            ratio, rst = storage_ratio(row.get("value"), row.get("value_raw"))
            exp = snap_power_of_ten(ratio) if rst == "OK" else None
            dim, cexp, tok = scan_unit(row.get("col_label", ""))
            cells.append({
                "row_index": i,
                "row_path": row.get("row_path", ""),
                "col_label": row.get("col_label", ""),
                "value_raw": row.get("value_raw", ""),
                "value": row.get("value", ""),
                "parsed_raw": raw,
                "parse_status": st,
                "storage_ratio": ratio,
                "storage_ratio_status": rst,
                "storage_exp": exp,
                "column_dimension": dim,
                "column_scale_exponent": cexp,
                "column_unit_token": tok,
            })
    return cells


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out-files", required=True)
    ap.add_argument("--out-cells", required=False)
    ap.add_argument("--summary", required=True)
    a = ap.parse_args()

    files = sorted(Path(a.data_dir).glob("*.csv"))
    frecs = []
    agg = collections.Counter()
    cross = collections.Counter()
    cells_fh = open(a.out_cells, "w", encoding="utf-8") if a.out_cells else None
    for p in files:
        cells = scan_file(p)
        money_exps = sorted({c["storage_exp"] for c in cells
                             if c["storage_exp"] is not None and c["column_dimension"] == MONEY})
        all_exps = sorted({c["storage_exp"] for c in cells if c["storage_exp"] is not None})
        excl = sum(1 for c in cells if c["storage_exp"] is None)
        # header/storage disagreement: column says 10^e but storage kept raw scale
        disagree = sum(1 for c in cells
                       if c["column_dimension"] == MONEY and c["storage_exp"] is not None
                       and c["column_scale_exponent"] not in (None, 0)
                       and c["storage_exp"] != c["column_scale_exponent"])
        rec = {
            "file": p.name,
            "n_cells": len(cells),
            "n_excluded": excl,
            "storage_exps_money": money_exps,
            "storage_exps_all": all_exps,
            "mixed_scale_narrow": len(money_exps) >= 2,
            "mixed_scale_broad": len(all_exps) >= 2,
            "n_header_storage_disagree": disagree,
        }
        frecs.append(rec)
        agg["files"] += 1
        agg["mixed_narrow"] += rec["mixed_scale_narrow"]
        agg["mixed_broad"] += rec["mixed_scale_broad"]
        agg["cells"] += len(cells)
        agg["cells_excluded"] += excl
        for c in cells:
            cross[(str(c["storage_exp"]), c["column_dimension"], str(c["column_scale_exponent"]))] += 1
            if cells_fh:
                cells_fh.write(json.dumps({"file": p.name, **c}, ensure_ascii=False, sort_keys=True) + "\n")
    if cells_fh:
        cells_fh.close()

    with open(a.out_files, "w", encoding="utf-8") as fh:
        for r in frecs:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    summary = {
        "n_files": agg["files"],
        "n_cells": agg["cells"],
        "n_cells_excluded_from_scale": agg["cells_excluded"],
        "mixed_scale_files_narrow_money": agg["mixed_narrow"],
        "mixed_scale_files_broad_all": agg["mixed_broad"],
        "cross_storage_exp__column_dim__column_exp": {
            "|".join(k): v for k, v in sorted(cross.items(), key=lambda kv: (-kv[1], kv[0]))
        },
        "n_files_with_header_storage_disagreement":
            sum(1 for r in frecs if r["n_header_storage_disagree"] > 0),
        "n_cells_header_storage_disagreement":
            sum(r["n_header_storage_disagree"] for r in frecs),
    }
    Path(a.summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
