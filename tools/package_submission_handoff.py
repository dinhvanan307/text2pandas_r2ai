"""Create a verified manual-upload handoff without bypassing promotion policy."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from text2pandas.application.usecases.submission import replay_zip, validate_zip
from text2pandas.infrastructure.checksums import sha256_file

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "data/raw/btc/questions/questions.jsonl"
CORPUS = ROOT / "data/raw/btc/financial_statements"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    stage = ROOT / "artifacts/runs/answer" / args.candidate_run_id
    source_zip = stage.with_suffix(".zip")
    manifest_path = stage / "manifest.json"
    if not source_zip.is_file():
        parser.error(f"missing candidate ZIP: {source_zip}")
    if not manifest_path.is_file():
        parser.error(f"missing candidate manifest: {manifest_path}")
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

    questions = {
        int(row["id"]): str(row["question"])
        for row in (
            json.loads(line)
            for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    validation = validate_zip(source_zip, questions, corpus_root=CORPUS)
    with tempfile.TemporaryDirectory(prefix="text2pandas-handoff-") as temp:
        replay = replay_zip(source_zip, Path(temp) / "replay")
    replay_mismatches = replay["executed"] - replay["matched"]
    if validation.errors or replay["error"] or replay_mismatches:
        raise ValueError(
            "candidate failed fresh handoff verification: "
            f"validation={validation.errors}, replay={replay}"
        )

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
    blockers = ", ".join(str(value) for value in handoff["publication_blockers"])
    (output / "README.md").write_text(
        "# Text2Pandas leaderboard submission handoff\n\n"
        "Upload `submission.zip` directly to the competition leaderboard.\n\n"
        f"- Records: {validation.n_records}\n"
        f"- SHA-256: `{actual_sha}`\n"
        f"- Replay: {replay['matched']}/{replay['executed']} matched\n"
        "- Validation errors/warnings: 0/0\n"
        "- Release class: experimental manual-upload candidate\n"
        f"- Production-promotion blockers: {blockers or 'none'}\n\n"
        "Manual leaderboard upload is allowed for measurement; it does not mark "
        "Semantic V3 as production-promoted. Record the returned submission ID and "
        "all ten official metrics in the implementation report.\n",
        encoding="utf-8",
    )
    print(json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
