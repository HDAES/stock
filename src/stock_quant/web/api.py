from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from stock_quant.analysis import (
    CacheMissError,
    app_config_payload,
    cached_symbols,
    evaluate_intraday,
    intraday_market_open,
    intraday_state,
    kline_records,
    load_cached_kline,
    load_default_config,
    stock_summary,
    strategy_backtest,
    strategy_rank,
)
from stock_quant.cache import DataCache
from stock_quant.intraday_auto_trade import load_auto_trade_state, save_auto_trade_state
from stock_quant.intraday_backtest import intraday_backtest, load_intraday_history
from stock_quant.intraday_data import ensure_intraday_history_for_today, resolve_intraday_backtest_symbols
from stock_quant.intraday_report import read_intraday_report, write_intraday_report
from stock_quant.longbridge import LongbridgeClient, LongbridgeError
from stock_quant.longbridge_paper import LongbridgePaperTradingClient, PaperOrderRequest

from .schemas import KlinePoint, RefreshResult, StockSummary, SymbolList


class PaperOrderPayload(BaseModel):
    symbol: str
    side: Literal["buy", "sell", "BUY", "SELL"]
    quantity: int = Field(gt=0)
    order_type: str = "market"
    price: float | None = Field(default=None, gt=0)
    time_in_force: str = "day"


class PaperCancelPayload(BaseModel):
    order_id: str = Field(min_length=1)


class AutoTradePayload(BaseModel):
    enabled: bool


