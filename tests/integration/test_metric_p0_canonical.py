from __future__ import annotations

import json
from pathlib import Path

import pytest

from text2pandas.application.usecases.canonical_run import run_canonical_pipeline
from text2pandas.infrastructure.paths import ProjectPaths
from text2pandas.infrastructure.snapshots import ActiveSnapshots

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.integration


def _record(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_shadow_is_output_identical_and_guarded_is_explicit(tmp_path: Path) -> None:
    active = ActiveSnapshots.load(ProjectPaths.from_repo_root(ROOT))
    arguments = (
        active.a6_path / "silver.db",
        active.retrieval_path / "retrieval.db",
        active.raw_path / "questions/questions.jsonl",
    )
    off = run_canonical_pipeline(
        *arguments,
        tmp_path / "off",
        question_ids=frozenset({44}),
    )
    shadow = run_canonical_pipeline(
        *arguments,
        tmp_path / "shadow",
        question_ids=frozenset({44}),
        metric_selector_mode="shadow",
        p0_source_build_id=active.a6_build_id,
    )
    guarded = run_canonical_pipeline(
        *arguments,
        tmp_path / "guarded",
        question_ids=frozenset({44}),
        metric_selector_mode="guarded",
        p0_source_build_id=active.a6_build_id,
    )

    assert off.results == shadow.results
    off_record = _record(tmp_path / "off/records.jsonl")
    shadow_record = _record(tmp_path / "shadow/records.jsonl")
    metric_trace = shadow_record.pop("metric_p0")
    assert shadow_record == off_record
    assert metric_trace["resolution"]["selected_metric_id"] == "total_assets"
    assert metric_trace["differential"] == "LEGACY_ONLY"
    assert metric_trace["selected_for_output"] is False
    assert shadow.metric_differential_counts == {"LEGACY_ONLY": 1}

    assert guarded.n_answered == 0
    guarded_record = _record(tmp_path / "guarded/records.jsonl")
    assert guarded_record["metric_p0"]["selected_for_output"] is True
    assert guarded_record["reason"] == "BIND:METRIC_CANDIDATE_EMPTY"
