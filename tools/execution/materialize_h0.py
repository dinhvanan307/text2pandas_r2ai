"""Rebuild the small H0 adjudication and deterministic-package reports."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from execution.dong_goi_c1r import dung  # noqa: E402
from text2pandas.application.usecases.materialized_gates import (  # noqa: E402
    determinism_report,
    resolved_unit_adjudications,
    sha256_file,
    write_jsonl,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    output = ROOT / "artifacts" / "execution" / "h0"
    output.mkdir(parents=True, exist_ok=True)
    ledger_path = output / "unit_conflict_adjudication.jsonl"
    report_path = output / "determinism_report_v2.json"
    if report_path.exists() and not args.force:
        raise FileExistsError(report_path)

    records = ROOT / "data" / "curated" / "dev-legacy" / "answer_a6" / "records_a6.jsonl"
    questions = ROOT / "data" / "raw" / "btc" / "questions" / "questions.jsonl"
    baseline = ROOT / "artifacts" / "submissions" / "legacy" / "submission_P0G2.zip"
    canonical = ROOT / "artifacts" / "submissions" / "legacy" / "submission_C1R_LOCAL.zip"
    ledger = resolved_unit_adjudications(records, questions)
    write_jsonl(ledger, ledger_path, force=args.force)

    with tempfile.TemporaryDirectory(prefix="text2pandas-h0-") as temporary:
        root = Path(temporary)
        first = root / "clean-build-1" / "submission_C1R_LOCAL.zip"
        second = root / "clean-build-2" / "submission_C1R_LOCAL.zip"
        first.parent.mkdir()
        second.parent.mkdir()
        dung(first)
        dung(second)
        report = determinism_report(
            first,
            second,
            canonical=canonical,
            input_hashes={
                "records_a6.jsonl": sha256_file(records),
                "submission_P0G2.zip": sha256_file(baseline),
            },
        )
        # Temporary absolute paths are not stable provenance; retain distinct
        # logical clean-build identities while hashes attest the actual bytes.
        report["run_1"]["path"] = "clean-build-1/submission_C1R_LOCAL.zip"
        report["run_2"]["path"] = "clean-build-2/submission_C1R_LOCAL.zip"

    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not report["deterministic_full_zip_sha256"]:
        raise SystemExit("H0 determinism gate failed")
    if not report["canonical"]["matches_rebuild"]:
        raise SystemExit("canonical C1R does not match clean rebuild")
    print(f"materialized {len(ledger)} adjudications and deterministic ZIP report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
