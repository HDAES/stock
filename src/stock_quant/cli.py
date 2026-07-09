from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import pandas as pd

from .account_report import build_account_report, format_account_report, send_feishu_text
from .analysis import CacheMissError, evaluate_intraday, load_strategy_inputs, strategy_backtest
from .cache import DataCache
from .config import load_config
from .factors import build_factor_table
from .intraday_backtest import intraday_backtest, load_intraday_history
from .intraday_data import fetch_intraday_history, resolve_intraday_backtest_symbols, resolve_intraday_symbols
from .intraday_report import write_intraday_report
from .longbridge import LongbridgeClient


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
    rank_parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Fail instead of fetching missing strategy cache files",
    )

    backtest_parser = subparsers.add_parser("backtest", help="Run a first-pass cached-data backtest")
    backtest_parser.add_argument("--config", default="config/default.json")
    backtest_parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Fail instead of fetching missing strategy cache files",
    )

    intraday_fetch_parser = subparsers.add_parser(
        "intraday-fetch",
        help="Fetch and cache Longbridge intraday kline data",
    )
    intraday_fetch_parser.add_argument("--config", default="config/default.json")
    intraday_fetch_parser.add_argument("--symbols", nargs="*", help="Override configured intraday symbols, e.g. AAPL.US MSFT.US")
    intraday_fetch_parser.add_argument("--data-dir", default=None, help="Directory to write intraday JSON files")
    intraday_fetch_parser.add_argument("--count", type=int, default=None, help="Number of intraday bars per symbol")
    intraday_fetch_parser.add_argument("--period", default=None, help="Longbridge kline period, default from config")
    intraday_fetch_parser.add_argument("--session", default=None, help="Longbridge kline session, default from config")
    intraday_fetch_parser.add_argument("--refresh", action="store_true", help="Refetch even when cache files exist")
    intraday_fetch_parser.add_argument(
        "--no-watchlist",
        action="store_true",
        help="Deprecated; intraday symbols now come from config.intraday.symbols by default",
    )

    intraday_once_parser = subparsers.add_parser("intraday-once", help="Evaluate intraday paper signals once")
    intraday_once_parser.add_argument("--config", default="config/default.json")

    intraday_watch_parser = subparsers.add_parser("intraday-watch", help="Continuously evaluate intraday paper signals")
    intraday_watch_parser.add_argument("--config", default="config/default.json")

    intraday_backtest_parser = subparsers.add_parser(
        "intraday-backtest",
        help="Run a historical intraday paper backtest from local 5m JSON files",
    )
    intraday_backtest_parser.add_argument("--config", default="config/default.json")
    intraday_backtest_parser.add_argument("--symbols", nargs="*", help="Override configured intraday symbols, e.g. AAPL.US MSFT.US")
    intraday_backtest_parser.add_argument("--data-dir", default=None, help="Directory containing intraday JSON files")
    intraday_backtest_parser.add_argument("--commission-bps", type=float, default=None)
    intraday_backtest_parser.add_argument("--slippage-bps", type=float, default=None)
    intraday_backtest_parser.add_argument(
        "--save-report",
        action="store_true",
        help="Write backtest artifacts to reports/intraday or --report-dir",
    )
    intraday_backtest_parser.add_argument(
        "--report-dir",
        default="reports/intraday",
        help="Directory for intraday report files when --save-report is used",
    )

    account_report_parser = subparsers.add_parser(
        "account-report",
        help="Fetch account assets/positions and optionally notify Feishu",
    )
    account_report_parser.add_argument("--config", default="config/default.json")
    account_report_parser.add_argument("--currency", default="USD")
    account_report_parser.add_argument(
        "--webhook-url",
        default=None,
        help="Feishu robot webhook URL. Defaults to notifications.feishu_webhook_url in config.",
    )
    account_report_parser.add_argument(
        "--send",
        action="store_true",
        help="Send the report to Feishu when a webhook URL is configured.",
    )

    args = parser.parse_args()
    if args.command == "fetch":
        run_fetch(args)
    elif args.command == "rank":
        run_rank(args)
    elif args.command == "backtest":
        run_backtest(args)
    elif args.command == "intraday-fetch":
        run_intraday_fetch(args)
    elif args.command == "intraday-once":
        run_intraday_once(args)
    elif args.command == "intraday-watch":
        run_intraday_watch(args)
    elif args.command == "intraday-backtest":
        run_intraday_backtest(args)
    elif args.command == "account-report":
        run_account_report(args)


def run_fetch(args: argparse.Namespace) -> None:
    cache = DataCache(args.cache_dir)
    for symbol in args.symbols:
        cache.fetch_kline(symbol, count=args.count, refresh=args.refresh)
        if symbol != "SPY.US":
            cache.fetch_calc_index(symbol, refresh=args.refresh)
        print(f"cached {symbol}")


