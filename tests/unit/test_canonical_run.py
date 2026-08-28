from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from text2pandas.application.usecases.canonical_run import (
    QuestionSelector,
    load_candidate_cells,
    run_canonical_pipeline,
)
from text2pandas.pipelines.answering import CandidateCell, Unit
from text2pandas.pipelines.answering.ir import OperandSlot
from text2pandas.pipelines.answering.units import MONEY


def test_canonical_runner_rejects_unknown_explicit_question_ids(tmp_path) -> None:
    questions = tmp_path / "questions.jsonl"
    questions.write_text('{"id": 1, "question": "Q"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r"unknown question IDs: \[2\]"):
        run_canonical_pipeline(
            tmp_path / "missing-a6.db",
            tmp_path / "missing-retrieval.db",
            questions,
            tmp_path / "run",
            question_ids=frozenset({2}),
        )


def _cell(row: str, *, section: str = "", context: str = "", rank: int = 0) -> CandidateCell:
    return CandidateCell(
        df_var="df1",
        csv_path="data/t.csv",
        row_index=0,
        row_path=row,
        col_label="31.12.2022 Triệu VND",
        value_raw="1.000",
        value=1000.0,
        parsed_raw=1000.0,
        storage_exponent=0,
        unit=Unit(MONEY, 6),
        period="2022-12-31",
        table_uid="t",
        entity="ACB",
        basis="separate",
        table_rank=rank,
        section_text=section,
        table_context=context,
    )


def test_category_axis_outweighs_generic_metric_match() -> None:
    question = "Số dư cho vay khách hàng ngành Thương mại của ACB cuối năm 2022"
    category = _cell(
        "9.6 Theo ngành nghề kinh doanh › Thương mại",
        section="9.6 Theo ngành nghề kinh doanh",
        context="Cho vay khách hàng | Thương mại | Sản xuất",
    )
    generic = _cell(
        "Dự phòng rủi ro cho vay khách hàng",
        section="Dự phòng rủi ro cho vay khách hàng",
        context="Cho vay khách hàng",
        rank=1,
    )
    selector = QuestionSelector(question, frozenset(), drop=("ACB",))

    selected = selector.pick(
        OperandSlot("value", period="2022", basis="separate", entity="ACB"),
        [generic, category],
    )

    assert selected is category


def test_selector_prefers_closing_balance_when_question_says_end_of_year() -> None:
    selector = QuestionSelector(
        "Số dư tiền gửi cuối năm 2022 là bao nhiêu?",
        frozenset(),
    )
    opening = replace(_cell("Tiền gửi"), period_role="opening")
    closing = replace(_cell("Tiền gửi"), period_role="closing")

    selected = selector.pick(OperandSlot("value", period="2022"), [opening, closing])

    assert selected is closing


def test_selector_treats_written_31_december_as_closing_cue() -> None:
    selector = QuestionSelector(
        "Giá trị đến ngày 31 tháng 12 năm 2024 là bao nhiêu?",
        frozenset({"metric"}),
    )
    prior = replace(_cell("Metric"), metric_code="metric", period_role="prior")
    current = replace(_cell("Metric"), metric_code="metric", period_role="current")

    selected = selector.pick(OperandSlot("value", period="2022"), [prior, current])

    assert selected is current


def test_selector_uses_consolidated_as_soft_basis_prior() -> None:
    selector = QuestionSelector(
        "Chi phí xây dựng cơ bản dở dang cuối năm 2022 là bao nhiêu?",
        frozenset(),
        preferred_basis="consolidated",
    )
    separate = _cell("Chi phí xây dựng cơ bản dở dang")
    consolidated = replace(separate, basis="consolidated")

    selected = selector.pick(
        OperandSlot("value", period="2022"),
        [separate, consolidated],
    )

    assert selected is consolidated


def test_selector_soft_basis_prior_keeps_standalone_only_fallback() -> None:
    selector = QuestionSelector(
        "Chi phí xây dựng cơ bản dở dang cuối năm 2022 là bao nhiêu?",
        frozenset(),
        preferred_basis="consolidated",
    )
    separate = _cell("Chi phí xây dựng cơ bản dở dang")

    selected = selector.pick(OperandSlot("value", period="2022"), [separate])

    assert selected is separate


def test_selector_prefers_semantically_valid_retrieval_output_table() -> None:
    preferred = replace(_cell("Vay ngân hàng ngắn hạn"), table_uid="retrieved")
    wider_pool = replace(
        _cell("Vay ngân hàng ngắn hạn"),
        table_uid="fallback",
        metric_code="320",
    )
    selector = QuestionSelector(
        "Vay ngân hàng ngắn hạn cuối năm 2022 là bao nhiêu?",
        frozenset({"320"}),
        preferred_table_uids=frozenset({"retrieved"}),
    )

    selected = selector.pick(
        OperandSlot("value", period="2022"),
        [wider_pool, preferred],
    )

    assert selected is preferred


def test_selector_uses_wider_pool_when_retrieval_output_fails_semantic_gate() -> None:
    preferred = replace(_cell("Tài sản khác"), table_uid="retrieved")
    fallback = replace(_cell("Vay ngân hàng ngắn hạn"), table_uid="fallback")
    selector = QuestionSelector(
        "Vay ngân hàng ngắn hạn cuối năm 2022 là bao nhiêu?",
        frozenset(),
        preferred_table_uids=frozenset({"retrieved"}),
    )

    selected = selector.pick(
        OperandSlot("value", period="2022"),
        [preferred, fallback],
    )

    assert selected is fallback


def test_selector_does_not_reward_keyword_stuffing_in_ancestors() -> None:
    selector = QuestionSelector(
        "Chi phí dịch vụ mua ngoài năm 2023 là bao nhiêu?",
        frozenset(),
    )
    direct = _cell("Chi phí bán hàng › Chi phí dịch vụ mua ngoài")
    stuffed = _cell(
        "Chi phí thuế thu nhập › Chi phí sản xuất kinh doanh › Chi phí dịch vụ mua ngoài"
    )

    selected = selector.pick(OperandSlot("value", period="2022"), [stuffed, direct])

    assert selected is direct


def test_selector_abstains_without_phrase_or_metric_evidence() -> None:
    selector = QuestionSelector("Chi phí dự phòng của STB năm 2020", frozenset())
    unrelated = _cell("Tài sản Có khác", section="Nghĩa vụ ngân sách")
    assert selector.pick(OperandSlot("value", period="2020"), [unrelated]) is None


def test_aggregate_question_prefers_aggregate_over_child_row() -> None:
    selector = QuestionSelector("Tổng phải thu ngắn hạn khác của ACB năm 2022", frozenset())
    child = _cell("Phải thu ngắn hạn khác › Bên thứ ba")
    total = _cell("Phải thu ngắn hạn khác › Tổng cộng")

    selected = selector.pick(OperandSlot("value", period="2022"), [child, total])

    assert selected is total


def test_total_value_wording_accepts_direct_reported_metric() -> None:
    selector = QuestionSelector(
        "Tổng giá trị hàng tồn kho của công ty mẹ ACB cuối năm 2022",
        frozenset(),
    )
    direct = _cell("Hàng tồn kho")

    selected = selector.pick(OperandSlot("value", period="2022"), [direct])

    assert selected is direct


def test_generic_gia_tri_does_not_select_value_added_tax() -> None:
    selector = QuestionSelector(
        "Tổng giá trị đầu tư vào công ty con cuối năm 2024",
        frozenset(),
    )
    investment = _cell("Đầu tư vào công ty con")
    value_added_tax = _cell("Thuế giá trị gia tăng")

    selected = selector.pick(
        OperandSlot("value", period="2022"),
        [value_added_tax, investment],
    )

    assert selected is investment


def test_cross_entity_sum_does_not_require_an_aggregate_row_per_entity() -> None:
    selector = QuestionSelector(
        "Tổng chi phí tài chính của ACB và VNM năm 2022",
        frozenset(),
        cross_entity_sum=True,
    )
    direct = _cell("Chi phí tài chính")

    selected = selector.pick(OperandSlot("entity_value", period="2022"), [direct])

    assert selected is direct


def test_a6_loader_excludes_scale_conflicts() -> None:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE tables (
          table_uid TEXT PRIMARY KEY, basis TEXT, section_text TEXT, context_clean TEXT
        );
        CREATE TABLE table_cards (table_uid TEXT PRIMARY KEY, table_search_text TEXT);
        CREATE TABLE observation_readiness (
          observation_uid TEXT PRIMARY KEY, execution_ready INTEGER
        );
        CREATE TABLE observations (
          observation_uid TEXT PRIMARY KEY, table_uid TEXT, ticker TEXT,
          row_path_text TEXT, metric_label_clean TEXT, col_path_text TEXT,
          value_source_raw TEXT, value_decimal_text TEXT, unit_kind TEXT,
          currency TEXT, scale_exponent INTEGER, period_end TEXT,
          period_role TEXT, metric_code TEXT, is_restated INTEGER,
          grid_row_idx INTEGER, grid_col_idx INTEGER
        );
        INSERT INTO tables VALUES ('t1', 'separate', 'Doanh thu', '');
        INSERT INTO table_cards VALUES ('t1', 'Doanh thu thuần');
        INSERT INTO observation_readiness VALUES ('ok', 1), ('bad', 1);
        INSERT INTO observations VALUES
          ('ok','t1','VNM','Doanh thu thuần',NULL,'2022 Triệu đồng',
           '1.000','1000','money','VND',6,'2022-12-31','current','10',0,1,1),
          ('bad','t1','VNM','Doanh thu khác',NULL,'2022 Triệu đồng',
           '2.000','2000','money','VND',0,'2022-12-31','current',NULL,0,2,1);
        """
    )

    cells, frames = load_candidate_cells(connection, ["t1"])

    assert [cell.row_path for cell in cells] == ["Doanh thu thuần"]
    assert list(frames) == ["data/t1.csv"]


def test_a6_loader_repairs_explicit_unit_glued_to_header_token() -> None:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE tables (
          table_uid TEXT PRIMARY KEY, basis TEXT, statement_type TEXT,
          section_text TEXT, context_clean TEXT
        );
        CREATE TABLE table_cards (table_uid TEXT PRIMARY KEY, table_search_text TEXT);
        CREATE TABLE observation_readiness (
          observation_uid TEXT PRIMARY KEY, execution_ready INTEGER
        );
        CREATE TABLE observations (
          observation_uid TEXT PRIMARY KEY, table_uid TEXT, ticker TEXT,
          row_path_text TEXT, metric_label_clean TEXT, col_path_text TEXT,
          value_source_raw TEXT, value_decimal_text TEXT, unit_kind TEXT,
          currency TEXT, scale_exponent INTEGER, scale_source TEXT, period_end TEXT,
          period_role TEXT, metric_code TEXT, is_restated INTEGER,
          grid_row_idx INTEGER, grid_col_idx INTEGER
        );
        INSERT INTO tables VALUES ('t1', 'consolidated', 'note', 'Phải thu', '');
        INSERT INTO table_cards VALUES ('t1', 'Phải thu');
        INSERT INTO observation_readiness VALUES ('glued', 1);
        INSERT INTO observations VALUES
          ('glued','t1','NAB','Phải thu chuyển tiền',NULL,'Số cuối nămTriệu đồng',
           '440.883','440883','money','VND',0,'column_path','2024-12-31',
           'current',NULL,0,1,1);
        """
    )

    cells, _frames = load_candidate_cells(connection, ["t1"])

    assert len(cells) == 1
    assert cells[0].unit.scale_exponent == 6


