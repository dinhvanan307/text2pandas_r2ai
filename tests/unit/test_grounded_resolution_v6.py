from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from text2pandas.application.usecases.grounded_resolution import (
    LogicalFactResolver,
    LogicalMetricContract,
    has_hard_logical_fact_conflict,
    is_high_trust_logical_fact,
)
from text2pandas.application.usecases.grounded_synthesis import GroundedFact
from text2pandas.domain.semantic import Basis, Dimension, PeriodSemantics


def _fact(
    uid: str,
    row: str,
    column: str,
    value: str,
    *,
    metric: str,
    role: str,
    statement: str = "note",
    document_year: int = 2024,
    metric_code: str | None = None,
    score: float = 100.0,
) -> GroundedFact:
    return GroundedFact(
        observation_uid=uid,
        table_uid=f"table-{uid}",
        document_id=f"AAA_financial_statements_{document_year}_consolidated",
        entity="AAA",
        period="2024-12-31",
        basis=Basis.CONSOLIDATED,
        row_path=row,
        column_path=column,
        section_text=row.rsplit("›", 1)[0],
        value=Decimal(value),
        dimension=Dimension.MONEY,
        scale_exponent=6,
        metric_code=metric_code,
        statement_type=statement,
        retrieval_metric=metric,
        score=score,
        document_year=document_year,
        period_role=role,
        source_confidence=0.9,
    )


