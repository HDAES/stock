from __future__ import annotations

import math
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .backtest import performance_metrics, portfolio_returns
from .cache import DataCache, symbol_to_filename
from .config import AppConfig, load_config
from .factors import annualized_volatility, build_factor_table
from .intraday import (
    MARKET_TIMEZONE,
    evaluate_trend_signal,
    market_is_open,
    normalize_intraday_kline,
)
from .intraday_auto_trade import maybe_execute_auto_trade
from .intraday_data import configured_intraday_symbols, merge_intraday_history
from .longbridge import LongbridgeClient
from .paper import PaperPortfolio
from .strategy import equal_weight_targets, market_exposure, select_top_symbols


DEFAULT_CONFIG_PATH = Path("config/default.json")


class CacheMissError(FileNotFoundError):
    """Raised when a cache-first operation cannot find local data."""


def app_config_payload(config: AppConfig) -> dict[str, Any]:
    return {
        "benchmark": config.benchmark,
        "universe": config.universe,
        "data": {
            "cache_dir": str(config.data.cache_dir),
            "history_count": config.data.history_count,
        },
        "strategy": asdict(config.strategy),
        "intraday": asdict(config.intraday),
        "factor_weights": config.factor_weights,
    }


def cached_symbols(cache_dir: str | Path) -> list[str]:
    kline_dir = Path(cache_dir) / "kline"
    if not kline_dir.exists():
        return []
    return sorted(path.stem.replace("_", ".") for path in kline_dir.glob("*.json"))


def load_cached_kline(cache: DataCache, symbol: str, count: int | None = None) -> pd.DataFrame:
    path = cache.kline_dir / f"{symbol_to_filename(symbol)}.json"
    if not path.exists():
        raise CacheMissError(
            f"No cached kline data for {symbol}. Fetch it first or use the refresh action."
        )
    frame = cache.fetch_kline(symbol, refresh=False)
    return frame.tail(count).reset_index(drop=True) if count else frame


def load_cached_calc_index(cache: DataCache, symbol: str) -> dict[str, Any]:
    path = cache.calc_index_dir / f"{symbol_to_filename(symbol)}.json"
    if not path.exists():
        raise CacheMissError(
            f"No cached calc-index data for {symbol}. Fetch it first or use the refresh action."
        )
    return cache.fetch_calc_index(symbol, refresh=False)


def kline_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records = []
    for row in frame.itertuples(index=False):
        records.append(
            {
                "date": row.date.date().isoformat(),
                "open": _safe_float(getattr(row, "open", math.nan)),
                "high": _safe_float(getattr(row, "high", math.nan)),
                "low": _safe_float(getattr(row, "low", math.nan)),
                "close": _safe_float(getattr(row, "close", math.nan)),
                "volume": _safe_float(getattr(row, "volume", math.nan)),
            }
        )
    return records


def stock_summary(cache: DataCache, symbol: str, history_count: int = 500) -> dict[str, Any]:
    prices = load_cached_kline(cache, symbol, history_count)
    close = prices["close"].dropna()
    if close.empty:
        raise ValueError(f"No close prices available for {symbol}")

    latest = prices.dropna(subset=["close"]).iloc[-1]
    previous_close = close.iloc[-2] if len(close) >= 2 else math.nan
    latest_close = float(latest["close"])
    change = latest_close - previous_close if not math.isnan(previous_close) else math.nan
    change_percent = change / previous_close if previous_close and not math.isnan(previous_close) else math.nan

    return {
        "symbol": symbol,
        "date": latest["date"].date().isoformat(),
        "last": latest_close,
        "previous_close": _safe_float(previous_close),
        "change": _safe_float(change),
        "change_percent": _safe_float(change_percent),
        "open": _safe_float(latest.get("open", math.nan)),
        "high": _safe_float(latest.get("high", math.nan)),
        "low": _safe_float(latest.get("low", math.nan)),
        "volume": _safe_float(latest.get("volume", math.nan)),
        "sma20": _moving_average(close, 20),
        "sma50": _moving_average(close, 50),
        "sma200": _moving_average(close, 200),
        "return5": _trailing_return(close, 5),
        "return20": _trailing_return(close, 20),
        "return60": _trailing_return(close, 60),
        "return120": _trailing_return(close, 120),
        "rsi14": _rsi(close, 14),
        "annualized_volatility60": _safe_float(annualized_volatility(close, 60)),
    }


