from text2pandas.application.parsing import ParseResult
from text2pandas.domain.semantic import (
    Basis,
    Dimension,
    MetricBindingHint,
    MetricRef,
    OutputSpec,
    QuestionAST,
    ResultKind,
    UnitSpec,
)
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.retrieval.grounded_query import GroundedQueryExpander


class _StaticParser:
    def __init__(self, ast: QuestionAST) -> None:
        self.ast = ast

    def parse(self, _question: str) -> ParseResult:
        return ParseResult("OK", self.ast)


class _AbstainingSourceParser:
    def __init__(self, binding: MetricBindingHint) -> None:
        self.binding = binding

    def parse(self, _question: str) -> ParseResult:
        return ParseResult(
            "ABSTAIN",
            reason="COMPOSITION_UNRESOLVED",
            source_bindings=(self.binding,),
        )


def test_expander_emits_canonical_working_capital_and_cashflow_concepts() -> None:
    expansion = GroundedQueryExpander(load_ontology()).analyze(
        "Năm 2024, có bao nhiêu doanh nghiệp có vốn lưu động ròng âm "
        "và lưu chuyển tiền thuần từ hoạt động kinh doanh dương?"
    )

    assert expansion.metric_ids == (
        "cash_flow_from_operations",
        "current_assets",
        "current_liabilities",
    )


def test_expander_removes_generic_alias_nested_in_net_revenue() -> None:
    expansion = GroundedQueryExpander(load_ontology()).analyze(
        "Biên lợi nhuận gộp và tỷ số dòng tiền hoạt động trên doanh thu thuần, "
        "sau đó trả về ROE."
    )

    assert "reported_da1c8d56459ce400" not in expansion.metric_ids
    assert {
        "gross_profit",
        "net_revenue",
        "cash_flow_from_operations",
        "profit_after_tax",
        "equity",
    } <= set(expansion.metric_ids)


def test_expander_prefers_full_reported_concept_over_nested_generic_aliases() -> None:
    expansion = GroundedQueryExpander(load_ontology()).analyze(
        "Chi phí chờ phân bổ của doanh nghiệp cuối năm 2024 là bao nhiêu?"
    )

    assert expansion.metric_ids == ("reported_allocated_expenses",)


def test_expander_does_not_treat_industry_revenue_as_answer_metric() -> None:
    expansion = GroundedQueryExpander(load_ontology()).analyze(
        "Trong các doanh nghiệp ngành quản lý và phát triển bất động sản, "
        "công ty có doanh thu thuần lớn nhất là công ty nào?"
    )

    assert "net_revenue" in expansion.metric_ids
    assert all(
        metric_id == "net_revenue" or not metric_id.startswith("reported_")
        for metric_id in expansion.metric_ids
    )


def test_expander_resolves_financial_acronyms_used_in_cohort_predicates() -> None:
    expansion = GroundedQueryExpander(load_ontology()).analyze(
        "Các doanh nghiệp có LNST dương và CFO dương trong cả hai năm, "
        "tăng trưởng doanh thu thuần bình quân là bao nhiêu?"
    )

    assert {
        "profit_after_tax",
        "cash_flow_from_operations",
        "net_revenue",
    } <= set(expansion.metric_ids)


def test_expander_suppresses_overlapping_reported_total_revenue_alias() -> None:
    expansion = GroundedQueryExpander(load_ontology()).analyze(
        "Tổng doanh thu thuần năm 2024 của nhóm là bao nhiêu?"
    )

    assert "net_revenue" in expansion.metric_ids
    assert "reported_b216ed84963bff39" not in expansion.metric_ids


def test_expander_suppresses_generic_debt_formula_overlapping_debt_to_equity() -> None:
    expansion = GroundedQueryExpander(load_ontology()).analyze(
        "Có bao nhiêu doanh nghiệp có hệ số thanh toán nhanh trên 1 lần và "
        "hệ số nợ phải trả trên vốn chủ sở hữu dưới 1,5 lần?"
    )

    assert {formula.formula_id for formula in expansion.formulas} == {
        "quick_ratio",
        "debt_to_equity",
    }
    assert "total_assets" not in expansion.metric_ids


def test_expander_keeps_product_cost_component_out_of_canonical_cogs() -> None:
    expansion = GroundedQueryExpander(load_ontology()).analyze(
        "Giá vốn hàng hóa của DIG trong năm 2023 là bao nhiêu tỷ đồng?"
    )

    assert expansion.metric_ids == ("reported_48d711d33b1fb3b5",)
    concept = expansion.concepts[0]
    assert concept.aliases == ("hang hoa",)
    assert concept.query_surfaces == ("gia von hang hoa",)


def test_expander_maps_bare_interest_row_to_expense_metric() -> None:
    expansion = GroundedQueryExpander(load_ontology()).analyze(
        "Lãi vay của công ty mẹ VSF năm 2022 là bao nhiêu triệu đồng?"
    )

    assert expansion.metric_ids == ("interest_expense",)
    assert "lai vay" in expansion.concepts[0].aliases
    assert expansion.concepts[0].period_semantics.value == "flow"


