from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .config import IntradayConfig


SYMBOL_PATTERN = re.compile(r"^[A-Z0-9.\-]+\.US$")


@dataclass(frozen=True)
class IntradaySignal:
    symbol: str
    action: str
    reason: str
    price: float | None
    timestamp: str | None
    indicators: dict[str, float | None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "reason": self.reason,
            "price": self.price,
            "timestamp": self.timestamp,
            "indicators": self.indicators,
        }


def normalize_intraday_kline(payload: list[dict], symbol: str) -> pd.DataFrame:
    frame = pd.DataFrame(payload)
    if frame.empty:
        raise ValueError(f"No intraday kline data for {symbol}")

    date_col = next((col for col in ("date", "time", "timestamp") if col in frame.columns), None)
    if date_col is None:
        raise ValueError(f"Intraday kline payload for {symbol} has no date/time column")

    frame["date"] = pd.to_datetime(frame[date_col]).dt.tz_localize(None)
    for column in ("open", "high", "low", "close", "volume"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    if "close" not in frame.columns:
        close_col = next((col for col in ("last", "last_done", "price") if col in frame.columns), None)
        if close_col is None:
            raise ValueError(f"Intraday kline payload for {symbol} has no close column")
        frame["close"] = pd.to_numeric(frame[close_col], errors="coerce")

    for column in ("open", "high", "low"):
        if column not in frame.columns:
            frame[column] = frame["close"]
    if "volume" not in frame.columns:
        frame["volume"] = 0.0

    frame["symbol"] = symbol
    return frame.sort_values("date").dropna(subset=["close"]).reset_index(drop=True)


def add_intraday_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    enriched = frame.copy()
    close = enriched["close"].astype(float)
    volume = enriched["volume"].fillna(0).astype(float)
    cumulative_volume = volume.cumsum()
    cumulative_value = (close * volume).cumsum()
    enriched["vwap"] = cumulative_value.divide(cumulative_volume.where(cumulative_volume > 0))
    enriched["ema9"] = close.ewm(span=9, adjust=False).mean()
    enriched["ema21"] = close.ewm(span=21, adjust=False).mean()
    return enriched


def evaluate_trend_signal(
    symbol: str,
    frame: pd.DataFrame,
    config: IntradayConfig,
    has_position: bool = False,
    entry_price: float | None = None,
    daily_stop: bool = False,
    market_open: bool = True,
) -> IntradaySignal:
    enriched = add_intraday_indicators(frame)
    required = max(config.breakout_lookback, config.volume_lookback) + 1
    if len(enriched) < required:
        return _signal(symbol, "HOLD", "insufficient_intraday_history", enriched)

    latest = enriched.iloc[-1]
    previous_breakout = enriched.iloc[-config.breakout_lookback - 1 : -1]
    previous_volume = enriched.iloc[-config.volume_lookback - 1 : -1]
    price = _safe_float(latest["close"])
    vwap = _safe_float(latest["vwap"])
    ema9 = _safe_float(latest["ema9"])
    ema21 = _safe_float(latest["ema21"])
    previous_high = _safe_float(previous_breakout["high"].max())
    average_volume = _safe_float(previous_volume["volume"].mean())
    latest_volume = _safe_float(latest["volume"])

    if price is None:
        return _signal(symbol, "HOLD", "missing_latest_price", enriched)

    if has_position:
        if entry_price and price <= entry_price * (1.0 - config.stop_loss_pct):
            return _signal(symbol, "SELL", "stop_loss", enriched)
        if entry_price and price >= entry_price * (1.0 + config.take_profit_pct):
            return _signal(symbol, "SELL", "take_profit", enriched)
        if ema21 is not None and price < ema21:
            return _signal(symbol, "SELL", "close_below_ema21", enriched)
        if vwap is not None and price < vwap:
            return _signal(symbol, "SELL", "close_below_vwap", enriched)
        return _signal(symbol, "HOLD", "position_held", enriched)

    if not market_open:
        return _signal(symbol, "HOLD", "market_closed", enriched)
    if daily_stop:
        return _signal(symbol, "HOLD", "daily_loss_limit_reached", enriched)

    volume_ok = (
        latest_volume is not None
        and average_volume is not None
        and average_volume > 0
        and latest_volume >= average_volume * config.volume_multiplier
    )
    breakout_ok = previous_high is not None and price > previous_high
    trend_ok = vwap is not None and ema9 is not None and ema21 is not None and price > vwap and ema9 > ema21
    if breakout_ok and trend_ok and volume_ok:
        return _signal(symbol, "BUY", "trend_breakout", enriched)
    return _signal(symbol, "HOLD", "no_breakout_setup", enriched)


def extract_watchlist_symbols(payload: Any) -> list[str]:
    symbols: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in {"symbol", "security_code", "code"} and isinstance(item, str):
                    normalized = item.upper()
                    if SYMBOL_PATTERN.match(normalized):
                        symbols.add(normalized)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str):
            normalized = value.upper()
            if SYMBOL_PATTERN.match(normalized):
                symbols.add(normalized)

    visit(payload)
    return sorted(symbols)


def market_is_open(payload: Any, market: str = "US") -> bool:
    statuses: list[str] = []

    def visit(value: Any, parent_market: str | None = None) -> None:
        if isinstance(value, dict):
            current_market = parent_market
            for key, item in value.items():
                if key.lower() in {"market", "region", "exchange"} and isinstance(item, str):
                    current_market = item.upper()
            for key, item in value.items():
                if key.lower() in {"status", "trade_status", "market_status"} and isinstance(item, str):
                    if current_market is None or market.upper() in current_market:
                        statuses.append(item.lower())
                visit(item, current_market)
        elif isinstance(value, list):
            for item in value:
                visit(item, parent_market)

    visit(payload)
    return any(status in {"open", "trading", "trade", "regular"} for status in statuses)


def _signal(symbol: str, action: str, reason: str, frame: pd.DataFrame) -> IntradaySignal:
    if frame.empty:
        return IntradaySignal(symbol, action, reason, None, None, {})
    latest = frame.iloc[-1]
    timestamp = latest["date"].isoformat() if "date" in latest and pd.notna(latest["date"]) else None
    return IntradaySignal(
        symbol=symbol,
        action=action,
        reason=reason,
        price=_safe_float(latest.get("close")),
        timestamp=timestamp,
        indicators={
            "vwap": _safe_float(latest.get("vwap")),
            "ema9": _safe_float(latest.get("ema9")),
            "ema21": _safe_float(latest.get("ema21")),
            "volume": _safe_float(latest.get("volume")),
        },
    )


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number