def strategy_rank(config: AppConfig, cache: DataCache) -> list[dict[str, Any]]:
    prices, calc_indexes = load_strategy_inputs(cache, config)
    factor_table = build_factor_table(
        prices,
        calc_indexes,
        config.strategy.momentum_window,
        config.strategy.volatility_window,
        config.factor_weights,
    )
    rows = []
    for rank, (symbol, row) in enumerate(factor_table.iterrows(), start=1):
        record = {"rank": rank, "symbol": symbol}
        for column, value in row.items():
            record[column] = _safe_float(value)
        rows.append(record)
    return rows


def strategy_backtest(config: AppConfig, cache: DataCache) -> dict[str, Any]:
    prices, calc_indexes = load_strategy_inputs(cache, config)
    benchmark = load_cached_kline(cache, config.benchmark, config.data.history_count)
    factor_table = build_factor_table(
        prices,
        calc_indexes,
        config.strategy.momentum_window,
        config.strategy.volatility_window,
        config.factor_weights,
    )
    selected = select_top_symbols(factor_table, config.strategy.top_n)
    exposure = market_exposure(
        benchmark,
        config.strategy.risk_ma_window,
        config.strategy.full_exposure,
        config.strategy.defensive_exposure,
    )
    weights = equal_weight_targets(selected, exposure)
    returns = portfolio_returns(prices, weights)
    equity = (1.0 + returns).cumprod()
    metrics = performance_metrics(returns)

    return {
        "selected_symbols": selected,
        "weights": weights,
        "exposure": exposure,
        "risk_status": "full" if exposure == config.strategy.full_exposure else "defensive",
        "metrics": metrics,
        "equity_curve": [
            {"date": index.date().isoformat(), "equity": float(value)}
            for index, value in equity.items()
        ],
    }


def intraday_state(config: AppConfig) -> dict[str, Any]:
    portfolio = PaperPortfolio.load(
        _intraday_state_path(config),
        config.intraday.initial_cash,
    )
    return portfolio.to_dict()


