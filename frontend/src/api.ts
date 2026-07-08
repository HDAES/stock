import type { AppConfig, BacktestResult, IntradayReport, IntradayState, KlinePoint, RankRow, StockSummary, SymbolList } from "./types";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      message = body.detail ?? message;
    } catch {
      // Keep the HTTP status message when the response is not JSON.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  config: () => request<AppConfig>("/api/config"),
  symbols: () => request<SymbolList>("/api/symbols"),
  summary: (symbol: string) => request<StockSummary>(`/api/stocks/${encodeURIComponent(symbol)}/summary`),
  klines: (symbol: string, count = 260) =>
    request<KlinePoint[]>(`/api/stocks/${encodeURIComponent(symbol)}/klines?count=${count}`),
  refresh: (symbol: string) =>
    request<{ symbol: string; refreshed: boolean; kline_rows: number }>(
      `/api/stocks/${encodeURIComponent(symbol)}/refresh`,
      { method: "POST" }
    ),
  rank: () => request<RankRow[]>("/api/strategy/rank"),
  backtest: () => request<BacktestResult>("/api/strategy/backtest"),
  intradayState: () => request<IntradayState>("/api/intraday/state"),
  intradayReport: () => request<IntradayReport>("/api/intraday/report"),
  intradayEvaluate: () => request<IntradayState>("/api/intraday/evaluate", { method: "POST" })
};
