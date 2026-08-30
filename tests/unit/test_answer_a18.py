from __future__ import annotations

from decimal import Decimal

import pytest

from tools.answer_a18.run_a18 import (
    A18Error,
    ExpressionCompiler,
    SemanticProfile,
    _agreement,
    _apply_transform,
    _canonicalize_expression,
    _confidence_score,
    _expanded_years,
    _normalize,
    _semantic_profiles,
    _semantic_score,
    _validated_solution,
)


def _candidate(
    uid: str,
    *,
    table_uid: str,
    value: str,
    scale: int = 0,
    kind: str = "money",
    ticker: str = "AAA",
    period: str = "2024",
) -> dict[str, object]:
    return {
        "uid": uid,
        "table_uid": table_uid,
        "ticker": ticker,
        "doc_year": int(period),
        "basis": "consolidated",
        "statement_type": "balance_sheet",
        "section": "",
        "row": "metric",
        "column": period,
        "period": period,
        "period_role": "current",
        "value": value,
        "value_kind": kind,
        "unit_kind": kind,
        "currency": "VND" if kind == "money" else None,
        "scale_exponent": scale,
        "evidence_ref": "DOC|line:1",
        "lexical_score": 1.0,
    }


def _packet(
    question: str = "Chênh lệch năm 2024 và 2023 là bao nhiêu tỷ đồng?",
) -> dict[str, object]:
    return {
        "qid": 1,
        "question": question,
        "question_sha256": "0" * 64,
        "candidates": [
            _candidate("1" * 16, table_uid="a" * 16, value="250", scale=9),
            _candidate(
                "2" * 16,
                table_uid="b" * 16,
                value="100000000000",
                scale=0,
                period="2023",
            ),
        ],
    }


def test_expands_explicit_year_range() -> None:
    assert _expanded_years("Trong giai đoạn 2019-2022", [2019, 2022]) == [
        2019,
        2020,
        2021,
        2022,
    ]


def test_normalize_preserves_vietnamese_d_semantics() -> None:
    assert _normalize("Dòng tiền từ hoạt động") == "dong tien tu hoat dong"


def test_canonicalizes_only_transform_owned_unit_conversion() -> None:
    expression, notes = _canonicalize_expression(
        "(obs('1111111111111111') - obs('2222222222222222')) / 1e9",
        "MONEY_BILLION_VND",
    )

    assert expression == "obs('1111111111111111') - obs('2222222222222222')"
    assert notes == ("REMOVE_REDUNDANT_MONEY_UNIT_DIVISOR",)
    unchanged, unchanged_notes = _canonicalize_expression(
        "obs('1111111111111111') / 2",
        "MONEY_BILLION_VND",
    )
    assert unchanged.endswith("/ 2")
    assert unchanged_notes == ()
    assert _expanded_years("Từ năm 2022 đến năm 2025", [2022, 2025]) == [
        2022,
        2023,
        2024,
        2025,
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("high", 1.0), ("medium", 0.6), ("low", 0.2), (0.8, 0.8), ("unknown", 0.0)],
)
def test_confidence_score_supports_a6_labels(raw: object, expected: float) -> None:
    assert _confidence_score(raw) == expected


def test_reviewed_alias_dominates_generic_long_row() -> None:
    profile = SemanticProfile(
        aliases=("hang ton kho",),
        forbidden_prefixes=("du phong giam gia hang ton kho",),
        forbidden_contains=(),
        statement_types=("balance_sheet", "note"),
    )
    exact, exact_key = _semantic_score(
        question="Tỷ lệ hàng tồn kho trên tổng tài sản",
        leaf="Hàng tồn kho",
        statement_type="balance_sheet",
        profiles=(profile,),
    )
    child, child_key = _semantic_score(
        question="Tỷ lệ hàng tồn kho trên tổng tài sản",
        leaf="Dự phòng giảm giá hàng tồn kho",
        statement_type="note",
        profiles=(profile,),
    )

    assert exact_key == "hang ton kho"
    assert child_key is None
    assert exact > child


def test_semantic_profiles_expand_formula_and_common_shorthand() -> None:
    from text2pandas.infrastructure.ontology import load_ontology

    profiles = _semantic_profiles("Năm có D/E cao nhất, CFO/LNST là bao nhiêu?", load_ontology())
    aliases = {alias for profile in profiles for alias in profile.aliases}

    assert "no phai tra" in aliases
    assert "von chu so huu" in aliases
    assert "luu chuyen tien thuan tu hoat dong kinh doanh" in aliases
    assert "loi nhuan sau thue" in aliases


def test_compiler_recomputes_scaled_a6_values_and_billion_output() -> None:
    compiler = ExpressionCompiler(_packet())
    quantity = compiler.compile('obs("1111111111111111") - obs("2222222222222222")')
    answer, query = _apply_transform(quantity, "MONEY_BILLION_VND")

    assert answer == Decimal(150)
    assert "1111111111111111" in query
    assert "2222222222222222" in query
    assert "/ 1000000000" in query
    assert compiler.evidence(quantity.uids) == [
        {
            "variable": "df1",
            "table_uid": "aaaaaaaaaaaaaaaa",
            "observation_uids": ["1111111111111111"],
        },
        {
            "variable": "df2",
            "table_uid": "bbbbbbbbbbbbbbbb",
            "observation_uids": ["2222222222222222"],
        },
    ]


def test_compiler_rejects_uid_outside_packet() -> None:
    with pytest.raises(A18Error, match="outside the packet"):
        ExpressionCompiler(_packet()).compile('obs("ffffffffffffffff")')


def test_compiler_rejects_model_constant_not_in_question() -> None:
    with pytest.raises(A18Error, match="not present in the question"):
        ExpressionCompiler(_packet()).compile('obs("1111111111111111") * 7')


def test_percent_change_uses_absolute_negative_base() -> None:
    packet = _packet("Tăng trưởng từ năm 2023 đến năm 2024 là bao nhiêu phần trăm?")
    packet["candidates"] = [
        _candidate("1" * 16, table_uid="a" * 16, value="-100", scale=6),
        _candidate("2" * 16, table_uid="b" * 16, value="-150", scale=6),
    ]
    quantity = ExpressionCompiler(packet).compile(
        'percent_change(obs("1111111111111111"), obs("2222222222222222"))'
    )
    answer, _ = _apply_transform(quantity, "PERCENT_NATIVE")

    assert answer == Decimal(-50)


def test_validated_solution_requires_declared_uid_exactness() -> None:
    packet = _packet()
    row = {
        "solution": {
            "status": "SOLVED",
            "expression": 'obs("1111111111111111")',
            "output_transform": "MONEY_BILLION_VND",
            "used_observation_uids": [],
            "operation": "LOOKUP",
            "entities": ["AAA"],
            "periods": ["2024"],
            "basis": "consolidated",
            "confidence": "HIGH",
            "reason": "",
        }
    }

    with pytest.raises(A18Error, match="declared UID set differs"):
        _validated_solution(packet, row)


def test_two_pass_agreement_checks_scope_and_value() -> None:
    base = {
        "answer_decimal": "1",
        "used_observation_uids": ["1" * 16],
        "operation": "LOOKUP",
        "entities": ["AAA"],
        "periods": ["2024"],
        "basis": "consolidated",
        "output_transform": "RAW_NUMBER",
    }
    changed = {**base, "basis": "separate"}

    assert _agreement(base, base) == []
    assert _agreement(base, changed) == ["basis"]
