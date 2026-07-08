from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from .cache import symbol_to_filename
from .config import AppConfig
from .intraday import extract_watchlist_symbols
from .longbridge import LongbridgeClient


class IntradayDataClient(Protocol):
    def kline(
        self,
        symbol: str,
        count: int = 500,
        period: str = "5m",
        session: str = "intraday",
    ) -> list[dict]: ...

    def watchlist(self) -> dict | list[dict]: ...


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


def resolve_intraday_backtest_symbols(
    config: AppConfig,
    data_dir: str | Path,
    explicit_symbols: list[str] | None = None,
) -> list[str]:
    """Resolve symbols for local intraday backtests.

    Backtests run from local files. If symbols are omitted, prefer the files
    that actually exist under ``data_dir`` so a partially cached universe can
    still be backtested.
    """
    if explicit_symbols:
        return _dedupe_symbols(explicit_symbols)

    cached = cached_intraday_symbols(data_dir, config.intraday.period)
    if cached:
        return cached
    if config.intraday.symbols:
        return _dedupe_symbols(config.intraday.symbols)
    return _dedupe_symbols(config.universe)


def resolve_intraday_symbols(
    config: AppConfig,
    explicit_symbols: list[str] | None = None,
    client: IntradayDataClient | None = None,
    prefer_watchlist: bool = True,
) -> list[str]:
    """Resolve the symbols to use for intraday fetch/backtest.

    Priority:
    1. explicit command-line symbols
    2. Longbridge watchlist, when enabled and available
    3. config.intraday.symbols
    4. config.universe
    """
    if explicit_symbols:
        return _dedupe_symbols(explicit_symbols)

    symbols: list[str] = []
    if prefer_watchlist:
        longbridge = client or LongbridgeClient()
        try:
            symbols = extract_watchlist_symbols(longbridge.watchlist())
        except Exception:
            symbols = []

    if not symbols:
        symbols = list(config.intraday.symbols)
    if not symbols:
        symbols = list(config.universe)
    return _dedupe_symbols(symbols)


def fetch_intraday_history(
    data_dir: str | Path,
    symbols: list[str],
    count: int,
    period: str,
    session: str,
    refresh: bool = False,
    client: IntradayDataClient | None = None,
) -> dict[str, Path]:
    """Fetch intraday bars through Longbridge and cache raw JSON locally."""
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
        path.write_text(json.dumps(payload, indent=2))
        cached[symbol] = path
    return cached


def _dedupe_symbols(symbols: list[str]) -> list[str]:
    return sorted(dict.fromkeys(str(symbol).upper() for symbol in symbols if str(symbol).strip()))
