from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from stock_quant.config import AppConfig, DataConfig, IntradayConfig, StrategyConfig
from stock_quant.intraday_auto_trade import (
    auto_trade_state_path,
    load_auto_trade_state,
    maybe_execute_auto_trade,
    save_auto_trade_state,
)
from stock_quant.longbridge_paper import (
    LegacyTradingReadOnlyError,
    LongbridgePaperTradingClient,
    PaperOrderRequest,
)
from stock_quant.web.api import create_app


class FakeLongbridgeClient:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run_json(
        self,
        args: list[str],
        input_text: str | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        del input_text, timeout
        self.calls.append(args)
        return {"args": args}

    def auth_status(self) -> dict[str, Any]:
        return {
            "account": {
                "account_type": "paper",
                "name": "Paper Trading",
                "account_channel": "lb",
                "account_no": "12345678",
            }
        }

    def auth_status_text(self) -> str:
        return "Account Paper Trading"


def make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        benchmark="SPY.US",
        universe=["AAPL.US"],
        data=DataConfig(cache_dir=tmp_path / "cache", history_count=100),
        strategy=StrategyConfig(
            top_n=1,
            rebalance="monthly",
            momentum_window=60,
            volatility_window=20,
            risk_ma_window=200,
            full_exposure=1.0,
            defensive_exposure=0.0,
            transaction_cost_bps=5.0,
        ),
        intraday=IntradayConfig(
            enabled=True,
            period="5m",
            session="intraday",
            poll_seconds=60,
            initial_cash=100000.0,
            max_position_pct=0.2,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
            max_daily_loss_pct=0.04,
            breakout_lookback=12,
            volume_lookback=12,
            volume_multiplier=1.5,
            symbols=["AAPL.US"],
        ),
        factor_weights={"momentum": 1.0},
    )


def write_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "benchmark": "SPY.US",
                "universe": ["AAPL.US"],
                "data": {"cache_dir": "data/cache", "history_count": 100},
                "strategy": {
                    "top_n": 1,
                    "rebalance": "monthly",
                    "momentum_window": 60,
                    "volatility_window": 20,
                    "risk_ma_window": 200,
                    "full_exposure": 1.0,
                    "defensive_exposure": 0.0,
                    "transaction_cost_bps": 5.0,
                },
                "intraday": {
                    "enabled": True,
                    "period": "5m",
                    "session": "intraday",
                    "poll_seconds": 60,
                    "initial_cash": 100000,
                    "max_position_pct": 0.2,
                    "stop_loss_pct": 0.02,
                    "take_profit_pct": 0.04,
                    "max_daily_loss_pct": 0.04,
                    "breakout_lookback": 12,
                    "volume_lookback": 12,
                    "volume_multiplier": 1.5,
                    "symbols": ["AAPL.US"],
                },
                "factor_weights": {"momentum": 1.0},
                "longbridge_account": {
                    "account_label": "Paper Trading",
                    "is_simulated_account": True,
                },
            }
        ),
        encoding="utf-8",
    )


def test_stale_enabled_state_is_forced_off_and_persisted(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    path = auto_trade_state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "enabled": True,
                "mode": "longbridge_paper",
                "confirmed_non_simulated": True,
            }
        ),
        encoding="utf-8",
    )

    state = load_auto_trade_state(config)

    assert state["enabled"] is False
    assert state["mode"] == "READ_ONLY"
    assert state["read_only"] is True
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["enabled"] is False
    assert persisted["mode"] == "READ_ONLY"
    assert persisted["confirmed_non_simulated"] is False


def test_auto_trade_cannot_be_enabled_or_execute(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    state = save_auto_trade_state(config, True, confirmed_non_simulated=True)
    result = maybe_execute_auto_trade(
        config,
        FakeLongbridgeClient(),
        {"symbol": "aapl.us", "action": "BUY"},
    )

    assert state["enabled"] is False
    assert state["mode"] == "READ_ONLY"
    assert result == {
        "enabled": False,
        "mode": "READ_ONLY",
        "submitted": False,
        "symbol": "AAPL.US",
        "action": "BUY",
        "reason": "legacy_trading_frozen_for_trading_core_v2",
        "read_only": True,
    }


def test_broker_reads_remain_available_but_writes_are_blocked() -> None:
    raw_client = FakeLongbridgeClient()
    client = LongbridgePaperTradingClient(raw_client)  # type: ignore[arg-type]

    assert client.account() == {"args": ["account"]}
    assert client.positions() == {"args": ["positions"]}
    assert client.orders() == {"args": ["order"]}
    raw_client.calls.clear()

    with pytest.raises(LegacyTradingReadOnlyError, match="READ_ONLY"):
        client.submit_order(PaperOrderRequest(symbol="AAPL.US", side="buy", quantity=1))
    with pytest.raises(LegacyTradingReadOnlyError, match="READ_ONLY"):
        client.cancel_order("order-1")

    assert raw_client.calls == []


def test_legacy_write_apis_are_blocked(tmp_path: Path) -> None:
    config_path = tmp_path / "config" / "default.json"
    write_config(config_path)
    raw_client = FakeLongbridgeClient()
    app = create_app(config_path=config_path, longbridge_client=raw_client, auto_intraday=False)  # type: ignore[arg-type]

    with TestClient(app) as client:
        auto_trade = client.post(
            "/api/intraday/auto-trade",
            json={"enabled": True, "confirm_non_simulated": True},
        )
        submit = client.post(
            "/api/longbridge-paper/order",
            json={"symbol": "AAPL.US", "side": "buy", "quantity": 1},
        )
        cancel = client.post(
            "/api/longbridge-paper/cancel",
            json={"order_id": "order-1"},
        )

    assert auto_trade.status_code == 200
    assert auto_trade.json()["enabled"] is False
    assert auto_trade.json()["mode"] == "READ_ONLY"
    assert submit.status_code == 502
    assert "READ_ONLY" in submit.json()["detail"]
    assert cancel.status_code == 502
    assert "READ_ONLY" in cancel.json()["detail"]
    assert raw_client.calls == []
