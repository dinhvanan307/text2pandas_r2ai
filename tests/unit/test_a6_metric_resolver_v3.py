from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

from text2pandas.application.parsing import (
    OperationKind,
    QuestionAnnotations,
    SemanticParser,
)
from text2pandas.domain.semantic import (
    Aggregate,
    Arithmetic,
    Basis,
    Dimension,
    MetricRef,
    UnitSpec,
)
from text2pandas.infrastructure.ontology import load_ontology
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
  blocked_scope_tokens: [cua, cong, ty, co, phan, me, so, du, dau, cuoi, ky, nam, vnd, bang, cp]
abbreviation_rules:
  - rule_id: usd-currency-name
    phrase: usd
    replacement: do la my usd
    evidence_qids: [213]
    negative_examples: [doanh thu bán hàng]
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


class _StaticAnnotator:
    def __init__(self, annotations: QuestionAnnotations) -> None:
        self.annotations = annotations

    def annotate(self, question: str) -> QuestionAnnotations:
        del question
        return self.annotations


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


def test_resolver_rejects_corporate_scope_as_metric_mention(tmp_path: Path) -> None:
    connection = _database(
        (
            (
                "corporate",
                "AAA",
                "2024-12-31",
                "Đầu tư trực tiếp của Công ty Mẹ",
                "Thông tin doanh nghiệp › Đầu tư trực tiếp của Công ty Mẹ",
                "",
                "money",
                "note",
            ),
            (
                "penalty",
                "AAA",
                "2024-12-31",
                "Chi phí phạt",
                "Chi phí khác › Chi phí phạt",
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

    blocked = resolver.resolve(
        "Khoản phải thu của công ty mẹ AAA năm 2024?",
        _annotations(),
    )
    metric = resolver.resolve(
        "Chi phí phạt của công ty mẹ AAA năm 2024?",
        _annotations(),
    )

    assert blocked.status == "ABSTAIN"
    assert metric.status == "RESOLVED"
    assert metric.selected[0].aliases == ("Chi phí phạt",)


def test_growth_resolves_money_leaf_despite_percent_output(tmp_path: Path) -> None:
    connection = _database(
        (
            (
                "o1",
                "AAA",
                "2023-12-31",
                "Chi phí dịch vụ mua ngoài",
                "Chi phí quản lý › Chi phí dịch vụ mua ngoài",
                "",
                "money",
                "note",
            ),
            (
                "o2",
                "AAA",
                "2024-12-31",
                "Chi phí dịch vụ mua ngoài",
                "Chi phí quản lý › Chi phí dịch vụ mua ngoài",
                "",
                "money",
                "note",
            ),
        )
    )
    annotations = replace(
        _annotations(),
        periods=("2023", "2024"),
        requested_unit=UnitSpec(Dimension.PERCENT),
        operation=OperationKind.GROWTH,
    )
    resolver = A6MetricMentionResolver(
        connection,
        source_build_id="fixture-build",
        config_path=_config(tmp_path / "resolver.yaml"),
    )

    result = resolver.resolve(
        "Chi phí dịch vụ mua ngoài của AAA tăng bao nhiêu phần trăm từ 2023 đến 2024?",
        annotations,
    )

    assert result.status == "RESOLVED"
    assert result.selected[0].unit.dimension == Dimension.MONEY


def test_parser_promotes_unique_source_metric_for_derived_operation(
    tmp_path: Path,
) -> None:
    connection = _database(
        (
            (
                "o1",
                "AAA",
                "2023-12-31",
                "Chi phí dịch vụ mua ngoài",
                "Chi phí quản lý › Chi phí dịch vụ mua ngoài",
                "",
                "money",
                "note",
            ),
            (
                "o2",
                "AAA",
                "2024-12-31",
                "Chi phí dịch vụ mua ngoài",
                "Chi phí quản lý › Chi phí dịch vụ mua ngoài",
                "",
                "money",
                "note",
            ),
        )
    )
    annotations = replace(
        _annotations(),
        periods=("2023", "2024"),
        requested_unit=UnitSpec(Dimension.PERCENT),
        operation=OperationKind.GROWTH,
    )
    resolver = A6MetricMentionResolver(
        connection,
        source_build_id="fixture-build",
        config_path=_config(tmp_path / "resolver.yaml"),
    )
    parser = SemanticParser(load_ontology(), _StaticAnnotator(annotations), resolver)

    result = parser.parse(
        "Chi phí dịch vụ mua ngoài của AAA tăng bao nhiêu phần trăm từ 2023 đến 2024?"
    )

    assert result.ok
    assert isinstance(result.ast.expression, Arithmetic)
    assert isinstance(result.ast.expression.left, MetricRef)
    assert isinstance(result.ast.expression.right, MetricRef)
    assert result.ast.expression.left.metric_id.startswith("source_")
    assert result.ast.expression.left.source_binding is not None
    assert result.ast.expression.right.source_binding is not None


def test_parser_replaces_structural_currency_member_with_complete_source_metric(
    tmp_path: Path,
) -> None:
    connection = _database(
        (
            (
                "specific",
                "AAA",
                "2024-12-31",
                "Mua nợ bằng VND",
                "Phân tích mua nợ › Mua nợ bằng VND",
                "",
                "money",
                "note",
            ),
            (
                "qualifier",
                "AAA",
                "2024-12-31",
                "Bằng VND",
                "Phân tích dư nợ › Bằng VND",
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
    parser = SemanticParser(load_ontology(), _StaticAnnotator(_annotations()), resolver)

    result = parser.parse("Số dư mua nợ bằng VND của AAA năm 2024 là bao nhiêu?")

    assert result.ok
    assert isinstance(result.ast.expression, MetricRef)
    assert result.ast.expression.metric_id.startswith("source_")
    assert result.ast.expression.source_binding is not None
    assert result.ast.expression.source_binding.labels == ("Mua nợ bằng VND",)


def test_resolver_blocks_elided_entity_suffix_from_metric_candidates(tmp_path: Path) -> None:
    connection = _database(
        (
            (
                "loan",
                "STB",
                "2024-12-31",
                "Cho vay khách hàng",
                "Cho vay khách hàng",
                "",
                "money",
                "note",
            ),
            (
                "subsidiary",
                "STB",
                "2024-12-31",
                "Ngân hàng Sài Gòn Thương Tín Campuchia",
                "Đầu tư dài hạn › Ngân hàng Sài Gòn Thương Tín Campuchia",
                "",
                "money",
                "note",
            ),
        )
    )
    resolver = A6MetricMentionResolver(
        connection,
        source_build_id="fixture-build",
        entity_aliases={"STB": ("Ngân hàng TMCP Sài Gòn Thương Tín",)},
        config_path=_config(tmp_path / "resolver.yaml"),
    )

    result = resolver.resolve(
        "Tổng cho vay khách hàng của TMCP Sài Gòn Thương Tín (STB) năm 2024?",
        _annotations(entity="STB"),
    )

    assert result.status == "RESOLVED"
    assert len(result.selected) == 1
    assert result.selected[0].aliases == ("Cho vay khách hàng",)


def test_resolver_prefers_complete_reordered_qualifier_phrase(tmp_path: Path) -> None:
    connection = _database(
        (
            (
                "generic",
                "AAA",
                "2024-12-31",
                "Các khoản phải thu ngắn hạn",
                "Các khoản phải thu ngắn hạn",
                "",
                "money",
                "note",
            ),
            (
                "specific",
                "AAA",
                "2024-12-31",
                "Phải thu ngắn hạn khác",
                "Các khoản phải thu khác › Phải thu ngắn hạn khác",
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

    result = resolver.resolve(
        "Chênh lệch tổng giá trị các khoản phải thu khác ngắn hạn của AAA năm 2024?",
        _annotations(),
    )

    assert result.status == "RESOLVED"
    assert result.selected[0].aliases == ("Phải thu ngắn hạn khác",)
    assert "phai thu khac ngan han" in result.selected[0].mention.normalized_surface
    assert result.selected[0].match_method == "a6_scoped_metric_token_set"


def test_resolver_retains_adjacent_metric_qualifier_in_binding_surface(
    tmp_path: Path,
) -> None:
    connection = _database(
        (
            (
                "depreciation",
                "AAA",
                "2024-12-31",
                "Chi phí khấu hao",
                "Chi phí sản xuất › Chi phí khấu hao",
                "",
                "money",
                "note",
            ),
            (
                "movement",
                "AAA",
                "2024-12-31",
                "Khấu hao trong năm",
                "Tài sản cố định hữu hình › Khấu hao trong năm",
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

    result = resolver.resolve(
        "Tính tổng chi phí khấu hao nhà cửa trong năm của AAA?",
        replace(_annotations(), operation=OperationKind.SUM),
    )

    assert result.status == "RESOLVED"
    assert result.selected[0].aliases == ("Khấu hao trong năm",)
    assert result.selected[0].mention.normalized_surface.endswith("khau hao nha cua trong nam")


def test_resolver_expands_currency_abbreviation_for_source_label(tmp_path: Path) -> None:
    connection = _database(
        (
            (
                "usd",
                "AAA",
                "2024-12-31",
                "Ngoại tệ - Đô la Mỹ (USD)",
                "Ngoại tệ các loại › Đô la Mỹ (USD)",
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

    result = resolver.resolve("Số dư ngoại tệ USD của AAA năm 2024?", _annotations())

    assert result.status == "RESOLVED"
    assert result.selected[0].aliases == ("Ngoại tệ - Đô la Mỹ (USD)",)
    assert result.selected[0].mention.normalized_surface == "so du ngoai te usd"


def test_parser_uses_one_coherent_source_metric_for_composite_average_phrase(
    tmp_path: Path,
) -> None:
    connection = _database(
        (
            (
                "specific",
                "AAA",
                "2024-12-31",
                "Chi phí lãi vay phải trả",
                "Chi phí phải trả ngắn hạn › Chi phí lãi vay phải trả",
                "",
                "money",
                "note",
            ),
            (
                "debt",
                "AAA",
                "2024-12-31",
                "Vay ngắn hạn phải trả bên liên quan",
                "Vay và nợ thuê tài chính › Vay ngắn hạn phải trả bên liên quan",
                "",
                "money",
                "note",
            ),
        )
    )
    annotations = replace(
        _annotations(),
        entities=("AAA", "BBB"),
        operation=OperationKind.AVERAGE,
    )
    parser = SemanticParser(
        load_ontology(),
        _StaticAnnotator(annotations),
        A6MetricMentionResolver(
            connection,
            source_build_id="fixture-build",
            config_path=_config(tmp_path / "resolver.yaml"),
        ),
    )

    result = parser.parse(
        "Giá trị trung bình của chi phí lãi vay ngắn hạn phải trả của AAA năm 2024?"
    )

    assert result.ok
    assert isinstance(result.ast.expression, Aggregate)
    assert isinstance(result.ast.expression.expression, MetricRef)
    binding = result.ast.expression.expression.source_binding
    assert binding is not None
    assert binding.labels == ("Chi phí lãi vay phải trả",)


def test_resolver_merges_reordered_source_labels_into_one_logical_metric(
    tmp_path: Path,
) -> None:
    connection = _database(
        (
            (
                "first",
                "AAA",
                "2024-12-31",
                "Giá vốn cho thuê dài hạn đất và cơ sở hạ tầng",
                "Giá vốn › Giá vốn cho thuê dài hạn đất và cơ sở hạ tầng",
                "",
                "money",
                "note",
            ),
            (
                "second",
                "AAA",
                "2024-12-31",
                "Giá vốn đất và cơ sở hạ tầng cho thuê dài hạn",
                "Giá vốn › Giá vốn đất và cơ sở hạ tầng cho thuê dài hạn",
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

    result = resolver.resolve(
        "Giá vốn cho thuê dài hạn đất và cơ sở hạ tầng của AAA năm 2024?",
        _annotations(),
    )

    assert result.status == "RESOLVED"
    assert len(result.selected) == 1
    assert result.selected[0].aliases == (
        "Giá vốn cho thuê dài hạn đất và cơ sở hạ tầng",
        "Giá vốn đất và cơ sở hạ tầng cho thuê dài hạn",
    )


def test_resolver_merges_central_bank_legal_and_abbreviated_labels(
    tmp_path: Path,
) -> None:
    connection = _database(
        (
            (
                "legal",
                "AAA",
                "2024-12-31",
                "Tiền gửi tại Ngân hàng Nhà nước Việt Nam",
                "B02/TCTD › Tiền gửi tại Ngân hàng Nhà nước Việt Nam",
                "",
                "money",
                "balance_sheet",
            ),
            (
                "short",
                "AAA",
                "2024-12-31",
                "Tiền gửi tại Ngân hàng Nhà nước",
                "B02/TCTD-HN › Tiền gửi tại Ngân hàng Nhà nước",
                "",
                "money",
                "balance_sheet",
            ),
        )
    )
    resolver = A6MetricMentionResolver(
        connection,
        source_build_id="fixture-build",
        config_path=_config(tmp_path / "resolver.yaml"),
    )

    result = resolver.resolve(
        "Tiền gửi tại Ngân hàng Nhà nước Việt Nam của AAA năm 2024?",
        _annotations(),
    )

    assert result.status == "RESOLVED"
    assert result.selected[0].aliases == (
        "Tiền gửi tại Ngân hàng Nhà nước",
        "Tiền gửi tại Ngân hàng Nhà nước Việt Nam",
    )


def test_resolver_does_not_widen_base_metric_to_distinctive_qualified_metric(
    tmp_path: Path,
) -> None:
    connection = _database(
        (
            (
                "surplus",
                "AAA",
                "2024-12-31",
                "Thặng dư vốn cổ phần",
                "Vốn chủ sở hữu › Thặng dư vốn cổ phần",
                "411.2",
                "money",
                "balance_sheet",
            ),
        )
    )
    resolver = A6MetricMentionResolver(
        connection,
        source_build_id="fixture-build",
        config_path=_config(tmp_path / "resolver.yaml"),
    )

    result = resolver.resolve("Vốn cổ phần của AAA cuối năm 2024?", _annotations())

    assert result.status != "RESOLVED"


def test_resolver_does_not_bind_broad_shareholder_profit_to_nci(
    tmp_path: Path,
) -> None:
    connection = _database(
        (
            (
                "owners",
                "AAA",
                "2024-12-31",
                "Lợi nhuận thuần phân bổ cho các cổ đông",
                "Lợi nhuận thuần phân bổ cho các cổ đông",
                "",
                "money",
                "note",
            ),
            (
                "nci",
                "AAA",
                "2024-12-31",
                "Lợi nhuận thuần phân bổ cho cổ đông không kiểm soát",
                "Lợi nhuận thuần phân bổ cho cổ đông không kiểm soát",
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

    result = resolver.resolve(
        "Lợi nhuận thuần phân bổ cho cổ đông của AAA năm 2024?",
        _annotations(),
    )

    assert result.status == "RESOLVED"
    assert result.selected[0].aliases == (
        "Lợi nhuận thuần phân bổ cho các cổ đông",
    )
