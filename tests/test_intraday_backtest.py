from __future__ import annotations

from pathlib import Path

import pandas as pd

from stock_quant.config import IntradayConfig
from stock_quant.intraday import market_is_open, normalize_intraday_kline
from stock_quant.intraday_backtest import apply_slippage, intraday_backtest
from stock_quant.intraday_metrics import max_consecutive_losses, max_drawdown


def _config() -> IntradayConfig:
    return IntradayConfig(
        enabled=True,
        period="5m",
        session="intraday",
        poll_seconds=60,
        initial_cash=100_000,
        max_position_pct=0.2,
        stop_loss_pct=0.02,
        take_profit_pct=0.20,
        max_daily_loss_pct=0.04,
        breakout_lookback=3,
        volume_lookback=3,
        volume_multiplier=1.5,
        symbols=["TEST.US"],
        data_dir=Path("."),
        commission_bps=0.0,
        slippage_bps=0.0,
    )


def _bars(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    start = pd.Timestamp("2024-01-02 09:30")
    volumes = volumes or [100.0] * len(closes)
    rows = []
    for index, close in enumerate(closes):
        timestamp = start + pd.Timedelta(minutes=5 * index)
        rows.append(
            {
                "date": timestamp,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": volumes[index],
            }
        )
    return pd.DataFrame(rows)


def test_normalize_intraday_kline_converts_utc_to_market_time() -> None:
    frame = normalize_intraday_kline(
        [
            {
                "date": "2024-01-02T14:30:00Z",
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100.5,
                "volume": 1000,
            }
        ],
        "TEST.US",
    )

    assert str(frame.iloc[0]["date"]) == "2024-01-02 09:30:00"


def test_market_is_open_parses_nested_us_status() -> None:
    assert market_is_open({"markets": [{"market": "US", "status": "Open"}]}, "US") is True
    assert market_is_open({"markets": [{"market": "US", "status": "Closed"}]}, "US") is False


def test_intraday_backtest_buys_on_next_bar_after_breakout() -> None:
    frame = _bars(
        [100.0, 100.4, 100.8, 102.0, 102.2],
        [100.0, 100.0, 100.0, 300.0, 100.0],
    )

    result = intraday_backtest({"TEST.US": frame}, _config())

    buys = [trade for trade in result["trades"] if trade["side"] == "BUY"]
    assert len(buys) == 1
    assert buys[0]["timestamp"] == "2024-01-02T09:50:00"
    assert buys[0]["created_at"] == "2024-01-02T09:45:00"
    assert result["metrics"]["final_equity"] > 0


def test_intraday_backtest_sells_on_next_bar_after_stop_loss() -> None:
    frame = _bars(
        [100.0, 100.4, 100.8, 102.0, 102.2, 99.0, 98.5],
        [100.0, 100.0, 100.0, 300.0, 100.0, 100.0, 100.0],
    )

    result = intraday_backtest({"TEST.US": frame}, _config())

    sells = [trade for trade in result["trades"] if trade["side"] == "SELL"]
    assert len(sells) == 1
    assert sells[0]["reason"] == "stop_loss"
    assert sells[0]["timestamp"] == "2024-01-02T10:00:00"
    assert sells[0]["realized_pnl"] < 0


def test_intraday_backtest_does_not_use_same_bar_for_execution() -> None:
    frame = _bars(
        [100.0, 100.4, 100.8, 102.0],
        [100.0, 100.0, 100.0, 300.0],
    )

    result = intraday_backtest({"TEST.US": frame}, _config())

    assert result["trades"] == []


def test_apply_slippage_moves_prices_against_trade() -> None:
    assert apply_slippage(100.0, "BUY", 10.0) == 100.1
    assert apply_slippage(100.0, "SELL", 10.0) == 99.9


def test_intraday_metrics_helpers() -> None:
    equity = pd.Series([100.0, 120.0, 90.0, 110.0])
    assert round(max_drawdown(equity), 4) == -0.25
    assert max_consecutive_losses([1.0, -1.0, -2.0, 3.0, -1.0]) == 2
