from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .cache import symbol_to_filename
from .config import IntradayConfig
from .intraday import evaluate_trend_signal, normalize_intraday_kline
from .intraday_metrics import intraday_metrics, max_drawdown
from .paper import PaperPortfolio


def prepare_intraday_frame(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize an intraday OHLCV frame."""
    if frame.empty:
        raise ValueError(f"No intraday bars for {symbol}")

    prepared = frame.copy()
    prepared["date"] = pd.to_datetime(prepared["date"]).dt.tz_localize(None)
    for column in ("open", "high", "low", "close", "volume"):
        if column in prepared.columns:
            prepared[column] = pd.to_numeric(prepared[column], errors="coerce")

    if "close" not in prepared.columns:
        raise ValueError(f"Intraday bars for {symbol} have no close column")
    for column in ("open", "high", "low"):
        if column not in prepared.columns:
            prepared[column] = prepared["close"]
    if "volume" not in prepared.columns:
        prepared["volume"] = 0.0

    prepared["symbol"] = symbol
    return prepared.sort_values("date").dropna(subset=["close"]).reset_index(drop=True)


def load_intraday_history(
    data_dir: str | Path,
    symbols: list[str],
    period: str = "5m",
) -> dict[str, pd.DataFrame]:
    """Load local intraday JSON files for the requested symbols.

    Supported filenames are ``AAPL_US_5m.json`` and ``AAPL_US.json``.
    Files may contain either a raw list of bars or a dict with a common
    payload key such as ``data``, ``items``, ``bars``, or ``kline``.
    """
    root = Path(data_dir)
    frames: dict[str, pd.DataFrame] = {}
    missing: list[str] = []

    for symbol in symbols:
        path = _find_intraday_file(root, symbol, period)
        if path is None:
            missing.append(symbol)
            continue
        payload = json.loads(path.read_text())
        bars = _extract_bar_payload(payload, path)
        frames[symbol] = normalize_intraday_kline(bars, symbol)

    if missing:
        raise FileNotFoundError(
            f"Missing intraday files for: {', '.join(missing)} under {root}"
        )
    return frames


def build_timeline(symbol_frames: dict[str, pd.DataFrame]) -> list[pd.Timestamp]:
    dates: set[pd.Timestamp] = set()
    for frame in symbol_frames.values():
        dates.update(pd.to_datetime(frame["date"]).dt.tz_localize(None).tolist())
    return sorted(dates)


def apply_slippage(price: float, side: str, slippage_bps: float) -> float:
    rate = slippage_bps / 10000.0
    if side == "BUY":
        return price * (1.0 + rate)
    if side == "SELL":
        return price * (1.0 - rate)
    return price


def commission_cost(value: float, commission_bps: float) -> float:
    return value * commission_bps / 10000.0


def intraday_backtest(
    symbol_frames: dict[str, pd.DataFrame],
    config: IntradayConfig,
    commission_bps: float | None = None,
    slippage_bps: float | None = None,
) -> dict[str, Any]:
    """Run a bar-by-bar historical intraday paper backtest.

    Signals are generated after each completed bar using data up to that
    timestamp. BUY/SELL orders are scheduled for the next available bar open
    for that symbol to avoid same-bar lookahead.
    """
    frames = {
        symbol.upper(): prepare_intraday_frame(symbol.upper(), frame)
        for symbol, frame in symbol_frames.items()
    }
    timeline = build_timeline(frames)
    if not timeline:
        return {
            "equity_curve": [],
            "daily_summary": [],
            "trades": [],
            "signals": [],
            "metrics": intraday_metrics([], []),
        }

    commission = config.commission_bps if commission_bps is None else commission_bps
    slippage = config.slippage_bps if slippage_bps is None else slippage_bps
    portfolio = PaperPortfolio.empty(config.initial_cash, day=timeline[0].date().isoformat())

    pending_orders: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    signal_records: list[dict[str, Any]] = []

    for current_time in timeline:
        _roll_portfolio_day(portfolio, current_time)

        executable, pending_orders = _pop_executable_orders(pending_orders, current_time)
        for order in executable:
            _execute_order(portfolio, order, commission, slippage)

        marks = _latest_prices_at(frames, current_time)
        portfolio.mark(marks)
        portfolio.refresh_daily_stop(config.max_daily_loss_pct)

        for symbol, frame in frames.items():
            history = frame[frame["date"] <= current_time]
            if history.empty:
                continue

            position = portfolio.positions.get(symbol)
            signal = evaluate_trend_signal(
                symbol=symbol,
                frame=history,
                config=config,
                has_position=position is not None,
                entry_price=position.avg_price if position else None,
                daily_stop=portfolio.daily_stop,
                market_open=True,
            )
            signal_record = signal.to_dict()
            signal_record["evaluated_at"] = current_time.isoformat()
            signal_records.append(signal_record)

            if signal.action in {"BUY", "SELL"}:
                if signal.action == "BUY" and position is not None:
                    continue
                if _has_pending_order(pending_orders, symbol, signal.action):
                    continue
                next_bar = _next_bar(frame, current_time)
                if next_bar is None:
                    continue
                pending_orders.append(
                    {
                        "symbol": symbol,
                        "side": signal.action,
                        "reason": signal.reason,
                        "created_at": current_time,
                        "execute_at": next_bar["date"],
                        "raw_price": float(next_bar["open"]),
                        "signal_price": signal.price,
                        "max_position_pct": config.max_position_pct,
                    }
                )

        equity_curve.append(_equity_record(portfolio, current_time))

    trades = list(portfolio.trades)
    return {
        "equity_curve": equity_curve,
        "daily_summary": daily_summary(equity_curve, trades),
        "trades": trades,
        "signals": signal_records,
        "metrics": intraday_metrics(equity_curve, trades),
    }


def daily_summary(
    equity_curve: list[dict[str, Any]],
    trades: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not equity_curve:
        return []

    frame = pd.DataFrame(equity_curve)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame["day"] = frame["timestamp"].dt.date.astype(str)

    trades_by_day: dict[str, int] = {}
    realized_by_day: dict[str, float] = {}
    for trade in trades:
        timestamp = trade.get("timestamp")
        if not timestamp:
            continue
        day = str(pd.to_datetime(timestamp).date())
        trades_by_day[day] = trades_by_day.get(day, 0) + 1
        if trade.get("side") == "SELL":
            realized_by_day[day] = realized_by_day.get(day, 0.0) + float(
                trade.get("net_realized_pnl", trade.get("realized_pnl", 0.0))
            )

    rows: list[dict[str, Any]] = []
    for day, group in frame.groupby("day", sort=True):
        equity = pd.to_numeric(group["equity"], errors="coerce")
        start = float(equity.iloc[0])
        end = float(equity.iloc[-1])
        rows.append(
            {
                "day": day,
                "start_equity": start,
                "end_equity": end,
                "daily_return": 0.0 if start <= 0 else end / start - 1.0,
                "high_equity": float(equity.max()),
                "low_equity": float(equity.min()),
                "max_drawdown": max_drawdown(equity),
                "trade_count": trades_by_day.get(day, 0),
                "realized_pnl": realized_by_day.get(day, 0.0),
            }
        )
    return rows


def _find_intraday_file(root: Path, symbol: str, period: str) -> Path | None:
    safe_symbol = symbol_to_filename(symbol)
    candidates = [
        root / f"{safe_symbol}_{period}.json",
        root / f"{safe_symbol}.json",
        root / symbol / f"{period}.json",
        root / symbol / "kline.json",
    ]
    return next((path for path in candidates if path.exists()), None)


def _extract_bar_payload(payload: Any, path: Path) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "items", "bars", "kline", "klines", "candles"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise ValueError(f"Unsupported intraday payload shape in {path}")


def _pop_executable_orders(
    pending_orders: list[dict[str, Any]],
    current_time: pd.Timestamp,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    executable = []
    remaining = []
    for order in pending_orders:
        if order["execute_at"] <= current_time:
            executable.append(order)
        else:
            remaining.append(order)
    return executable, remaining


def _execute_order(
    portfolio: PaperPortfolio,
    order: dict[str, Any],
    commission_bps: float,
    slippage_bps: float,
) -> None:
    side = str(order["side"])
    symbol = str(order["symbol"])
    price = apply_slippage(float(order["raw_price"]), side, slippage_bps)
    timestamp = order["execute_at"].isoformat()

    if side == "BUY":
        trade = portfolio.buy(symbol, price, timestamp, order.get("max_position_pct", 1.0), str(order["reason"]))
    elif side == "SELL":
        trade = portfolio.sell(symbol, price, timestamp, str(order["reason"]))
    else:
        trade = None

    if trade is None:
        return

    fee = commission_cost(float(trade["value"]), commission_bps)
    portfolio.cash -= fee
    if side == "SELL":
        trade["net_realized_pnl"] = float(trade.get("realized_pnl", 0.0)) - fee
    trade.update(
        {
            "commission": fee,
            "raw_price": float(order["raw_price"]),
            "slippage_bps": slippage_bps,
            "created_at": order["created_at"].isoformat(),
            "signal_price": order.get("signal_price"),
        }
    )


def _latest_prices_at(
    frames: dict[str, pd.DataFrame],
    current_time: pd.Timestamp,
) -> dict[str, float]:
    prices: dict[str, float] = {}
    for symbol, frame in frames.items():
        history = frame[frame["date"] <= current_time]
        if history.empty:
            continue
        prices[symbol] = float(history.iloc[-1]["close"])
    return prices


def _next_bar(frame: pd.DataFrame, current_time: pd.Timestamp) -> dict[str, Any] | None:
    future = frame[frame["date"] > current_time]
    if future.empty:
        return None
    row = future.iloc[0]
    open_price = row["open"] if pd.notna(row["open"]) else row["close"]
    return {
        "date": row["date"],
        "open": open_price,
    }


def _has_pending_order(
    pending_orders: list[dict[str, Any]],
    symbol: str,
    side: str,
) -> bool:
    return any(order["symbol"] == symbol and order["side"] == side for order in pending_orders)


def _roll_portfolio_day(portfolio: PaperPortfolio, current_time: pd.Timestamp) -> None:
    day = current_time.date().isoformat()
    if portfolio.day == day:
        return
    portfolio.day = day
    portfolio.day_start_equity = portfolio.equity()
    portfolio.daily_stop = False


def _equity_record(portfolio: PaperPortfolio, current_time: pd.Timestamp) -> dict[str, Any]:
    return {
        "timestamp": current_time.isoformat(),
        "cash": float(portfolio.cash),
        "equity": float(portfolio.equity()),
        "daily_loss_pct": float(portfolio.daily_loss_pct()),
        "positions": {
            symbol: position.to_dict()
            for symbol, position in portfolio.positions.items()
        },
    }
