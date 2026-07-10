import type {
  AppConfig,
  BacktestResult,
  IntradayAutoTradeState,
  IntradayReport,
  KlinePoint,
  LongbridgePaperOrderPayload,
  LongbridgePaperSummary,
  RankRow,
  StockSummary,
  SymbolList
} from "./types";

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

function intradayBacktestPath(symbols?: string[], options?: { forceRefresh?: boolean; autoFetchCount?: number }): string {
  const params = new URLSearchParams();
  for (const symbol of symbols ?? []) {
    const normalized = symbol.trim().toUpperCase();
    if (normalized) params.append("symbols", normalized);
  }
  if (options?.forceRefresh) params.set("force_refresh", "true");
  if (options?.autoFetchCount) params.set("auto_fetch_count", String(options.autoFetchCount));
  const query = params.toString();
  return `/api/intraday/backtest${query ? `?${query}` : ""}`;
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
  intradayReport: () => request<IntradayReport>("/api/intraday/report"),
  intradayBacktest: (symbols?: string[], options?: { forceRefresh?: boolean; autoFetchCount?: number }) =>
    request<IntradayReport>(intradayBacktestPath(symbols, options), { method: "POST" }),
  intradayAutoTrade: () => request<IntradayAutoTradeState>("/api/intraday/auto-trade"),
  updateIntradayAutoTrade: (enabled: boolean, confirmNonSimulated = false) =>
    request<IntradayAutoTradeState>("/api/intraday/auto-trade", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled, confirm_non_simulated: confirmNonSimulated })
    }),
  longbridgePaperSummary: () => request<LongbridgePaperSummary>("/api/longbridge-paper/summary"),
  longbridgePaperFeishuReport: () =>
    request<unknown>("/api/longbridge-paper/feishu-report", {
      method: "POST"
    }),
  longbridgePaperOrder: (payload: LongbridgePaperOrderPayload) =>
    request<unknown>("/api/longbridge-paper/order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }),
  longbridgePaperCancel: (orderId: string) =>
    request<unknown>("/api/longbridge-paper/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ order_id: orderId })
    })
};
