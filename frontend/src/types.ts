export type AppConfig = {
  benchmark: string;
  universe: string[];
  data: {
    cache_dir: string;
    history_count: number;
  };
  strategy: Record<string, number | string>;
  intraday: Record<string, number | string | boolean | string[]>;
  factor_weights: Record<string, number>;
};

export type SymbolList = {
  universe: string[];
  cached: string[];
};

export type StockSummary = {
  symbol: string;
  date: string;
  last: number;
  previous_close: number | null;
  change: number | null;
  change_percent: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  sma20: number | null;
  sma50: number | null;
  sma200: number | null;
  return5: number | null;
  return20: number | null;
  return60: number | null;
  return120: number | null;
  rsi14: number | null;
  annualized_volatility60: number | null;
};

export type KlinePoint = {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
};

export type RankRow = {
  rank: number;
  symbol: string;
  momentum: number | null;
  value: number | null;
  quality: number | null;
  low_volatility: number | null;
  momentum_z: number | null;
  value_z: number | null;
  quality_z: number | null;
  low_volatility_z: number | null;
  score: number | null;
};

export type BacktestResult = {
  selected_symbols: string[];
  weights: Record<string, number>;
  exposure: number;
  risk_status: string;
  metrics: {
    cagr: number;
    sharpe: number;
    max_drawdown: number;
    volatility: number;
  };
  equity_curve: Array<{
    date: string;
    equity: number;
  }>;
};

export type IntradaySignal = {
  symbol: string;
  action: string;
  reason: string;
  price: number | null;
  execution_price?: number | null;
  timestamp: string | null;
  evaluated_at?: string;
  indicators: Record<string, number | null>;
  trade?: Record<string, string | number | null> | null;
  longbridge_order?: Record<string, string | number | boolean | null | unknown> | null;
};

export type IntradayPosition = {
  symbol: string;
  quantity: number;
  avg_price: number;
  entry_time: string;
  last_price: number;
  unrealized_pnl: number;
};

export type IntradayState = {
  cash: number;
  initial_cash: number;
  equity: number;
  day: string;
  day_start_equity: number;
  daily_loss_pct: number;
  daily_stop: boolean;
  realized_pnl: number;
  unrealized_pnl: number;
  positions: Record<string, IntradayPosition>;
  trades: Array<Record<string, string | number | null>>;
  last_signals: IntradaySignal[];
};

export type IntradayReport = {
  report_dir: string;
  generated_at?: string;
  symbols?: string[];
  auto_fetched_symbols?: string[];
  auto_fetch_count?: number;
  metrics: Record<string, number>;
  equity_curve: Array<{
    timestamp: string;
    cash: number;
    equity: number;
    daily_loss_pct?: number;
    positions?: Record<string, IntradayPosition> | string;
  }>;
  daily_summary: Array<Record<string, string | number | null>>;
  trades: Array<Record<string, string | number | null>>;
  signals: IntradaySignal[];
};

export type IntradayAutoTradeState = {
  enabled: boolean;
  mode: string;
  updated_at?: string | null;
  error?: string;
  confirmed_non_simulated?: boolean;
  account?: {
    account_type?: string | null;
    account_name?: string | null;
    account_label?: string | null;
    account_type_label?: string | null;
    account_channel?: string | null;
    account_no_masked?: string | null;
    is_simulated?: boolean;
    requires_confirmation?: boolean;
    source?: string;
    error?: string;
  } | null;
};

export type LongbridgePaperSummary = {
  fetched_at?: string;
  account: unknown;
  positions: unknown;
  orders: unknown;
  executions?: unknown;
};

export type LongbridgePaperOrderPayload = {
  symbol: string;
  side: "buy" | "sell";
  quantity: number;
  order_type: string;
  price?: number | null;
  time_in_force: string;
};
