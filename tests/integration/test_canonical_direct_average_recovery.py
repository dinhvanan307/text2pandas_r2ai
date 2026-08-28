from __future__ import annotations

import json
from pathlib import Path

import pytest

from text2pandas.application.usecases.canonical_run import run_canonical_pipeline
from text2pandas.infrastructure.paths import ProjectPaths
from text2pandas.infrastructure.snapshots import ActiveSnapshots

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]


def test_q954_direct_interest_expense_average_is_default_off(tmp_path: Path) -> None:
    active = ActiveSnapshots.load(ProjectPaths.from_repo_root(ROOT))
    report = run_canonical_pipeline(
        active.a6_path / "silver.db",
        active.retrieval_path / "retrieval.db",
        active.raw_path / "questions/questions.jsonl",
        tmp_path / "q954-default",
        question_ids=frozenset({954}),
    )

    assert report.n_questions == 1
    assert report.n_answered == 0
    record = json.loads(
        (tmp_path / "q954-default/records.jsonl").read_text(encoding="utf-8")
    )
    assert record["status"] == "ABSTAIN"
    assert record["reason"] == "MULTI_ENTITY_OPERATION_NOT_SUPPORTED"


def test_q954_direct_interest_expense_average_is_grounded_and_replayable(
    tmp_path: Path,
) -> None:
    active = ActiveSnapshots.load(ProjectPaths.from_repo_root(ROOT))
    report = run_canonical_pipeline(
        active.a6_path / "silver.db",
        active.retrieval_path / "retrieval.db",
        active.raw_path / "questions/questions.jsonl",
        tmp_path / "q954",
        question_ids=frozenset({954}),
        enable_direct_interest_average=True,
    )

    assert report.n_questions == 1
    assert report.n_answered == 1
    record = json.loads((tmp_path / "q954/records.jsonl").read_text(encoding="utf-8"))
    assert record["status"] == "OK"
    assert record["answer"] == pytest.approx(294.6151000696667)
    assert record["relevant_tables"] == [
        "DPM_financial_statements_2019_consolidated|337",
        "VIF_financial_statements_2018_consolidated|300",
        "HSG_financial_statements_2018_consolidated|238",
    ]
    assert record["binding"]["selected_evidence_table_ids"] == [
        "feb5f4e440a5c1e0",
        "8b7c2752e32f8112",
        "eed2f40df8900789",
    ]
    assert record["pandas_query"].count("abs(") == 3
