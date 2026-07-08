from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

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
from stock_quant.longbridge import LongbridgeClient

from .schemas import KlinePoint, RefreshResult, StockSummary, SymbolList


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

    @app.post("/api/intraday/evaluate")
    def run_intraday_evaluate() -> dict:
        try:
            return evaluate_intraday(get_config(), get_longbridge(), print)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Intraday evaluation failed: {exc}") from exc

    return app


app = create_app()
