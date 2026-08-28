from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from text2pandas.application.parsing import SemanticParser
from text2pandas.application.usecases.semantic_v3 import SemanticV3Engine
from text2pandas.infrastructure.execution import PandasSandboxReplay
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.paths import ProjectPaths
from text2pandas.infrastructure.retrieval import SqliteOperandRetriever
from text2pandas.infrastructure.semantic import LegacyVietnameseAnnotator
from text2pandas.infrastructure.snapshots import ActiveSnapshots
from text2pandas.pipelines.retrieval.alias_store import load_aliases

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "data/raw/btc/questions/questions.jsonl"


def test_recovery_qids_stop_at_the_reviewed_semantic_boundary() -> None:
    questions = {
        int(record["id"]): str(record["question"])
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for record in (json.loads(line),)
    }
    expected_reasons = {
        464: "SELECT_AT_ARG_SELECTED_EXPRESSION_UNRESOLVED",
        508: "METRIC_REJECT_ALL",
        586: "REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION",
        783: "BINDING_TIE",
        792: "REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION",
    }
    ontology = load_ontology()
    parser = SemanticParser(ontology, LegacyVietnameseAnnotator(load_aliases("a6")))
    active = ActiveSnapshots.load(ProjectPaths.from_repo_root(ROOT))
    database = (active.a6_path / "silver.db").resolve()
    connection = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
    try:
        engine = SemanticV3Engine(
            parser,
            SqliteOperandRetriever(connection, ontology, top_k=20),
            PandasSandboxReplay(),
        )
        results = {
            qid: engine.answer(questions[qid], qid=qid)
            for qid in expected_reasons
        }
    finally:
        connection.close()

    for qid, prefix in expected_reasons.items():
        result = results[qid]
        assert not result.ok
        assert result.reason is not None and result.reason.startswith(prefix), (
            qid,
            result.stage_failed,
            result.reason,
        )

    # Entity recovery is real even though later semantic gates still abstain.
    q508 = results[508].ast
    q783 = results[783].ast
    assert q508 is not None and q508["expression"]["expression"]["entities"] == [
        "ACB",
        "OCB",
        "STB",
    ]
    assert q783 is not None
    assert q783["expression"]["left"]["entities"] == ["MBB"]
    assert q783["expression"]["right"]["entities"] == ["EIB"]
