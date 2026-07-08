from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .config import IntradayConfig


SYMBOL_PATTERN = re.compile(r"^[A-Z0-9.\-]+\.US$")
MARKET_TIMEZONE = "America/New_York"


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

    frame["date"] = normalize_intraday_datetime(frame[date_col], date_col)
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


def normalize_intraday_datetime(values: pd.Series, source_column: str = "date") -> pd.Series:
    """Normalize intraday timestamps to US market time without timezone info.

    Longbridge payloads may contain exchange-local strings, UTC strings with a
    trailing ``Z``, ISO strings with an explicit offset, or epoch timestamps.
    Timezone-aware inputs are converted to America/New_York before the timezone
    is dropped. Naive strings are treated as already being market time.
    """
    if pd.api.types.is_numeric_dtype(values) or source_column == "timestamp":
        numeric = pd.to_numeric(values, errors="coerce")
        if numeric.dropna().empty:
            parsed_numeric = pd.to_datetime(values, errors="coerce")
        else:
            median_abs = float(numeric.dropna().abs().median())
            unit = "ms" if median_abs > 10_000_000_000 else "s"
            parsed_numeric = pd.to_datetime(numeric, unit=unit, errors="coerce", utc=True)
        return parsed_numeric.dt.tz_convert(MARKET_TIMEZONE).dt.tz_localize(None)

    as_text = values.astype(str).str.strip()
    has_timezone = as_text.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", case=False, regex=True).fillna(False)
    if bool(has_timezone.any()):
        parsed_tz = pd.to_datetime(values, errors="coerce", utc=True)
        return parsed_tz.dt.tz_convert(MARKET_TIMEZONE).dt.tz_localize(None)

    parsed = pd.to_datetime(values, errors="coerce")
    timezone = getattr(parsed.dt, "tz", None)
    if timezone is not None:
        return parsed.dt.tz_convert(MARKET_TIMEZONE).dt.tz_localize(None)
    return parsed


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
    has_position: bool,
    entry_price: float | None = None,
    daily_stop: bool = False,
    market_open: bool = True,
) -> IntradaySignal:
    required = max(config.breakout_lookback, config.volume_lookback) + 1
    if len(frame) < required:
        return _signal(
            symbol,
            "HOLD",
            "insufficient_intraday_history",
            _last_close(frame),
            _last_time(frame),
            {},
        )

    enriched = add_intraday_indicators(frame)
    latest = enriched.iloc[-1]
    previous_breakout = enriched.iloc[-required:-1]
    previous_volume = enriched.iloc[-config.volume_lookback - 1:-1]

    price = _as_float(latest.get("close"))
    vwap = _as_float(latest.get("vwap"))
    ema9 = _as_float(latest.get("ema9"))
    ema21 = _as_float(latest.get("ema21"))
    previous_high = _as_float(previous_breakout["high"].max())
    average_volume = _as_float(previous_volume["volume"].mean())
    latest_volume = _as_float(latest.get("volume"))
    timestamp = str(latest.get("date"))

    if price is None:
        return _signal(symbol, "HOLD", "missing_price", None, timestamp, {})

    if has_position and entry_price:
        if price <= entry_price * (1 - config.stop_loss_pct):
            return _signal(symbol, "SELL", "stop_loss", price, timestamp, latest)
        if price >= entry_price * (1 + config.take_profit_pct):
            return _signal(symbol, "SELL", "take_profit", price, timestamp, latest)
        if ema21 is not None and price < ema21:
            return _signal(symbol, "SELL", "close_below_ema21", price, timestamp, latest)
        if vwap is not None and price < vwap:
            return _signal(symbol, "SELL", "close_below_vwap", price, timestamp, latest)
        return _signal(symbol, "HOLD", "position_held", price, timestamp, latest)

    if not market_open:
        return _signal(symbol, "HOLD", "market_closed", price, timestamp, latest)
    if daily_stop:
        return _signal(symbol, "HOLD", "daily_loss_limit_reached", price, timestamp, latest)

    volume_ok = average_volume is not None and latest_volume is not None and latest_volume >= average_volume * config.volume_multiplier
    breakout_ok = previous_high is not None and price > previous_high
    trend_ok = vwap is not None and ema9 is not None and ema21 is not None and price > vwap and ema9 > ema21

    if volume_ok and breakout_ok and trend_ok:
        return _signal(symbol, "BUY", "trend_breakout", price, timestamp, latest)
    return _signal(symbol, "HOLD", "no_breakout_setup", price, timestamp, latest)


def extract_watchlist_symbols(payload: dict | list[dict]) -> list[str]:
    symbols: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str):
                    normalized = value.strip().upper()
                    if SYMBOL_PATTERN.match(normalized):
                        symbols.add(normalized)
                    elif key.lower() in {"symbol", "code", "ticker", "security_code"}:
                        candidate = _normalize_symbol_candidate(normalized)
                        if candidate:
                            symbols.add(candidate)
                elif isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return sorted(symbols)


def _normalize_symbol_candidate(value: str) -> str | None:
    candidate = value.replace("/", ".").replace("-", ".")
    if SYMBOL_PATTERN.match(candidate):
        return candidate
    if re.fullmatch(r"[A-Z0-9.\-]+", candidate) and "." not in candidate:
        us_candidate = f"{candidate}.US"
        if SYMBOL_PATTERN.match(us_candidate):
            return us_candidate
    return None


def _signal(symbol: str, action: str, reason: str, price: float | None, timestamp: str | None, indicators: Any) -> IntradaySignal:
    return IntradaySignal(
        symbol=symbol,
        action=action,
        reason=reason,
        price=price,
        timestamp=timestamp,
        indicators={
            "vwap": _as_float(indicators.get("vwap")) if hasattr(indicators, "get") else None,
            "ema9": _as_float(indicators.get("ema9")) if hasattr(indicators, "get") else None,
            "ema21": _as_float(indicators.get("ema21")) if hasattr(indicators, "get") else None,
            "volume": _as_float(indicators.get("volume")) if hasattr(indicators, "get") else None,
        },
    )


def _last_close(frame: pd.DataFrame) -> float | None:
    if frame.empty or "close" not in frame:
        return None
    return _as_float(frame.iloc[-1].get("close"))


def _last_time(frame: pd.DataFrame) -> str | None:
    if frame.empty or "date" not in frame:
        return None
    return str(frame.iloc[-1].get("date"))


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number
