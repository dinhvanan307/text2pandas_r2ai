"""Build and verify a source-adjudicated, baseline-preserving submission."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from text2pandas.application.usecases.safe_recovery import (
    build_source_adjudicated_candidate,
)
from text2pandas.application.usecases.submission import (
    publication_blockers,
    replay_zip,
    validate_zip,
)
from text2pandas.infrastructure.checksums import sha256_file

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "artifacts/official/submission-3821/submission.zip"
DEFAULT_SOURCE_RECORDS = ROOT / (
    "artifacts/runs/grounded-v5/"
    "grounded-v6-downloaded-replace-trusted-20260830-r1/records.jsonl"
)
DEFAULT_LEDGER = ROOT / "configs/evaluation/grounded_v6_recovery_review_3821_v1.json"
DEFAULT_QUESTIONS = ROOT / "data/raw/btc/questions/questions.jsonl"
DEFAULT_CORPUS = ROOT / "data/raw/btc/financial_statements"
DEFAULT_RUN_ROOT = ROOT / "artifacts/runs/safe-recovery"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
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
    parser.add_argument(
        "--cohort",
        required=True,
        choices=["trusted", "trusted_and_shadow"],
    )
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--source-records", type=Path, default=DEFAULT_SOURCE_RECORDS)
    parser.add_argument("--review-ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    args = parser.parse_args()

    if not args.run_id or Path(args.run_id).name != args.run_id:
        parser.error("run id must be one path-safe name")
    dirty = _git("status", "--porcelain")
    if dirty:
        parser.error("candidate builds require a clean committed source tree")
    source_commit = _git("rev-parse", "HEAD")

    stage = args.run_root.expanduser().resolve() / args.run_id
    output_zip = stage.with_suffix(".zip")
    if stage.exists() or output_zip.exists():
        parser.error(f"immutable run output already exists: {stage}")
    baseline = args.baseline.expanduser().resolve()
    source_records = args.source_records.expanduser().resolve()
    review_ledger = args.review_ledger.expanduser().resolve()
    questions_path = args.questions.expanduser().resolve()
    corpus = args.corpus.expanduser().resolve()
    required = (baseline, source_records, review_ledger, questions_path, corpus)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        parser.error(f"required inputs are missing: {missing}")

    build = build_source_adjudicated_candidate(
        baseline_zip=baseline,
        source_records=source_records,
        review_ledger=review_ledger,
        output_zip=output_zip,
        cohort=args.cohort,
    )
    questions = _question_scope(questions_path)
    validations = {
        profile: validate_zip(
            output_zip,
            questions,
            corpus_root=corpus,
            profile=profile,
        )
        for profile in ("competition", "complete")
    }
    with tempfile.TemporaryDirectory(prefix="text2pandas-safe-recovery-") as temp:
        replays = {
            profile: replay_zip(
                output_zip,
                Path(temp) / profile,
                profile=profile,
            )
            for profile in ("competition", "complete")
        }
    competition_blockers = publication_blockers(
        validations["competition"],
        replays["competition"],
        expected_records=len(questions),
        profile="competition",
    )
    if competition_blockers:
        output_zip.unlink(missing_ok=True)
        raise ValueError(f"competition release gate failed: {competition_blockers[:10]}")
    if replays["competition"]["executed"] != build.candidate_executable:
        output_zip.unlink(missing_ok=True)
        raise ValueError("candidate executable count differs from clean replay")

    ledger = json.loads(review_ledger.read_text(encoding="utf-8"))
    decisions = Counter(row["decision"] for row in ledger["reviews"])
    cohort_decisions = {
        cohort: dict(
            Counter(
                row["decision"]
                for row in ledger["reviews"]
                if row["cohort"] == cohort
            )
        )
        for cohort in ("trusted", "shadow")
    }
    manifest = {
        "schema_version": 1,
        "kind": "text2pandas.safe_recovery_candidate",
        "run_id": args.run_id,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source": {
            "git_commit": source_commit,
            "git_dirty": False,
            "baseline_zip": {
                "path": str(baseline),
                "sha256": sha256_file(baseline),
            },
            "source_records": {
                "path": str(source_records),
                "sha256": sha256_file(source_records),
            },
            "review_ledger": {
                "path": str(review_ledger),
                "sha256": sha256_file(review_ledger),
            },
            "questions": {
                "path": str(questions_path),
                "sha256": sha256_file(questions_path),
                "records": len(questions),
            },
        },
        "configuration": {
            "cohort": args.cohort,
            "runtime_model_gold": False,
            "replace_existing_answers": False,
            "replace_retrieval": False,
        },
        "review": {
            "records": len(ledger["reviews"]),
            "decisions": dict(decisions),
            "by_cohort": cohort_decisions,
            "accepted_qids": list(build.accepted_qids),
            "trusted_qids": list(build.trusted_qids),
            "shadow_qids": list(build.shadow_qids),
            "official_correctness": "NOT_MEASURED",
            "independent_gold": "NOT_AVAILABLE",
        },
        "coverage": {
            "baseline_executable": build.baseline_executable,
            "baseline_unresolved": build.baseline_unresolved,
            "candidate_executable": build.candidate_executable,
            "candidate_unresolved": build.candidate_unresolved,
            "fill_count": len(build.accepted_qids),
            "rate": build.candidate_executable / len(questions),
        },
        "preservation": {
            "baseline_answer_query_evidence": {
                "preserved": build.protected_answer_query_evidence,
                "expected": build.baseline_executable,
            },
            "baseline_retrieval": {
                "preserved": build.protected_retrieval,
                "expected": len(questions),
            },
            "baseline_csv_payloads": {
                "preserved": build.protected_csv_payloads,
                "expected": build.baseline_csv_members,
            },
            "answer_layer_changed_qids": list(build.accepted_qids),
            "retrieval_changed_qids": [],
        },
        "package": {
            "path": str(output_zip),
            "sha256": sha256_file(output_zip),
            "records": len(questions),
            "csv_members": build.candidate_csv_members,
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
                "independent-gold:not-available",
            ],
            "release_class": "EXPERIMENTAL_MANUAL_UPLOAD_CANDIDATE",
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