def create_app(
    config_path: str | Path = "config/default.json",
    longbridge_client: LongbridgeClient | None = None,
    auto_intraday: bool = True,
) -> FastAPI:
    def get_config():
        return load_default_config(config_path)

    def get_cache() -> DataCache:
        return DataCache(get_config().data.cache_dir)

    def get_longbridge() -> LongbridgeClient | None:
        return longbridge_client

    def get_paper_client() -> LongbridgePaperTradingClient:
        return LongbridgePaperTradingClient(get_longbridge() or LongbridgeClient())

    intraday_task: asyncio.Task | None = None

    async def intraday_background_loop() -> None:
        while True:
            config = get_config()
            wait_seconds = max(5, config.intraday.poll_seconds)
            print(f"[intraday] next scan in {wait_seconds}s", flush=True)
            await asyncio.sleep(wait_seconds)
            config = get_config()
            if config.intraday.enabled and intraday_market_open(get_longbridge()):
                await asyncio.to_thread(evaluate_intraday, config, get_longbridge(), print)
            else:
                print("[intraday] market closed or intraday disabled, skipping scan", flush=True)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal intraday_task
        if auto_intraday and intraday_task is None:
            config = get_config()
            if config.intraday.enabled and intraday_market_open(get_longbridge()):
                await asyncio.to_thread(evaluate_intraday, config, get_longbridge(), print)
            else:
                print("[intraday] startup scan skipped: market closed or intraday disabled", flush=True)
            intraday_task = asyncio.create_task(intraday_background_loop())
        try:
            yield
        finally:
            if intraday_task is not None:
                intraday_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await intraday_task
                intraday_task = None

    app = FastAPI(title="Stock Quant API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/config")
    def read_config() -> dict:
        return app_config_payload(get_config())

    @app.get("/api/symbols", response_model=SymbolList)
    def read_symbols() -> SymbolList:
        config = get_config()
        return SymbolList(
            universe=config.universe,
            cached=cached_symbols(config.data.cache_dir),
        )

    @app.get("/api/stocks/{symbol}/summary", response_model=StockSummary)
    def read_stock_summary(symbol: str) -> StockSummary:
        try:
            return StockSummary(**stock_summary(get_cache(), symbol.upper(), get_config().data.history_count))
        except CacheMissError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/stocks/{symbol}/klines", response_model=list[KlinePoint])
    def read_stock_klines(
        symbol: str,
        count: int = Query(default=260, ge=1, le=2000),
    ) -> list[KlinePoint]:
        try:
            frame = load_cached_kline(get_cache(), symbol.upper(), count)
            return [KlinePoint(**record) for record in kline_records(frame)]
        except CacheMissError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/stocks/{symbol}/refresh", response_model=RefreshResult)
    def refresh_stock(symbol: str) -> RefreshResult:
        config = get_config()
        cache = get_cache()
        normalized_symbol = symbol.upper()
        try:
            frame = cache.fetch_kline(normalized_symbol, count=config.data.history_count, refresh=True)
            if normalized_symbol != config.benchmark:
                cache.fetch_calc_index(normalized_symbol, refresh=True)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Longbridge refresh failed: {exc}") from exc
        return RefreshResult(symbol=normalized_symbol, refreshed=True, kline_rows=len(frame))

    @app.get("/api/strategy/rank")
    def read_strategy_rank() -> list[dict]:
        try:
            return strategy_rank(get_config(), get_cache())
        except CacheMissError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/strategy/backtest")
    def read_strategy_backtest() -> dict:
        try:
            return strategy_backtest(get_config(), get_cache())
        except CacheMissError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/intraday/state")
    def read_intraday_state() -> dict:
        return intraday_state(get_config())

    @app.get("/api/intraday/auto-trade")
    def read_intraday_auto_trade() -> dict[str, Any]:
        return load_auto_trade_state(get_config())

    @app.post("/api/intraday/auto-trade")
    def update_intraday_auto_trade(payload: AutoTradePayload) -> dict[str, Any]:
        return save_auto_trade_state(get_config(), payload.enabled)

    @app.get("/api/intraday/report")
    def read_intraday_backtest_report(
        report_dir: str = Query(default="reports/intraday"),
    ) -> dict:
        try:
            return read_intraday_report(report_dir)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/intraday/backtest")
    def run_intraday_backtest_report(
        symbols: list[str] = Query(default=[]),
        report_dir: str = Query(default="reports/intraday"),
        commission_bps: float | None = Query(default=None),
        slippage_bps: float | None = Query(default=None),
        auto_fetch_count: int = Query(default=1000, ge=1, le=2000),
    ) -> dict:
        config = get_config()
        data_dir = config.intraday.data_dir
        commission = config.intraday.commission_bps if commission_bps is None else commission_bps
        slippage = config.intraday.slippage_bps if slippage_bps is None else slippage_bps
        try:
            selected_symbols = resolve_intraday_backtest_symbols(
                config,
                data_dir,
                explicit_symbols=symbols or None,
            )
            fetched_symbols = ensure_intraday_history_for_today(
                data_dir,
                selected_symbols,
                config.intraday.period,
                config.intraday.session,
                count=auto_fetch_count,
                client=get_longbridge(),
            )
            frames = load_intraday_history(data_dir, selected_symbols, config.intraday.period)
            result = intraday_backtest(
                frames,
                config.intraday,
                commission_bps=commission,
                slippage_bps=slippage,
            )
            write_intraday_report(result, report_dir)
            report = read_intraday_report(report_dir)
            report["symbols"] = selected_symbols
            report["auto_fetched_symbols"] = fetched_symbols
            report["auto_fetch_count"] = auto_fetch_count
            return report
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Intraday backtest failed: {exc}") from exc

    @app.post("/api/intraday/evaluate")
    def run_intraday_evaluate() -> dict:
        try:
            return evaluate_intraday(get_config(), get_longbridge(), print)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Intraday evaluation failed: {exc}") from exc

    @app.get("/api/longbridge-paper/summary")
    def read_longbridge_paper_summary() -> dict[str, Any]:
        try:
            return get_paper_client().summary()
        except LongbridgeError as exc:
            raise HTTPException(status_code=502, detail=f"Longbridge paper summary failed: {exc}") from exc

    @app.get("/api/longbridge-paper/account")
    def read_longbridge_paper_account() -> Any:
        try:
            return get_paper_client().account()
        except LongbridgeError as exc:
            raise HTTPException(status_code=502, detail=f"Longbridge paper account failed: {exc}") from exc

    @app.get("/api/longbridge-paper/positions")
    def read_longbridge_paper_positions() -> Any:
        try:
            return get_paper_client().positions()
        except LongbridgeError as exc:
            raise HTTPException(status_code=502, detail=f"Longbridge paper positions failed: {exc}") from exc

    @app.get("/api/longbridge-paper/orders")
    def read_longbridge_paper_orders() -> Any:
        try:
            return get_paper_client().orders()
        except LongbridgeError as exc:
            raise HTTPException(status_code=502, detail=f"Longbridge paper orders failed: {exc}") from exc

    @app.post("/api/longbridge-paper/order")
    def submit_longbridge_paper_order(payload: PaperOrderPayload) -> Any:
        try:
            request = PaperOrderRequest(
                symbol=payload.symbol.upper(),
                side=payload.side.lower(),
                quantity=payload.quantity,
                order_type=payload.order_type.lower(),
                price=payload.price,
                time_in_force=payload.time_in_force.lower(),
            )
            return get_paper_client().submit_order(request)
        except LongbridgeError as exc:
            raise HTTPException(status_code=502, detail=f"Longbridge paper order failed: {exc}") from exc

    @app.post("/api/longbridge-paper/cancel")
    def cancel_longbridge_paper_order(payload: PaperCancelPayload) -> Any:
        try:
            return get_paper_client().cancel_order(payload.order_id)
        except LongbridgeError as exc:
            raise HTTPException(status_code=502, detail=f"Longbridge paper cancel failed: {exc}") from exc

    return app


app = create_app()
