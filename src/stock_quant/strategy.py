from __future__ import annotations

import pandas as pd


def select_top_symbols(factor_table: pd.DataFrame, top_n: int) -> list[str]:
    return factor_table.dropna(subset=["score"]).head(top_n).index.tolist()


def equal_weight_targets(symbols: list[str], exposure: float) -> dict[str, float]:
    if not symbols:
        return {}
    weight = exposure / len(symbols)
    return {symbol: weight for symbol in symbols}


def market_exposure(benchmark: pd.DataFrame, ma_window: int, full: float, defensive: float) -> float:
    close = benchmark["close"].dropna()
    if len(close) < ma_window:
        return defensive
    moving_average = close.rolling(ma_window).mean().iloc[-1]
    return full if close.iloc[-1] > moving_average else defensive