def test_expander_recovers_cfo_to_profit_formula_with_parenthetical_acronym() -> None:
    expansion = GroundedQueryExpander(load_ontology()).analyze(
        "Ở năm có tỷ lệ dòng tiền thuần từ hoạt động kinh doanh (CFO) trên "
        "lợi nhuận sau thuế thấp nhất, hệ số thanh toán nhanh là bao nhiêu?"
    )

    assert {
        "cash_flow_from_operations_to_profit_after_tax",
        "quick_ratio",
    } <= {formula.formula_id for formula in expansion.formulas}


def test_expander_assigns_filter_rank_output_for_thresholded_three_ratios() -> None:
    expansion = GroundedQueryExpander(load_ontology()).analyze(
        "Năm 2024, các doanh nghiệp có tỉ số thanh toán hiện hành lớn hơn "
        "1.5, tỉ trọng hàng tồn kho trên tổng tài sản của doanh nghiệp có tỉ "
        "số thanh toán nhanh thấp nhất là bao nhiêu phần trăm?"
    )

    assert {formula.formula_id: formula.role for formula in expansion.formulas} == {
        "current_ratio": "filter",
        "inventory_to_assets": "output",
        "quick_ratio": "rank",
    }


def test_expander_excludes_period_and_rank_tokens_from_metric_surface() -> None:
    expansion = GroundedQueryExpander(load_ontology()).analyze(
        "Trong các năm 2017, 2020, 2023 và 2024, tổng phải trả người bán "
        "ngắn hạn cuối năm trong năm có tổng chi phí bán hàng lớn nhất là bao nhiêu?"
    )
    concepts = {concept.metric_id: concept for concept in expansion.concepts}

    payables = concepts["reported_1029817c0c0df089"].query_surfaces
    selling = concepts["selling_expense"].query_surfaces

    assert payables == ("tong phai tra nguoi ban ngan han",)
    assert selling == ("tong chi phi ban hang",)


def test_total_metric_surface_does_not_capture_preceding_ticker() -> None:
    expansion = GroundedQueryExpander(load_ontology()).analyze(
        "Trong bốn mã HPG, HSG, MSR và NKG, tổng doanh thu thuần năm 2024 là bao nhiêu?"
    )
    concepts = {concept.metric_id: concept for concept in expansion.concepts}

    assert concepts["net_revenue"].query_surfaces == ("tong doanh thu thuan",)


def test_asset_turnover_formula_does_not_become_total_assets_qualifier() -> None:
    expansion = GroundedQueryExpander(load_ontology()).analyze(
        "Trong các mã ACV, HHV và VSC, vòng quay tổng tài sản của doanh nghiệp "
        "có tỷ trọng tài sản dài hạn trên tổng tài sản cao nhất?"
    )
    concepts = {concept.metric_id: concept for concept in expansion.concepts}

    assert concepts["total_assets"].query_surfaces == ("tong tai san",)


def test_explicit_average_equity_selects_average_balance_roe_contract() -> None:
    expansion = GroundedQueryExpander(load_ontology()).analyze(
        "ROE cao nhất là bao nhiêu phần trăm? ROE được tính bằng lợi nhuận sau "
        "thuế chia cho vốn chủ sở hữu bình quân đầu và cuối kỳ."
    )

    assert {formula.formula_id for formula in expansion.formulas} == {
        "roe_average_equity"
    }


def test_expander_uses_source_resolved_ast_as_retrieval_contract() -> None:
    metric_id = "a6_metric_dynamic"
    binding = MetricBindingHint(
        source_metric_id=metric_id,
        source_build_id="c6887fb633374fad",
        labels=("chi phi dac thu",),
        metric_codes=("200",),
        row_paths=("Thuyet minh › Chi phi dac thu",),
        question_surface="chi phi dac thu",
        preferred_basis=Basis.SEPARATE,
    )
    ast = QuestionAST(
        expression=MetricRef(
            metric_id,
            entities=("AAA",),
            periods=("2024",),
            basis=Basis.SEPARATE,
            statement_types=("note",),
            required_context_phrases=("doi tac dac thu",),
            source_binding=binding,
        ),
        output=OutputSpec(
            ResultKind.SCALAR,
            UnitSpec(Dimension.MONEY, 6),
        ),
        question="Chi phí đặc thù của công ty mẹ AAA năm 2024?",
    )

    expansion = GroundedQueryExpander(
        load_ontology(),
        _StaticParser(ast),  # type: ignore[arg-type]
    ).analyze(ast.question)

    assert expansion.semantic_ast == ast
    assert expansion.metric_ids == (metric_id,)
    assert expansion.concepts[0].aliases == ("chi phi dac thu",)
    assert expansion.concepts[0].metric_codes == ("200",)
    assert expansion.concepts[0].preferred_basis is Basis.SEPARATE
    assert expansion.concepts[0].required_context_phrases == (
        "doi tac dac thu",
    )


