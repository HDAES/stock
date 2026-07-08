import json

import pandas as pd
import pytest

from stock_quant.analysis import (
    CacheMissError,
    load_cached_kline,
    stock_summary,
    strategy_backtest,
    strategy_rank,
)
from stock_quant.cache import DataCache, symbol_to_filename
from stock_quant.config import load_config


def test_stock_summary_calculates_core_metrics(tmp_path):
    cache = DataCache(tmp_path / "cache")
    _write_kline(cache, "TSLA.US", [float(index) for index in range(1, 222)])

    summary = stock_summary(cache, "TSLA.US", 500)

    assert summary["symbol"] == "TSLA.US"
    assert summary["last"] == 221.0
    assert summary["previous_close"] == 220.0
    assert summary["change"] == 1.0
    assert summary["sma20"] == pytest.approx(sum(range(202, 222)) / 20)
    assert summary["sma50"] == pytest.approx(sum(range(172, 222)) / 50)
    assert summary["sma200"] == pytest.approx(sum(range(22, 222)) / 200)
    assert summary["return5"] == pytest.approx(221.0 / 216.0 - 1.0)
    assert summary["rsi14"] == 100.0
    assert summary["annualized_volatility60"] is not None


def test_load_cached_kline_raises_for_missing_symbol(tmp_path):
    cache = DataCache(tmp_path / "cache")

    with pytest.raises(CacheMissError):
        load_cached_kline(cache, "MSFT.US")


def test_strategy_rank_and_backtest_return_structured_results(tmp_path):
    config_path = _write_config(tmp_path)
    cache = DataCache(tmp_path / "data" / "cache")
    _write_kline(cache, "A.US", [100 + index for index in range(260)])
    _write_kline(cache, "B.US", [200 + index * 0.5 for index in range(260)])
    _write_kline(cache, "SPY.US", [300 + index for index in range(260)])
    _write_calc_index(cache, "A.US", {"pe": "20", "pb": "3", "roe": "0.20"})
    _write_calc_index(cache, "B.US", {"pe": "30", "pb": "4", "roe": "0.10"})
    config = load_config(config_path)

    ranked = strategy_rank(config, cache)
    backtest = strategy_backtest(config, cache)

    assert [row["rank"] for row in ranked] == [1, 2]
    assert {row["symbol"] for row in ranked} == {"A.US", "B.US"}
    assert "score" in ranked[0]
    assert len(backtest["selected_symbols"]) == 1
    assert backtest["exposure"] == 1.0
    assert backtest["metrics"]["cagr"] != 0.0
    assert backtest["equity_curve"]


def _write_config(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    path = config_dir / "default.json"
    path.write_text(
        json.dumps(
            {
                "benchmark": "SPY.US",
                "universe": ["A.US", "B.US"],
                "data": {"cache_dir": "data/cache", "history_count": 260},
                "strategy": {
                    "top_n": 1,
                    "rebalance": "M",
                    "momentum_window": 60,
                    "volatility_window": 60,
                    "risk_ma_window": 200,
                    "full_exposure": 1.0,
                    "defensive_exposure": 0.4,
                    "transaction_cost_bps": 10,
                },
                "factor_weights": {
                    "momentum": 0.3,
                    "value": 0.25,
                    "quality": 0.25,
                    "low_volatility": 0.2,
                },
            }
        )
    )
    return path


def _write_kline(cache, symbol, closes):
    payload = []
    for index, close in enumerate(closes):
        payload.append(
            {
                "time": (pd.Timestamp("2024-01-01") + pd.Timedelta(days=index)).isoformat(),
                "open": str(close - 0.5),
                "high": str(close + 1.0),
                "low": str(close - 1.0),
                "close": str(close),
                "volume": str(1_000_000 + index),
            }
        )
    path = cache.kline_dir / f"{symbol_to_filename(symbol)}.json"
    path.write_text(json.dumps(payload))


def _write_calc_index(cache, symbol, payload):
    path = cache.calc_index_dir / f"{symbol_to_filename(symbol)}.json"
    path.write_text(json.dumps([payload]))
