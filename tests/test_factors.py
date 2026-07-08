import pandas as pd

from stock_quant.factors import annualized_volatility, trailing_return, zscore
from stock_quant.strategy import equal_weight_targets


def test_zscore_constant_series_returns_zeroes():
    result = zscore(pd.Series([3.0, 3.0, 3.0]))
    assert result.tolist() == [0.0, 0.0, 0.0]


def test_trailing_return_uses_window_start():
    prices = pd.Series([100.0, 105.0, 110.0, 121.0])
    assert trailing_return(prices, 2) == 121.0 / 105.0 - 1.0


def test_annualized_volatility_needs_enough_data():
    prices = pd.Series([100.0, 101.0, 102.0])
    assert pd.isna(annualized_volatility(prices, 60))


def test_equal_weight_targets_respects_exposure():
    result = equal_weight_targets(["A.US", "B.US"], 0.8)
    assert result == {"A.US": 0.4, "B.US": 0.4}

