"""Semantic contract v2 — the schema the candidate generator will be built on.

These tests assert the contract can EXPRESS the things the old one could not.
They deliberately do not test the router: the schema is frozen first, wired
after local gold exists (review 173 constraint 1).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from text2pandas.answer_pipeline.spec import (  # noqa: E402
    AXIS_ENTITY, AXIS_METRIC, AXIS_NONE, AXIS_PERIOD, CandidateObservation,
    EntitySelector, FilterSpec, OperandSpec, PeriodSelector,
    QuestionSemanticFrameV2, RankSpec, ReturnSpec, OP_GT,
)
from text2pandas.answer_pipeline import result_kind as RK  # noqa: E402
from text2pandas.answer_pipeline.units import MONEY, PERCENT, Unit  # noqa: E402


def test_ratio_of_two_different_metrics_is_expressible():
    """THE defect: the old contract copied one metric_id into every slot."""
    f = QuestionSemanticFrameV2(
        qid=1, question="Tỷ lệ nợ xấu trên tổng dư nợ năm 2023 của ACB là bao nhiêu %?",
        operand_specs=(
            OperandSpec("numerator", metric_id="bad_debt",
                        entity=EntitySelector("ACB"), period=PeriodSelector("2023"),
                        aggregation_axis=AXIS_METRIC),
            OperandSpec("denominator", metric_id="total_loans",
                        entity=EntitySelector("ACB"), period=PeriodSelector("2023"),
                        aggregation_axis=AXIS_METRIC),
        ),
        returns=ReturnSpec(RK.PERCENT_VALUE, Unit(PERCENT)))
    assert f.spec("numerator").metric_id != f.spec("denominator").metric_id
    assert f.varies_axis == AXIS_METRIC


def test_two_period_difference_varies_period_only():
    f = QuestionSemanticFrameV2(
        qid=2, question="Chênh lệch doanh thu 2023 so với 2022?",
        operand_specs=(
            OperandSpec("minuend", metric_id="revenue", period=PeriodSelector("2023"),
                        aggregation_axis=AXIS_PERIOD),
            OperandSpec("subtrahend", metric_id="revenue", period=PeriodSelector("2022"),
                        aggregation_axis=AXIS_PERIOD),
        ))
    assert f.varies_axis == AXIS_PERIOD
    assert {s.metric_id for s in f.operand_specs} == {"revenue"}


def test_cross_entity_aggregation_varies_entity():
    f = QuestionSemanticFrameV2(
        qid=3, question="Tổng doanh thu của HPG, HSG và NKG năm 2024?",
        operand_specs=tuple(
            OperandSpec("summand", metric_id="revenue", entity=EntitySelector(t),
                        period=PeriodSelector("2024"), aggregation_axis=AXIS_ENTITY)
            for t in ("HPG", "HSG", "NKG")))
    assert f.varies_axis == AXIS_ENTITY
    assert len(f.operand_specs) == 3


def test_filter_predicate_is_expressible():
    """'các năm có biên lợi nhuận ròng trên 10%' -- 67 EXTREMUM questions need this."""
    flt = FilterSpec(metric_id="net_margin", comparator=OP_GT, threshold=10.0,
                     unit=Unit(PERCENT))
    s = OperandSpec("value", metric_id="revenue", filters=(flt,))
    assert s.filters[0].comparator == OP_GT
    assert s.filters[0].threshold == 10.0


def test_group_statistic_threshold_is_expressible():
    """'thấp hơn trung vị của nhóm' cannot be a constant."""
    flt = FilterSpec(metric_id="debt_to_equity", comparator="<", threshold=0.0,
                     threshold_is_group_statistic="MEDIAN")
    assert flt.threshold_is_group_statistic == "MEDIAN"


def test_select_at_argmax_is_expressible():
    """Rank by one metric, return a DIFFERENT one at the winning position --
    72 SELECT_AT_ARG questions, previously not representable at all."""
    f = QuestionSemanticFrameV2(
        qid=4, question="Tại năm có chi phí XDCB cao nhất, số dư nợ đủ tiêu chuẩn là bao nhiêu?",
        rank=RankSpec(key_metric_id="capex_wip", axis=AXIS_PERIOD, direction="MAX"),
        returns=ReturnSpec(RK.MONEY_AMOUNT, Unit(MONEY, 9),
                           select_metric_id="standard_loans"))
    assert f.rank.key_metric_id != f.returns.select_metric_id
    assert f.rank.direction == "MAX"


def test_arg_period_returns_the_label_not_the_value():
    """'Năm nào ... cao nhất' -- 53 questions whose answer is a YEAR."""
    f = QuestionSemanticFrameV2(
        qid=5, question="Năm nào có doanh thu cao nhất?",
        rank=RankSpec(key_metric_id="revenue", axis=AXIS_PERIOD, direction="MAX"),
        returns=ReturnSpec(RK.PERIOD_YEAR, select_axis_value_only=True))
    assert f.returns.result_kind == RK.PERIOD_YEAR
    assert f.returns.select_axis_value_only is True


def test_basis_is_per_operand():
    """separate vs consolidated can differ between compared operands."""
    a = OperandSpec("minuend", metric_id="revenue", basis="separate")
    b = OperandSpec("subtrahend", metric_id="revenue", basis="consolidated")
    assert a.basis != b.basis


def test_opening_balance_is_distinguishable_from_annual_flow():
    """'Số đầu năm' is an instant, not a flow -- an open risk in 173 §5.6."""
    assert PeriodSelector("2023", point="OPENING") != PeriodSelector("2023", point="PERIOD")


def test_unspecified_operand_is_detectable():
    assert OperandSpec("value").is_specified is False
    assert OperandSpec("value", metric_id="revenue").is_specified is True


def test_varies_axis_is_none_when_ambiguous():
    f = QuestionSemanticFrameV2(qid=6, question="x", operand_specs=(
        OperandSpec("a", metric_id="m", aggregation_axis=AXIS_PERIOD),
        OperandSpec("b", metric_id="m", aggregation_axis=AXIS_ENTITY)))
    assert f.varies_axis is None


def test_bad_comparator_rejected():
    with pytest.raises(ValueError):
        FilterSpec(metric_id="x", comparator="~=", threshold=1.0)


def test_candidate_observation_uid_is_deterministic_and_dedups():
    a = CandidateObservation.make_uid("t.csv", 3, "value")
    b = CandidateObservation.make_uid("t.csv", 3, "value")
    c = CandidateObservation.make_uid("t.csv", 4, "value")
    assert a == b and a != c


def test_frame_serialises():
    f = QuestionSemanticFrameV2(
        qid=7, question="x",
        operand_specs=(OperandSpec("numerator", metric_id="a", aggregation_axis=AXIS_METRIC),
                       OperandSpec("denominator", metric_id="b", aggregation_axis=AXIS_METRIC)),
        returns=ReturnSpec(RK.PERCENT_VALUE))
    d = f.to_dict()
    assert d["varies_axis"] == AXIS_METRIC
    assert [s["metric_id"] for s in d["operand_specs"]] == ["a", "b"]
