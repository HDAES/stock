from __future__ import annotations

from pathlib import Path

from stock_quant.config import AppConfig, DataConfig, IntradayConfig, StrategyConfig
from stock_quant.intraday_auto_trade import load_auto_trade_state, maybe_execute_auto_trade, save_auto_trade_state


class FakeLongbridgeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str | None, float | None]] = []
        self.account_payload = {"cash": "1000", "total_assets": "1000"}
        self.positions_payload: list[dict[str, str]] = []

    def run_json(self, args: list[str], input_text: str | None = None, timeout: float | None = None):
        self.calls.append((args, input_text, timeout))
        if args == ["account"]:
            return self.account_payload
        if args == ["positions"]:
            return self.positions_payload
        return {"order_id": "1", "args": args}


def test_auto_trade_state_defaults_to_disabled(tmp_path: Path) -> None:
    config = _config(tmp_path)

    state = load_auto_trade_state(config)

    assert state["enabled"] is False
    assert state["mode"] == "longbridge_paper"


def test_auto_trade_submits_longbridge_buy_from_broker_account_when_enabled(tmp_path: Path) -> None:
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
    )

    assert result["submitted"] is True
    assert result["quantity"] == 1
    assert client.calls[-1][0] == ["order", "buy", "AAPL.US", "1", "--price", "100.12"]
    assert client.calls[-1][1] == "y\n"


def test_auto_trade_submits_longbridge_sell_from_broker_position(tmp_path: Path) -> None:
    config = _config(tmp_path)
    save_auto_trade_state(config, True)
    client = FakeLongbridgeClient()
    client.positions_payload = [{"symbol": "AAPL.US", "quantity": "7", "avg_price": "101"}]

    result = maybe_execute_auto_trade(
        config,
        client,  # type: ignore[arg-type]
        {
            "symbol": "AAPL.US",
            "action": "SELL",
            "execution_price": 99.99,
            "timestamp": "2026-01-01T09:35:00",
            "bar_id": "2026-01-01T09:30:00",
        },
    )

    assert result["submitted"] is True
    assert result["quantity"] == 7
    assert client.calls[-1][0] == ["order", "sell", "AAPL.US", "7", "--price", "99.99"]


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
