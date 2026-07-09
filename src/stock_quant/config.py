from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path


@dataclass(frozen=True)
class DataConfig:
    cache_dir: Path
    history_count: int


@dataclass(frozen=True)
class StrategyConfig:
    top_n: int
    rebalance: str
    momentum_window: int
    volatility_window: int
    risk_ma_window: int
    full_exposure: float
    defensive_exposure: float
    transaction_cost_bps: float


@dataclass(frozen=True)
class IntradayConfig:
    enabled: bool
    period: str
    session: str
    poll_seconds: int
    initial_cash: float
    max_position_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    max_daily_loss_pct: float
    breakout_lookback: int
    volume_lookback: int
    volume_multiplier: float
    symbols: list[str]
    history_count: int = 500
    data_dir: Path = Path("data/intraday/kline")
    commission_bps: float = 0.0
    slippage_bps: float = 0.0
    order_timeout_seconds: int = 120


@dataclass(frozen=True)
class NotificationConfig:
    feishu_webhook_url: str = ""


@dataclass(frozen=True)
class LongbridgeAccountConfig:
    account_label: str = ""
    is_simulated_account: bool | None = None


@dataclass(frozen=True)
class AppConfig:
    benchmark: str
    universe: list[str]
    data: DataConfig
    strategy: StrategyConfig
    intraday: IntradayConfig
    factor_weights: dict[str, float]
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    longbridge_account: LongbridgeAccountConfig = field(default_factory=LongbridgeAccountConfig)


def _resolve_config_path(config_path: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (config_path.parent / ".." / path).resolve()


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    raw = json.loads(config_path.read_text())
    data = raw["data"]
    strategy = raw["strategy"]
    intraday = raw.get("intraday", {})
    notifications = raw.get("notifications", {})
    longbridge_account = raw.get("longbridge_account", {})
    return AppConfig(
        benchmark=raw["benchmark"],
        universe=list(raw["universe"]),
        data=DataConfig(
            cache_dir=_resolve_config_path(config_path, data["cache_dir"]),
            history_count=int(data["history_count"]),
        ),
        strategy=StrategyConfig(
            top_n=int(strategy["top_n"]),
            rebalance=strategy["rebalance"],
            momentum_window=int(strategy["momentum_window"]),
            volatility_window=int(strategy["volatility_window"]),
            risk_ma_window=int(strategy["risk_ma_window"]),
            full_exposure=float(strategy["full_exposure"]),
            defensive_exposure=float(strategy["defensive_exposure"]),
            transaction_cost_bps=float(strategy["transaction_cost_bps"]),
        ),
        intraday=IntradayConfig(
            enabled=bool(intraday.get("enabled", True)),
            period=str(intraday.get("period", "5m")),
            session=str(intraday.get("session", "intraday")),
            poll_seconds=int(intraday.get("poll_seconds", 60)),
            initial_cash=float(intraday.get("initial_cash", 100000)),
            max_position_pct=float(intraday.get("max_position_pct", 0.20)),
            stop_loss_pct=float(intraday.get("stop_loss_pct", 0.02)),
            take_profit_pct=float(intraday.get("take_profit_pct", 0.04)),
            max_daily_loss_pct=float(intraday.get("max_daily_loss_pct", 0.04)),
            breakout_lookback=int(intraday.get("breakout_lookback", 12)),
            volume_lookback=int(intraday.get("volume_lookback", 12)),
            volume_multiplier=float(intraday.get("volume_multiplier", 1.5)),
            symbols=[str(symbol).upper() for symbol in intraday.get("symbols", [])],
            history_count=int(intraday.get("history_count", 500)),
            data_dir=_resolve_config_path(config_path, intraday.get("data_dir", "data/intraday/kline")),
            commission_bps=float(intraday.get("commission_bps", 0.0)),
            slippage_bps=float(intraday.get("slippage_bps", 0.0)),
            order_timeout_seconds=int(intraday.get("order_timeout_seconds", 120)),
        ),
        factor_weights={key: float(value) for key, value in raw["factor_weights"].items()},
        notifications=NotificationConfig(
            feishu_webhook_url=str(notifications.get("feishu_webhook_url", "")),
        ),
        longbridge_account=LongbridgeAccountConfig(
            account_label=str(longbridge_account.get("account_label", "")),
            is_simulated_account=_optional_bool(longbridge_account.get("is_simulated_account")),
        ),
    )


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    return bool(value)
