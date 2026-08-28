from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from text2pandas.application.parsing import SemanticParser
from text2pandas.application.planning import compile_execution_plan
from text2pandas.domain.semantic import Aggregate, Filter, MetricRef, SelectAtArg
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.paths import ProjectPaths
from text2pandas.infrastructure.retrieval import SqliteOperandRetriever
from text2pandas.infrastructure.semantic import (
    A6MetricMentionResolver,
    LegacyVietnameseAnnotator,
)
from text2pandas.infrastructure.snapshots import ActiveSnapshots
from text2pandas.pipelines.retrieval.alias_store import load_aliases

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]


def test_required_metric_unresolved_qids_preserve_resolution_and_roles() -> None:
    paths = ProjectPaths.from_repo_root(ROOT)
    active = ActiveSnapshots.load(paths)
    questions = {
        int(record["id"]): str(record["question"])
        for line in (paths.raw_btc / "questions/questions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
        for record in (json.loads(line),)
    }
    aliases = load_aliases("a6")
    ontology = load_ontology()
    connection = sqlite3.connect(
        f"file:{(active.a6_path / 'silver.db').resolve()}?mode=ro&immutable=1",
        uri=True,
    )
    try:
        resolver = A6MetricMentionResolver(
            connection,
            source_build_id=active.a6_build_id,
            entity_aliases=aliases,
        )
        parser = SemanticParser(ontology, LegacyVietnameseAnnotator(aliases), resolver)
        parsed = {
            qid: parser.parse(questions[qid], qid=qid)
            for qid in (5, 15, 89, 100, 426, 502, 508, 870)
        }

        for qid in (5, 89):
            assert parsed[qid].ok
            assert isinstance(parsed[qid].ast.expression, MetricRef)
            assert parsed[qid].ast.expression.source_binding is not None
            plan = compile_execution_plan(parsed[qid].ast, ontology)
            retriever = SqliteOperandRetriever(
                connection,
                ontology,
                source_build_id=active.a6_build_id,
            )
            assert retriever.retrieve(plan.requests[0]).candidates

        q89_binding = parsed[89].ast.expression.source_binding
        assert q89_binding is not None and q89_binding.metric_codes == ("51",)
        assert parsed[15].reason == "METRIC_SOURCE_SPECIFICITY_REQUIRED"
        assert parsed[100].reason == "METRIC_SOURCE_SPECIFICITY_REQUIRED"
        assert parsed[426].reason is not None
        assert parsed[426].reason.startswith("SELECT_AT_ARG_")

        q502 = parsed[502]
        assert q502.ok and isinstance(q502.ast.expression, SelectAtArg)
        assert isinstance(q502.ast.expression.rank.by, MetricRef)
        assert isinstance(q502.ast.expression.expression, MetricRef)
        assert q502.ast.expression.rank.by.metric_id != q502.ast.expression.expression.metric_id
        q502_plan = compile_execution_plan(q502.ast, ontology)
        consumers = {value for request in q502_plan.requests for value in request.consumers}
        assert any(".rank.by" in value for value in consumers)
        assert any(value.endswith(".expression") for value in consumers)

        q508 = parsed[508]
        assert q508.ok and isinstance(q508.ast.expression, SelectAtArg)
        assert isinstance(q508.ast.expression.rank.by, MetricRef)
        rank_hint = q508.ast.expression.rank.by.source_binding
        assert rank_hint is not None
        assert "Chi phí chờ phân bổ" in rank_hint.labels
        assert isinstance(q508.ast.expression.expression, MetricRef)
        assert q508.ast.expression.rank.by.metric_id != q508.ast.expression.expression.metric_id

        q870 = parsed[870]
        assert q870.ok and isinstance(q870.ast.expression, Aggregate)
        assert q870.ast.expression.function.value == "count"
        assert isinstance(q870.ast.expression.expression, Filter)
        q870_plan = compile_execution_plan(q870.ast, ontology)
        assert q870_plan.requests
        assert all(request.source_binding is not None for request in q870_plan.requests)
    finally:
        connection.close()