def test_expander_preserves_source_codes_when_parser_abstains_on_composition() -> None:
    binding = MetricBindingHint(
        source_metric_id="source_operating_profit",
        source_build_id="fixture-build",
        labels=("Lợi nhuận thuần từ hoạt động kinh doanh (30=20+21-22)",),
        metric_codes=("30",),
        row_paths=("Lợi nhuận thuần từ hoạt động kinh doanh (30=20+21-22)",),
        question_surface="loi nhuan thuan tu hoat dong kinh doanh",
    )
    question = (
        "Doanh nghiệp có tỷ lệ lưu chuyển tiền thuần từ hoạt động kinh doanh "
        "trên lợi nhuận thuần từ hoạt động kinh doanh thấp nhất?"
    )

    expansion = GroundedQueryExpander(
        load_ontology(),
        _AbstainingSourceParser(binding),  # type: ignore[arg-type]
    ).analyze(question)

    concept = next(
        value
        for value in expansion.concepts
        if value.metric_id == "reported_5dafdc9a37317139"
    )
    assert concept.metric_codes == ("30",)
    assert "loi nhuan thuan tu hoat dong kinh doanh (30=20+21-22)" in concept.aliases


def test_expander_projects_source_binding_without_ontology_concept() -> None:
    binding = MetricBindingHint(
        source_metric_id="source_board_compensation",
        source_build_id="c6887fb633374fad",
        labels=("thu lao cua thanh vien hoi dong quan tri",),
        metric_codes=("board_compensation",),
        row_paths=("Thu lao › Hoi dong quan tri",),
        question_surface="thu lao cua thanh vien hoi dong quan tri",
        preferred_basis=Basis.SEPARATE,
    )

    expansion = GroundedQueryExpander(
        load_ontology(),
        _AbstainingSourceParser(binding),  # type: ignore[arg-type]
    ).analyze("Thù lao của thành viên Hội đồng quản trị là bao nhiêu?")

    assert expansion.metric_ids == ("source_board_compensation",)
    assert expansion.concepts[0].aliases == (
        "thu lao cua thanh vien hoi dong quan tri",
    )
    assert expansion.concepts[0].metric_codes == ("board_compensation",)
    assert expansion.concepts[0].preferred_basis is Basis.SEPARATE


def test_expander_does_not_mix_unmatched_source_binding_into_canonical_domain() -> None:
    binding = MetricBindingHint(
        source_metric_id="source_company_name_collision",
        source_build_id="c6887fb633374fad",
        labels=("cong ty co phan",),
        row_paths=("Cong ty con › Cong ty co phan",),
        question_surface="cong ty co phan",
    )

    expansion = GroundedQueryExpander(
        load_ontology(),
        _AbstainingSourceParser(binding),  # type: ignore[arg-type]
    ).analyze("Công ty cổ phần có hàng tồn kho năm 2024 là bao nhiêu?")

    assert expansion.metric_ids == ("inventory",)


def test_source_contract_drops_adjacent_entity_words_from_question_surface() -> None:
    metric_id = "a6_other_income"
    binding = MetricBindingHint(
        source_metric_id=metric_id,
        source_build_id="c6887fb633374fad",
        labels=("lai thuan tu hoat dong khac",),
        row_paths=("B03/TCTD › Lai thuan tu hoat dong khac",),
        question_surface="sai gon thuong tin lai thuan tu hoat dong khac",
        preferred_basis=Basis.SEPARATE,
    )
    ast = QuestionAST(
        expression=MetricRef(
            metric_id,
            entities=("STB",),
            periods=("2021",),
            basis=Basis.SEPARATE,
            source_binding=binding,
        ),
        output=OutputSpec(ResultKind.SCALAR, UnitSpec(Dimension.MONEY, 6)),
        question="Lãi thuần từ hoạt động khác của STB?",
    )

    expansion = GroundedQueryExpander(
        load_ontology(),
        _StaticParser(ast),  # type: ignore[arg-type]
    ).analyze(ast.question)

    assert expansion.concepts[0].query_surfaces == (
        "lai thuan tu hoat dong khac",
    )


def test_semantic_ast_merge_preserves_accounting_source_qualifier_surface() -> None:
    ast = QuestionAST(
        expression=MetricRef(
            "tangible_fixed_assets",
            entities=("AAA", "BBB"),
            periods=("2023",),
            basis=Basis.CONSOLIDATED,
        ),
        output=OutputSpec(
            ResultKind.SCALAR,
            UnitSpec(Dimension.MONEY, 9),
        ),
        question=(
            "Hiệu giữa giá trị còn lại của tài sản cố định hữu hình cuối năm "
            "2023 của AAA và BBB là bao nhiêu?"
        ),
    )

    expansion = GroundedQueryExpander(
        load_ontology(),
        _StaticParser(ast),  # type: ignore[arg-type]
    ).analyze(ast.question)

    concept = next(
        value
        for value in expansion.concepts
        if value.metric_id == "tangible_fixed_assets"
    )
    assert concept.query_surfaces == (
        "gia tri con lai tai san co dinh huu hinh",
    )