def evaluate_intraday(
    config: AppConfig,
    client: LongbridgeClient | None = None,
    logger: Any | None = None,
) -> dict[str, Any]:
    longbridge = client or LongbridgeClient()
    portfolio = PaperPortfolio.load(
        _intraday_state_path(config),
        config.intraday.initial_cash,
    )

    if not config.intraday.enabled:
        _log_intraday(logger, "disabled, skipping scan")
        portfolio.last_signals = []
        portfolio.save(_intraday_state_path(config))
        return portfolio.to_dict()

    symbols = _intraday_symbols(config)
    market_open = _market_open(longbridge)
    status = "open" if market_open else "closed"
    _log_intraday(logger, f"market {status}, scanning {len(symbols)} configured intraday symbols")
    quotes = _quote_prices(longbridge, symbols)
    portfolio.mark(quotes)
    portfolio.refresh_daily_stop(config.intraday.max_daily_loss_pct)
    if portfolio.daily_stop:
        _log_intraday(logger, f"daily loss guard active ({portfolio.daily_loss_pct():.2%})")

    signals: list[dict[str, Any]] = []
    mark_prices: dict[str, float] = {}
    executable_signals: list[dict[str, Any]] = []
    for symbol in symbols:
        try:
            payload = longbridge.kline(
                symbol,
                count=max(60, config.intraday.breakout_lookback + config.intraday.volume_lookback + 5),
                period=config.intraday.period,
                session=config.intraday.session,
            )
            try:
                cache_path = merge_intraday_history(
                    config.intraday.data_dir,
                    symbol,
                    config.intraday.period,
                    payload,
                )
                _log_intraday(logger, f"{symbol} cached 5m bars to {cache_path}")
            except Exception as cache_exc:
                _log_intraday(logger, f"{symbol} cache save skipped: {cache_exc}")
            frame = normalize_intraday_kline(payload, symbol)
            frame = _completed_intraday_frame(frame, config.intraday.period)
        except Exception as exc:
            signals.append(
                {
                    "symbol": symbol,
                    "action": "ERROR",
                    "reason": str(exc),
                    "price": None,
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "indicators": {},
                }
            )
            _log_intraday(logger, f"{symbol} ERROR {exc}")
            continue

        if frame.empty:
            signal = {
                "symbol": symbol,
                "action": "HOLD",
                "reason": "waiting_for_completed_5m_bar",
                "price": quotes.get(symbol),
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "indicators": {},
            }
            signals.append(signal)
            _log_intraday(logger, f"{symbol} HOLD waiting_for_completed_5m_bar")
            continue

        bar_id = _intraday_bar_id(frame)
        last_processed = portfolio.processed_intraday_bars.get(symbol)
        if last_processed == bar_id:
            latest_price = _safe_float(frame.iloc[-1].get("close"))
            signal = {
                "symbol": symbol,
                "action": "HOLD",
                "reason": "bar_already_processed",
                "price": latest_price,
                "timestamp": bar_id,
                "bar_id": bar_id,
                "indicators": {},
            }
            signals.append(signal)
            _log_intraday(logger, f"{symbol} HOLD bar_already_processed bar={bar_id}")
            continue

        position = portfolio.positions.get(symbol)
        signal = evaluate_trend_signal(
            symbol=symbol,
            frame=frame,
            config=config.intraday,
            has_position=position is not None,
            entry_price=position.avg_price if position else None,
            daily_stop=portfolio.daily_stop,
            market_open=market_open,
        ).to_dict()
        signal["bar_id"] = bar_id
        trade_price = quotes.get(symbol) or signal["price"]
        if trade_price is not None:
            signal["execution_price"] = trade_price
            mark_prices[symbol] = float(trade_price)

        if signal["action"] == "BUY" and trade_price is not None:
            trade = portfolio.buy(
                symbol,
                float(trade_price),
                str(signal["timestamp"] or datetime.now().isoformat(timespec="seconds")),
                config.intraday.max_position_pct,
                str(signal["reason"]),
            )
            signal["trade"] = trade
        elif signal["action"] == "SELL" and trade_price is not None:
            trade = portfolio.sell(
                symbol,
                float(trade_price),
                str(signal["timestamp"] or datetime.now().isoformat(timespec="seconds")),
                str(signal["reason"]),
            )
            signal["trade"] = trade

        trade_payload = signal.get("trade")
        if isinstance(trade_payload, dict):
            signal["longbridge_order"] = maybe_execute_auto_trade(
                config,
                longbridge,
                signal,
                trade_payload,
                logger,
            )

        portfolio.processed_intraday_bars[symbol] = bar_id
        executable_signals.append(signal)
        price_text = _format_price(signal.get("execution_price") or signal.get("price"))
        trade = signal.get("trade")
        trade_text = ""
        if isinstance(trade, dict):
            trade_text = f" qty={trade.get('quantity')}"
        auto_trade = signal.get("longbridge_order")
        if isinstance(auto_trade, dict) and auto_trade.get("enabled"):
            trade_text += f" longbridge={auto_trade.get('reason')}"
        _log_intraday(
            logger,
            f"{symbol} {signal['action']} {signal['reason']} bar={bar_id} price={price_text}{trade_text}",
        )
        signals.append(signal)

    portfolio.mark(mark_prices)
    portfolio.refresh_daily_stop(config.intraday.max_daily_loss_pct)
    portfolio.last_signals = signals
    portfolio.save(_intraday_state_path(config))
    _append_intraday_signals(config, executable_signals)
    _log_intraday(
        logger,
        f"scan complete equity={portfolio.equity():.2f} cash={portfolio.cash:.2f} daily_pnl={portfolio.daily_loss_pct():.2%}",
    )
    return portfolio.to_dict()


def intraday_market_open(
    client: LongbridgeClient | None = None,
) -> bool:
    longbridge = client or LongbridgeClient()
    return _market_open(longbridge)


