from __future__ import annotations

import sqlite3
from pathlib import Path

from text2pandas.application.parsing import OperationKind, QuestionAnnotations
from text2pandas.domain.semantic import Basis, Dimension, UnitSpec
from text2pandas.infrastructure.semantic import A6MetricMentionResolver


def _config(path: Path) -> Path:
    path.write_text(
        """\
schema_version: 1
resolver_id: fixture-source-resolver-v1
source:
  a6_build_id: fixture-build
matching:
  min_contiguous_tokens: 3
  min_token_overlap: 3
  min_source_coverage_milli: 600
  max_hypotheses: 20
  require_unique_winner_per_span: true
abbreviation_rules:
  - rule_id: tax-current
    phrase: chi phi thue thu nhap hien hanh
    replacement: chi phi thue tndn hien hanh
    evidence_qids: [89]
    negative_examples: [thu nhập khác]
""",
        encoding="utf-8",
    )
    return path


def _database(rows: tuple[tuple[str, ...], ...]) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE documents (document_uid TEXT PRIMARY KEY, basis TEXT);
        CREATE TABLE tables (table_uid TEXT PRIMARY KEY, document_uid TEXT);
        CREATE TABLE observations (
            observation_uid TEXT PRIMARY KEY,
            table_uid TEXT,
            ticker TEXT,
            period_end TEXT,
            metric_label_clean TEXT,
            row_path_text TEXT,
            metric_code TEXT,
            unit_kind TEXT,
            statement_type TEXT,
            value_decimal_text TEXT
        );
        CREATE TABLE observation_readiness (
            observation_uid TEXT PRIMARY KEY,
            execution_ready INTEGER
        );
        INSERT INTO documents VALUES ('d1', 'separate');
        INSERT INTO tables VALUES ('t1', 'd1');
        """
    )
    for row in rows:
        connection.execute(
            "INSERT INTO observations VALUES (?, 't1', ?, ?, ?, ?, ?, ?, ?, '1')",
            row,
        )
        connection.execute("INSERT INTO observation_readiness VALUES (?, 1)", (row[0],))
    return connection


def _annotations(*, entity: str = "AAA") -> QuestionAnnotations:
    return QuestionAnnotations(
        entities=(entity,),
        periods=("2024",),
        basis=Basis.SEPARATE,
        requested_unit=UnitSpec(Dimension.MONEY),
        operation=OperationKind.LOOKUP,
        mode="lookup",
    )


def test_resolver_is_scoped_deterministic_and_retains_hierarchy(tmp_path: Path) -> None:
    connection = _database(
        (
            (
                "o1",
                "AAA",
                "2024-12-31",
                "Chi phí phạt",
                "Chi phí khác › Chi phí phạt",
                "",
                "money",
                "note",
            ),
            (
                "o2",
                "BBB",
                "2024-12-31",
                "Chi phí phạt",
                "Sai hierarchy › Chi phí phạt",
                "",
                "money",
                "note",
            ),
        )
    )
    resolver = A6MetricMentionResolver(
        connection,
        source_build_id="fixture-build",
        config_path=_config(tmp_path / "resolver.yaml"),
    )

    first = resolver.resolve("Chi phí phạt của AAA năm 2024?", _annotations())
    second = resolver.resolve("Chi phí phạt của AAA năm 2024?", _annotations())

    assert first.status == "RESOLVED"
    assert first.selected == second.selected
    assert first.selected[0].aliases == ("Chi phí phạt",)
    assert first.selected[0].row_paths == ("Chi phí khác › Chi phí phạt",)
    assert resolver.metadata["lookup_count"] == 1
    assert resolver.metadata["cache_hits"] == 1


def test_resolver_applies_versioned_abbreviation_and_fails_closed_on_tie(
    tmp_path: Path,
) -> None:
    connection = _database(
        (
            (
                "tax",
                "AAA",
                "2024-12-31",
                "Chi phí thuế TNDN hiện hành",
                "Chi phí thuế TNDN hiện hành",
                "51",
                "money",
                "income_statement",
            ),
            (
                "a",
                "AAA",
                "2024-12-31",
                "Chi phí dịch vụ A",
                "Chi phí dịch vụ A",
                "",
                "money",
                "note",
            ),
            (
                "b",
                "AAA",
                "2024-12-31",
                "Chi phí dịch vụ B",
                "Chi phí dịch vụ B",
                "",
                "money",
                "note",
            ),
        )
    )
    resolver = A6MetricMentionResolver(
        connection,
        source_build_id="fixture-build",
        config_path=_config(tmp_path / "resolver.yaml"),
    )

    tax = resolver.resolve("Chi phí thuế thu nhập hiện hành của AAA năm 2024?", _annotations())
    tied = resolver.resolve("Chi phí dịch vụ của AAA năm 2024?", _annotations())

    assert tax.status == "RESOLVED"
    assert tax.selected[0].metric_codes == ("51",)
    assert tied.status == "ABSTAIN"
    assert tied.reason == "METRIC_HYPOTHESES_AMBIGUOUS"


def test_resolver_rejects_missing_scope_and_hierarchy_only_match(tmp_path: Path) -> None:
    connection = _database(
        (
            (
                "o1",
                "AAA",
                "2024-12-31",
                "Phí phạt",
                "Chi phí khác › Phí phạt",
                "",
                "money",
                "note",
            ),
        )
    )
    resolver = A6MetricMentionResolver(
        connection,
        source_build_id="fixture-build",
        config_path=_config(tmp_path / "resolver.yaml"),
    )

    hierarchy_only = resolver.resolve("Chi phí khác của AAA năm 2024?", _annotations())
    wrong_entity = resolver.resolve("Phí phạt của BBB năm 2024?", _annotations(entity="BBB"))

    assert hierarchy_only.status == "ABSTAIN"
    assert hierarchy_only.reason == "METRIC_SOURCE_SPECIFICITY_REQUIRED"
    assert wrong_entity.status == "ABSTAIN"
    assert wrong_entity.selected == ()
