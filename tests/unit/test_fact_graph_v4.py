from __future__ import annotations

import sqlite3
from decimal import Decimal

from text2pandas.application.planning import OperandRequest
from text2pandas.application.retrieval import ObservationCandidate
from text2pandas.domain.facts import FactReadiness, make_logical_table_uid
from text2pandas.domain.semantic import Basis, Dimension, PeriodSemantics, UnitSpec
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.retrieval import SqliteOperandRetriever, project_candidate


def test_continuation_fragments_share_logical_table_identity() -> None:
    first = make_logical_table_uid(
        document_id="VCB-2024",
        statement_type="balance_sheet",
        section_text="Bảng cân đối kế toán",
        physical_table_uid="table-1",
    )
    continuation = make_logical_table_uid(
        document_id="VCB-2024",
        statement_type="balance_sheet",
        section_text="BẢNG CÂN ĐỐI KẾ TOÁN (tiếp theo)",
        physical_table_uid="table-2",
    )
    generic_first = make_logical_table_uid(
        document_id="VCB-2024",
        statement_type="note",
        section_text="Thuyết minh",
        physical_table_uid="table-3",
    )
    generic_second = make_logical_table_uid(
        document_id="VCB-2024",
        statement_type="note",
        section_text="Thuyết minh",
        physical_table_uid="table-4",
    )

    assert first == continuation
    assert generic_first != generic_second


def test_candidate_projects_to_immutable_logical_fact() -> None:
    candidate = ObservationCandidate(
        observation_uid="obs-1",
        table_uid="table-1",
        document_id="VCB-2024",
        entity="VCB",
        basis=Basis.CONSOLIDATED,
        statement_type="balance_sheet",
        metric_id="total_assets",
        row_path="Tài sản › Tổng cộng",
        column_path="2024 › Cuối năm",
        period="2024-12-31",
        period_role="closing",
        value=Decimal(1000),
        value_raw="1.000",
        unit=UnitSpec(Dimension.MONEY, 6, "VND"),
        is_restated=False,
        score=30.0,
        score_reasons=("metric:exact",),
        grid_row=10,
        grid_column=2,
        row_uid="row-1",
        column_uid="column-1",
        logical_table_uid="logical-1",
    )

    fact = project_candidate(candidate)

    assert fact.logical_table_uid == "logical-1"
    assert fact.row_hierarchy == ("Tài sản", "Tổng cộng")
    assert fact.column_hierarchy == ("2024", "Cuối năm")
    assert fact.readiness == FactReadiness.READY


def test_recoverable_collision_requires_explicit_retriever_policy() -> None:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE tables (
            table_uid TEXT PRIMARY KEY, document_uid TEXT, directory_doc_id TEXT,
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
            grid_row_idx INTEGER, grid_col_idx INTEGER, row_uid TEXT,
            column_uid TEXT, collision_class TEXT, metric_code TEXT
        );
        CREATE TABLE observation_readiness (
            observation_uid TEXT PRIMARY KEY, execution_ready INTEGER,
            confidence REAL
        );
        INSERT INTO documents VALUES ('d1', 'VCB-2024', 'consolidated');
        INSERT INTO tables VALUES ('t1', 'd1', 'VCB-2024', 'Bảng cân đối kế toán');
        INSERT INTO observations VALUES (
            'recoverable', 't1', 'VCB', 'balance_sheet', 'Tổng cộng tài sản',
            'Tổng tài sản', 'Số cuối năm', '2024-12-31', 'closing', '1000',
            '1.000', 'money', 'VND', 6, 0, 10, 2, 'row-1', 'column-1',
            'missing_row_parent', 'total_assets'
        );
        INSERT INTO observation_readiness VALUES ('recoverable', 0, 0.72);
        """
    )
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

    locked = SqliteOperandRetriever(connection, load_ontology()).retrieve(request)
    experimental = SqliteOperandRetriever(
        connection,
        load_ontology(),
        include_recoverable_collisions=True,
    ).retrieve(request)

    assert locked.candidates == ()
    assert [candidate.observation_uid for candidate in experimental.candidates] == [
        "recoverable"
    ]
    assert experimental.candidates[0].readiness == "recoverable"
    assert experimental.candidates[0].source_confidence == 0.72