def load_strategy_inputs(
    cache: DataCache,
    config: AppConfig,
) -> tuple[dict[str, pd.DataFrame], dict[str, dict[str, Any]]]:
    prices = {}
    calc_indexes = {}
    for symbol in config.universe:
        prices[symbol] = load_cached_kline(cache, symbol, config.data.history_count)
        calc_indexes[symbol] = load_cached_calc_index(cache, symbol)
    return prices, calc_indexes


def load_default_config(path: str | Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    return load_config(path)


def _moving_average(series: pd.Series, window: int) -> float | None:
    if len(series) < window:
        return None
    return _safe_float(series.tail(window).mean())


def _trailing_return(series: pd.Series, window: int) -> float | None:
    if len(series) <= window:
        return None
    return _safe_float(series.iloc[-1] / series.iloc[-window - 1] - 1.0)


def _rsi(series: pd.Series, window: int) -> float | None:
    if len(series) <= window:
        return None
    changes = series.diff().dropna().tail(window)
    gains = changes.clip(lower=0)
    losses = -changes.clip(upper=0)
    average_loss = losses.mean()
    if average_loss == 0:
        return 100.0
    relative_strength = gains.mean() / average_loss
    return _safe_float(100.0 - (100.0 / (1.0 + relative_strength)))


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _completed_intraday_frame(frame: pd.DataFrame, period: str) -> pd.DataFrame:
    if frame.empty or "date" not in frame.columns:
        return frame.iloc[0:0].copy()

    minutes = _period_minutes(period)
    now = pd.Timestamp.now(tz=MARKET_TIMEZONE).tz_localize(None)
    dates = pd.to_datetime(frame["date"], errors="coerce")
    latest = dates.max()
    if pd.isna(latest):
        return frame.iloc[0:0].copy()

    reference_time = now if latest.date() == now.date() else latest + pd.Timedelta(minutes=minutes)
    cutoff = reference_time - pd.Timedelta(minutes=minutes)
    completed = frame[(dates <= cutoff) & (dates.dt.date == latest.date())]
    return completed.reset_index(drop=True)


def _period_minutes(period: str) -> int:
    normalized = str(period).strip().lower()
    if normalized.endswith("m"):
        try:
            return max(1, int(normalized[:-1]))
        except ValueError:
            return 5
    return 5


def _intraday_bar_id(frame: pd.DataFrame) -> str:
    timestamp = pd.Timestamp(frame.iloc[-1]["date"])
    return timestamp.isoformat(timespec="seconds")


def _intraday_dir(config: AppConfig) -> Path:
    return config.data.cache_dir.parent / "intraday"


def _intraday_state_path(config: AppConfig) -> Path:
    return _intraday_dir(config) / "paper_state.json"


def _intraday_signals_path(config: AppConfig) -> Path:
    return _intraday_dir(config) / "signals.jsonl"


def _intraday_symbols(config: AppConfig) -> list[str]:
    return configured_intraday_symbols(config)


def _market_open(client: LongbridgeClient) -> bool:
    try:
        return market_is_open(client.market_status(), "US")
    except Exception:
        return False


def _quote_prices(client: LongbridgeClient, symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    try:
        payload = client.quote(*symbols)
    except Exception:
        return {}

    records = payload if isinstance(payload, list) else [payload]
    prices: dict[str, float] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        symbol = str(record.get("symbol", "")).upper()
        price = _safe_float(record.get("last_done") or record.get("last") or record.get("price"))
        if symbol and price is not None:
            prices[symbol] = price
    return prices


def _append_intraday_signals(config: AppConfig, signals: list[dict[str, Any]]) -> None:
    if not signals:
        return
    path = _intraday_signals_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    evaluated_at = datetime.now().isoformat(timespec="seconds")
    with path.open("a") as handle:
        for signal in signals:
            handle.write(json.dumps({"evaluated_at": evaluated_at, **signal}) + "\n")


def _log_intraday(logger: Any | None, message: str) -> None:
    if logger is None:
        return
    line = f"[intraday] {datetime.now().isoformat(timespec='seconds')} {message}"
    try:
        logger(line, flush=True)
    except TypeError:
        logger(line)


def _format_price(value: Any) -> str:
    price = _safe_float(value)
    if price is None:
        return "n/a"
    return f"{price:.4f}"
