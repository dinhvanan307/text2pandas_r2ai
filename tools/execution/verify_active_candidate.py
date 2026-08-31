"""Fail-closed gate for two active canonical submission runs.

This replaces no historical evidence. It validates only immutable artifacts
created by the current ``raw -> A6 -> retrieval -> canonical V2`` lineage.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.application.usecases.submission import (
    publication_blockers,
    replay_zip,
    validate_zip,
)
from text2pandas.infrastructure.checksums import sha256_file
from text2pandas.infrastructure.paths import ProjectPaths
from text2pandas.infrastructure.snapshots import ActiveSnapshots


class ActiveCandidateError(RuntimeError):
    """Raised when a current-release artifact violates an acceptance invariant."""


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ActiveCandidateError(f"missing artifact: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ActiveCandidateError(f"expected JSON object: {path}")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ActiveCandidateError(message)


def _questions(active: ActiveSnapshots) -> dict[int, str]:
    path = active.raw_path / "questions" / "questions.jsonl"
    questions: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            questions[int(record["id"])] = str(record["question"])
    _require(len(questions) == 1012, f"active question count is {len(questions)}, expected 1012")
    return questions


def _check_run(
    paths: ProjectPaths,
    active: ActiveSnapshots,
    run_id: str,
    questions: dict[int, str],
) -> dict[str, Any]:
    stage = paths.run_dir("answer", run_id)
    pipeline_path = stage / "manifest.json"
    submission_path = stage / "submission_manifest.json"
    records_path = stage / "records.jsonl"
    package_path = paths.artifact_root / "submissions" / f"submission_{run_id}.zip"
    pipeline = _read_json(pipeline_path)
    submission = _read_json(submission_path)

    source = pipeline.get("source") or {}
    snapshots = pipeline.get("snapshots") or {}
    metrics = pipeline.get("metrics") or {}
    outputs = pipeline.get("outputs") or {}
    records_output = outputs.get("records_jsonl") or {}
    validation_claim = submission.get("validation") or {}
    replay_claim = submission.get("replay") or {}
    package_claim = submission.get("package") or {}

    _require(pipeline.get("kind") == "text2pandas.answering_run", f"{run_id}: bad run kind")
    _require(pipeline.get("run_id") == run_id, f"{run_id}: pipeline run_id mismatch")
    _require(source.get("git_commit"), f"{run_id}: missing git commit")
    _require(source.get("git_dirty") is False, f"{run_id}: source is dirty")
    _require(
        all(item.get("status") == "PASS" for item in pipeline.get("preflight", [])),
        f"{run_id}: snapshot preflight is not all PASS",
    )
    _require(
        (snapshots.get("raw") or {}).get("snapshot_id") == active.raw_snapshot_id,
        f"{run_id}: raw snapshot mismatch",
    )
    _require(
        (snapshots.get("a6") or {}).get("build_id") == active.a6_build_id,
        f"{run_id}: A6 build mismatch",
    )
    retrieval = snapshots.get("retrieval") or {}
    _require(
        retrieval.get("index_id") == active.retrieval_index_id,
        f"{run_id}: retrieval index mismatch",
    )
    _require(
        retrieval.get("source_a6_build_id") == active.a6_build_id,
        f"{run_id}: retrieval/A6 lineage mismatch",
    )
    _require(metrics.get("questions") == 1012, f"{run_id}: pipeline did not cover 1012 questions")
    _require(records_output.get("records") == 1012, f"{run_id}: records claim is not 1012")
    _require(records_path.is_file(), f"{run_id}: records.jsonl is missing")
    _require(
        sha256_file(records_path) == records_output.get("sha256"),
        f"{run_id}: records SHA-256 mismatch",
    )

    _require(
        submission.get("kind") == "text2pandas.submission_run", f"{run_id}: bad submission kind"
    )
    _require(submission.get("run_id") == run_id, f"{run_id}: submission run_id mismatch")
    _require(submission.get("status") == "VALIDATED", f"{run_id}: submission not VALIDATED")
    _require(validation_claim.get("ok") is True, f"{run_id}: validation claim is false")
    _require(validation_claim.get("records") == 1012, f"{run_id}: validation count is not 1012")
    _require(validation_claim.get("errors") == [], f"{run_id}: manifest validation errors")
    _require(validation_claim.get("warnings") == [], f"{run_id}: manifest validation warnings")
    _require(replay_claim.get("error") == 0, f"{run_id}: manifest replay errors")
    _require(replay_claim.get("executed") == 1012, f"{run_id}: manifest replay incomplete")
    _require(replay_claim.get("matched") == 1012, f"{run_id}: manifest replay mismatch")
    _require(replay_claim.get("no_evidence") == 0, f"{run_id}: manifest has no-evidence rows")
    _require(package_path.is_file(), f"{run_id}: published ZIP is missing")
    package_sha = sha256_file(package_path)
    _require(package_sha == package_claim.get("sha256"), f"{run_id}: package SHA-256 mismatch")
    _require(
        package_path.stat().st_size == package_claim.get("bytes"),
        f"{run_id}: package byte size mismatch",
    )

    validation = validate_zip(
        package_path,
        questions,
        corpus_root=active.raw_path / "financial_statements",
        strict=True,
    )
    _require(validation.ok, f"{run_id}: independent validation errors: {validation.errors[:3]}")
    _require(validation.warnings == [], f"{run_id}: independent validation warnings")
    _require(validation.n_records == 1012, f"{run_id}: independent record count is not 1012")
    replay = replay_zip(package_path, paths.artifact_root / "execution" / "active-candidate")
    blockers = publication_blockers(validation, replay, expected_records=1012)
    _require(not blockers, f"{run_id}: independent publication blockers: {blockers[:3]}")

    return {
        "run_id": run_id,
        "git_commit": source["git_commit"],
        "records_sha256": records_output["sha256"],
        "zip_path": str(package_path),
        "zip_bytes": package_path.stat().st_size,
        "zip_sha256": package_sha,
        "validation": {
            "records": validation.n_records,
            "errors": validation.errors,
            "warnings": validation.warnings,
        },
        "replay": replay,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-a", required=True)
    parser.add_argument("--run-b", required=True)
    parser.add_argument("--report-out")
    args = parser.parse_args()
    _require(args.run_a != args.run_b, "run A and run B must be distinct immutable runs")

    paths = ProjectPaths.from_repo_root(ROOT)
    active = ActiveSnapshots.load(paths)
    questions = _questions(active)
    first = _check_run(paths, active, args.run_a, questions)
    second = _check_run(paths, active, args.run_b, questions)
    _require(first["git_commit"] == second["git_commit"], "run source commits differ")
    deterministic = first["zip_sha256"] == second["zip_sha256"] and filecmp.cmp(
        first["zip_path"], second["zip_path"], shallow=False
    )
    _require(deterministic, "canonical A/B ZIPs are not byte-identical")

    report = {
        "schema_version": "1.0",
        "kind": "text2pandas.active_candidate_gate",
        "status": "PASS",
        "active_snapshots": {
            "raw_snapshot_id": active.raw_snapshot_id,
            "a6_build_id": active.a6_build_id,
            "retrieval_index_id": active.retrieval_index_id,
        },
        "run_a": first,
        "run_b": second,
        "deterministic_full_zip_sha256": True,
    }
    output = (
        Path(args.report_out).expanduser().resolve()
        if args.report_out
        else paths.artifact_root
        / "reports"
        / "active-candidate"
        / f"{args.run_a}__{args.run_b}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"PASS active candidate gate: {first['zip_sha256']}")
    print(output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ActiveCandidateError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"FAIL active candidate gate: {error}", file=sys.stderr)
        raise SystemExit(1) from error
