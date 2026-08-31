from tools.evaluation.build_recovery_wave2_inventory import classify_case


def test_wave2_inventory_classifies_source_backed_simple_shapes_as_tier_a() -> None:
    assert classify_case(
        operation="lookup",
        formula_count=0,
        concept_count=1,
        candidate_facts=8,
        question="Tiền cuối năm 2024 là bao nhiêu?",
    ) == ("direct_lookup", "A")
    assert classify_case(
        operation="subtract",
        formula_count=0,
        concept_count=1,
        candidate_facts=12,
        question="Chênh lệch doanh thu năm 2024 và 2023 là bao nhiêu?",
    ) == ("two_period_difference", "A")


def test_wave2_inventory_keeps_missing_or_complex_cases_out_of_tier_a() -> None:
    assert classify_case(
        operation="lookup",
        formula_count=0,
        concept_count=1,
        candidate_facts=0,
        question="Tiền cuối năm 2024 là bao nhiêu?",
    ) == ("direct_lookup", "D")
    assert classify_case(
        operation="average",
        formula_count=1,
        concept_count=2,
        candidate_facts=100,
        question="Tại năm có tỷ lệ cao nhất, giá trị trung bình là bao nhiêu?",
    ) == ("single_metric_average", "C")


def test_wave2_inventory_classifies_single_metric_extremum_as_tier_b() -> None:
    assert classify_case(
        operation="extremum",
        formula_count=0,
        concept_count=1,
        candidate_facts=30,
        question="Năm nào có doanh thu cao nhất?",
    ) == ("simple_extremum", "B")
