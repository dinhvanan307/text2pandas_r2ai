from text2pandas.infrastructure.retrieval import fact_label_segments, normalize_fact_label


def test_normalize_fact_label_removes_numeric_formula_suffix() -> None:
    assert normalize_fact_label("TÀI SẢN NGẮN HẠN(100 = 110 + 120)") == (
        "tai san ngan han"
    )


def test_normalize_fact_label_removes_number_and_roman_enumerators() -> None:
    assert normalize_fact_label("1. Tài sản ngắn hạn") == "tai san ngan han"
    assert normalize_fact_label("IV - Tài sản ngắn hạn") == "tai san ngan han"


def test_normalize_fact_label_keeps_semantic_parenthetical() -> None:
    assert normalize_fact_label("Chi phí khác (ngân hàng mẹ)") == (
        "chi phi khac ngan hang me"
    )


def test_fact_label_segments_preserve_hierarchy() -> None:
    assert fact_label_segments("I. Tài sản › Tài sản ngắn hạn › Tổng cộng") == (
        "tai san",
        "tai san ngan han",
        "tong cong",
    )