def test_closing_balance_rejects_in_year_movement_column() -> None:
    movement = _fact(
        "movement",
        "Nghĩa vụ với ngân sách › Thuế TNDN",
        "Số phát sinh trong năm › Số phải nộp",
        "249023",
        metric="tax_payable",
        role="current",
        score=220.0,
    )
    closing = _fact(
        "closing",
        "Nghĩa vụ với ngân sách › Thuế TNDN",
        "Số dư cuối năm",
        "86375",
        metric="tax_payable",
        role="closing",
        score=100.0,
    )
    contract = LogicalMetricContract(
        "tax_payable",
        aliases=("thue tndn",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Thuế TNDN phải nộp cuối năm 2024 là bao nhiêu?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((movement, closing), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["closing"]
    assert "period:closing_match" in resolved[0].score_reasons


def test_primary_total_beats_lexically_stronger_maturity_note() -> None:
    note = _fact(
        "note",
        "Bảng phân tích tài sản và công nợ theo kỳ hạn lãi suất › I",
        "Tổng › Nợ phải trả",
        "13379500",
        metric="total_liabilities",
        role="closing",
        score=260.0,
    )
    statement = _fact(
        "statement",
        "BẢNG CÂN ĐỐI KẾ TOÁN › Nợ phải trả",
        "Số cuối năm",
        "108950874",
        metric="total_liabilities",
        role="closing",
        statement="balance_sheet",
        metric_code="300",
        score=100.0,
    )
    contract = LogicalMetricContract(
        "total_liabilities",
        aliases=("no phai tra",),
        statement_types=("balance_sheet",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Tổng nợ phải trả đến ngày 31/12/2024 là bao nhiêu?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((note, statement), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["statement"]
    assert "metric:governed_code" in resolved[0].score_reasons


def test_query_qualifier_prevents_broad_reported_alias_collision() -> None:
    inventory = _fact(
        "inventory",
        "Hàng tồn kho › Hàng hóa",
        "Giá gốc",
        "1292",
        metric="reported_goods",
        role="closing",
        score=240.0,
    )
    cogs = _fact(
        "cogs",
        "Giá vốn hàng hóa",
        "Năm nay",
        "37015",
        metric="reported_goods",
        role="current",
        statement="income_statement",
        score=100.0,
    )
    contract = LogicalMetricContract(
        "reported_goods",
        aliases=("hang hoa",),
        query_surfaces=("gia von hang hoa",),
        period_semantics=PeriodSemantics.FLOW,
    )

    resolved = LogicalFactResolver(
        "Giá vốn hàng hóa năm 2024 là bao nhiêu?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((inventory, cogs), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["cogs"]
    assert "metric:query_qualifier_match" in resolved[0].score_reasons


def test_current_report_beats_restated_comparative_duplicate() -> None:
    current = _fact(
        "current",
        "Lợi nhuận sau thuế",
        "Năm 2024",
        "100",
        metric="profit_after_tax",
        role="current",
        statement="income_statement",
        document_year=2024,
    )
    comparative = _fact(
        "comparative",
        "Lợi nhuận sau thuế",
        "Năm trước (trình bày lại)",
        "95",
        metric="profit_after_tax",
        role="prior",
        statement="income_statement",
        document_year=2025,
        score=115.0,
    )
    comparative = replace(comparative, is_restated=True)
    contract = LogicalMetricContract(
        "profit_after_tax",
        aliases=("loi nhuan sau thue",),
        statement_types=("income_statement",),
        period_semantics=PeriodSemantics.FLOW,
    )

    resolved = LogicalFactResolver(
        "Lợi nhuận sau thuế năm 2024 là bao nhiêu?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((comparative, current), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["current"]


def test_required_counterparty_context_beats_broad_total_row() -> None:
    broad = _fact(
        "broad",
        "Rủi ro thanh khoản › Các khoản phải thu",
        "Tổng cộng",
        "346669",
        metric="receivable",
        role="closing",
        score=240.0,
    )
    counterparty = _fact(
        "counterparty",
        "Phải thu từ các bên liên quan › Bảo Việt Nhân thọ",
        "Số cuối năm",
        "222575",
        metric="receivable",
        role="closing",
        score=100.0,
    )
    contract = LogicalMetricContract(
        "receivable",
        aliases=("cac khoan phai thu",),
        required_context_phrases=("bao viet nhan tho",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Khoản phải thu từ Bảo Việt Nhân thọ cuối năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((broad, counterparty), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["counterparty"]
    assert "metric:required_context_match" in resolved[0].score_reasons


def test_source_metric_missing_distinctive_alias_tokens_is_hard_conflict() -> None:
    wrong = _fact(
        "wrong",
        "Chứng khoán đầu tư sẵn sàng để bán",
        "Số cuối năm",
        "26916591",
        metric="source_afs_provision",
        role="closing",
    )
    contract = LogicalMetricContract(
        "source_afs_provision",
        aliases=("du phong giam gia chung khoan dau tu san sang de ban",),
    )

    resolved = LogicalFactResolver(
        "Số dư dự phòng giảm giá chứng khoán đầu tư sẵn sàng để bán?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((wrong,), limit=10)

    assert has_hard_logical_fact_conflict(resolved[0])
    assert any(
        reason.startswith("metric:missing_source_alias_tokens")
        for reason in resolved[0].score_reasons
    )


def test_source_metric_keeps_components_only_when_no_safe_total_exists() -> None:
    common = _fact(
        "common",
        "Chứng khoán đầu tư sẵn sàng để bán › Dự phòng chung",
        "Số cuối năm",
        "-10",
        metric="source_afs_provision",
        role="closing",
    )
    specific = _fact(
        "specific",
        "Chứng khoán đầu tư sẵn sàng để bán › Dự phòng cụ thể",
        "Số cuối năm",
        "-20",
        metric="source_afs_provision",
        role="closing",
    )
    contract = LogicalMetricContract(
        "source_afs_provision",
        aliases=("du phong giam gia chung khoan dau tu san sang de ban",),
    )

    resolved = LogicalFactResolver(
        "Dự phòng giảm giá chứng khoán đầu tư sẵn sàng để bán?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((common, specific), limit=10)

    assert {fact.observation_uid for fact in resolved} == {"common", "specific"}
    assert all(not has_hard_logical_fact_conflict(fact) for fact in resolved)


def test_source_metric_prefers_safe_total_over_physical_components() -> None:
    total = _fact(
        "total",
        "Chứng khoán đầu tư sẵn sàng để bán › Dự phòng giảm giá chứng khoán đầu tư sẵn sàng để bán",
        "Số cuối năm",
        "-30",
        metric="source_afs_provision",
        role="closing",
    )
    component = _fact(
        "component",
        "Chứng khoán đầu tư sẵn sàng để bán › Dự phòng chung",
        "Số cuối năm",
        "-10",
        metric="source_afs_provision",
        role="closing",
        score=300.0,
    )
    contract = LogicalMetricContract(
        "source_afs_provision",
        aliases=("du phong giam gia chung khoan dau tu san sang de ban",),
    )

    resolved = LogicalFactResolver(
        "Dự phòng giảm giá chứng khoán đầu tư sẵn sàng để bán?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((component, total), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["total"]


def test_depreciation_movement_requires_asset_roll_forward_context() -> None:
    wrong = _fact(
        "wrong",
        "Phải thu về cho vay dài hạn › Khấu hao trong năm",
        "Nhà cửa",
        "932",
        metric="source_depreciation_movement",
        role="current",
        score=300.0,
    )
    asset = _fact(
        "asset",
        "Tài sản cố định hữu hình › Khấu hao trong năm",
        "Nhà cửa",
        "115",
        metric="source_depreciation_movement",
        role="current",
    )
    contract = LogicalMetricContract(
        "source_depreciation_movement",
        aliases=("khau hao trong nam",),
        query_surfaces=("khau hao nha cua trong nam",),
        period_semantics=PeriodSemantics.FLOW,
    )

    resolved = LogicalFactResolver(
        "Khấu hao nhà cửa trong năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((wrong, asset), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["asset"]


def test_central_bank_balance_rejects_unrelated_expense_note_duplicate() -> None:
    wrong = _fact(
        "wrong",
        "Chi phí hoạt động › Tiền gửi tại Ngân hàng Nhà nước Việt Nam",
        "Năm 2024",
        "80",
        metric="source_central_bank_deposit",
        role="current",
        score=300.0,
    )
    statement = _fact(
        "statement",
        "B02/TCTD-HN › Tiền gửi tại Ngân hàng Nhà nước",
        "Năm 2024",
        "100",
        metric="source_central_bank_deposit",
        role="current",
        statement="balance_sheet",
    )
    contract = LogicalMetricContract(
        "source_central_bank_deposit",
        aliases=(
            "tien gui tai ngan hang nha nuoc",
            "tien gui tai ngan hang nha nuoc viet nam",
        ),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Tiền gửi tại Ngân hàng Nhà nước Việt Nam năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((wrong, statement), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["statement"]


def test_explicit_opening_rejects_next_year_physical_boundary() -> None:
    wrong = _fact(
        "wrong",
        "Thuế và các khoản phải nộp › Thuế TNDN",
        "1/1/2022 › Số phải nộp",
        "100",
        metric="source_tax_payable",
        role="opening",
        document_year=2022,
        score=300.0,
    )
    correct = _fact(
        "correct",
        "Thuế và các khoản phải nộp › Thuế TNDN",
        "1/1/2021 › Số phải nộp",
        "80",
        metric="source_tax_payable",
        role="opening",
        document_year=2021,
    )
    contract = LogicalMetricContract(
        "source_tax_payable",
        aliases=("thue tndn",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Thuế TNDN phải nộp đầu năm 2021?",
        requested_periods=("2021",),
        contracts=(contract,),
    ).resolve((wrong, correct), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["correct"]


def test_explicit_closing_distinguishes_first_january_from_thirty_first_december() -> None:
    opening = _fact(
        "opening-boundary",
        "Vay và nợ thuê tài chính",
        "1/1/2023Giá trị ghi sổ và số có khả năng trả nợ",
        "100",
        metric="short_term_borrowings",
        role="current",
        score=300.0,
    )
    closing = _fact(
        "closing-boundary",
        "Vay và nợ thuê tài chính",
        "31/12/2022",
        "80",
        metric="short_term_borrowings",
        role="current",
    )
    contract = LogicalMetricContract(
        "short_term_borrowings",
        aliases=("vay va no thue tai chinh",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Vay và nợ thuê tài chính cuối năm 2022?",
        requested_periods=("2022",),
        contracts=(contract,),
    ).resolve((opening, closing), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["closing-boundary"]
    assert not has_hard_logical_fact_conflict(resolved[0])


def test_thirty_first_december_query_does_not_activate_opening_contract() -> None:
    closing = _fact(
        "closing-boundary",
        "Vay và nợ thuê tài chính",
        "31/12/2022",
        "80",
        metric="short_term_borrowings",
        role="closing",
    )
    contract = LogicalMetricContract(
        "short_term_borrowings",
        aliases=("vay va no thue tai chinh",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Vay và nợ thuê tài chính tại ngày 31/12/2022?",
        requested_periods=("2022",),
        contracts=(contract,),
    ).resolve((closing,), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["closing-boundary"]
    assert "period:closing_match" in resolved[0].score_reasons
    assert not any("opening" in reason for reason in resolved[0].score_reasons)


def test_governed_short_term_borrowings_total_beats_loan_component() -> None:
    component = _fact(
        "loan-component",
        "Vay và trái phiếu phát hành ngắn hạn › Vay ngắn hạn",
        "31/12/2022",
        "58",
        metric="short_term_borrowings",
        role="closing",
        score=220.0,
    )
    total = _fact(
        "borrowings-total",
        "Vay và trái phiếu phát hành ngắn hạn",
        "31/12/2022 › NGUỒN VỐN",
        "131",
        metric="short_term_borrowings",
        role="closing",
        metric_code="320",
        statement="balance_sheet",
        score=100.0,
    )
    contract = LogicalMetricContract(
        "short_term_borrowings",
        aliases=("vay va trai phieu phat hanh ngan han", "vay ngan han"),
        statement_types=("balance_sheet", "note"),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
        query_surfaces=("no vay ngan han",),
    )

    resolved = LogicalFactResolver(
        "Nợ vay ngắn hạn cuối năm 2022?",
        requested_periods=("2022",),
        contracts=(contract,),
    ).resolve((component, total), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["borrowings-total"]
    assert "metric:governed_code" in resolved[0].score_reasons


def test_closing_cue_on_selector_does_not_force_flow_output_to_repeat_it() -> None:
    closing_balance = _fact(
        "deferred-cost",
        "Tài sản Có khác › Chi phí chờ phân bổ",
        "Số dư cuối năm",
        "100",
        metric="source_deferred_cost",
        role="current",
    )
    flow_output = _fact(
        "other-income",
        "B03/TCTD › Lãi thuần từ hoạt động khác",
        "Năm nay",
        "20",
        metric="source_other_income",
        role="current",
    )
    contracts = (
        LogicalMetricContract(
            "source_deferred_cost",
            aliases=("chi phi cho phan bo",),
            period_semantics=PeriodSemantics.UNKNOWN,
        ),
        LogicalMetricContract(
            "source_other_income",
            aliases=("lai thuan tu hoat dong khac",),
            period_semantics=PeriodSemantics.FLOW,
        ),
    )

    resolved = LogicalFactResolver(
        "Lãi thuần từ hoạt động khác của ngân hàng có chi phí chờ phân bổ "
        "cuối năm cao nhất?",
        requested_periods=("2024",),
        contracts=contracts,
    ).resolve((closing_balance, flow_output), limit=10)

    assert {fact.observation_uid for fact in resolved} == {
        "deferred-cost",
        "other-income",
    }
    assert all(not has_hard_logical_fact_conflict(fact) for fact in resolved)


def test_explicit_closing_requires_physical_boundary_for_source_fact() -> None:
    wrong = _fact(
        "wrong",
        "Tiền gửi của khách hàng",
        "Tiền tệ khác",
        "145413",
        metric="source_customer_deposits",
        role="closing",
        score=300.0,
    )
    correct = _fact(
        "correct",
        "B02/TCTD-HN › Tiền gửi của khách hàng",
        "31/12/2024",
        "259211308",
        metric="source_customer_deposits",
        role="closing",
    )
    contract = LogicalMetricContract(
        "source_customer_deposits",
        aliases=("tien gui cua khach hang",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Tiền gửi của khách hàng cuối năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((wrong, correct), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["correct"]


def test_bare_expense_by_nature_prefers_total_disclosure() -> None:
    functional = _fact(
        "functional",
        "Chi phí quản lý doanh nghiệp › Chi phí dịch vụ mua ngoài",
        "Năm 2024",
        "15",
        metric="source_external_service_expense",
        role="current",
        score=300.0,
    )
    total = _fact(
        "total",
        "Chi phí sản xuất kinh doanh theo yếu tố › Chi phí dịch vụ mua ngoài",
        "Năm 2024",
        "63",
        metric="source_external_service_expense",
        role="current",
    )
    contract = LogicalMetricContract(
        "source_external_service_expense",
        aliases=("chi phi dich vu mua ngoai",),
        period_semantics=PeriodSemantics.FLOW,
    )

    resolved = LogicalFactResolver(
        "Chi phí dịch vụ mua ngoài năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((functional, total), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["total"]


def test_bare_interest_flow_rejects_accrued_payable_balance() -> None:
    payable = _fact(
        "payable",
        "Chi phí phải trả › Lãi vay",
        "31/12/2024",
        "10",
        metric="source_interest",
        role="closing",
        score=300.0,
    )
    expense = _fact(
        "expense",
        "Chi phí hoạt động tài chính › Lãi vay",
        "Năm 2024",
        "20",
        metric="source_interest",
        role="current",
    )
    contract = LogicalMetricContract("source_interest", aliases=("lai vay",))

    resolved = LogicalFactResolver(
        "Lãi vay năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((payable, expense), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["expense"]


def test_broad_debt_security_balance_rejects_one_portfolio_component() -> None:
    component = _fact(
        "component",
        "Chứng khoán đầu tư giữ đến ngày đáo hạn › Chứng khoán nợ",
        "31/12/2024",
        "10",
        metric="source_debt_securities",
        role="closing",
        score=300.0,
    )
    total = _fact(
        "total",
        "Chứng khoán nợ",
        "31/12/2024",
        "100",
        metric="source_debt_securities",
        role="closing",
    )
    contract = LogicalMetricContract(
        "source_debt_securities",
        aliases=("chung khoan no",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Số dư chứng khoán nợ cuối năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((component, total), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["total"]


def test_ratio_grammar_is_not_treated_as_a_source_metric_qualifier() -> None:
    fact = _fact(
        "gross-profit",
        "B02-DN › Lợi nhuận gộp về bán hàng và cung cấp dịch vụ",
        "Năm 2024",
        "100",
        metric="gross_profit",
        role="current",
        metric_code="20",
        statement="income_statement",
    )
    contract = LogicalMetricContract(
        "gross_profit",
        aliases=("loi nhuan gop",),
        query_surfaces=("bien loi nhuan gop va bien loi nhuan sau thue",),
        period_semantics=PeriodSemantics.FLOW,
    )

    resolved = LogicalFactResolver(
        "Biên lợi nhuận gộp và biên lợi nhuận sau thuế năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((fact,), limit=10)

    assert not has_hard_logical_fact_conflict(resolved[0])
    assert not any(
        reason.startswith("metric:missing_query_qualifier")
        for reason in resolved[0].score_reasons
    )


def test_filter_conjunction_is_not_a_physical_metric_qualifier() -> None:
    fact = _fact(
        "revenue",
        "B02-DN › Doanh thu thuần về bán hàng và cung cấp dịch vụ",
        "Năm 2024",
        "100",
        metric="net_revenue",
        role="current",
        metric_code="10",
        statement="income_statement",
    )
    contract = LogicalMetricContract(
        "net_revenue",
        aliases=("doanh thu thuan",),
        query_surfaces=("nhung doanh thu thuan",),
        period_semantics=PeriodSemantics.FLOW,
    )

    resolved = LogicalFactResolver(
        "Các công ty có CFO dương nhưng doanh thu thuần giảm?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((fact,), limit=10)

    assert not has_hard_logical_fact_conflict(resolved[0])


def test_semantic_operator_prefix_is_not_a_physical_metric_qualifier() -> None:
    revenue = _fact(
        "revenue-cagr",
        "B02-DN › Doanh thu thuần về bán hàng và cung cấp dịch vụ",
        "Năm 2024",
        "100",
        metric="net_revenue",
        role="current",
        metric_code="10",
        statement="income_statement",
    )
    cash_flow = _fact(
        "continuous-cfo",
        "B03-DN › Lưu chuyển tiền thuần từ hoạt động kinh doanh",
        "Năm 2024",
        "20",
        metric="cash_flow_from_operations",
        role="current",
        metric_code="20",
        statement="cash_flow",
    )
    contracts = (
        LogicalMetricContract(
            "net_revenue",
            aliases=("doanh thu thuan",),
            query_surfaces=("cagr doanh thu thuan",),
            period_semantics=PeriodSemantics.FLOW,
        ),
        LogicalMetricContract(
            "cash_flow_from_operations",
            aliases=("luu chuyen tien thuan tu hoat dong kinh doanh",),
            query_surfaces=("duy luu chuyen tien thuan tu hoat dong kinh doanh",),
            period_semantics=PeriodSemantics.FLOW,
        ),
    )

    resolved = LogicalFactResolver(
        "Duy trì CFO dương và có CAGR doanh thu thuần cao nhất?",
        requested_periods=("2024",),
        contracts=contracts,
    ).resolve((revenue, cash_flow), limit=10)

    assert {fact.observation_uid for fact in resolved} == {
        "revenue-cagr",
        "continuous-cfo",
    }
    assert all(not has_hard_logical_fact_conflict(fact) for fact in resolved)


def test_metric_code_221_implies_fixed_asset_carrying_amount() -> None:
    fact = _fact(
        "fixed-asset-balance",
        "B01-DN › Tài sản cố định hữu hình",
        "31/12/2024",
        "100",
        metric="tangible_fixed_assets",
        role="current",
        metric_code="221",
        statement="balance_sheet",
    )
    contract = LogicalMetricContract(
        "tangible_fixed_assets",
        aliases=("tai san co dinh huu hinh",),
        query_surfaces=("gia tri con lai cua tai san co dinh huu hinh",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Giá trị còn lại của tài sản cố định hữu hình cuối năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((fact,), limit=10)

    assert "metric:implied_fixed_asset_carrying_amount" in resolved[0].score_reasons


def test_source_contract_code_makes_exact_physical_row_high_trust() -> None:
    fact = _fact(
        "non-current-assets",
        "TÀI SẢN DÀI HẠN",
        "31/12/2024",
        "100",
        metric="source_non_current_assets",
        role="closing",
        metric_code="200",
        statement="balance_sheet",
    )
    contract = LogicalMetricContract(
        "source_non_current_assets",
        aliases=("tai san dai han",),
        statement_types=("balance_sheet",),
        metric_codes=("200",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Tài sản dài hạn cuối năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((fact,), limit=10)

    assert "metric:governed_code" in resolved[0].score_reasons
    assert is_high_trust_logical_fact(resolved[0])


def test_core_metric_code_embedded_in_statement_formula_is_governed() -> None:
    fact = _fact(
        "current-assets",
        "A - (100=110+120+130+140+150)",
        "31/12/2024 › TÀI SẢN NGẮN HẠN",
        "100",
        metric="current_assets",
        role="closing",
        statement="balance_sheet",
    )
    contract = LogicalMetricContract(
        "current_assets",
        aliases=("tai san ngan han",),
        statement_types=("balance_sheet",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Tài sản ngắn hạn cuối năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((fact,), limit=10)

    assert "metric:governed_code" in resolved[0].score_reasons
    assert is_high_trust_logical_fact(resolved[0])
    assert not has_hard_logical_fact_conflict(resolved[0])


def test_explicit_fixed_asset_carrying_disclosure_beats_implied_statement_line() -> None:
    implied = _fact(
        "fixed-asset-statement",
        "B01-DN › Tài sản cố định hữu hình",
        "31/12/2024",
        "100",
        metric="tangible_fixed_assets",
        role="closing",
        metric_code="221",
        statement="balance_sheet",
        score=250.0,
    )
    explicit = _fact(
        "fixed-asset-disclosure",
        "Tài sản cố định hữu hình › Giá trị còn lại › Tại ngày cuối năm",
        "Tổng cộng",
        "100",
        metric="tangible_fixed_assets",
        role="closing",
        statement="note",
        score=100.0,
    )
    contract = LogicalMetricContract(
        "tangible_fixed_assets",
        aliases=("tai san co dinh huu hinh",),
        query_surfaces=("gia tri con lai cua tai san co dinh huu hinh",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Giá trị còn lại của tài sản cố định hữu hình cuối năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((implied, explicit), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["fixed-asset-disclosure"]


def test_governed_exact_row_can_recover_missing_label_collision() -> None:
    fact = replace(
        _fact(
            "assets",
            "B01-DN › Tổng cộng tài sản",
            "31/12/2024",
            "100",
            metric="total_assets",
            role="closing",
            metric_code="270",
            statement="balance_sheet",
        ),
        collision_class="missing_label_or_split",
    )
    contract = LogicalMetricContract(
        "total_assets",
        aliases=("tong cong tai san",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Tổng cộng tài sản cuối năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((fact,), limit=10)

    assert "metric:governed_code" in resolved[0].score_reasons
    assert "metric:exact_row" in resolved[0].score_reasons
    assert not has_hard_logical_fact_conflict(resolved[0])


def test_governed_code_recovers_high_confidence_missing_dimension_collision() -> None:
    net = replace(
        _fact(
            "inventory-net",
            "B01-DN › Hàng tồn kho",
            "31/12/2020",
            "100",
            metric="inventory",
            role="closing",
            metric_code="140",
            statement="balance_sheet",
        ),
        collision_class="missing_dimension",
    )
    gross = replace(
        _fact(
            "inventory-gross",
            "B01-DN › Hàng tồn kho",
            "31/12/2020",
            "120",
            metric="inventory",
            role="closing",
            metric_code="141",
            statement="balance_sheet",
            score=1_000.0,
        ),
        collision_class="missing_dimension",
    )
    contract = LogicalMetricContract(
        "inventory",
        aliases=("hang ton kho",),
        metric_codes=("140",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Hàng tồn kho cuối năm 2020?",
        requested_periods=("2020",),
        contracts=(contract,),
    ).resolve((gross, net), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["inventory-net"]
    assert "metric:governed_code" in resolved[0].score_reasons
    assert "metric:exact_row" in resolved[0].score_reasons
    assert not has_hard_logical_fact_conflict(resolved[0])


def test_low_confidence_collision_remains_a_hard_conflict() -> None:
    fact = replace(
        _fact(
            "assets-low-confidence",
            "B01-DN › Tổng cộng tài sản",
            "31/12/2024",
            "100",
            metric="total_assets",
            role="closing",
            metric_code="270",
            statement="balance_sheet",
        ),
        collision_class="missing_label_or_split",
        source_confidence=0.7,
    )
    contract = LogicalMetricContract(
        "total_assets",
        aliases=("tong cong tai san",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Tổng cộng tài sản cuối năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((fact,), limit=10)

    assert has_hard_logical_fact_conflict(resolved[0])


def test_fact_limit_preserves_all_governed_operands_before_lexical_fallbacks() -> None:
    governed_a = _fact(
        "governed-a",
        "Chỉ tiêu A",
        "Năm 2024",
        "1",
        metric="metric_a",
        role="current",
        score=1.0,
    )
    governed_b = replace(
        _fact(
            "governed-b",
            "Chỉ tiêu B",
            "Năm 2024",
            "2",
            metric="metric_b",
            role="current",
            score=1.0,
        ),
        entity="BBB",
    )
    lexical = tuple(
        replace(
            _fact(
                f"lexical-{index}",
                f"Lexical {index}",
                "Năm 2024",
                str(index + 10),
                metric=f"lexical_{index}",
                role="current",
                score=1_000.0 - index,
            ),
            entity=f"L{index}",
        )
        for index in range(4)
    )
    contracts = (
        LogicalMetricContract("metric_a", aliases=("chi tieu a",)),
        LogicalMetricContract("metric_b", aliases=("chi tieu b",)),
    )

    resolved = LogicalFactResolver(
        "Chỉ tiêu A và chỉ tiêu B năm 2024?",
        requested_periods=("2024",),
        contracts=contracts,
    ).resolve((*lexical, governed_a, governed_b), limit=2)

    assert {fact.observation_uid for fact in resolved} == {"governed-a", "governed-b"}


def test_fact_limit_balances_metrics_across_entity_period_scopes() -> None:
    facts = tuple(
        replace(
            _fact(
                f"{metric}-{year}",
                f"Chỉ tiêu {metric}",
                f"Năm {year}",
                str(index + 1),
                metric=f"metric_{metric}",
                role="current",
                score=score,
            ),
            period=f"{year}-12-31",
            document_year=year,
        )
        for year in (2022, 2023, 2024)
        for index, (metric, score) in enumerate(
            (("a", 300.0), ("b", 200.0), ("c", 100.0))
        )
    )
    contracts = tuple(
        LogicalMetricContract(f"metric_{metric}", aliases=(f"chi tieu {metric}",))
        for metric in ("a", "b", "c")
    )

    resolved = LogicalFactResolver(
        "Chỉ tiêu A, B và C giai đoạn 2022-2024?",
        requested_periods=("2022", "2023", "2024"),
        contracts=contracts,
    ).resolve(facts, limit=6)

    metric_counts = {
        metric: sum(fact.retrieval_metric == metric for fact in resolved)
        for metric in ("metric_a", "metric_b", "metric_c")
    }
    assert metric_counts == {"metric_a": 2, "metric_b": 2, "metric_c": 2}
    assert {fact.period_year for fact in resolved} == {2022, 2023, 2024}


def test_fact_limit_selects_one_complete_statement_basis_bundle() -> None:
    consolidated_a = _fact(
        "consolidated-a",
        "Chỉ tiêu A",
        "Năm 2024",
        "1",
        metric="metric_a",
        role="current",
        score=10.0,
    )
    consolidated_b = _fact(
        "consolidated-b",
        "Chỉ tiêu B",
        "Năm 2024",
        "2",
        metric="metric_b",
        role="current",
        score=10.0,
    )
    separate_a = replace(
        _fact(
            "separate-a",
            "Chỉ tiêu A",
            "Năm 2024",
            "100",
            metric="metric_a",
            role="current",
            score=1_000.0,
        ),
        basis=Basis.SEPARATE,
    )
    contracts = (
        LogicalMetricContract("metric_a", aliases=("chi tieu a",)),
        LogicalMetricContract("metric_b", aliases=("chi tieu b",)),
    )

    resolved = LogicalFactResolver(
        "Chỉ tiêu A và chỉ tiêu B năm 2024?",
        requested_periods=("2024",),
        contracts=contracts,
    ).resolve((separate_a, consolidated_a, consolidated_b), limit=2)

    assert {fact.observation_uid for fact in resolved} == {
        "consolidated-a",
        "consolidated-b",
    }


def test_requested_source_total_prefers_physical_note_total() -> None:
    statement = _fact(
        "statement-total",
        "Phải thu ngắn hạn khác",
        "Số cuối năm",
        "100",
        metric="source_other_receivables",
        role="closing",
        statement="balance_sheet",
        score=300.0,
    )
    disclosure = _fact(
        "disclosure-total",
        "Các khoản phải thu khác › TỔNG CỘNG",
        "Số cuối năm › Ngắn hạn",
        "100",
        metric="source_other_receivables",
        role="closing",
        statement="note",
    )
    contract = LogicalMetricContract(
        "source_other_receivables",
        aliases=("phai thu ngan han khac",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Tổng giá trị các khoản phải thu khác ngắn hạn cuối năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((statement, disclosure), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["disclosure-total"]


def test_reported_statement_metric_prefers_primary_statement_source() -> None:
    note = _fact(
        "tax-note",
        "Chi phí thuế thu nhập doanh nghiệp hiện hành",
        "Năm 2024",
        "10",
        metric="reported_current_tax_expense",
        role="current",
        statement="note",
        score=150.0,
    )
    statement = _fact(
        "tax-statement",
        "Chi phí thuế thu nhập doanh nghiệp hiện hành",
        "Năm 2024",
        "10",
        metric="reported_current_tax_expense",
        role="current",
        statement="income_statement",
        score=100.0,
    )
    contract = LogicalMetricContract(
        "reported_current_tax_expense",
        aliases=("chi phi thue thu nhap doanh nghiep hien hanh",),
        period_semantics=PeriodSemantics.FLOW,
    )

    resolved = LogicalFactResolver(
        "Chi phí thuế thu nhập doanh nghiệp hiện hành năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((note, statement), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["tax-statement"]


def test_unqualified_provision_prefers_aggregate_column() -> None:
    component = _fact(
        "provision-common",
        "Dự phòng trích lập trong năm",
        "Dự phòng chung › Triệu VND",
        "10",
        metric="source_provision_charge",
        role="current",
        score=180.0,
    )
    total = _fact(
        "provision-total",
        "Dự phòng trích lập trong năm",
        "Tổng cộng › Triệu VND",
        "30",
        metric="source_provision_charge",
        role="current",
        score=100.0,
    )
    contract = LogicalMetricContract(
        "source_provision_charge",
        aliases=("du phong trich lap trong nam",),
        period_semantics=PeriodSemantics.FLOW,
    )

    resolved = LogicalFactResolver(
        "Dự phòng trích lập trong năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((component, total), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["provision-total"]


def test_safe_qualified_source_beats_higher_scoring_hard_conflict() -> None:
    hard = _fact(
        "hard-balance",
        "Tài sản cố định hữu hình",
        "Số cuối năm",
        "100",
        metric="tangible_fixed_assets",
        role="closing",
        statement="balance_sheet",
        score=1_000.0,
    )
    qualified = _fact(
        "qualified-note",
        "Tài sản cố định hữu hình › Giá trị còn lại › Tại ngày cuối năm",
        "Tổng VND",
        "100",
        metric="tangible_fixed_assets",
        role="closing",
        statement="note",
        score=10.0,
    )
    contract = LogicalMetricContract(
        "tangible_fixed_assets",
        aliases=("tai san co dinh huu hinh",),
        query_surfaces=("gia tri con lai tai san co dinh huu hinh",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Giá trị còn lại của tài sản cố định hữu hình cuối năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((hard, qualified), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["qualified-note"]
    assert not has_hard_logical_fact_conflict(resolved[0])


def test_short_term_contract_rejects_long_term_row_despite_column_noise() -> None:
    short_term = _fact(
        "short-term",
        "Các khoản phải thu khác › TỔNG CỘNG",
        "Số cuối năm › Ngắn hạn",
        "100",
        metric="source_other_receivables",
        role="closing",
        score=20.0,
    )
    long_term = _fact(
        "long-term",
        "Các khoản phải thu khác › Dài hạn › TỔNG CỘNG",
        "Số cuối năm › Ngắn hạn",
        "10",
        metric="source_other_receivables",
        role="closing",
        score=1_000.0,
    )
    contract = LogicalMetricContract(
        "source_other_receivables",
        aliases=("phai thu ngan han khac",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Tổng giá trị các khoản phải thu khác ngắn hạn cuối năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((long_term, short_term), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["short-term"]


def test_fixed_asset_carrying_amount_prefers_aggregate_roll_forward_column() -> None:
    component = _fact(
        "fixed-asset-component",
        "Tài sản cố định hữu hình › Giá trị còn lại › Tại ngày cuối năm",
        "Máy móc và thiết bị › Nguyên giá",
        "60",
        metric="tangible_fixed_assets",
        role="closing",
        score=300.0,
    )
    total = _fact(
        "fixed-asset-total",
        "Tài sản cố định hữu hình › Giá trị còn lại › Tại ngày cuối năm",
        "Tổng cộng › Nguyên giá",
        "100",
        metric="tangible_fixed_assets",
        role="closing",
        score=100.0,
    )
    contract = LogicalMetricContract(
        "tangible_fixed_assets",
        aliases=("tai san co dinh huu hinh",),
        query_surfaces=("gia tri con lai cua tai san co dinh huu hinh",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Giá trị còn lại của tài sản cố định hữu hình cuối năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((component, total), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["fixed-asset-total"]


def test_physical_opening_row_overrides_incorrect_closing_metadata() -> None:
    opening = _fact(
        "physical-opening",
        "Tài sản cố định hữu hình › Giá trị còn lại › Tại ngày đầu năm",
        "Tổng cộng › Nguyên giá",
        "130",
        metric="tangible_fixed_assets",
        # A6 can inherit the table-wide closing period into every roll-forward
        # observation. The physical row boundary must remain authoritative.
        role="closing",
        score=500.0,
    )
    closing = _fact(
        "physical-closing",
        "Tài sản cố định hữu hình › Giá trị còn lại › Tại ngày cuối năm",
        "Tổng cộng › Nguyên giá",
        "100",
        metric="tangible_fixed_assets",
        role="closing",
        score=100.0,
    )
    contract = LogicalMetricContract(
        "tangible_fixed_assets",
        aliases=("tai san co dinh huu hinh",),
        query_surfaces=("gia tri con lai cua tai san co dinh huu hinh",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Giá trị còn lại của tài sản cố định hữu hình cuối năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((opening, closing), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["physical-closing"]


def test_unrequested_segment_source_is_a_hard_conflict() -> None:
    segment = _fact(
        "segment-tax",
        "Thông tin theo bộ phận › Chi phí thuế thu nhập hiện hành",
        "Năm 2024 › MCH",
        "10",
        metric="reported_current_tax_expense",
        role="current",
        statement="income_statement",
        score=500.0,
    )
    disclosure = _fact(
        "tax-disclosure",
        "Thuế thu nhập doanh nghiệp › Chi phí thuế thu nhập hiện hành",
        "Năm 2024",
        "100",
        metric="reported_current_tax_expense",
        role="current",
        statement="note",
        score=100.0,
    )
    contract = LogicalMetricContract(
        "reported_current_tax_expense",
        aliases=("chi phi thue thu nhap hien hanh",),
        period_semantics=PeriodSemantics.FLOW,
    )

    resolved = LogicalFactResolver(
        "Chi phí thuế thu nhập hiện hành năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((segment, disclosure), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["tax-disclosure"]
    assert not has_hard_logical_fact_conflict(resolved[0])


def test_movement_source_rejects_closing_balance_with_same_subject() -> None:
    balance = _fact(
        "provision-balance",
        "Chứng khoán đầu tư sẵn sàng để bán › Dự phòng chung",
        "Số cuối năm",
        "-10",
        metric="reported_afs_provision_charge",
        role="current",
        score=500.0,
    )
    movement = _fact(
        "provision-movement",
        "Số trích lập/(hoàn nhập) trong năm › Chứng khoán đầu tư sẵn sàng để bán",
        "Năm nay",
        "-20",
        metric="reported_afs_provision_charge",
        role="current",
        score=100.0,
    )
    contract = LogicalMetricContract(
        "reported_afs_provision_charge",
        aliases=(
            "trich lap hoan nhap du phong chung khoan dau tu san sang de ban",
            "chung khoan dau tu san sang de ban",
        ),
        period_semantics=PeriodSemantics.FLOW,
    )

    resolved = LogicalFactResolver(
        "Số trích lập/(hoàn nhập) dự phòng chứng khoán đầu tư sẵn sàng để bán?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((balance, movement), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["provision-movement"]


def test_slash_date_column_is_recognized_as_balance_for_movement_conflict() -> None:
    balance = _fact(
        "slash-balance",
        "Chứng khoán đầu tư sẵn sàng để bán",
        "31/12/2024 › Triệu VND",
        "100",
        metric="reported_afs_provision_charge",
        role="current",
    )
    contract = LogicalMetricContract(
        "reported_afs_provision_charge",
        aliases=("chung khoan dau tu san sang de ban",),
        period_semantics=PeriodSemantics.FLOW,
    )

    resolved = LogicalFactResolver(
        "Trích lập/(hoàn nhập) dự phòng chứng khoán đầu tư sẵn sàng để bán?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((balance,), limit=10)

    assert has_hard_logical_fact_conflict(resolved[0])


def test_structurally_restored_movement_parent_recovers_parent_collision() -> None:
    movement = replace(
        _fact(
            "restored-movement",
            "Số trích lập/(hoàn nhập) trong năm › Chứng khoán đầu tư sẵn sàng để bán",
            "Năm nay",
            "-20",
            metric="reported_afs_provision_charge",
            role="current",
        ),
        collision_class="missing_row_parent",
        source_confidence=0.65,
    )
    contract = LogicalMetricContract(
        "reported_afs_provision_charge",
        aliases=("chung khoan dau tu san sang de ban",),
        period_semantics=PeriodSemantics.FLOW,
    )

    resolved = LogicalFactResolver(
        "Số trích lập/(hoàn nhập) dự phòng chứng khoán đầu tư sẵn sàng để bán?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((movement,), limit=10)

    assert "source:movement_presentation_order_match" in resolved[0].score_reasons
    assert not has_hard_logical_fact_conflict(resolved[0])


def test_broad_shareholder_profit_rejects_unrequested_nci_component() -> None:
    nci = _fact(
        "nci-profit",
        "Lợi nhuận thuần phân bổ cho cổ đông không kiểm soát trong năm",
        "Năm 2024",
        "10",
        metric="source_attributable_profit",
        role="current",
        score=500.0,
    )
    owners = _fact(
        "owners-profit",
        "Lợi nhuận thuần phân bổ cho các cổ đông",
        "Năm 2024",
        "100",
        metric="source_attributable_profit",
        role="current",
        score=100.0,
    )
    contract = LogicalMetricContract(
        "source_attributable_profit",
        aliases=("loi nhuan thuan phan bo cho co dong",),
        period_semantics=PeriodSemantics.FLOW,
    )

    resolved = LogicalFactResolver(
        "Lợi nhuận thuần phân bổ cho cổ đông năm 2024?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((nci, owners), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["owners-profit"]


def test_loan_loss_common_provision_rejects_afs_provision_context() -> None:
    afs = _fact(
        "afs-common",
        "Chứng khoán đầu tư sẵn sàng để bán › Dự phòng chung",
        "31/12/2024",
        "10",
        metric="common_loan_loss_provision",
        role="closing",
        score=500.0,
    )
    loans = _fact(
        "loan-common",
        "Dự phòng rủi ro cho vay khách hàng › Dự phòng chung",
        "31/12/2024",
        "100",
        metric="common_loan_loss_provision",
        role="closing",
        score=100.0,
    )
    contract = LogicalMetricContract(
        "common_loan_loss_provision",
        aliases=("du phong chung",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Dự phòng chung trên tổng dự phòng rủi ro cho vay khách hàng?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((afs, loans), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["loan-common"]


def test_fixed_asset_total_rejects_unrequested_disclosed_component() -> None:
    component = _fact(
        "collateral-component",
        "Tài sản cố định hữu hình › Giá trị còn lại › Trong đó: thế chấp",
        "Tổng cộng",
        "10",
        metric="tangible_fixed_assets",
        role="closing",
        score=500.0,
    )
    total = _fact(
        "carrying-total",
        "Tài sản cố định hữu hình › Giá trị còn lại › Tại ngày cuối năm",
        "Tổng cộng",
        "100",
        metric="tangible_fixed_assets",
        role="closing",
        score=100.0,
    )
    contract = LogicalMetricContract(
        "tangible_fixed_assets",
        aliases=("tai san co dinh huu hinh",),
        query_surfaces=("gia tri con lai cua tai san co dinh huu hinh",),
        period_semantics=PeriodSemantics.POINT_IN_TIME,
    )

    resolved = LogicalFactResolver(
        "Giá trị còn lại của tài sản cố định hữu hình cuối năm?",
        requested_periods=("2024",),
        contracts=(contract,),
    ).resolve((component, total), limit=10)

    assert [fact.observation_uid for fact in resolved] == ["carrying-total"]