def test_a6_loader_inherits_unanimous_explicit_table_scale_for_date_only_column() -> None:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE tables (
          table_uid TEXT PRIMARY KEY, basis TEXT, statement_type TEXT,
          section_text TEXT, context_clean TEXT
        );
        CREATE TABLE table_cards (table_uid TEXT PRIMARY KEY, table_search_text TEXT);
        CREATE TABLE observation_readiness (
          observation_uid TEXT PRIMARY KEY, execution_ready INTEGER
        );
        CREATE TABLE observations (
          observation_uid TEXT PRIMARY KEY, table_uid TEXT, ticker TEXT,
          row_path_text TEXT, metric_label_clean TEXT, col_path_text TEXT,
          value_source_raw TEXT, value_decimal_text TEXT, unit_kind TEXT,
          currency TEXT, scale_exponent INTEGER, scale_source TEXT, period_end TEXT,
          period_role TEXT, metric_code TEXT, is_restated INTEGER,
          grid_row_idx INTEGER, grid_col_idx INTEGER
        );
        INSERT INTO tables VALUES ('t1', 'consolidated', 'note', 'Vay ngắn hạn', '');
        INSERT INTO table_cards VALUES ('t1', 'Vay ngắn hạn');
        INSERT INTO observation_readiness VALUES ('movement', 1), ('closing', 1);
        INSERT INTO observations VALUES
          ('movement','t1','MSR','Vay ngắn hạn',NULL,'Tăng › Nghìn VND',
           '2','2','money','VND',3,'column_path','2024-12-31','current',NULL,0,1,1),
          ('closing','t1','MSR','Vay ngắn hạn',NULL,'31/12/2024',
           '100','100','money','VND',0,'table_context','2024-12-31','closing',NULL,0,1,2);
        """
    )

    cells, _frames = load_candidate_cells(connection, ["t1"])
    closing = next(cell for cell in cells if cell.period_role == "closing")

    assert closing.unit.scale_exponent == 3


def test_a6_loader_prefers_row_local_per_share_unit_over_table_scale() -> None:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE tables (
          table_uid TEXT PRIMARY KEY, basis TEXT, statement_type TEXT,
          section_text TEXT, context_clean TEXT
        );
        CREATE TABLE table_cards (table_uid TEXT PRIMARY KEY, table_search_text TEXT);
        CREATE TABLE observation_readiness (
          observation_uid TEXT PRIMARY KEY, execution_ready INTEGER
        );
        CREATE TABLE observations (
          observation_uid TEXT PRIMARY KEY, table_uid TEXT, ticker TEXT,
          row_path_text TEXT, metric_label_clean TEXT, col_path_text TEXT,
          value_source_raw TEXT, value_decimal_text TEXT, unit_kind TEXT,
          currency TEXT, scale_exponent INTEGER, scale_source TEXT, period_end TEXT,
          period_role TEXT, metric_code TEXT, is_restated INTEGER,
          grid_row_idx INTEGER, grid_col_idx INTEGER
        );
        INSERT INTO tables VALUES (
          't1', 'consolidated', 'income_statement', 'Kết quả kinh doanh', 'Đơn vị: Triệu đồng'
        );
        INSERT INTO table_cards VALUES ('t1', 'Kết quả kinh doanh | Đơn vị: Triệu đồng');
        INSERT INTO observation_readiness VALUES ('eps', 1);
        INSERT INTO observations VALUES
          ('eps','t1','VIB','Lãi trên mỗi cổ phiếu (VND/cổ phiếu)',NULL,'Năm 2015',
           '1.161','1161','money','VND',6,'table_context','2015-12-31','current',NULL,0,1,1);
        """
    )

    cells, _frames = load_candidate_cells(connection, ["t1"])

    assert len(cells) == 1
    assert cells[0].value == 1161
    assert cells[0].unit.dimension == MONEY
    assert cells[0].unit.scale_exponent == 0


