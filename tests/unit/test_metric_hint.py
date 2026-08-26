from text2pandas.pipelines.retrieval.metric_hint import metric_codes_hint


def test_metric_hint_prefers_tangible_fixed_assets_over_total_assets() -> None:
    question = "Tổng tài sản cố định hữu hình cuối năm 2023 là bao nhiêu?"

    assert metric_codes_hint(question) == frozenset({"221"})


def test_metric_hint_prefers_retained_earnings_over_net_income() -> None:
    question = "Lợi nhuận sau thuế chưa phân phối cuối năm 2023 là bao nhiêu?"

    assert metric_codes_hint(question) == frozenset({"421"})
