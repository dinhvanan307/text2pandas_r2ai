from __future__ import annotations

import sqlite3

from text2pandas.application.planning import OperandRequest
from text2pandas.domain.semantic import Basis, Dimension, PeriodSemantics, UnitSpec
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.retrieval import SqliteOperandRetriever


def _database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE tables (
            table_uid TEXT PRIMARY KEY, directory_doc_id TEXT, basis TEXT,
            section_text TEXT
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
        INSERT INTO tables VALUES ('t1', 'VCB-2024', 'consolidated', 'Bảng cân đối kế toán');
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
    assert batch.candidates[0].score_reasons[:2] == ("metric:direct", "statement")
    assert batch.trace["scanned"] == 2

