"""Build, replay, and seal a submission-rule-3 compliance candidate."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from text2pandas.application.usecases.rule3_compliance import (
    build_rule3_compliance_candidate,
)
from text2pandas.application.usecases.submission import (
    publication_blockers,
    replay_zip,
    validate_zip,
)
from text2pandas.infrastructure.checksums import sha256_file

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "artifacts/official/submission-3842/submission.zip"
DEFAULT_A6 = ROOT / "data/processed/a6/c6887fb633374fad/silver.db"
DEFAULT_CORPUS = ROOT / "data/raw/btc/financial_statements"
DEFAULT_LEDGER = ROOT / "configs/evaluation/rule3_compliance_repair_3842_v1.json"
DEFAULT_QUESTIONS = ROOT / "data/raw/btc/questions/questions.jsonl"
DEFAULT_RUN_ROOT = ROOT / "artifacts/runs/rule3-compliance"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _question_scope(path: Path) -> dict[int, str]:
    return {
        int(row["id"]): str(row["question"])
        for row in (
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--a6-database", type=Path, default=DEFAULT_A6)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--repair-ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    args = parser.parse_args()

    if not args.run_id or Path(args.run_id).name != args.run_id:
        parser.error("run id must be one path-safe name")
    if _git("status", "--porcelain"):
        parser.error("candidate builds require a clean committed source tree")
    source_commit = _git("rev-parse", "HEAD")

    stage = args.run_root.expanduser().resolve() / args.run_id
    output_zip = stage.with_suffix(".zip")
    if stage.exists() or output_zip.exists():
        parser.error(f"immutable run output already exists: {stage}")
    baseline = args.baseline.expanduser().resolve()
    a6_database = args.a6_database.expanduser().resolve()
    corpus = args.corpus.expanduser().resolve()
    repair_ledger = args.repair_ledger.expanduser().resolve()
    questions_path = args.questions.expanduser().resolve()
    required = (baseline, a6_database, corpus, repair_ledger, questions_path)
    if missing := [str(path) for path in required if not path.exists()]:
        parser.error(f"required inputs are missing: {missing}")

    questions = _question_scope(questions_path)
    baseline_validation = validate_zip(
        baseline,
        questions,
        corpus_root=corpus,
        profile="competition",
    )
    build = build_rule3_compliance_candidate(
        baseline_zip=baseline,
        a6_database=a6_database,
        corpus_root=corpus,
        repair_ledger=repair_ledger,
        output_zip=output_zip,
    )
    with tempfile.TemporaryDirectory(prefix="text2pandas-rule3-") as temp_name:
        temp = Path(temp_name)
        duplicate = temp / "duplicate.zip"
        build_rule3_compliance_candidate(
            baseline_zip=baseline,
            a6_database=a6_database,
            corpus_root=corpus,
            repair_ledger=repair_ledger,
            output_zip=duplicate,
        )
        deterministic = output_zip.read_bytes() == duplicate.read_bytes()
        validations = {
            profile: validate_zip(
                output_zip,
                questions,
                corpus_root=corpus,
                profile=profile,
            )
            for profile in ("competition", "complete")
        }
        replays = {
            profile: replay_zip(output_zip, temp / f"replay-{profile}", profile=profile)
            for profile in ("competition", "complete")
        }

    blockers = publication_blockers(
        validations["competition"],
        replays["competition"],
        expected_records=len(questions),
        profile="competition",
    )
    if blockers or not deterministic:
        output_zip.unlink(missing_ok=True)
        reasons = [*blockers, *([] if deterministic else ["package:not-deterministic"])]
        raise ValueError(f"rule-3 release gate failed: {reasons[:10]}")
    baseline_dependency_errors = [
        error
        for error in baseline_validation.errors
        if "does not depend" in error or "zero multiplier" in error
    ]
    manifest = {
        "schema_version": 1,
        "kind": "text2pandas.rule3_compliance_candidate",
        "run_id": args.run_id,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source": {
            "git_commit": source_commit,
            "git_dirty": False,
            "baseline_zip": {"path": str(baseline), "sha256": sha256_file(baseline)},
            "a6_database": {
                "path": str(a6_database),
                "sha256": sha256_file(a6_database),
            },
            "repair_ledger": {
                "path": str(repair_ledger),
                "sha256": sha256_file(repair_ledger),
            },
            "questions": {
                "path": str(questions_path),
                "sha256": sha256_file(questions_path),
                "records": len(questions),
            },
        },
        "repair": {
            "qids": list(build.repaired_qids),
            "count": len(build.repaired_qids),
            "baseline_effective_dependency_errors": len(baseline_dependency_errors),
            "answers_preserved": build.answers_preserved,
            "evidence_preserved": build.evidence_preserved,
            "csv_payloads_preserved": build.csv_payloads_preserved,
            "source_locator_rebound_qids": len(build.retrieval_rebound_qids),
        },
        "traceability": {
            "csv_members": build.csv_members,
            "csv_rows_verified": build.csv_rows_verified,
            "a6_uid_rows_verified": build.a6_uid_rows_verified,
            "raw_btc_rows_verified": build.raw_rows_verified,
            "source_locators_verified": build.source_locators_verified,
            "gate": "PASS",
        },
        "coverage": {
            "records": len(questions),
            "executable": build.executable_records,
            "unresolved": build.unresolved_records,
            "official_answer_accuracy": "NOT_MEASURED",
        },
        "package": {
            "path": str(output_zip),
            "sha256": sha256_file(output_zip),
            "deterministic_two_builds": deterministic,
        },
        "validation": {
            profile: {
                "errors": len(report.errors),
                "warnings": len(report.warnings),
                "error_examples": report.errors[:10],
                "warning_examples": report.warnings[:10],
            }
            for profile, report in validations.items()
        },
        "replay": replays,
        "policy": {
            "competition_gate": "PASS",
            "competition_blockers": [],
            "complete_gate": "PASS" if validations["complete"].ok else "FAIL",
            "publication_eligible": False,
            "publication_blockers": [
                "official-answer-accuracy:not-measured",
                f"unresolved-records:{build.unresolved_records}",
            ],
            "release_class": "COMPLIANCE_CANDIDATE_DO_NOT_AUTO_UPLOAD",
        },
    }
    stage.mkdir(parents=True)
    (stage / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    print(output_zip)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
