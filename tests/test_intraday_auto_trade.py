from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from stock_quant.config import AppConfig, DataConfig, IntradayConfig, StrategyConfig
from stock_quant.intraday_auto_trade import (
    auto_trade_orders_path,
    detect_longbridge_account_status,
    load_auto_trade_orders,
    load_auto_trade_state,
    maybe_execute_auto_trade,
    reconcile_auto_trade_orders,
    save_auto_trade_orders,
    save_auto_trade_state,
)
from stock_quant.longbridge_paper import LongbridgePaperTradingClient


class FakeLongbridgeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str | None, float | None]] = []
        self.account_payload = {"cash": "1000", "total_assets": "1000"}
        self.auth_status_payload = {
            "account": {
                "account_type": None,
                "name": "Paper Trading",
                "account_channel": "lb",
                "account_no": "123456789",
            }
        }
        self.positions_payload: list[dict[str, str]] = []
        self.orders_payload: list[dict[str, str]] = []
        self.auth_status_text_payload = "Token\nStatus        valid\n\nAccount       Paper Trading\nMember Id     12400432\n"

    def run_json(self, args: list[str], input_text: str | None = None, timeout: float | None = None):
        self.calls.append((args, input_text, timeout))
        if args == ["auth", "status"]:
            return self.auth_status_payload
        if args == ["account"]:
            return self.account_payload
        if args == ["positions"]:
            return self.positions_payload
        if args == ["order"]:
            return self.orders_payload
        if args[:2] == ["order", "cancel"]:
            return {"canceled": args[-1]}
        return {"order_id": "1", "args": args}

    def auth_status(self):
        self.calls.append((["auth", "status"], None, None))
        return self.auth_status_payload

    def auth_status_text(self):
        self.calls.append((["auth", "status"], None, None))
        return self.auth_status_text_payload


def test_auto_trade_state_defaults_to_disabled(tmp_path: Path) -> None:
    config = _config(tmp_path)

    state = load_auto_trade_state(config)

    assert state["enabled"] is False
    assert state["mode"] == "READ_ONLY"
    assert state["confirmed_non_simulated"] is False
    assert state["read_only"] is True


def test_detect_longbridge_account_status_masks_and_classifies_account() -> None:
    client = FakeLongbridgeClient()

    status = detect_longbridge_account_status(client)  # type: ignore[arg-type]

    assert status["account_label"] == "Paper Trading"
    assert status["account_type_label"] == "unknown"
    assert status["is_simulated"] is True
    assert status["requires_confirmation"] is False
    assert status["account_no_masked"] == "*****6789"


def test_detect_longbridge_account_status_uses_config_when_cli_account_is_empty() -> None:
    client = FakeLongbridgeClient()
    client.auth_status_payload = {"account": {"account_type": None, "name": None, "account_no": None}}
    client.auth_status_text_payload = "Token\nStatus        valid\n"

    status = detect_longbridge_account_status(
        client,  # type: ignore[arg-type]
        configured_label="Paper Trading",
        configured_is_simulated=True,
    )

    assert status["account_label"] == "Paper Trading"
    assert status["is_simulated"] is True
    assert status["requires_confirmation"] is False
    assert status["source"] == "config"


def test_auto_trade_remains_frozen_for_unknown_account(tmp_path: Path) -> None:
    config = _config(tmp_path)
    state = save_auto_trade_state(config, True)
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

    assert state["enabled"] is False
    assert result["submitted"] is False
    assert result["reason"] == "legacy_trading_frozen_for_trading_core_v2"
    assert all(call[0][:2] != ["order", "buy"] for call in client.calls)


def test_auto_trade_does_not_submit_longbridge_buy_when_enable_requested(tmp_path: Path) -> None:
    config = _config(tmp_path)
    client = FakeLongbridgeClient()
    save_auto_trade_state(config, True, account_status=detect_longbridge_account_status(client))  # type: ignore[arg-type]
    client.calls.clear()

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

    assert result["submitted"] is False
    assert result["mode"] == "READ_ONLY"
    assert result["reason"] == "legacy_trading_frozen_for_trading_core_v2"
    assert client.calls == []
    assert load_auto_trade_orders(config) == []


def test_auto_trade_does_not_submit_longbridge_sell_when_enable_requested(tmp_path: Path) -> None:
    config = _config(tmp_path)
    client = FakeLongbridgeClient()
    save_auto_trade_state(config, True, account_status=detect_longbridge_account_status(client))  # type: ignore[arg-type]
    client.positions_payload = [{"symbol": "AAPL.US", "quantity": "7", "avg_price": "101"}]
    client.calls.clear()

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

    assert result["submitted"] is False
    assert result["mode"] == "READ_ONLY"
    assert result["reason"] == "legacy_trading_frozen_for_trading_core_v2"
    assert client.calls == []


def test_reconcile_auto_trade_orders_cannot_cancel_stale_pending_order(tmp_path: Path) -> None:
    config = _config(tmp_path)
    client = FakeLongbridgeClient()
    submitted_at = (datetime.now() - timedelta(seconds=300)).isoformat(timespec="seconds")
    save_auto_trade_orders(
        config,
        [
            {
                "order_id": "old-1",
                "status": "pending",
                "symbol": "AAPL.US",
                "side": "BUY",
                "quantity": 1,
                "submitted_at": submitted_at,
                "timeout_seconds": 120,
            }
        ],
    )
    client.orders_payload = [{"order_id": "old-1", "status": "submitted"}]

    records = reconcile_auto_trade_orders(config, LongbridgePaperTradingClient(client))  # type: ignore[arg-type]

    assert records[0]["status"] == "cancel_failed"
    assert "READ_ONLY" in records[0]["cancel_error"]
    assert not any(call[0][:2] == ["order", "cancel"] for call in client.calls)
    persisted = json.loads(auto_trade_orders_path(config).read_text())
    assert persisted[0]["status"] == "cancel_failed"


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
