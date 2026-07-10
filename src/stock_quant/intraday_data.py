from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from .cache import symbol_to_filename
from .config import AppConfig
from .intraday import MARKET_TIMEZONE, normalize_intraday_kline
from .longbridge import LongbridgeClient


class IntradayDataClient(Protocol):
    def kline(
        self,
        symbol: str,
        count: int = 500,
        period: str = "5m",
        session: str = "intraday",
    ) -> list[dict]: ...


def intraday_history_path(data_dir: str | Path, symbol: str, period: str) -> Path:
    return Path(data_dir) / f"{symbol_to_filename(symbol.upper())}_{period}.json"


def cached_intraday_symbols(data_dir: str | Path, period: str) -> list[str]:
    """Return symbols that already have cached intraday JSON files."""
    root = Path(data_dir)
    if not root.exists():
        return []

    suffix = f"_{period}.json"
    symbols: list[str] = []
    for path in root.glob(f"*{suffix}"):
        stem = path.name[: -len(suffix)]
        symbols.append(stem.replace("_", ".").upper())
    return _dedupe_symbols(symbols)


def configured_intraday_symbols(
    config: AppConfig,
    explicit_symbols: list[str] | None = None,
) -> list[str]:
    """Return the configured intraday stock list.

    Intraday fetch, live/paper scans, and backtests should be bounded by the
    user's explicit intraday configuration. Command-line/API symbols are still
    allowed as an explicit override, but otherwise we do not fall back to the
    Longbridge watchlist or the broader daily-strategy universe.
    """
    symbols = _dedupe_symbols(explicit_symbols or config.intraday.symbols)
    if not symbols:
        raise ValueError(
            "No intraday symbols configured. Add symbols under intraday.symbols in config/default.json "
            "or pass --symbols explicitly."
        )
    return symbols


def resolve_intraday_backtest_symbols(
    config: AppConfig,
    data_dir: str | Path,
    explicit_symbols: list[str] | None = None,
) -> list[str]:
    """Resolve symbols for local intraday backtests.

    Backtests are intentionally limited to ``config.intraday.symbols`` by
    default. Existing cache files for other symbols are ignored unless those
    symbols are configured or explicitly passed.
    """
    return configured_intraday_symbols(config, explicit_symbols)


def resolve_intraday_symbols(
    config: AppConfig,
    explicit_symbols: list[str] | None = None,
    client: IntradayDataClient | None = None,
    prefer_watchlist: bool = False,
) -> list[str]:
    """Resolve symbols for intraday data fetches.

    By default this returns only ``config.intraday.symbols``. ``client`` and
    ``prefer_watchlist`` are accepted for backwards-compatible call sites but
    are intentionally ignored so the intraday universe stays configuration-led.
    """
    _ = client, prefer_watchlist
    return configured_intraday_symbols(config, explicit_symbols)


def intraday_cache_has_today(data_dir: str | Path, symbol: str, period: str) -> bool:
    """Return whether a cached intraday file contains today's US-market bars."""
    path = intraday_history_path(data_dir, symbol, period)
    payload = _read_json_list(path)
    if not payload:
        return False
    try:
        frame = normalize_intraday_kline(payload, symbol.upper())
    except Exception:
        return False
    if frame.empty:
        return False
    today = pd.Timestamp.now(tz=MARKET_TIMEZONE).date()
    dates = pd.to_datetime(frame["date"], errors="coerce")
    return bool((dates.dt.date == today).any())


def ensure_intraday_history_for_today(
    data_dir: str | Path,
    symbols: list[str],
    period: str,
    session: str,
    count: int = 1000,
    client: IntradayDataClient | None = None,
    force_refresh: bool = False,
) -> list[str]:
    """Fetch and merge recent bars for missing or explicitly refreshed symbols."""
    requested = _dedupe_symbols(symbols)
    missing_today = requested if force_refresh else [
        symbol for symbol in requested if not intraday_cache_has_today(data_dir, symbol, period)
    ]
    if not missing_today:
        return []

    longbridge = client or LongbridgeClient()
    fetched: list[str] = []
    for symbol in missing_today:
        payload = longbridge.kline(symbol, count=count, period=period, session=session)
        merge_intraday_history(data_dir, symbol, period, payload)
        fetched.append(symbol)
    return fetched


def merge_intraday_history(
    data_dir: str | Path,
    symbol: str,
    period: str,
    payload: list[dict],
) -> Path:
    """Merge newly fetched intraday bars into the local backtest cache.

    The saved cache is normalized to US regular-session bars, sorted by time,
    and de-duplicated by timestamp. This makes data collected during live/paper
    intraday scans reusable by ``intraday-backtest``.
    """
    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = intraday_history_path(root, symbol, period)

    existing = _read_json_list(path)
    combined = [*existing, *payload]
    frame = normalize_intraday_kline(combined, symbol.upper())
    frame = frame.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    path.write_text(json.dumps(_frame_to_payload(frame), indent=2))
    return path


def fetch_intraday_history(
    data_dir: str | Path,
    symbols: list[str],
    count: int,
    period: str,
    session: str,
    refresh: bool = False,
    client: IntradayDataClient | None = None,
) -> dict[str, Path]:
    """Fetch intraday bars through Longbridge and cache normalized JSON locally."""
    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    longbridge = client or LongbridgeClient()
    cached: dict[str, Path] = {}

    for symbol in _dedupe_symbols(symbols):
        path = intraday_history_path(root, symbol, period)
        if path.exists() and not refresh:
            cached[symbol] = path
            continue
        payload = longbridge.kline(symbol, count=count, period=period, session=session)
        if refresh and path.exists():
            path.unlink()
        cached[symbol] = merge_intraday_history(root, symbol, period, payload)
    return cached


def _read_json_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _frame_to_payload(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False):
        rows.append(
            {
                "date": pd.Timestamp(row.date).isoformat(timespec="seconds"),
                "open": _safe_float(getattr(row, "open", None)),
                "high": _safe_float(getattr(row, "high", None)),
                "low": _safe_float(getattr(row, "low", None)),
                "close": _safe_float(getattr(row, "close", None)),
                "volume": _safe_float(getattr(row, "volume", None)),
            }
        )
    return rows


def _safe_float(value: Any) -> float | int | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number.is_integer():
        return int(number)
    return number


def _dedupe_symbols(symbols: list[str]) -> list[str]:
    return sorted(dict.fromkeys(str(symbol).upper() for symbol in symbols if str(symbol).strip()))
