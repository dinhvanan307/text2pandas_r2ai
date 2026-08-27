from __future__ import annotations

import pytest

from text2pandas.pipelines.answering.frame import (
    COUNT_OP,
    EXTREMUM,
    classify_operation,
    parse_question,
)
from text2pandas.pipelines.answering.ir import GROWTH, LOOKUP, SUBTRACT, SUM
from text2pandas.pipelines.answering.router import route
from text2pandas.pipelines.answering.units import MONEY, Unit


@pytest.mark.parametrize(
    "question,expected",
    [
        ("Tổng phải thu ngắn hạn khác cuối năm 2025 là bao nhiêu?", LOOKUP),
        ("Số cổ phiếu phổ thông bình quân gia quyền năm 2020 là bao nhiêu?", LOOKUP),
        ("Lỗ chênh lệch tỷ giá năm 2023 là bao nhiêu?", LOOKUP),
        ("Khoản phải trả trên báo cáo hợp nhất là bao nhiêu?", LOOKUP),
        ("Chi phí năm 2025 bé hơn năm 2024 mấy tỷ đồng?", SUBTRACT),
        ("Tính biến động số dư giữa năm 2024 và 2023.", SUBTRACT),
        ("Doanh thu của VNM năm 2024 trừ đi doanh thu HPG.", SUBTRACT),
        ("Hiệu giữa doanh thu VNM và HPG năm 2024 là bao nhiêu?", SUBTRACT),
        ("Doanh thu VNM lớn hơn của HPG bao nhiêu tỷ đồng?", SUBTRACT),
        ("Doanh thu VNM kém hơn HPG mấy tỷ đồng?", SUBTRACT),
        ("Kết quả thuần từ hoạt động tài chính năm 2024 là bao nhiêu?", SUBTRACT),
        ("Chi phí năm 2023 tăng bao nhiêu phần trăm so với năm 2022?", GROWTH),
        ("Tài sản từ năm 2018 đến năm 2023 tăng bao nhiêu triệu đồng?", SUBTRACT),
        ("Dư nợ cuối năm 2021 tăng so với cuối năm 2020 bao nhiêu phần trăm?", GROWTH),
        ("Tỷ lệ tăng % khoản trả trước từ năm 2020 đến 2021 là bao nhiêu?", GROWTH),
        ("Thay đổi số dư vay từ năm 2023 đến 2024 là bao nhiêu triệu đồng?", SUBTRACT),
        ("Số dư tối đa trong các năm 2022, 2023 và 2024 là bao nhiêu?", EXTREMUM),
        ("Có bao nhiêu trong số AAA, BBB và CCC có CFO dương?", COUNT_OP),
        ("Tính tổng chi phí khấu hao cho các năm 2019, 2022 và 2024.", SUM),
    ],
)
def test_corpus_operation_regressions(question: str, expected: str) -> None:
    assert classify_operation(question).op == expected


def test_less_than_difference_reverses_period_operands() -> None:
    frame = parse_question(
        "Chi phí cuối năm 2025 bé hơn cuối năm 2024 mấy tỷ đồng?",
        requested_unit=Unit(MONEY, 9),
    )

    result = route(frame)

    assert result.ok and result.ir is not None
    assert [slot.period for slot in result.ir.slots] == ["2024", "2025"]


def test_kem_hon_marks_reverse_difference() -> None:
    operation = classify_operation(
        "Doanh thu SCR kém hơn NLG bao nhiêu tỷ đồng?"
    )

    assert operation.op == SUBTRACT
    assert operation.reverse_difference is True


@pytest.mark.parametrize(
    "question,expected_reverse",
    [
        (
            "So với SCR, khoản tiền gửi của CRE cao hơn bao nhiêu tỷ đồng?",
            True,
        ),
        (
            "So với SCR, khoản tiền gửi của CRE thấp hơn bao nhiêu tỷ đồng?",
            False,
        ),
    ],
)
def test_fronted_comparison_reference_controls_operand_direction(
    question: str,
    expected_reverse: bool,
) -> None:
    operation = classify_operation(question)

    assert operation.op == SUBTRACT
    assert operation.reverse_difference is expected_reverse


def test_explicit_absolute_difference_is_preserved_in_operation_contract() -> None:
    operation = classify_operation(
        "Chênh lệch tuyệt đối dư nợ giữa HDB và EIB là bao nhiêu triệu đồng?"
    )

    assert operation.op == SUBTRACT
    assert operation.absolute_difference is True
