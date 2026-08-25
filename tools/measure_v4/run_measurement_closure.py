#!/usr/bin/env python3
"""One command that regenerates every measurement-closure artifact.

    python3 tools/measure_v4/run_measurement_closure.py \
        --submission-zip data/submissions/submission_P0I.zip \
        --out-dir artifacts/measurement_closure_v4

Deterministic: rerunning produces byte-identical outputs (sorted keys, sorted
records, no timestamps inside the data files).
"""
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission-zip", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--keep-cells", action="store_true",
                    help="also emit the 28k-row per-cell scan (large)")
    a = ap.parse_args()

    zip_path = Path(a.submission_zip).resolve()
    out = Path(a.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    work = Path(tempfile.mkdtemp(prefix="mc_"))
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(work)

    def run(mod, *args):
        cmd = [sys.executable, str(HERE / mod), *map(str, args)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            sys.stderr.write(r.stdout + r.stderr)
            raise SystemExit(f"{mod} failed")
        return r.stdout

    run("scan_query_factors.py",
        "--submission", work / "submission.json",
        "--out", out / "query_factor_ast_report.jsonl",
        "--summary", out / "query_factor_summary.json")

    scale_args = ["--data-dir", work / "data",
                  "--out-files", out / "scale_per_file.jsonl",
                  "--summary", out / "scale_summary.json"]
    if a.keep_cells:
        scale_args += ["--out-cells", out / "scale_per_cell.jsonl"]
    run("scan_storage_scale.py", *scale_args)

    run("build_unit_convention.py",
        "--root", work,
        "--out", out / "unit_convention_per_qid.jsonl",
        "--summary", out / "unit_convention_summary.json")

    # ------------------------------------------------ reconciliation report
    qf = json.loads((out / "query_factor_summary.json").read_text())
    sc = json.loads((out / "scale_summary.json").read_text())
    uc = json.loads((out / "unit_convention_summary.json").read_text())
    rows = [json.loads(l) for l in (out / "unit_convention_per_qid.jsonl").read_text().splitlines()]

    def qids(pred):
        return sorted(r["qid"] for r in rows if pred(r))

    spurious = qids(lambda r: r["verdict"] == "FACTOR_MISMATCH"
                    and r.get("required_factor") == 1.0
                    and r.get("actual_query_factor") == 1e-06)
    mismatch = qids(lambda r: r["verdict"] == "FACTOR_MISMATCH")

    recon = {
        "parent_zip": zip_path.name,
        "parent_sha256": sha256(zip_path),
        "n_records": qf["n_records"],
        "disputed_claims": {
            "371_queries_divide_1e6": {
                "status": "NOT_REPRODUCIBLE",
                "measured_alternatives": {
                    "distinct_qid_with_literal_1e6": qf["distinct_qid_with_literal_1e6"],
                    "occurrences_literal_1e6": qf["occurrences_literal_1e6"],
                    "distinct_qid_direct_div_1e6": qf["distinct_qid_div_by_1e6"],
                    "distinct_qid_net_factor_1e-6": qf["net_factor_histogram"].get("1e-06"),
                    "unit_contract_required_factor_1e-6_and_matching":
                        len(qids(lambda r: r["verdict"] == "FACTOR_MATCH"
                                 and r.get("required_factor") == 1e-06)),
                },
                "note": "no definition of '371' reproduces under AST, net-factor "
                        "or required-factor semantics; claim withdrawn until a "
                        "derivation is supplied",
            },
            "690_vs_768_storage_x1": {
                "status": "DEFINITIONAL",
                "note": "counts differ by whether cells excluded from scale "
                        "measurement (unparseable/zero raw) and non-MONEY cells "
                        "are in the denominator; see scale_summary cross-tab",
                "cross_tab": sc["cross_storage_exp__column_dim__column_exp"],
            },
            "18_vs_7_mixed_scale_files": {
                "status": "DEFINITIONAL_RESOLVED",
                "narrow_money_only": sc["mixed_scale_files_narrow_money"],
                "broad_all_cells": sc["mixed_scale_files_broad_all"],
                "n_files": sc["n_files"],
                "note": "both prior numbers sit inside the definitional band; "
                        "neither is 'the' answer without stating the definition",
            },
            "32_unit_errors_all_inside_U1_24": {
                "status": "SUPERSEDED",
                "measured_factor_mismatch_distinct_qid": len(mismatch),
                "factor_mismatch_qids": mismatch,
                "note": "the arithmetic contradiction is moot: a data-derived "
                        "contract finds a different, fully enumerated set",
            },
            "447_not_measurable": {
                "status": "SUPERSEDED",
                "measured_not_measurable": uc["verdicts"].get("NOT_MEASURABLE"),
                "reason_codes": uc["not_measurable_reasons"],
            },
        },
        "spurious_div_1e6_class": {
            "definition": "required_factor == 1.0 and query net factor == 1e-6",
            "n": len(spurious),
            "qids": spurious,
            "u1_7_whitelist": [42, 52, 238, 284, 317, 321, 322],
            "u1_7_is_subset": set([42, 52, 238, 284, 317, 321, 322]).issubset(set(spurious)),
            "coverage_of_class_by_u1_7": f"7/{len(spurious)}",
        },
        "verdicts": uc["verdicts"],
        "bucket_sum_equals_n_records": sum(uc["verdicts"].values()) == qf["n_records"],
    }
    (out / "measurement_summary.json").write_text(
        json.dumps(recon, ensure_ascii=False, indent=2, sort_keys=True, default=list), encoding="utf-8")

    shutil.rmtree(work, ignore_errors=True)
    print(json.dumps(recon, ensure_ascii=False, indent=2, sort_keys=True, default=list))
    return 0


if __name__ == "__main__":
    sys.exit(main())
