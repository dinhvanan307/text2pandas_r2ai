"""Create a verified manual-upload handoff without bypassing promotion policy."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from text2pandas.application.usecases.submission import (
    publication_blockers,
    replay_zip,
    validate_zip,
)
from text2pandas.infrastructure.checksums import sha256_file

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "data/raw/btc/questions/questions.jsonl"
CORPUS = ROOT / "data/raw/btc/financial_statements"
RUN_ROOTS = ("answer", "grounded-v5")


def _resolve_candidate_stage(run_id: str) -> tuple[Path, Path]:
    if not run_id or Path(run_id).name != run_id:
        raise ValueError("candidate run id must be one path-safe name")
    matches: list[tuple[Path, Path]] = []
    checked: list[Path] = []
    for run_kind in RUN_ROOTS:
        stage = ROOT / "artifacts/runs" / run_kind / run_id
        source_zip = stage.with_suffix(".zip")
        checked.append(stage)
        if source_zip.is_file() and (stage / "manifest.json").is_file():
            matches.append((stage, source_zip))
    if not matches:
        locations = ", ".join(str(path) for path in checked)
        raise FileNotFoundError(f"candidate run not found under: {locations}")
    if len(matches) > 1:
        raise ValueError(f"candidate run id is ambiguous across run roots: {run_id}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--release-profile",
        choices=["complete", "competition"],
        default="complete",
        help="Explicitly select the all-QID or competition-compatible release contract",
    )
    parser.add_argument(
        "--questions",
        type=Path,
        default=QUESTIONS,
        help="Exact leaderboard phase question JSONL used as the release scope",
    )
    args = parser.parse_args()
    try:
        stage, source_zip = _resolve_candidate_stage(args.candidate_run_id)
    except (FileNotFoundError, ValueError) as error:
        parser.error(str(error))
    manifest_path = stage / "manifest.json"
    output = args.output.expanduser().resolve()
    if output.exists():
        parser.error(f"immutable output already exists: {output}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_sha = sha256_file(source_zip)
    declared_sha = str((manifest.get("package") or {}).get("sha256") or "")
    if actual_sha != declared_sha:
        raise ValueError("candidate ZIP sha256 does not match manifest")
    source = manifest.get("source") or {}
    if source.get("git_dirty") is not False or not source.get("git_commit"):
        raise ValueError("candidate source identity is not a clean Git commit")

    questions_path = args.questions.expanduser().resolve()
    if not questions_path.is_file():
        parser.error(f"evaluation question scope is missing: {questions_path}")
    questions = {
        int(row["id"]): str(row["question"])
        for row in (
            json.loads(line)
            for line in questions_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    validation = validate_zip(
        source_zip,
        questions,
        corpus_root=CORPUS,
        profile=args.release_profile,
    )
    with tempfile.TemporaryDirectory(prefix="text2pandas-handoff-") as temp:
        replay = replay_zip(
            source_zip,
            Path(temp) / "replay",
            profile=args.release_profile,
        )
    replay_mismatches = replay["executed"] - replay["matched"]
    blockers = publication_blockers(
        validation,
        replay,
        expected_records=len(questions),
        profile=args.release_profile,
    )
    if blockers:
        raise ValueError(f"candidate failed fresh handoff verification: blockers={blockers[:10]}")

    output.mkdir(parents=True)
    submission_path = output / "submission.zip"
    shutil.copy2(source_zip, submission_path)
    shutil.copy2(manifest_path, output / "candidate_manifest.json")
    policy = manifest.get("policy") or {}
    handoff = {
        "schema_version": 1,
        "kind": "text2pandas.manual_leaderboard_submission_handoff",
        "status": "READY_FOR_MANUAL_LEADERBOARD_UPLOAD_EXPERIMENTAL",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "candidate_run_id": args.candidate_run_id,
        "release_profile": args.release_profile,
        "evaluation_scope": {
            "path": str(questions_path),
            "sha256": sha256_file(questions_path),
            "records": len(questions),
        },
        "production_promoted": bool(policy.get("publication_eligible", False)),
        "publication_blockers": policy.get("publication_blockers") or [],
        "submission": {
            "path": "submission.zip",
            "sha256": actual_sha,
            "records": validation.n_records,
        },
        "validation": {
            "errors": validation.errors,
            "warnings": validation.warnings,
        },
        "replay": {**replay, "mismatches": replay_mismatches},
        "coverage": {
            "executable": replay["executed"],
            "unresolved": replay["no_evidence"],
            "rate": replay["executed"] / replay["total"] if replay["total"] else 0.0,
        },
        "source": source,
    }
    (output / "HANDOFF.json").write_text(
        json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "SHA256SUMS").write_text(
        f"{actual_sha}  submission.zip\n"
        f"{sha256_file(output / 'candidate_manifest.json')}  candidate_manifest.json\n",
        encoding="utf-8",
    )
    policy_blocker_text = ", ".join(
        str(value) for value in handoff["publication_blockers"]
    )
    (output / "README.md").write_text(
        "# Text2Pandas leaderboard submission handoff\n\n"
        "Upload `submission.zip` directly to the competition leaderboard.\n\n"
        f"- Records: {validation.n_records}\n"
        f"- SHA-256: `{actual_sha}`\n"
        f"- Replay: {replay['matched']}/{replay['executed']} matched\n"
        f"- Validation errors/warnings: {len(validation.errors)}/{len(validation.warnings)}\n"
        f"- Coverage: {replay['executed']}/{replay['total']} executable\n"
        f"- Release profile: {args.release_profile}\n"
        "- Release class: experimental manual-upload candidate\n"
        f"- Production-promotion blockers: {policy_blocker_text or 'none'}\n\n"
        "Manual leaderboard upload is allowed for measurement; it does not mark "
        "the semantic candidate as production-promoted. Record the returned submission ID and "
        "all ten official metrics in the implementation report.\n",
        encoding="utf-8",
    )
    print(json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
