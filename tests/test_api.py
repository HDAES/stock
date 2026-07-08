import json

import pandas as pd
import pytest

from stock_quant.cache import symbol_to_filename

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from stock_quant.web.api import create_app


def test_api_reads_cached_stock_summary(tmp_path):
    config_path = _write_web_fixture(tmp_path)
    client = TestClient(create_app(config_path, auto_intraday=False))

    response = client.get("/api/stocks/TSLA.US/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "TSLA.US"
    assert data["last"] == 260.0
    assert data["sma200"] is not None


def test_api_returns_404_for_missing_cache(tmp_path):
    config_path = _write_web_fixture(tmp_path)
    client = TestClient(create_app(config_path, auto_intraday=False))

    response = client.get("/api/stocks/MSFT.US/summary")

    assert response.status_code == 404
    assert "No cached kline data" in response.json()["detail"]


def test_api_strategy_endpoints_return_backtest_payload(tmp_path):
    config_path = _write_web_fixture(tmp_path)
    client = TestClient(create_app(config_path, auto_intraday=False))

    rank_response = client.get("/api/strategy/rank")
    backtest_response = client.get("/api/strategy/backtest")

    assert rank_response.status_code == 200
    assert len(rank_response.json()) == 2
    assert backtest_response.status_code == 200
    backtest = backtest_response.json()
    assert backtest["selected_symbols"]
    assert backtest["weights"]
    assert backtest["equity_curve"]


def test_api_intraday_state_returns_empty_paper_portfolio(tmp_path):
    config_path = _write_web_fixture(tmp_path)
    client = TestClient(create_app(config_path, auto_intraday=False))

    response = client.get("/api/intraday/state")

    assert response.status_code == 200
    data = response.json()
    assert data["cash"] == 100000
    assert data["positions"] == {}


def test_api_intraday_evaluate_uses_fake_longbridge_client(tmp_path):
    config_path = _write_web_fixture(tmp_path, intraday_symbols=["AAPL.US"])
    client = TestClient(create_app(config_path, longbridge_client=_FakeLongbridge(), auto_intraday=False))

    response = client.post("/api/intraday/evaluate")

    assert response.status_code == 200
    data = response.json()
    assert "AAPL.US" in data["positions"]
    assert data["last_signals"][0]["action"] == "BUY"


def test_api_startup_auto_scans_intraday_when_market_open(tmp_path):
    config_path = _write_web_fixture(tmp_path, intraday_symbols=["AAPL.US"], poll_seconds=60)
    with TestClient(create_app(config_path, longbridge_client=_FakeLongbridge())) as client:
        response = client.get("/api/intraday/state")

    assert response.status_code == 200
    data = response.json()
    assert "AAPL.US" in data["positions"]
    assert data["last_signals"][0]["action"] == "BUY"


def _write_web_fixture(tmp_path, intraday_symbols=None, poll_seconds=60):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    cache_dir = tmp_path / "data" / "cache"
    (cache_dir / "kline").mkdir(parents=True)
    (cache_dir / "calc_index").mkdir(parents=True)
    config_path = config_dir / "default.json"
    config_path.write_text(
        json.dumps(
            {
                "benchmark": "SPY.US",
                "universe": ["TSLA.US", "AAPL.US"],
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
                "intraday": {
                    "enabled": True,
                    "period": "5m",
                    "session": "intraday",
                    "poll_seconds": poll_seconds,
                    "initial_cash": 100000,
                    "max_position_pct": 0.2,
                    "stop_loss_pct": 0.02,
                    "take_profit_pct": 0.04,
                    "max_daily_loss_pct": 0.04,
                    "breakout_lookback": 12,
                    "volume_lookback": 12,
                    "volume_multiplier": 1.5,
                    "symbols": intraday_symbols or [],
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
    _write_kline(cache_dir, "TSLA.US", [index + 1 for index in range(260)])
    _write_kline(cache_dir, "AAPL.US", [index + 10 for index in range(260)])
    _write_kline(cache_dir, "SPY.US", [index + 20 for index in range(260)])
    _write_calc(cache_dir, "TSLA.US", {"pe": "40", "pb": "8", "roe": "0.20"})
    _write_calc(cache_dir, "AAPL.US", {"pe": "30", "pb": "7", "roe": "0.18"})
    return config_path


class _FakeLongbridge:
    def watchlist(self):
        return [{"name": "Default", "securities": [{"symbol": "AAPL.US"}]}]

    def market_status(self):
        return [{"market": "US", "status": "trading"}]

    def quote(self, *symbols):
        return [{"symbol": symbol, "last_done": "104"} for symbol in symbols]

    def kline(self, symbol, count=500, period="day", session="intraday"):
        rows = []
        closes = [100 + index * 0.2 for index in range(12)] + [104.0]
        for index, close in enumerate(closes):
            rows.append(
                {
                    "time": (pd.Timestamp("2026-07-07 09:30") + pd.Timedelta(minutes=5 * index)).isoformat(),
                    "open": str(close - 0.1),
                    "high": str(close + 0.1),
                    "low": str(close - 0.2),
                    "close": str(close),
                    "volume": "240" if index == len(closes) - 1 else "100",
                }
            )
        return rows


def _write_kline(cache_dir, symbol, closes):
    rows = []
    for index, close in enumerate(closes):
        rows.append(
            {
                "time": (pd.Timestamp("2024-01-01") + pd.Timedelta(days=index)).isoformat(),
                "open": str(close),
                "high": str(close + 1),
                "low": str(close - 1),
                "close": str(close),
                "volume": str(1000 + index),
            }
        )
    (cache_dir / "kline" / f"{symbol_to_filename(symbol)}.json").write_text(json.dumps(rows))


def _write_calc(cache_dir, symbol, payload):
    (cache_dir / "calc_index" / f"{symbol_to_filename(symbol)}.json").write_text(
        json.dumps([payload])
    )
