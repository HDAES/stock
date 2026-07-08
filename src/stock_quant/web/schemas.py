from __future__ import annotations

from pydantic import BaseModel


class KlinePoint(BaseModel):
    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None


class StockSummary(BaseModel):
    symbol: str
    date: str
    last: float
    previous_close: float | None
    change: float | None
    change_percent: float | None
    open: float | None
    high: float | None
    low: float | None
    volume: float | None
    sma20: float | None
    sma50: float | None
    sma200: float | None
    return5: float | None
    return20: float | None
    return60: float | None
    return120: float | None
    rsi14: float | None
    annualized_volatility60: float | None


class SymbolList(BaseModel):
    universe: list[str]
    cached: list[str]


class RefreshResult(BaseModel):
    symbol: str
    refreshed: bool
    kline_rows: int
