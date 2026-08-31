"""Build and gate an additive, source-sealed recovery candidate."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from text2pandas.application.usecases.submission import (
    publication_blockers,
    replay_zip,
    validate_zip,
)
from text2pandas.application.usecases.wave2_recovery import (
    build_recovery_candidate,
)
from text2pandas.infrastructure.checksums import sha256_file

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "artifacts/official/submission-3828/submission.zip"
DEFAULT_A6 = ROOT / "data/processed/a6/c6887fb633374fad/silver.db"
DEFAULT_LEDGER = ROOT / "configs/evaluation/recovery_wave2_review_3828_v1.json"
DEFAULT_QUESTIONS = ROOT / "data/raw/btc/questions/questions.jsonl"
DEFAULT_CORPUS = ROOT / "data/raw/btc/financial_statements"
DEFAULT_RUN_ROOT = ROOT / "artifacts/runs/recovery-wave2"


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
    parser.add_argument("--review-ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument(
        "--candidate-kind",
        default="text2pandas.recovery_wave2_candidate",
    )
    parser.add_argument("--evidence-prefix", default="wave2")
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
    a6_database = args.a6_database.expanduser().resolve()
    review_ledger = args.review_ledger.expanduser().resolve()
    questions_path = args.questions.expanduser().resolve()
    corpus = args.corpus.expanduser().resolve()
    missing = [
        str(path)
        for path in (baseline, a6_database, review_ledger, questions_path, corpus)
        if not path.exists()
    ]
    if missing:
        parser.error(f"required inputs are missing: {missing}")

    build = build_recovery_candidate(
        baseline_zip=baseline,
        a6_database=a6_database,
        review_ledger=review_ledger,
        output_zip=output_zip,
        evidence_prefix=args.evidence_prefix,
    )
    questions = _question_scope(questions_path)
    validations = {
        profile: validate_zip(output_zip, questions, corpus_root=corpus, profile=profile)
        for profile in ("competition", "complete")
    }
    with tempfile.TemporaryDirectory(prefix="text2pandas-wave2-") as temp:
        replays = {
            profile: replay_zip(output_zip, Path(temp) / profile, profile=profile)
            for profile in ("competition", "complete")
        }
    blockers = publication_blockers(
        validations["competition"],
        replays["competition"],
        expected_records=len(questions),
        profile="competition",
    )
    if blockers:
        output_zip.unlink(missing_ok=True)
        raise ValueError(f"competition release gate failed: {blockers[:10]}")
    if replays["competition"]["executed"] != build.candidate_executable:
        output_zip.unlink(missing_ok=True)
        raise ValueError("candidate executable count differs from clean replay")

    ledger = json.loads(review_ledger.read_text(encoding="utf-8"))
    decisions = Counter(row["decision"] for row in ledger["reviews"])
    cohorts = {
        cohort: dict(
            Counter(row["decision"] for row in ledger["reviews"] if row["cohort"] == cohort)
        )
        for cohort in sorted({row["cohort"] for row in ledger["reviews"]})
    }
    manifest = {
        "schema_version": 1,
        "kind": args.candidate_kind,
        "run_id": args.run_id,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source": {
            "git_commit": source_commit,
            "git_dirty": False,
            "baseline_zip": {"path": str(baseline), "sha256": sha256_file(baseline)},
            "a6_database": {"path": str(a6_database), "sha256": sha256_file(a6_database)},
            "review_ledger": {"path": str(review_ledger), "sha256": sha256_file(review_ledger)},
            "questions": {
                "path": str(questions_path),
                "sha256": sha256_file(questions_path),
                "records": len(questions),
            },
        },
        "configuration": {
            "mode": "additive_only",
            "runtime_model_gold": False,
            "replace_existing_answers": False,
            "replace_retrieval": False,
            "max_new_qids": len(build.accepted_qids),
        },
        "review": {
            "records": len(ledger["reviews"]),
            "decisions": dict(decisions),
            "by_cohort": cohorts,
            "accepted_qids": list(build.accepted_qids),
            "rejected_qids": list(build.rejected_qids),
            "source_fact_count": build.source_fact_count,
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
