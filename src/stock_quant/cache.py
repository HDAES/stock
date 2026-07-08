from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .longbridge import LongbridgeClient


def symbol_to_filename(symbol: str) -> str:
    return symbol.replace(".", "_")


class DataCache:
    def __init__(self, cache_dir: str | Path, client: LongbridgeClient | None = None) -> None:
        self.cache_dir = Path(cache_dir)
        self.client = client or LongbridgeClient()
        self.kline_dir = self.cache_dir / "kline"
        self.calc_index_dir = self.cache_dir / "calc_index"
        self.kline_dir.mkdir(parents=True, exist_ok=True)
        self.calc_index_dir.mkdir(parents=True, exist_ok=True)

    def fetch_kline(self, symbol: str, count: int = 500, refresh: bool = False) -> pd.DataFrame:
        path = self.kline_dir / f"{symbol_to_filename(symbol)}.json"
        if refresh or not path.exists():
            payload = self.client.kline(symbol, count=count)
            path.write_text(json.dumps(payload, indent=2))
        return normalize_kline(json.loads(path.read_text()), symbol)

    def fetch_calc_index(self, symbol: str, refresh: bool = False) -> dict:
        path = self.calc_index_dir / f"{symbol_to_filename(symbol)}.json"
        if refresh or not path.exists():
            payload = self.client.calc_index(symbol)
            path.write_text(json.dumps(payload, indent=2))
        data = json.loads(path.read_text())
        if isinstance(data, list):
            return data[0] if data else {}
        return data


def normalize_kline(payload: list[dict], symbol: str) -> pd.DataFrame:
    rows = payload
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError(f"No kline data for {symbol}")

    date_col = next((col for col in ("date", "time", "timestamp") if col in frame.columns), None)
    if date_col is None:
        raise ValueError(f"Kline payload for {symbol} has no date/time column")

    frame["date"] = pd.to_datetime(frame[date_col]).dt.tz_localize(None)
    for column in ("open", "high", "low", "close", "volume"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    if "close" not in frame.columns:
        close_col = next((col for col in ("last", "last_done") if col in frame.columns), None)
        if close_col is None:
            raise ValueError(f"Kline payload for {symbol} has no close column")
        frame["close"] = pd.to_numeric(frame[close_col], errors="coerce")

    frame["symbol"] = symbol
    return frame.sort_values("date").dropna(subset=["close"]).reset_index(drop=True)

