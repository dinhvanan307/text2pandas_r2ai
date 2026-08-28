from __future__ import annotations

import sqlite3
from dataclasses import replace

from text2pandas.application.planning import OperandRequest
from text2pandas.domain.semantic import (
    Basis,
    Dimension,
    MetricBindingHint,
    PeriodSemantics,
    UnitSpec,
)
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.retrieval import SqliteOperandRetriever


def _database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE tables (
            table_uid TEXT PRIMARY KEY, document_uid TEXT, directory_doc_id TEXT, basis TEXT,
            section_text TEXT
        );
        CREATE TABLE documents (
            document_uid TEXT PRIMARY KEY, directory_doc_id TEXT, basis TEXT
        );
        CREATE TABLE observations (
            observation_uid TEXT PRIMARY KEY, table_uid TEXT, ticker TEXT,
            statement_type TEXT, row_path_text TEXT, metric_label_clean TEXT,
            col_path_text TEXT, period_end TEXT, period_role TEXT,
            value_decimal_text TEXT, value_source_raw TEXT, unit_kind TEXT,
            currency TEXT, scale_exponent INTEGER, is_restated INTEGER,
            grid_row_idx INTEGER, grid_col_idx INTEGER
        );
        CREATE TABLE observation_readiness (
            observation_uid TEXT PRIMARY KEY, execution_ready INTEGER
        );
        INSERT INTO documents VALUES ('d1', 'VCB-2024', 'consolidated');
        INSERT INTO tables VALUES
          ('t1', 'd1', 'VCB-2024', 'separate', 'Bảng cân đối kế toán');
        INSERT INTO observations VALUES
          ('good', 't1', 'VCB', 'balance_sheet', 'TỔNG CỘNG TÀI SẢN',
           'Tổng tài sản', 'Số cuối năm', '2024-12-31', 'closing',
           '1000', '1.000', 'money', 'VND', 6, 0, 10, 2),
          ('wrong-child', 't1', 'VCB', 'balance_sheet', 'Tài sản ngắn hạn',
           'Tài sản ngắn hạn', 'Số cuối năm', '2024-12-31', 'closing',
           '600', '600', 'money', 'VND', 6, 0, 11, 2);
        INSERT INTO observation_readiness VALUES ('good', 1), ('wrong-child', 1);
        """
    )
    return connection


def test_sqlite_retriever_queries_one_operand_and_rejects_descendants() -> None:
    request = OperandRequest(
        request_id="operand:test",
        metric_id="total_assets",
        entity="VCB",
        period="2024",
        basis=Basis.CONSOLIDATED,
        preferred_basis=Basis.CONSOLIDATED,
        statement_types=("balance_sheet",),
        expected_unit=UnitSpec(Dimension.MONEY),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
        qualifiers=(),
        consumers=("$.expression",),
    )

    batch = SqliteOperandRetriever(_database(), load_ontology()).retrieve(request)

    assert [candidate.observation_uid for candidate in batch.candidates] == ["good"]
    assert batch.candidates[0].score_reasons[:2] == ("metric:exact", "statement")
    assert batch.trace["scanned"] == 2


def test_source_binding_requires_build_label_hierarchy_scope_and_unit() -> None:
    connection = _database()
    connection.executescript(
        """
        INSERT INTO observations VALUES
          ('source-good', 't1', 'VCB', 'note', 'Chi phí khác › Chi phí phạt',
           'Chi phí phạt', 'Năm nay', '2024-12-31', 'current',
           '10', '10', 'money', 'VND', 6, 0, 30, 2),
          ('source-wrong-path', 't1', 'VCB', 'note', 'Chi phí khác › Chi phí phạt khác',
           'Chi phí phạt', 'Năm nay', '2024-12-31', 'current',
           '20', '20', 'money', 'VND', 6, 0, 31, 2);
        INSERT INTO observation_readiness VALUES
          ('source-good', 1), ('source-wrong-path', 1);
        """
    )
    binding = MetricBindingHint(
        source_metric_id="source:penalty",
        source_build_id="fixture-build",
        labels=("Chi phí phạt",),
        row_paths=("Chi phí khác › Chi phí phạt",),
        preferred_basis=Basis.CONSOLIDATED,
    )
    request = OperandRequest(
        request_id="operand:source",
        metric_id="source:penalty",
        entity="VCB",
        period="2024",
        basis=Basis.CONSOLIDATED,
        preferred_basis=Basis.CONSOLIDATED,
        statement_types=("note",),
        expected_unit=UnitSpec(Dimension.MONEY),
        period_semantics=PeriodSemantics.UNKNOWN,
        qualifiers=(),
        consumers=("$.expression",),
        source_binding=binding,
    )
    retriever = SqliteOperandRetriever(connection, load_ontology(), source_build_id="fixture-build")

    batch = retriever.retrieve(request)
    wrong_build = retriever.retrieve(
        replace(
            request,
            source_binding=replace(binding, source_build_id="other-build"),
        )
    )
    wrong_scope = retriever.retrieve(replace(request, entity="OTHER"))
    wrong_unit = retriever.retrieve(replace(request, expected_unit=UnitSpec(Dimension.SHARES)))

    assert [value.observation_uid for value in batch.candidates] == ["source-good"]
    assert wrong_build.trace["reason"] == "SOURCE_BINDING_HINT_REJECTED"
    assert wrong_scope.trace["reason"] == "SCOPE_EMPTY"
    assert wrong_unit.candidates == ()
    assert wrong_unit.trace["unit_rejected"] == 1


def test_sqlite_retriever_uses_question_qualifiers_and_primary_document_period() -> None:
    connection = _database()
    connection.executescript(
        """
        INSERT INTO documents VALUES ('d2', 'VCB-2025', 'consolidated');
        INSERT INTO tables VALUES
          ('t2', 'd2', 'VCB-2025', 'separate', 'Bảng cân đối kế toán');
        INSERT INTO observations VALUES
          ('qualified', 't1', 'VCB', 'balance_sheet', 'TỔNG CỘNG TÀI SẢN',
           'Tổng tài sản', 'Số cuối năm hợp nhất', '2024-12-31', 'closing',
           '1100', '1.100', 'money', 'VND', 6, 0, 12, 2),
          ('comparative', 't2', 'VCB', 'balance_sheet', 'TỔNG CỘNG TÀI SẢN',
           'Tổng tài sản', 'Năm trước hợp nhất', '2024-12-31', 'prior',
           '1100', '1.100', 'money', 'VND', 6, 0, 12, 2);
        INSERT INTO observation_readiness VALUES ('qualified', 1), ('comparative', 1);
        """
    )
    request = OperandRequest(
        request_id="operand:qualified",
        metric_id="total_assets",
        entity="VCB",
        period="2024",
        basis=Basis.CONSOLIDATED,
        preferred_basis=Basis.CONSOLIDATED,
        statement_types=("balance_sheet",),
        expected_unit=UnitSpec(Dimension.MONEY),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
        qualifiers=("hop", "nhat"),
        consumers=("$.expression",),
    )

    batch = SqliteOperandRetriever(connection, load_ontology()).retrieve(request)

    assert batch.candidates[0].observation_uid == "qualified"
    assert "qualifier" in batch.candidates[0].score_reasons
    assert "document_period" in batch.candidates[0].score_reasons
    assert batch.candidates[0].score > next(
        value.score for value in batch.candidates if value.observation_uid == "comparative"
    )


def test_exact_metric_leaf_outranks_prefixed_subcomponents() -> None:
    connection = _database()
    connection.executescript(
        """
        INSERT INTO observations VALUES
          ('profit-exact', 't1', 'VCB', 'income_statement', 'Lợi nhuận sau thuế',
           'Lợi nhuận sau thuế', 'Năm nay', '2024-12-31', 'current',
           '100', '100', 'money', 'VND', 6, 0, 20, 2),
          ('profit-prefix', 't1', 'VCB', 'income_statement',
           'Lợi nhuận sau thuế chưa thực hiện', 'Lợi nhuận sau thuế chưa thực hiện',
           'Năm nay', '2024-12-31', 'current',
           '40', '40', 'money', 'VND', 6, 0, 21, 2);
        INSERT INTO observation_readiness VALUES ('profit-exact', 1), ('profit-prefix', 1);
        """
    )
    request = OperandRequest(
        request_id="operand:profit",
        metric_id="profit_after_tax",
        entity="VCB",
        period="2024",
        basis=Basis.CONSOLIDATED,
        preferred_basis=Basis.CONSOLIDATED,
        statement_types=("income_statement",),
        expected_unit=UnitSpec(Dimension.MONEY),
        period_semantics=PeriodSemantics.FLOW,
        qualifiers=(),
        consumers=("$.expression",),
    )

    batch = SqliteOperandRetriever(connection, load_ontology()).retrieve(request)

    assert batch.candidates[0].observation_uid == "profit-exact"
    assert batch.candidates[0].score_reasons[0] == "metric:exact"
    assert batch.candidates[1].score_reasons[0] == "metric:prefix"


def test_exact_leaf_bonus_does_not_override_stronger_period_context() -> None:
    connection = _database()
    connection.executescript(
        """
        INSERT INTO documents VALUES ('d2', 'VCB-2025', 'consolidated');
        INSERT INTO tables VALUES
          ('t2', 'd2', 'VCB-2025', 'consolidated', 'Thuyết minh');
        INSERT INTO observations VALUES
          ('current-prefix', 't1', 'VCB', 'income_statement',
           'Lợi nhuận sau thuế đã thực hiện',
           'Lợi nhuận sau thuế đã thực hiện',
           'Năm nay', '2024-12-31', 'current',
           '100', '100', 'money', 'VND', 6, 0, 20, 2),
          ('prior-exact', 't2', 'VCB', 'income_statement', 'Lợi nhuận sau thuế',
           'Lợi nhuận sau thuế', 'Năm trước', '2024-12-31', 'prior',
           '40', '40', 'money', 'VND', 6, 0, 21, 2);
        INSERT INTO observation_readiness VALUES ('current-prefix', 1), ('prior-exact', 1);
        """
    )
    request = OperandRequest(
        request_id="operand:period-context",
        metric_id="profit_after_tax",
        entity="VCB",
        period="2024",
        basis=Basis.CONSOLIDATED,
        preferred_basis=Basis.CONSOLIDATED,
        statement_types=("income_statement",),
        expected_unit=UnitSpec(Dimension.MONEY),
        period_semantics=PeriodSemantics.FLOW,
        qualifiers=(),
        consumers=("$.expression",),
    )

    batch = SqliteOperandRetriever(connection, load_ontology()).retrieve(request)

    assert batch.candidates[0].observation_uid == "current-prefix"
    assert batch.candidates[1].observation_uid == "prior-exact"


def test_required_counterparty_phrase_is_a_hard_evidence_constraint() -> None:
    connection = _database()
    connection.executescript(
        """
        INSERT INTO observations VALUES
          ('wrong-party', 't1', 'VCB', 'balance_sheet', 'TỔNG CỘNG TÀI SẢN',
           'Tổng tài sản', 'Công ty TNHH Khác', '2024-12-31', 'closing',
           '1200', '1200', 'money', 'VND', 6, 0, 30, 2),
          ('right-party', 't1', 'VCB', 'balance_sheet', 'TỔNG CỘNG TÀI SẢN',
           'Tổng tài sản', 'Công ty TNHH Coats Phong Phú', '2024-12-31', 'closing',
           '1100', '1100', 'money', 'VND', 6, 0, 31, 2);
        INSERT INTO observation_readiness VALUES ('wrong-party', 1), ('right-party', 1);
        """
    )
    request = OperandRequest(
        request_id="operand:counterparty",
        metric_id="total_assets",
        entity="VCB",
        period="2024",
        basis=Basis.CONSOLIDATED,
        preferred_basis=Basis.CONSOLIDATED,
        statement_types=("balance_sheet",),
        expected_unit=UnitSpec(Dimension.MONEY),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
        qualifiers=("coats", "phong", "phu"),
        consumers=("$.expression",),
        required_context_phrases=("tnhh coats phong phu",),
    )

    batch = SqliteOperandRetriever(connection, load_ontology()).retrieve(request)

    assert [candidate.observation_uid for candidate in batch.candidates] == ["right-party"]


def test_fact_normalization_recovers_punctuation_and_formula_suffix() -> None:
    connection = _database()
    connection.executescript(
        """
        INSERT INTO observations VALUES
          ('punctuated', 't1', 'VCB', 'balance_sheet',
           'I. TÀI SẢN NGẮN HẠN(100 = 110 + 120)',
           'Tài sản ngắn hạn', 'Số cuối năm', '2024-12-31', 'closing',
           '600', '600', 'money', 'VND', 6, 0, 40, 2);
        INSERT INTO observation_readiness VALUES ('punctuated', 1);
        """
    )
    request = OperandRequest(
        request_id="operand:punctuation",
        metric_id="current_assets",
        entity="VCB",
        period="2024",
        basis=Basis.CONSOLIDATED,
        preferred_basis=Basis.CONSOLIDATED,
        statement_types=("balance_sheet",),
        expected_unit=UnitSpec(Dimension.MONEY),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
        qualifiers=(),
        consumers=("$.expression",),
    )

    batch = SqliteOperandRetriever(connection, load_ontology()).retrieve(request)

    candidate = next(value for value in batch.candidates if value.observation_uid == "punctuated")
    assert candidate.match_method == "row_leaf_exact"
    assert candidate.matched_metric_id == "current_assets"
    assert batch.trace["reason"] is None


def test_hierarchy_parent_only_matches_generic_total_leaf() -> None:
    connection = _database()
    connection.executescript(
        """
        INSERT INTO observations VALUES
          ('hierarchy-total', 't1', 'VCB', 'balance_sheet',
           'Tài sản ngắn hạn › Tổng cộng', 'Tổng cộng', 'Số cuối năm',
           '2024-12-31', 'closing', '600', '600', 'money', 'VND', 6, 0, 41, 2),
          ('hierarchy-child', 't1', 'VCB', 'balance_sheet',
           'Tài sản ngắn hạn › Tiền', 'Tiền', 'Số cuối năm',
           '2024-12-31', 'closing', '200', '200', 'money', 'VND', 6, 0, 42, 2);
        INSERT INTO observation_readiness VALUES ('hierarchy-total', 1), ('hierarchy-child', 1);
        """
    )
    request = OperandRequest(
        request_id="operand:hierarchy",
        metric_id="current_assets",
        entity="VCB",
        period="2024",
        basis=Basis.CONSOLIDATED,
        preferred_basis=Basis.CONSOLIDATED,
        statement_types=("balance_sheet",),
        expected_unit=UnitSpec(Dimension.MONEY),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
        qualifiers=(),
        consumers=("$.expression",),
    )

    batch = SqliteOperandRetriever(connection, load_ontology()).retrieve(request)

    by_uid = {value.observation_uid: value for value in batch.candidates}
    assert by_uid["hierarchy-total"].match_method == "row_hierarchy_parent"
    assert "hierarchy-child" not in by_uid


def test_candidate_exposes_source_identity_when_a6_columns_exist() -> None:
    connection = _database()
    connection.execute("ALTER TABLE observations ADD COLUMN row_uid TEXT")
    connection.execute("ALTER TABLE observations ADD COLUMN metric_code TEXT")
    connection.execute(
        "UPDATE observations SET row_uid='row-total-assets', metric_code='270' "
        "WHERE observation_uid='good'"
    )
    request = OperandRequest(
        request_id="operand:identity",
        metric_id="total_assets",
        entity="VCB",
        period="2024",
        basis=Basis.CONSOLIDATED,
        preferred_basis=Basis.CONSOLIDATED,
        statement_types=("balance_sheet",),
        expected_unit=UnitSpec(Dimension.MONEY),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
        qualifiers=(),
        consumers=("$.expression",),
    )

    candidate = SqliteOperandRetriever(connection, load_ontology()).retrieve(request).candidates[0]

    assert candidate.row_uid == "row-total-assets"
    assert candidate.source_metric_code == "270"
    assert candidate.matched_metric_id == "total_assets"
    assert candidate.to_dict()["source_metric_code"] == "270"


def test_hard_filter_and_soft_table_prior_are_independent() -> None:
    connection = _database()
    connection.executescript(
        """
        INSERT INTO documents VALUES ('d2', 'VCB-2024-B', 'consolidated');
        INSERT INTO tables VALUES ('t2', 'd2', 'VCB-2024-B', 'consolidated', 'Bảng cân đối kế toán');
        INSERT INTO observations VALUES
          ('good-2', 't2', 'VCB', 'balance_sheet', 'TỔNG CỘNG TÀI SẢN',
           'Tổng tài sản', 'Số cuối năm', '2024-12-31', 'closing',
           '1000', '1.000', 'money', 'VND', 6, 0, 10, 2);
        INSERT INTO observation_readiness VALUES ('good-2', 1);
        """
    )
    request = OperandRequest(
        request_id="operand:prior",
        metric_id="total_assets",
        entity="VCB",
        period="2024",
        basis=Basis.CONSOLIDATED,
        preferred_basis=Basis.CONSOLIDATED,
        statement_types=("balance_sheet",),
        expected_unit=UnitSpec(Dimension.MONEY),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
        qualifiers=(),
        consumers=("$.expression",),
    )

    prior_batch = SqliteOperandRetriever(
        connection,
        load_ontology(),
        table_rank_priors=("t2", "t1"),
    ).retrieve(request)
    hard_batch = SqliteOperandRetriever(
        connection,
        load_ontology(),
        hard_allowed_table_uids=("t1",),
        table_rank_priors=("t2", "t1"),
    ).retrieve(request)

    assert prior_batch.candidates[0].table_uid == "t2"
    assert {candidate.table_uid for candidate in prior_batch.candidates} == {"t1", "t2"}
    assert {candidate.table_uid for candidate in hard_batch.candidates} == {"t1"}
    assert prior_batch.trace["hard_table_filter"] is False
    assert hard_batch.trace["hard_table_filter"] is True


def test_empty_batch_reports_scope_and_metric_failures_separately() -> None:
    request = OperandRequest(
        request_id="operand:empty",
        metric_id="total_assets",
        entity="VCB",
        period="2024",
        basis=Basis.CONSOLIDATED,
        preferred_basis=Basis.CONSOLIDATED,
        statement_types=("balance_sheet",),
        expected_unit=UnitSpec(Dimension.MONEY),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
        qualifiers=(),
        consumers=("$.expression",),
    )
    metric_empty = SqliteOperandRetriever(_database(), load_ontology()).retrieve(
        replace(request, metric_id="inventory")
    )
    scope_empty = SqliteOperandRetriever(_database(), load_ontology()).retrieve(
        replace(request, entity="NOT_IN_SCOPE")
    )

    assert metric_empty.trace["reason"] == "METRIC_REJECT_ALL"
    assert scope_empty.trace["reason"] == "SCOPE_EMPTY"
