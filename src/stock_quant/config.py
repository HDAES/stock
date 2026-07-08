from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
class IntradayRiskConfig:
    default: dict[str, float] = field(default_factory=dict)
    profiles: dict[str, dict[str, float]] = field(default_factory=dict)
    symbols: dict[str, str] = field(default_factory=dict)
    overrides: dict[str, dict[str, float]] = field(default_factory=dict)
    enable_atr: bool = True
    atr_window: int = 14
    atr_stop_multiplier: float = 1.2
    take_profit_r_multiple: float = 2.0
    min_stop_loss_pct: float = 0.006
    max_stop_loss_pct: float = 0.02
    enable_trailing_stop: bool = True


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
    risk: IntradayRiskConfig = field(default_factory=IntradayRiskConfig)


@dataclass(frozen=True)
class AppConfig:
    benchmark: str
    universe: list[str]
    data: DataConfig
    strategy: StrategyConfig
    intraday: IntradayConfig
    factor_weights: dict[str, float]


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
    stop_loss_pct = float(intraday.get("stop_loss_pct", 0.02))
    take_profit_pct = float(intraday.get("take_profit_pct", 0.04))
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
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            max_daily_loss_pct=float(intraday.get("max_daily_loss_pct", 0.04)),
            breakout_lookback=int(intraday.get("breakout_lookback", 12)),
            volume_lookback=int(intraday.get("volume_lookback", 12)),
            volume_multiplier=float(intraday.get("volume_multiplier", 1.5)),
            symbols=[str(symbol).upper() for symbol in intraday.get("symbols", [])],
            history_count=int(intraday.get("history_count", 500)),
            data_dir=_resolve_config_path(config_path, intraday.get("data_dir", "data/intraday/kline")),
            commission_bps=float(intraday.get("commission_bps", 0.0)),
            slippage_bps=float(intraday.get("slippage_bps", 0.0)),
            risk=_load_intraday_risk(intraday.get("risk", {}), stop_loss_pct, take_profit_pct),
        ),
        factor_weights={key: float(value) for key, value in raw["factor_weights"].items()},
    )


def _load_intraday_risk(
    payload: Any,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> IntradayRiskConfig:
    risk = payload if isinstance(payload, dict) else {}
    default_values = {
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": take_profit_pct,
        "trailing_stop_pct": float(risk.get("trailing_stop_pct", 0.0) or 0.0),
    }
    default_values.update(_float_dict(risk.get("default")))

    return IntradayRiskConfig(
        default=default_values,
        profiles={
            str(name): _float_dict(values)
            for name, values in _dict_payload(risk.get("profiles")).items()
        },
        symbols={
            str(symbol).upper(): str(profile)
            for symbol, profile in _dict_payload(risk.get("symbols")).items()
        },
        overrides={
            str(symbol).upper(): _float_dict(values)
            for symbol, values in _dict_payload(risk.get("overrides")).items()
        },
        enable_atr=bool(risk.get("enable_atr", True)),
        atr_window=int(risk.get("atr_window", 14)),
        atr_stop_multiplier=float(risk.get("atr_stop_multiplier", 1.2)),
        take_profit_r_multiple=float(risk.get("take_profit_r_multiple", 2.0)),
        min_stop_loss_pct=float(risk.get("min_stop_loss_pct", 0.006)),
        max_stop_loss_pct=float(risk.get("max_stop_loss_pct", 0.02)),
        enable_trailing_stop=bool(risk.get("enable_trailing_stop", True)),
    )


def _dict_payload(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float_dict(value: Any) -> dict[str, float]:
    result: dict[str, float] = {}
    if not isinstance(value, dict):
        return result
    for key, raw in value.items():
        try:
            result[str(key)] = float(raw)
        except (TypeError, ValueError):
            continue
    return result
