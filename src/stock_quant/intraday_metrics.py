from __future__ import annotations

import math
from typing import Any

import pandas as pd


def max_drawdown(equity: pd.Series) -> float:
    """Return the worst peak-to-trough drawdown for an equity series."""
    clean = pd.to_numeric(equity, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    peak = clean.cummax()
    drawdown = clean / peak - 1.0
    return float(drawdown.min())


def max_consecutive_losses(pnls: list[float]) -> int:
    longest = 0
    current = 0
    for pnl in pnls:
        if pnl < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def trade_metrics(trades: list[dict[str, Any]]) -> dict[str, float]:
    closed = [trade for trade in trades if trade.get("side") == "SELL"]
    pnls = [
        float(trade.get("net_realized_pnl", trade.get("realized_pnl", 0.0)))
        for trade in closed
    ]
    total_commission = sum(float(trade.get("commission", 0.0)) for trade in trades)

    if not pnls:
        return {
            "trade_count": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "average_pnl": 0.0,
            "average_win": 0.0,
            "average_loss": 0.0,
            "max_consecutive_losses": 0.0,
            "total_commission": total_commission,
        }

    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = math.inf if gross_profit else 0.0

    return {
        "trade_count": float(len(pnls)),
        "win_rate": float(len(wins) / len(pnls)),
        "profit_factor": float(profit_factor),
        "average_pnl": float(sum(pnls) / len(pnls)),
        "average_win": float(sum(wins) / len(wins)) if wins else 0.0,
        "average_loss": float(sum(losses) / len(losses)) if losses else 0.0,
        "max_consecutive_losses": float(max_consecutive_losses(pnls)),
        "total_commission": float(total_commission),
    }


def equity_curve_metrics(equity_curve: list[dict[str, Any]]) -> dict[str, float]:
    if not equity_curve:
        return {
            "initial_equity": 0.0,
            "final_equity": 0.0,
            "total_return": 0.0,
            "max_drawdown": 0.0,
        }

    frame = pd.DataFrame(equity_curve)
    equity = pd.to_numeric(frame["equity"], errors="coerce").dropna()
    if equity.empty:
        return {
            "initial_equity": 0.0,
            "final_equity": 0.0,
            "total_return": 0.0,
            "max_drawdown": 0.0,
        }

    initial = float(equity.iloc[0])
    final = float(equity.iloc[-1])
    total_return = 0.0 if initial <= 0 else final / initial - 1.0
    return {
        "initial_equity": initial,
        "final_equity": final,
        "total_return": float(total_return),
        "max_drawdown": max_drawdown(equity),
    }


def intraday_metrics(
    equity_curve: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> dict[str, float]:
    metrics = equity_curve_metrics(equity_curve)
    metrics.update(trade_metrics(trades))
    return metrics