def ensure_strategy_cache(cache: DataCache, config) -> None:
    symbols = list(dict.fromkeys([*config.universe, config.benchmark]))
    print("Missing cached strategy data detected. Fetching configured universe and benchmark...")
    for symbol in symbols:
        cache.fetch_kline(symbol, count=config.data.history_count, refresh=False)
        if symbol in config.universe:
            cache.fetch_calc_index(symbol, refresh=False)
        print(f"cached {symbol}")


def run_rank(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    cache = DataCache(config.data.cache_dir)
    try:
        prices, calc_indexes = load_strategy_inputs(cache, config)
    except CacheMissError as exc:
        if args.cache_only:
            raise SystemExit(str(exc)) from exc
        ensure_strategy_cache(cache, config)
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
    try:
        result = strategy_backtest(config, cache)
    except CacheMissError as exc:
        if args.cache_only:
            raise SystemExit(str(exc)) from exc
        ensure_strategy_cache(cache, config)
        result = strategy_backtest(config, cache)

    print("Selected symbols:")
    print(", ".join(result["selected_symbols"]))
    print("")
    print("Target weights:")
    print(pd.Series(result["weights"]).round(4).to_string())
    print("")
    print("Backtest metrics from cached window:")
    print(pd.Series(result["metrics"]).map(lambda value: f"{value:.4f}").to_string())


def run_intraday_fetch(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    try:
        symbols = resolve_intraday_symbols(
            config,
            explicit_symbols=args.symbols,
            prefer_watchlist=False,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    data_dir = args.data_dir or config.intraday.data_dir
    count = args.count or config.intraday.history_count
    period = args.period or config.intraday.period
    session = args.session or config.intraday.session

    cached = fetch_intraday_history(
        data_dir=data_dir,
        symbols=symbols,
        count=count,
        period=period,
        session=session,
        refresh=args.refresh,
    )

    print("Intraday cached files:")
    rows = [
        {
            "symbol": symbol,
            "path": str(path),
        }
        for symbol, path in cached.items()
    ]
    print(pd.DataFrame(rows).to_string(index=False))


def run_intraday_once(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    try:
        result = evaluate_intraday(config, logger=print)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print_intraday_result(result)


def run_intraday_watch(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    try:
        while True:
            try:
                result = evaluate_intraday(config, logger=print)
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            print_intraday_result(result)
            time.sleep(config.intraday.poll_seconds)
    except KeyboardInterrupt:
        print("intraday watch stopped")


def run_intraday_backtest(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    data_dir = args.data_dir or config.intraday.data_dir
    try:
        symbols = resolve_intraday_backtest_symbols(config, data_dir, explicit_symbols=args.symbols)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    commission_bps = config.intraday.commission_bps if args.commission_bps is None else args.commission_bps
    slippage_bps = config.intraday.slippage_bps if args.slippage_bps is None else args.slippage_bps

    frames = load_intraday_history(data_dir, symbols, config.intraday.period)
    result = intraday_backtest(
        frames,
        config.intraday,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
    )

    print("Intraday backtest symbols:")
    print(", ".join(symbols))
    print("")
    print("Intraday backtest metrics:")
    print(pd.Series(result["metrics"]).map(_format_metric).to_string())
    print("")
    if result["daily_summary"]:
        print("Daily summary:")
        print(pd.DataFrame(result["daily_summary"]).tail(10).to_string(index=False))
    else:
        print("Daily summary: (none)")
    print("")
    if result["trades"]:
        print("Trades:")
        print(pd.DataFrame(result["trades"]).tail(20).to_string(index=False))
    else:
        print("Trades: (none)")

    if args.save_report:
        written = write_intraday_report(result, Path(args.report_dir))
        print("")
        print("Report files:")
        rows = [
            {
                "artifact": key,
                "path": str(path),
            }
            for key, path in written.items()
        ]
        print(pd.DataFrame(rows).to_string(index=False))


def run_account_report(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    webhook_url = args.webhook_url
    if webhook_url is None:
        webhook_url = config.notifications.feishu_webhook_url
    report = build_account_report(LongbridgeClient(), currency=args.currency)
    text = format_account_report(report)
    print(text)
    if args.send:
        if not webhook_url:
            print("")
            print("Feishu webhook is empty; notification skipped.")
            return
        send_feishu_text(webhook_url, text)
        print("")
        print("Feishu notification sent.")


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


def _format_metric(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isinf(number):
        return "inf"
    return f"{number:.4f}"


if __name__ == "__main__":
    main()
