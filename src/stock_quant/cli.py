from __future__ import annotations

import argparse
import time

import pandas as pd

from .analysis import evaluate_intraday, load_strategy_inputs, strategy_backtest
from .cache import DataCache
from .config import load_config
from .factors import build_factor_table


def main() -> None:
    parser = argparse.ArgumentParser(prog="stock-quant")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch and cache Longbridge data")
    fetch_parser.add_argument("--symbols", nargs="+", required=True)
    fetch_parser.add_argument("--count", type=int, default=500)
    fetch_parser.add_argument("--cache-dir", default="data/cache")
    fetch_parser.add_argument("--refresh", action="store_true")

    rank_parser = subparsers.add_parser("rank", help="Rank symbols using cached data")
    rank_parser.add_argument("--config", default="config/default.json")

    backtest_parser = subparsers.add_parser("backtest", help="Run a first-pass cached-data backtest")
    backtest_parser.add_argument("--config", default="config/default.json")

    intraday_once_parser = subparsers.add_parser("intraday-once", help="Evaluate intraday paper signals once")
    intraday_once_parser.add_argument("--config", default="config/default.json")

    intraday_watch_parser = subparsers.add_parser("intraday-watch", help="Continuously evaluate intraday paper signals")
    intraday_watch_parser.add_argument("--config", default="config/default.json")

    args = parser.parse_args()
    if args.command == "fetch":
        run_fetch(args)
    elif args.command == "rank":
        run_rank(args)
    elif args.command == "backtest":
        run_backtest(args)
    elif args.command == "intraday-once":
        run_intraday_once(args)
    elif args.command == "intraday-watch":
        run_intraday_watch(args)


def run_fetch(args: argparse.Namespace) -> None:
    cache = DataCache(args.cache_dir)
    for symbol in args.symbols:
        cache.fetch_kline(symbol, count=args.count, refresh=args.refresh)
        if symbol != "SPY.US":
            cache.fetch_calc_index(symbol, refresh=args.refresh)
        print(f"cached {symbol}")


def run_rank(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    cache = DataCache(config.data.cache_dir)
    prices, calc_indexes = load_strategy_inputs(cache, config)
    factor_table = build_factor_table(
        prices,
        calc_indexes,
        config.strategy.momentum_window,
        config.strategy.volatility_window,
        config.factor_weights,
    )
    print(factor_table.round(4).head(config.strategy.top_n).to_string())


def run_backtest(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    cache = DataCache(config.data.cache_dir)
    result = strategy_backtest(config, cache)

    print("Selected symbols:")
    print(", ".join(result["selected_symbols"]))
    print("")
    print("Target weights:")
    print(pd.Series(result["weights"]).round(4).to_string())
    print("")
    print("Backtest metrics from cached window:")
    print(pd.Series(result["metrics"]).map(lambda value: f"{value:.4f}").to_string())


def run_intraday_once(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    result = evaluate_intraday(config, logger=print)
    print_intraday_result(result)


def run_intraday_watch(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    try:
        while True:
            result = evaluate_intraday(config, logger=print)
            print_intraday_result(result)
            time.sleep(config.intraday.poll_seconds)
    except KeyboardInterrupt:
        print("intraday watch stopped")


def print_intraday_result(result: dict) -> None:
    print("Paper portfolio:")
    print(f"equity={result['equity']:.2f} cash={result['cash']:.2f} daily_loss={result['daily_loss_pct']:.2%}")
    print("")
    print("Signals:")
    signals = result.get("last_signals", [])
    if not signals:
        print("(none)")
        return
    rows = [
        {
            "symbol": signal.get("symbol"),
            "action": signal.get("action"),
            "reason": signal.get("reason"),
            "price": signal.get("execution_price") or signal.get("price"),
        }
        for signal in signals
    ]
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
