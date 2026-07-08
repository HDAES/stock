import json

import pandas as pd
import pytest

from stock_quant.config import IntradayConfig
from stock_quant.intraday import evaluate_trend_signal, market_is_open, normalize_intraday_kline
from stock_quant.paper import PaperPortfolio


def test_trend_breakout_returns_buy():
    frame = normalize_intraday_kline(_bars([100 + index * 0.2 for index in range(12)] + [104.0], 240), "AAPL.US")

    signal = evaluate_trend_signal("AAPL.US", frame, _config())

    assert signal.action == "BUY"
    assert signal.reason == "trend_breakout"


def test_trend_breakout_missing_volume_returns_hold():
    frame = normalize_intraday_kline(_bars([100 + index * 0.2 for index in range(12)] + [104.0], 100), "AAPL.US")

    signal = evaluate_trend_signal("AAPL.US", frame, _config())

    assert signal.action == "HOLD"


@pytest.mark.parametrize(
    ("latest_close", "reason"),
    [
        (98.0, "stop_loss"),
        (104.0, "take_profit"),
    ],
)
def test_position_stop_loss_and_take_profit_return_sell(latest_close, reason):
    closes = [100 + index * 0.05 for index in range(12)] + [latest_close]
    frame = normalize_intraday_kline(_bars(closes, 240), "AAPL.US")

    signal = evaluate_trend_signal(
        "AAPL.US",
        frame,
        _config(),
        has_position=True,
        entry_price=100.0,
    )

    assert signal.action == "SELL"
    assert signal.reason == reason


def test_daily_loss_stop_blocks_new_buys():
    frame = normalize_intraday_kline(_bars([100 + index * 0.2 for index in range(12)] + [104.0], 240), "AAPL.US")

    signal = evaluate_trend_signal("AAPL.US", frame, _config(), daily_stop=True)

    assert signal.action == "HOLD"
    assert signal.reason == "daily_loss_limit_reached"


def test_paper_portfolio_uses_max_position_pct(tmp_path):
    portfolio = PaperPortfolio.empty(100000, "2026-07-07")

    trade = portfolio.buy("AAPL.US", 100.0, "2026-07-07T10:00:00", 0.20, "trend_breakout")

    assert trade["quantity"] == 200
    assert portfolio.cash == 80000
    assert portfolio.positions["AAPL.US"].avg_price == 100.0


def test_paper_portfolio_daily_stop_after_loss():
    portfolio = PaperPortfolio.empty(100000, "2026-07-07")
    portfolio.buy("AAPL.US", 100.0, "2026-07-07T10:00:00", 0.20, "trend_breakout")
    portfolio.mark({"AAPL.US": 75.0})

    assert portfolio.refresh_daily_stop(0.04) is True


def test_market_status_parser_detects_us_open():
    payload = [{"market": "US", "status": "trading"}]

    assert market_is_open(payload, "US") is True


def _config():
    return IntradayConfig(
        enabled=True,
        period="5m",
        session="intraday",
        poll_seconds=60,
        initial_cash=100000,
        max_position_pct=0.20,
        stop_loss_pct=0.02,
        take_profit_pct=0.04,
        max_daily_loss_pct=0.04,
        breakout_lookback=12,
        volume_lookback=12,
        volume_multiplier=1.5,
        symbols=[],
    )


def _bars(closes, latest_volume):
    rows = []
    for index, close in enumerate(closes):
        volume = latest_volume if index == len(closes) - 1 else 100
        rows.append(
            {
                "time": (pd.Timestamp("2026-07-07 09:30") + pd.Timedelta(minutes=5 * index)).isoformat(),
                "open": str(close - 0.1),
                "high": str(close + 0.1),
                "low": str(close - 0.2),
                "close": str(close),
                "volume": str(volume),
            }
        )
    return rows
