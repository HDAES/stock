import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  BarChart3,
  Database,
  Languages,
  LineChart,
  Loader2,
  RefreshCw,
  Search,
  TrendingUp,
  Zap
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { api } from "./api";
import { KlineChart } from "./price-chart";
import { formatCompact, formatNumber, formatPercent, signedClass } from "./format";
import { copy, type Copy, type Language } from "./i18n";
import type {
  AppConfig,
  BacktestResult,
  IntradayReport,
  IntradaySignal,
  IntradayState,
  KlinePoint,
  RankRow,
  StockSummary,
  SymbolList
} from "./types";
import "./styles.css";

type View = "stock" | "strategy" | "intraday";

function App() {
  const [view, setView] = useState<View>(
    window.location.pathname.startsWith("/strategy")
      ? "strategy"
      : window.location.pathname.startsWith("/intraday")
        ? "intraday"
        : "stock"
  );
  const [language, setLanguage] = useState<Language>(() => {
    const saved = window.localStorage.getItem("stock_quant_language");
    return saved === "en" || saved === "zh" ? saved : "zh";
  });
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [symbols, setSymbols] = useState<SymbolList | null>(null);
  const [symbol, setSymbol] = useState("TSLA.US");
  const [summary, setSummary] = useState<StockSummary | null>(null);
  const [klines, setKlines] = useState<KlinePoint[]>([]);
  const [rank, setRank] = useState<RankRow[]>([]);
  const [backtest, setBacktest] = useState<BacktestResult | null>(null);
  const [intraday, setIntraday] = useState<IntradayState | null>(null);
  const [intradayReport, setIntradayReport] = useState<IntradayReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [runningBacktest, setRunningBacktest] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.config(), api.symbols()])
      .then(([configPayload, symbolPayload]) => {
        setConfig(configPayload);
        setSymbols(symbolPayload);
        const preferred = symbolPayload.cached.includes("TSLA.US") ? "TSLA.US" : symbolPayload.cached[0] ?? configPayload.universe[0];
        setSymbol(preferred);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    setError(null);
    Promise.all([api.summary(symbol), api.klines(symbol)])
      .then(([summaryPayload, klinePayload]) => {
        setSummary(summaryPayload);
        setKlines(klinePayload);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [symbol]);

  useEffect(() => {
    if (view !== "strategy") return;
    setLoading(true);
    setError(null);
    Promise.all([api.rank(), api.backtest()])
      .then(([rankPayload, backtestPayload]) => {
        setRank(rankPayload);
        setBacktest(backtestPayload);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [view]);

  useEffect(() => {
    if (view !== "intraday") return;
    setLoading(true);
    setError(null);
    Promise.all([
      api.intradayState(),
      api.intradayReport().catch(() => null)
    ])
      .then(([statePayload, reportPayload]) => {
        setIntraday(statePayload);
        setIntradayReport(reportPayload);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [view]);

  const selectedRank = useMemo(() => rank.find((row) => row.symbol === symbol), [rank, symbol]);
  const t = copy[language];

  function toggleLanguage() {
    const nextLanguage = language === "zh" ? "en" : "zh";
    setLanguage(nextLanguage);
    window.localStorage.setItem("stock_quant_language", nextLanguage);
  }

  function navigate(nextView: View) {
    setView(nextView);
    const nextPath = nextView === "strategy" ? "/strategy" : nextView === "intraday" ? "/intraday" : `/stocks/${symbol}`;
    window.history.replaceState(null, "", nextPath);
  }

  function changeSymbol(nextSymbol: string) {
    const normalized = nextSymbol.trim().toUpperCase();
    setSymbol(normalized);
    if (view === "stock") {
      window.history.replaceState(null, "", `/stocks/${normalized}`);
    }
  }

  async function refreshSymbol() {
    if (!symbol) return;
    setRefreshing(true);
    setError(null);
    try {
      await api.refresh(symbol);
      const [summaryPayload, klinePayload] = await Promise.all([api.summary(symbol), api.klines(symbol)]);
      setSummary(summaryPayload);
      setKlines(klinePayload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh failed");
    } finally {
      setRefreshing(false);
    }
  }

  async function evaluateIntraday() {
    setEvaluating(true);
    setError(null);
    try {
      const payload = await api.intradayEvaluate();
      setIntraday(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Intraday evaluation failed");
    } finally {
      setEvaluating(false);
    }
  }

  async function runIntradayBacktest() {
    setRunningBacktest(true);
    setError(null);
    try {
      const payload = await api.intradayBacktest();
      setIntradayReport(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Intraday backtest failed");
    } finally {
      setRunningBacktest(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <TrendingUp size={24} />
          <div>
            <strong>Stock Quant</strong>
            <span>{t.appSubtitle}</span>
          </div>
        </div>
        <button className={view === "stock" ? "nav active" : "nav"} onClick={() => navigate("stock")}>
          <LineChart size={18} />
          {t.stockAnalysis}
        </button>
        <button className={view === "strategy" ? "nav active" : "nav"} onClick={() => navigate("strategy")}>
          <BarChart3 size={18} />
          {t.strategyBacktest}
        </button>
        <button className={view === "intraday" ? "nav active" : "nav"} onClick={() => navigate("intraday")}>
          <Zap size={18} />
          {t.intradayTrading}
        </button>
        <div className="cache-note">
          <Database size={16} />
          <span>{symbols?.cached.length ?? 0} {t.cachedSymbols}</span>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div className="symbol-picker">
            <Search size={18} />
            <input value={symbol} onChange={(event) => changeSymbol(event.target.value)} list="symbols" aria-label="Symbol" />
            <datalist id="symbols">
              {symbols?.cached.map((cachedSymbol) => <option key={cachedSymbol} value={cachedSymbol} />)}
            </datalist>
          </div>
          <div className="topbar-actions">
            <button className="text-button" onClick={toggleLanguage} title={t.languageTitle}>
              <Languages size={17} />
              {t.languageToggle}
            </button>
            <button className="icon-button" onClick={refreshSymbol} disabled={refreshing} title={t.refreshCachedData}>
              {refreshing ? <Loader2 className="spin" size={18} /> : <RefreshCw size={18} />}
            </button>
          </div>
        </header>

        {error && <div className="alert">{error}</div>}
        {loading && <div className="loading"><Loader2 className="spin" size={20} /> {t.loadingMarketData}</div>}

        {!loading && view === "stock" && summary && (
          <StockView t={t} summary={summary} klines={klines} rankRow={selectedRank} benchmark={config?.benchmark ?? "SPY.US"} />
        )}

        {!loading && view === "strategy" && backtest && (
          <StrategyView t={t} rank={rank} backtest={backtest} topN={Number(config?.strategy.top_n ?? 10)} />
        )}

        {!loading && view === "intraday" && intraday && (
          <IntradayView
            t={t}
            state={intraday}
            report={intradayReport}
            evaluating={evaluating}
            runningBacktest={runningBacktest}
            onEvaluate={evaluateIntraday}
            onRunBacktest={runIntradayBacktest}
          />
        )}
      </main>
    </div>
  );
}

function StockView({
  t,
  summary,
  klines,
  rankRow,
  benchmark
}: {
  t: Copy;
  summary: StockSummary;
  klines: KlinePoint[];
  rankRow?: RankRow;
  benchmark: string;
}) {
  const recentPerformance = [
    { label: "5D", value: summary.return5 },
    { label: "20D", value: summary.return20 },
    { label: "60D", value: summary.return60 },
    { label: "120D", value: summary.return120 }
  ];

  return (
    <section className="stack">
      <div className="title-row">
        <div>
          <p className="eyebrow">{t.stockAnalysis}</p>
          <h1>{summary.symbol}</h1>
        </div>
        <div className="quote">
          <span>{formatNumber(summary.last)}</span>
          <strong className={signedClass(summary.change_percent)}>{formatPercent(summary.change_percent)}</strong>
        </div>
      </div>

      <div className="metric-grid">
        <Metric label={t.open} value={formatNumber(summary.open)} />
        <Metric label={t.highLow} value={`${formatNumber(summary.high)} / ${formatNumber(summary.low)}`} />
        <Metric label={t.volume} value={formatCompact(summary.volume)} />
        <Metric label={t.lastDate} value={summary.date} />
      </div>

      <div className="panel chart-panel">
        <div className="panel-header">
          <h2>{t.price}</h2>
          <span>{t.ohlcCachedHistory}</span>
        </div>
        <KlineChart data={klines} />
      </div>

      <div className="two-column">
        <div className="panel">
          <div className="panel-header">
            <h2>{t.technicalSnapshot}</h2>
            <span>{t.trendAndVolatility}</span>
          </div>
          <div className="metric-list">
            <Metric label="SMA 20" value={formatNumber(summary.sma20)} />
            <Metric label="SMA 50" value={formatNumber(summary.sma50)} />
            <Metric label="SMA 200" value={formatNumber(summary.sma200)} />
            <Metric label="RSI 14" value={formatNumber(summary.rsi14)} />
            <Metric label={t.annualizedVol60D} value={formatPercent(summary.annualized_volatility60)} />
            <Metric label={t.benchmarkFilter} value={benchmark} />
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h2>{t.recentPerformance}</h2>
            <span>{t.trailingReturns}</span>
          </div>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={recentPerformance}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" />
              <YAxis tickFormatter={(value) => `${Math.round(Number(value) * 100)}%`} />
              <Tooltip formatter={(value) => formatPercent(Number(value))} />
              <Bar dataKey="value" radius={[4, 4, 0, 0]} fill="#2563eb" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <h2>{t.factorRank}</h2>
          <span>{t.defaultUniverseScore}</span>
        </div>
        {rankRow ? (
          <div className="metric-grid compact">
            <Metric label={t.rank} value={`#${rankRow.rank}`} />
            <Metric label={t.score} value={formatNumber(rankRow.score, 4)} />
            <Metric label={t.momentum} value={formatPercent(rankRow.momentum)} />
            <Metric label={t.quality} value={formatNumber(rankRow.quality, 4)} />
          </div>
        ) : (
          <p className="muted">{t.loadRanksHint}</p>
        )}
      </div>
    </section>
  );
}

function StrategyView({ t, rank, backtest, topN }: { t: Copy; rank: RankRow[]; backtest: BacktestResult; topN: number }) {
  const weights = Object.entries(backtest.weights).map(([symbol, weight]) => ({ symbol, weight }));
  const riskStatus = backtest.risk_status === "full" ? t.full : backtest.risk_status === "defensive" ? t.defensive : backtest.risk_status;

  return (
    <section className="stack">
      <div className="title-row">
        <div>
          <p className="eyebrow">{t.strategyBacktest}</p>
          <h1>{t.multiFactorRotation}</h1>
        </div>
        <div className="risk-pill"><Activity size={16} />{riskStatus} {t.exposure} {formatPercent(backtest.exposure)}</div>
      </div>

      <div className="metric-grid">
        <Metric label={t.cagr} value={formatPercent(backtest.metrics.cagr)} />
        <Metric label={t.sharpe} value={formatNumber(backtest.metrics.sharpe)} />
        <Metric label={t.maxDrawdown} value={formatPercent(backtest.metrics.max_drawdown)} />
        <Metric label={t.volatility} value={formatPercent(backtest.metrics.volatility)} />
      </div>

      <div className="panel chart-panel">
        <div className="panel-header">
          <h2>{t.equityCurve}</h2>
          <span>{t.currentCachedWindowBacktest}</span>
        </div>
        <ResponsiveContainer width="100%" height={360}>
          <AreaChart data={backtest.equity_curve}>
            <defs><linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#2563eb" stopOpacity={0.28} /><stop offset="95%" stopColor="#2563eb" stopOpacity={0.02} /></linearGradient></defs>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="date" minTickGap={32} />
            <YAxis domain={["auto", "auto"]} />
            <Tooltip formatter={(value) => formatNumber(Number(value), 4)} />
            <Area type="monotone" dataKey="equity" stroke="#2563eb" fill="url(#equityFill)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="two-column">
        <div className="panel">
          <div className="panel-header"><h2>{t.targetWeights}</h2><span>Top {topN} {t.topSelectedSymbols}</span></div>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={weights} layout="vertical" margin={{ left: 20 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" tickFormatter={(value) => `${Math.round(Number(value) * 100)}%`} />
              <YAxis type="category" dataKey="symbol" width={78} />
              <Tooltip formatter={(value) => formatPercent(Number(value))} />
              <Bar dataKey="weight" fill="#0f766e" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="panel">
          <div className="panel-header"><h2>{t.selectedSymbols}</h2><span>{t.currentFactorWinners}</span></div>
          <div className="symbol-chips">{backtest.selected_symbols.map((selected) => <span key={selected}>{selected}</span>)}</div>
        </div>
      </div>

      <div className="panel table-panel">
        <div className="panel-header"><h2>{t.factorRanking}</h2><span>{rank.length} {t.symbols}</span></div>
        <div className="table-scroll">
          <table><thead><tr><th>{t.rank}</th><th>{t.symbol}</th><th>{t.score}</th><th>{t.momentum}</th><th>{t.value}</th><th>{t.quality}</th><th>{t.lowVol}</th></tr></thead>
            <tbody>{rank.map((row) => (<tr key={row.symbol}><td>{row.rank}</td><td>{row.symbol}</td><td>{formatNumber(row.score, 4)}</td><td>{formatPercent(row.momentum)}</td><td>{formatNumber(row.value, 4)}</td><td>{formatNumber(row.quality, 4)}</td><td>{formatNumber(row.low_volatility, 4)}</td></tr>))}</tbody></table>
        </div>
      </div>
    </section>
  );
}

function IntradayView({
  t,
  state,
  report,
  evaluating,
  runningBacktest,
  onEvaluate,
  onRunBacktest
}: {
  t: Copy;
  state: IntradayState;
  report: IntradayReport | null;
  evaluating: boolean;
  runningBacktest: boolean;
  onEvaluate: () => void;
  onRunBacktest: () => void;
}) {
  const positions = Object.values(state.positions);
  const latestSignals = state.last_signals.slice(-25).reverse();
  const recentTrades = state.trades.slice(-20).reverse();

  return (
    <section className="stack">
      <div className="title-row">
        <div><p className="eyebrow">{t.intradayTrading}</p><h1>{t.paperPortfolio}</h1></div>
        <button className="text-button wide" onClick={onEvaluate} disabled={evaluating}>{evaluating ? <Loader2 className="spin" size={17} /> : <Zap size={17} />}{t.evaluateIntraday}</button>
      </div>

      <div className="metric-grid">
        <Metric label={t.equity} value={formatNumber(state.equity)} />
        <Metric label={t.cash} value={formatNumber(state.cash)} />
        <Metric label={t.dailyLoss} value={formatPercent(state.daily_loss_pct)} />
        <Metric label={t.dailyStop} value={state.daily_stop ? t.active : t.normal} />
      </div>

      <div className="metric-grid compact">
        <Metric label={t.realizedPnl} value={formatNumber(state.realized_pnl)} />
        <Metric label={t.unrealizedPnl} value={formatNumber(state.unrealized_pnl)} />
        <Metric label="Day" value={state.day} />
        <Metric label={t.startEquity} value={formatNumber(state.day_start_equity)} />
      </div>

      <IntradayReportView t={t} report={report} runningBacktest={runningBacktest} onRunBacktest={onRunBacktest} />

      <div className="panel table-panel">
        <div className="panel-header"><h2>{t.latestSignals}</h2><span>{latestSignals.length} {t.symbols}</span></div>
        <SignalTable t={t} signals={latestSignals} />
      </div>

      <div className="two-column">
        <div className="panel table-panel">
          <div className="panel-header"><h2>{t.positions}</h2><span>{positions.length} {t.symbols}</span></div>
          <div className="table-scroll"><table className="compact-table"><thead><tr><th>{t.symbol}</th><th>{t.quantity}</th><th>{t.avgPrice}</th><th>{t.lastPrice}</th><th>{t.unrealizedPnl}</th></tr></thead><tbody>{positions.map((position) => (<tr key={position.symbol}><td>{position.symbol}</td><td>{position.quantity}</td><td>{formatNumber(position.avg_price)}</td><td>{formatNumber(position.last_price)}</td><td className={signedClass(position.unrealized_pnl)}>{formatNumber(position.unrealized_pnl)}</td></tr>))}</tbody></table></div>
        </div>
        <div className="panel table-panel">
          <div className="panel-header"><h2>{t.recentTrades}</h2><span>{recentTrades.length}</span></div>
          <TradeTable t={t} trades={recentTrades} />
        </div>
      </div>
    </section>
  );
}

function IntradayReportView({
  t,
  report,
  runningBacktest,
  onRunBacktest
}: {
  t: Copy;
  report: IntradayReport | null;
  runningBacktest: boolean;
  onRunBacktest: () => void;
}) {
  const runButton = (
    <button className="text-button wide" onClick={onRunBacktest} disabled={runningBacktest}>
      {runningBacktest ? <Loader2 className="spin" size={17} /> : <BarChart3 size={17} />}
      {runningBacktest ? t.runningIntradayBacktest : t.runIntradayBacktest}
    </button>
  );

  if (!report) {
    return (
      <div className="panel">
        <div className="panel-header"><h2>{t.intradayBacktestReport}</h2>{runButton}</div>
        <p className="muted">{t.noIntradayReport}</p>
      </div>
    );
  }

  const dailyRows = report.daily_summary.slice(-10).reverse();
  const trades = report.trades.slice(-20).reverse();
  const signals = report.signals.slice(-25).reverse();

  return (
    <>
      <div className="panel">
        <div className="panel-header"><h2>{t.intradayBacktestReport}</h2>{runButton}</div>
        <p className="muted">{t.reportDirectory}: {report.report_dir}</p>
        <div className="metric-grid compact">
          <Metric label={t.finalEquity} value={formatNumber(report.metrics.final_equity)} />
          <Metric label={t.totalReturn} value={formatPercent(report.metrics.total_return)} />
          <Metric label={t.maxDrawdown} value={formatPercent(report.metrics.max_drawdown)} />
          <Metric label={t.winRate} value={formatPercent(report.metrics.win_rate)} />
          <Metric label={t.profitFactor} value={formatNumber(report.metrics.profit_factor)} />
          <Metric label={t.tradeCount} value={formatNumber(report.metrics.trade_count, 0)} />
        </div>
      </div>

      <div className="panel chart-panel">
        <div className="panel-header"><h2>{t.equityCurve}</h2><span>{t.intradayBacktestReport}</span></div>
        <ResponsiveContainer width="100%" height={320}>
          <AreaChart data={report.equity_curve}>
            <defs><linearGradient id="intradayEquityFill" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#0f766e" stopOpacity={0.28} /><stop offset="95%" stopColor="#0f766e" stopOpacity={0.02} /></linearGradient></defs>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="timestamp" minTickGap={32} tickFormatter={(value) => String(value).slice(5, 16)} />
            <YAxis domain={["auto", "auto"]} />
            <Tooltip formatter={(value) => formatNumber(Number(value), 2)} />
            <Area type="monotone" dataKey="equity" stroke="#0f766e" fill="url(#intradayEquityFill)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="panel table-panel">
        <div className="panel-header"><h2>{t.dailySummary}</h2><span>{dailyRows.length}</span></div>
        <div className="table-scroll"><table className="compact-table"><thead><tr><th>Day</th><th>{t.startEquity}</th><th>{t.endEquity}</th><th>{t.dailyReturn}</th><th>{t.maxDrawdown}</th><th>{t.tradeCount}</th></tr></thead><tbody>{dailyRows.map((row, index) => (<tr key={`${recordString(row, "day")}-${index}`}><td>{recordString(row, "day")}</td><td>{formatNumber(recordNumber(row, "start_equity"))}</td><td>{formatNumber(recordNumber(row, "end_equity"))}</td><td>{formatPercent(recordNumber(row, "daily_return"))}</td><td>{formatPercent(recordNumber(row, "max_drawdown"))}</td><td>{formatNumber(recordNumber(row, "trade_count"), 0)}</td></tr>))}</tbody></table></div>
      </div>

      <div className="two-column">
        <div className="panel table-panel"><div className="panel-header"><h2>{t.latestBacktestTrades}</h2><span>{trades.length}</span></div><TradeTable t={t} trades={trades} /></div>
        <div className="panel table-panel"><div className="panel-header"><h2>{t.backtestSignals}</h2><span>{signals.length}</span></div><SignalTable t={t} signals={signals} /></div>
      </div>
    </>
  );
}

function SignalTable({ t, signals }: { t: Copy; signals: IntradaySignal[] }) {
  return (
    <div className="table-scroll"><table><thead><tr><th>{t.symbol}</th><th>{t.action}</th><th>{t.reason}</th><th>{t.price}</th><th>VWAP</th><th>EMA9</th><th>EMA21</th></tr></thead><tbody>{signals.map((signal, index) => (<tr key={`${signal.symbol}-${signal.timestamp ?? signal.evaluated_at}-${index}`}><td>{signal.symbol}</td><td><span className={`action-badge ${signal.action.toLowerCase()}`}>{signal.action}</span></td><td>{signal.reason}</td><td>{formatNumber(signal.execution_price ?? signal.price)}</td><td>{formatNumber(signal.indicators?.vwap)}</td><td>{formatNumber(signal.indicators?.ema9)}</td><td>{formatNumber(signal.indicators?.ema21)}</td></tr>))}</tbody></table></div>
  );
}

function TradeTable({ t, trades }: { t: Copy; trades: Array<Record<string, string | number | null>> }) {
  return (
    <div className="table-scroll"><table className="compact-table"><thead><tr><th>{t.symbol}</th><th>{t.action}</th><th>{t.quantity}</th><th>{t.price}</th><th>{t.reason}</th></tr></thead><tbody>{trades.map((trade, index) => (<tr key={`${recordString(trade, "symbol")}-${recordString(trade, "timestamp")}-${index}`}><td>{recordString(trade, "symbol")}</td><td>{recordString(trade, "side")}</td><td>{formatNumber(recordNumber(trade, "quantity"), 0)}</td><td>{formatNumber(recordNumber(trade, "price"))}</td><td>{recordString(trade, "reason")}</td></tr>))}</tbody></table></div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>;
}

function recordNumber(record: Record<string, unknown>, key: string): number | null {
  const value = record[key];
  if (typeof value === "number") return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function recordString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (value === null || value === undefined) return "-";
  return String(value);
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
