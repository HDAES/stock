from __future__ import annotations

import math

import numpy as np
import pandas as pd


def zscore(series: pd.Series) -> pd.Series:
    clean = series.replace([np.inf, -np.inf], np.nan)
    std = clean.std(ddof=0)
    if not std or math.isnan(std):
        return pd.Series(0.0, index=series.index)
    return (clean - clean.mean()) / std


def trailing_return(prices: pd.Series, window: int) -> float:
    if len(prices) <= window:
        return float("nan")
    return float(prices.iloc[-1] / prices.iloc[-window - 1] - 1.0)


def annualized_volatility(prices: pd.Series, window: int) -> float:
    returns = prices.pct_change().dropna().tail(window)
    if len(returns) < max(10, window // 2):
        return float("nan")
    return float(returns.std(ddof=0) * math.sqrt(252))


def value_score(calc_index: dict) -> float:
    pe = _positive_number(calc_index, "pe_ttm", "pe", "price_earning_ratio")
    pb = _positive_number(calc_index, "pb", "price_book_ratio")
    parts = []
    if pe:
        parts.append(1.0 / pe)
    if pb:
        parts.append(1.0 / pb)
    return float(np.mean(parts)) if parts else float("nan")


def quality_score(calc_index: dict) -> float:
    return _number(calc_index, "roe", "roe_ttm", "return_on_equity")


def build_factor_table(
    price_history: dict[str, pd.DataFrame],
    calc_indexes: dict[str, dict],
    momentum_window: int,
    volatility_window: int,
    weights: dict[str, float],
) -> pd.DataFrame:
    rows = []
    for symbol, prices in price_history.items():
        close = prices["close"]
        rows.append(
            {
                "symbol": symbol,
                "momentum": trailing_return(close, momentum_window),
                "value": value_score(calc_indexes.get(symbol, {})),
                "quality": quality_score(calc_indexes.get(symbol, {})),
                "low_volatility": -annualized_volatility(close, volatility_window),
            }
        )

    frame = pd.DataFrame(rows).set_index("symbol")
    for factor in ("momentum", "value", "quality", "low_volatility"):
        frame[f"{factor}_z"] = zscore(frame[factor])

    frame["score"] = 0.0
    for factor, weight in weights.items():
        frame["score"] += frame[f"{factor}_z"].fillna(0.0) * weight

    return frame.sort_values("score", ascending=False)


def _number(data: dict, *keys: str) -> float:
    for key in keys:
        if key in data and data[key] not in (None, "-", ""):
            try:
                return float(data[key])
            except (TypeError, ValueError):
                continue
    return float("nan")


def _positive_number(data: dict, *keys: str) -> float | None:
    value = _number(data, *keys)
    if math.isnan(value) or value <= 0:
        return None
    return value

