from __future__ import annotations

from pathlib import Path

from stock_quant.config import AppConfig, DataConfig, IntradayConfig, StrategyConfig
from stock_quant.intraday_auto_trade import load_auto_trade_state, maybe_execute_auto_trade, save_auto_trade_state


class FakeLongbridgeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str | None, float | None]] = []

    def run_json(self, args: list[str], input_text: str | None = None, timeout: float | None = None):
        self.calls.append((args, input_text, timeout))
        return {"order_id": "1", "args": args}


def test_auto_trade_state_defaults_to_disabled(tmp_path: Path) -> None:
    config = _config(tmp_path)

    state = load_auto_trade_state(config)

    assert state["enabled"] is False
    assert state["mode"] == "longbridge_paper"


def test_auto_trade_submits_longbridge_order_when_enabled(tmp_path: Path) -> None:
    config = _config(tmp_path)
    save_auto_trade_state(config, True)
    client = FakeLongbridgeClient()

    result = maybe_execute_auto_trade(
        config,
        client,  # type: ignore[arg-type]
        {
            "symbol": "AAPL.US",
            "action": "BUY",
            "execution_price": 100.123,
            "timestamp": "2026-01-01T09:35:00",
            "bar_id": "2026-01-01T09:30:00",
        },
        {"quantity": 2, "price": 100.123},
    )

    assert result["submitted"] is True
    assert client.calls[0][0] == ["order", "buy", "AAPL.US", "2", "--price", "100.12"]
    assert client.calls[0][1] == "y\n"


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        benchmark="SPY.US",
        universe=["AAPL.US"],
        data=DataConfig(cache_dir=tmp_path / "cache", history_count=500),
        strategy=StrategyConfig(
            top_n=1,
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
            initial_cash=100000,
            max_position_pct=0.2,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
            max_daily_loss_pct=0.04,
            breakout_lookback=12,
            volume_lookback=12,
            volume_multiplier=1.5,
            symbols=["AAPL.US"],
            data_dir=tmp_path / "intraday" / "kline",
        ),
        factor_weights={"momentum": 1.0},
    )
