from __future__ import annotations

import json
from pathlib import Path

import pytest

from text2pandas.application.usecases.canonical_run import CanonicalPipelineReport
from text2pandas.application.usecases.run_manifest import (
    pipeline_manifest,
    submission_manifest,
    write_manifest,
)
from text2pandas.application.usecases.submission import ValidationReport
from text2pandas.infrastructure.paths import ProjectPaths
from text2pandas.infrastructure.snapshots import (
    ActiveSnapshots,
    VerificationItem,
    VerificationReport,
)


def test_pipeline_manifest_closes_snapshot_and_output_lineage(tmp_path: Path) -> None:
    paths = ProjectPaths.from_repo_root(tmp_path, environ={})
    active = ActiveSnapshots(
        raw_dataset_id="btc",
        raw_snapshot_id="raw-1",
        raw_path=tmp_path / "data/raw/btc",
        a6_build_id="a6-1",
        a6_path=tmp_path / "data/processed/a6/a6-1",
        retrieval_source_a6_build_id="a6-1",
        retrieval_index_id="idx-1",
        retrieval_path=tmp_path / "data/indexes/retrieval/a6-1/idx-1",
    )
    records = tmp_path / "artifacts/runs/answer/run-1/records.jsonl"
    records.parent.mkdir(parents=True)
    records.write_text('{"qid": 1}\n', encoding="utf-8")
    report = CanonicalPipelineReport(
        n_questions=1,
        n_with_entity=1,
        n_with_year=1,
        n_retrieved=1,
        n_answered=0,
        n_abstained=1,
        seconds=0.1,
        abstain_reasons={"SAFE": 1},
        results=[],
    )
    preflight = VerificationReport((VerificationItem("lineage", True, "ok"),))

    manifest = pipeline_manifest(
        paths,
        active,
        "run-1",
        {"offset": 0, "limit": 1},
        report,
        preflight,
        {"git_commit": "abc", "git_dirty": False},
        records,
    )

    assert manifest["snapshots"]["retrieval"]["source_a6_build_id"] == "a6-1"
    assert manifest["metrics"]["abstain_reasons"] == {"SAFE": 1}
    assert manifest["outputs"]["records_jsonl"]["sha256"]
    assert str(tmp_path) not in json.dumps(manifest)


def test_manifest_is_immutable(tmp_path: Path) -> None:
    target = tmp_path / "manifest.json"
    write_manifest(target, {"status": "first"})

    with pytest.raises(FileExistsError):
        write_manifest(target, {"status": "rewritten"})
    assert json.loads(target.read_text(encoding="utf-8"))["status"] == "first"


def test_failed_submission_manifest_never_claims_published_output(tmp_path: Path) -> None:
    paths = ProjectPaths.from_repo_root(tmp_path, environ={})
    pipeline = tmp_path / "pipeline.json"
    package = tmp_path / "submission.zip"
    pipeline.write_text("{}", encoding="utf-8")
    package.write_bytes(b"zip bytes")

    manifest = submission_manifest(
        paths,
        "run-1",
        pipeline,
        package,
        None,
        ValidationReport(1, errors=["invalid"]),
        {"executed": 1, "matched": 0, "error": 0},
    )

    assert manifest["status"] == "FAILED_VALIDATION"
    assert manifest["package"]["published_path"] is None
