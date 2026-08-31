from text2pandas.domain.semantic import Dimension
from text2pandas.infrastructure.retrieval.grounded import _dimension_prior


def test_direct_value_dimension_prior_separates_balance_from_rate_column() -> None:
    assert _dimension_prior(Dimension.MONEY, Dimension.MONEY) > 0
    assert _dimension_prior(Dimension.PERCENT, Dimension.MONEY) < 0
    assert _dimension_prior(Dimension.MONEY, Dimension.UNKNOWN) == 0

