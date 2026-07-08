from __future__ import annotations

import json
from pathlib import Path

from stock_quant.config import AppConfig, DataConfig, IntradayConfig, StrategyConfig
from stock_quant.intraday_data import (
    cached_intraday_symbols,
    fetch_intraday_history,
    intraday_history_path,
    merge_intraday_history,
    resolve_intraday_backtest_symbols,
    resolve_intraday_symbols,
)


class FakeClient:
    def __init__(self) -> None:
        self.kline_calls: list[tuple[str, int, str, str]] = []

    def kline(
        self,
        symbol: str,
        count: int = 500,
        period: str = "5m",
        session: str = "intraday",
    ) -> list[dict]:
        self.kline_calls.append((symbol, count, period, session))
        return [
            {
                "date": "2024-01-02 09:30:00",
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100.5,
                "volume": 1000,
            }
        ]

    def watchlist(self) -> dict:
        return {
            "items": [
                {"symbol": "MSFT.US"},
                {"security_code": "AAPL.US"},
                {"symbol": "MSFT.US"},
            ]
        }


class EmptyWatchlistClient(FakeClient):
    def watchlist(self) -> dict:
        return {"items": []}


def _config() -> AppConfig:
    return AppConfig(
        benchmark="SPY.US",
        universe=["NVDA.US", "AAPL.US"],
        data=DataConfig(cache_dir=Path("data/cache"), history_count=500),
        strategy=StrategyConfig(
            top_n=10,
            rebalance="M",
            momentum_window=60,
            volatility_window=60,
            risk_ma_window=200,
            full_exposure=1.0,
            defensive_exposure=0.4,
            transaction_cost_bps=10,
        ),
        intraday=IntradayConfig(
            enabled=True,
            period="5m",
            session="intraday",
            poll_seconds=60,
            initial_cash=100_000,
            max_position_pct=0.2,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
            max_daily_loss_pct=0.04,
            breakout_lookback=12,
            volume_lookback=12,
            volume_multiplier=1.5,
            symbols=["TSLA.US"],
        ),
        factor_weights={"momentum": 1.0},
    )


def test_resolve_intraday_symbols_prefers_explicit_symbols() -> None:
    symbols = resolve_intraday_symbols(
        _config(),
        explicit_symbols=["msft.us", "AAPL.US", "MSFT.US"],
        client=FakeClient(),
    )

    assert symbols == ["AAPL.US", "MSFT.US"]


def test_resolve_intraday_symbols_uses_watchlist_before_config() -> None:
    symbols = resolve_intraday_symbols(_config(), client=FakeClient())

    assert symbols == ["AAPL.US", "MSFT.US"]


def test_resolve_intraday_symbols_falls_back_to_config_symbols() -> None:
    symbols = resolve_intraday_symbols(_config(), client=EmptyWatchlistClient())

    assert symbols == ["TSLA.US"]


def test_cached_intraday_symbols_reads_existing_period_files(tmp_path: Path) -> None:
    intraday_history_path(tmp_path, "AAPL.US", "5m").write_text("[]")
    intraday_history_path(tmp_path, "MSFT.US", "5m").write_text("[]")
    intraday_history_path(tmp_path, "TSLA.US", "1m").write_text("[]")

    assert cached_intraday_symbols(tmp_path, "5m") == ["AAPL.US", "MSFT.US"]


def test_resolve_intraday_backtest_symbols_prefers_cached_files(tmp_path: Path) -> None:
    intraday_history_path(tmp_path, "MSFT.US", "5m").write_text("[]")

    symbols = resolve_intraday_backtest_symbols(_config(), tmp_path)

    assert symbols == ["MSFT.US"]


def test_resolve_intraday_backtest_symbols_keeps_explicit_symbols_strict(tmp_path: Path) -> None:
    intraday_history_path(tmp_path, "MSFT.US", "5m").write_text("[]")

    symbols = resolve_intraday_backtest_symbols(_config(), tmp_path, explicit_symbols=["AAPL.US"])

    assert symbols == ["AAPL.US"]


def test_fetch_intraday_history_writes_symbol_period_files(tmp_path: Path) -> None:
    client = FakeClient()

    cached = fetch_intraday_history(
        tmp_path,
        ["AAPL.US"],
        count=120,
        period="5m",
        session="intraday",
        client=client,
    )

    assert cached["AAPL.US"] == intraday_history_path(tmp_path, "AAPL.US", "5m")
    assert cached["AAPL.US"].exists()
    assert client.kline_calls == [("AAPL.US", 120, "5m", "intraday")]


def test_fetch_intraday_history_skips_existing_cache_without_refresh(tmp_path: Path) -> None:
    path = intraday_history_path(tmp_path, "AAPL.US", "5m")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[]")
    client = FakeClient()

    fetch_intraday_history(
        tmp_path,
        ["AAPL.US"],
        count=120,
        period="5m",
        session="intraday",
        refresh=False,
        client=client,
    )

    assert client.kline_calls == []


def test_merge_intraday_history_dedupes_sorts_and_filters_regular_session(tmp_path: Path) -> None:
    path = intraday_history_path(tmp_path, "AAPL.US", "5m")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [
                {
                    "date": "2024-01-02T09:35:00",
                    "open": 101,
                    "high": 102,
                    "low": 100,
                    "close": 101.5,
                    "volume": 1000,
                },
                {
                    "date": "2024-01-02T16:30:00",
                    "open": 99,
                    "high": 100,
                    "low": 98,
                    "close": 99.5,
                    "volume": 100,
                },
            ]
        )
    )

    merge_intraday_history(
        tmp_path,
        "AAPL.US",
        "5m",
        [
            {
                "date": "2024-01-02T09:30:00",
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100.5,
                "volume": 800,
            },
            {
                "date": "2024-01-02T09:35:00",
                "open": 102,
                "high": 103,
                "low": 101,
                "close": 102.5,
                "volume": 1200,
            },
        ],
    )

    rows = json.loads(path.read_text())
    assert [row["date"] for row in rows] == ["2024-01-02T09:30:00", "2024-01-02T09:35:00"]
    assert rows[-1]["close"] == 102.5
