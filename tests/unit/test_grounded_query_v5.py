from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.retrieval.grounded_query import GroundedQueryExpander


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
