from text2pandas.infrastructure.retrieval.grounded import (
    _contextual_alias_match,
    _restore_section_parent,
    _surface_qualifiers_present,
)


def test_generic_roll_forward_row_inherits_nearest_section_identity() -> None:
    restored = _restore_section_parent(
        "13 TÀI SẢN CỐ ĐỊNH HỮU HÌNH › Tại ngày cuối năm",
        "13 TÀI SẢN CỐ ĐỊNH HỮU HÌNH › GIÁ TRỊ CÒN LẠI",
        is_generic=True,
    )

    assert restored == (
        "13 TÀI SẢN CỐ ĐỊNH HỮU HÌNH › GIÁ TRỊ CÒN LẠI › Tại ngày cuối năm"
    )


def test_temporal_section_child_is_restored_despite_incorrect_generic_flag() -> None:
    restored = _restore_section_parent(
        "13 TÀI SẢN CỐ ĐỊNH HỮU HÌNH › Tại ngày cuối năm",
        "13 TÀI SẢN CỐ ĐỊNH HỮU HÌNH › GIÁ TRỊ CÒN LẠI",
        is_generic=False,
    )

    assert "GIÁ TRỊ CÒN LẠI › Tại ngày cuối năm" in restored


def test_specific_row_inherits_structural_preceding_section() -> None:
    row = "13 TÀI SẢN CỐ ĐỊNH HỮU HÌNH › Khấu hao trong năm"

    assert _restore_section_parent(
        row,
        "13 TÀI SẢN CỐ ĐỊNH HỮU HÌNH › GIÁ TRỊ HAO MÒN LŨY KẾ",
        is_generic=False,
    ) == (
        "13 TÀI SẢN CỐ ĐỊNH HỮU HÌNH › GIÁ TRỊ HAO MÒN LŨY KẾ › "
        "Khấu hao trong năm"
    )


def test_contextual_alias_repairs_split_vietnamese_ocr_token() -> None:
    assert _contextual_alias_match(
        "tai san co dinh huu hinh",
        "tang giam tai san co dinh hu u hinh gia tri con lai",
    )


def test_relational_surface_does_not_leak_denominator_tokens_into_numerator() -> None:
    assert _surface_qualifiers_present(
        ("du phong chung tren tong",),
        ("du phong chung",),
        "du phong rui ro cho vay khach hang bao gom du phong chung i",
    )
