from __future__ import annotations

import numpy as np
import pandas as pd


def portfolio_returns(price_history: dict[str, pd.DataFrame], weights: dict[str, float]) -> pd.Series:
    closes = {
        symbol: frame.set_index("date")["close"].rename(symbol)
        for symbol, frame in price_history.items()
        if symbol in weights
    }
    if not closes:
        return pd.Series(dtype=float)
    close_frame = pd.concat(closes.values(), axis=1).sort_index().ffill()
    returns = close_frame.pct_change().fillna(0.0)
    weight_series = pd.Series(weights).reindex(close_frame.columns).fillna(0.0)
    return returns.mul(weight_series, axis=1).sum(axis=1)


def apply_turnover_cost(returns: pd.Series, turnover: pd.Series, bps: float) -> pd.Series:
    cost = turnover.reindex(returns.index).fillna(0.0) * (bps / 10000.0)
    return returns - cost


def performance_metrics(returns: pd.Series) -> dict[str, float]:
    returns = returns.dropna()
    if returns.empty:
        return {"cagr": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "volatility": 0.0}

    equity = (1.0 + returns).cumprod()
    years = max(len(returns) / 252.0, 1 / 252.0)
    cagr = equity.iloc[-1] ** (1.0 / years) - 1.0
    volatility = returns.std(ddof=0) * np.sqrt(252)
    sharpe = 0.0 if volatility == 0 else returns.mean() * 252 / volatility
    drawdown = equity / equity.cummax() - 1.0
    return {
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "max_drawdown": float(drawdown.min()),
        "volatility": float(volatility),
    }

