from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
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
QUESTIONS = ROOT / "data" / "curated" / "evaluation" / "legacy" / "question_plans_1012.jsonl"


def test_real_a6_select_at_arg_uses_coherent_basis_and_replays() -> None:
    questions = {
        int(record["qid"]): str(record["question"])
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for record in (json.loads(line),)
    }
    # Independently checked from consolidated A6 observations:
    # q513 inventory peaks in 2017 -> raw materials 9,497,171,212 VND.
    # q521 cash equivalents peak in 2023 -> interest expense 500,688,616,629 VND.
    expected = {
        513: Decimal("9.497171212"),
        521: Decimal("500.688616629"),
    }
    ontology = load_ontology()
    parser = SemanticParser(ontology, LegacyVietnameseAnnotator(load_aliases("a6")))
    active = ActiveSnapshots.load(ProjectPaths.from_repo_root(ROOT))
    database = (active.a6_path / "silver.db").resolve()
    connection = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
    try:
        engine = SemanticV3Engine(
            parser,
            SqliteOperandRetriever(connection, ontology, top_k=8),
            PandasSandboxReplay(),
        )
        for qid, answer in expected.items():
            result = engine.answer(questions[qid], qid=qid)

            assert result.ok, (qid, result.stage_failed, result.reason)
            assert result.answer == answer
            assert result.query is not None and " if " in result.query
            assert result.trace[-1]["stage"] == "PANDAS_REPLAY"
            assert result.trace[-1]["status"] == "MATCH"
    finally:
        connection.close()


def test_real_a6_ambiguous_select_at_arg_fails_closed() -> None:
    question = next(
        str(record["question"])
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for record in (json.loads(line),)
        if int(record["qid"]) == 503
    )
    ontology = load_ontology()
    parser = SemanticParser(ontology, LegacyVietnameseAnnotator(load_aliases("a6")))
    active = ActiveSnapshots.load(ProjectPaths.from_repo_root(ROOT))
    database = (active.a6_path / "silver.db").resolve()
    connection = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
    try:
        result = SemanticV3Engine(
            parser,
            SqliteOperandRetriever(connection, ontology, top_k=8),
            PandasSandboxReplay(),
        ).answer(question, qid=503)
    finally:
        connection.close()

    assert not result.ok
    assert result.stage_failed == "BIND"
    assert result.reason == "AMBIGUOUS_BINDING"