def test_a6_loader_reuses_original_row_index_for_duplicate_observation() -> None:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE tables (
          table_uid TEXT PRIMARY KEY, basis TEXT, section_text TEXT, context_clean TEXT
        );
        CREATE TABLE table_cards (table_uid TEXT PRIMARY KEY, table_search_text TEXT);
        CREATE TABLE observation_readiness (
          observation_uid TEXT PRIMARY KEY, execution_ready INTEGER
        );
        CREATE TABLE observations (
          observation_uid TEXT PRIMARY KEY, table_uid TEXT, ticker TEXT,
          row_path_text TEXT, metric_label_clean TEXT, col_path_text TEXT,
          value_source_raw TEXT, value_decimal_text TEXT, unit_kind TEXT,
          currency TEXT, scale_exponent INTEGER, period_end TEXT,
          period_role TEXT, metric_code TEXT, is_restated INTEGER,
          grid_row_idx INTEGER, grid_col_idx INTEGER
        );
        INSERT INTO tables VALUES ('t1', 'separate', '', '');
        INSERT INTO table_cards VALUES ('t1', 'Doanh thu');
        INSERT INTO observation_readiness VALUES ('first', 1), ('other', 1), ('duplicate', 1);
        INSERT INTO observations VALUES
          ('first','t1','VNM','Doanh thu',NULL,'2024 VND','1','1','money','VND',0,
           '2024-12-31','current',NULL,0,1,1),
          ('other','t1','VNM','Chi phí',NULL,'2024 VND','2','2','money','VND',0,
           '2024-12-31','current',NULL,0,2,1),
          ('duplicate','t1','VNM','Doanh thu',NULL,'2024 VND','1','1','money','VND',0,
           '2024-12-31','current',NULL,0,3,1);
        """
    )

    cells, _frames = load_candidate_cells(connection, ["t1"])
    revenue = [cell for cell in cells if cell.row_path == "Doanh thu"]

    assert [cell.row_index for cell in revenue] == [0, 0]
