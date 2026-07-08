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
  IntradayAutoTradeState,
  IntradayReport,
  IntradaySignal,
  IntradayState,
  KlinePoint,
  LongbridgePaperOrderPayload,
  LongbridgePaperSummary,
  RankRow,
  StockSummary,
  SymbolList
} from "./types";
import "./styles.css";

type View = "stock" | "strategy" | "intraday" | "intradayBacktest" | "longbridgePaper";
type AnyRecord = Record<string, unknown>;
const REPORT_PAGE_SIZE = 20;

const DEFAULT_PAPER_ORDER: LongbridgePaperOrderPayload = {
  symbol: "TSLA.US",
  side: "buy",
  quantity: 1,
  order_type: "market",
  price: null,
  time_in_force: "day"
};

function App() {
  const [view, setView] = useState<View>(
    window.location.pathname.startsWith("/strategy")
      ? "strategy"
      : window.location.pathname.startsWith("/intraday-backtest")
        ? "intradayBacktest"
        : window.location.pathname.startsWith("/longbridge-paper")
          ? "longbridgePaper"
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
  const [selectedBacktestSymbols, setSelectedBacktestSymbols] = useState<string[]>([]);
  const [paperSummary, setPaperSummary] = useState<LongbridgePaperSummary | null>(null);
  const [autoTrade, setAutoTrade] = useState<IntradayAutoTradeState | null>(null);
  const [paperOrder, setPaperOrder] = useState<LongbridgePaperOrderPayload>(DEFAULT_PAPER_ORDER);
  const [paperCancelOrderId, setPaperCancelOrderId] = useState("");
  const [paperOperationResult, setPaperOperationResult] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [runningBacktest, setRunningBacktest] = useState(false);
  const [loadingPaper, setLoadingPaper] = useState(false);
  const [submittingPaper, setSubmittingPaper] = useState(false);
  const [updatingAutoTrade, setUpdatingAutoTrade] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.config(), api.symbols()])
      .then(([configPayload, symbolPayload]) => {
        setConfig(configPayload);
        setSymbols(symbolPayload);
        const configuredIntradaySymbols = getIntradayConfigSymbols(configPayload);
        setSelectedBacktestSymbols(configuredIntradaySymbols);
        const preferred = symbolPayload.cached.includes("TSLA.US") ? "TSLA.US" : symbolPayload.cached[0] ?? configPayload.universe[0];
        setSymbol(preferred);
        setPaperOrder((current) => ({ ...current, symbol: configuredIntradaySymbols[0] ?? preferred ?? current.symbol }));
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
    api.intradayState()
      .then((statePayload) => setIntraday(statePayload))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [view]);

  useEffect(() => {
    if (view !== "intradayBacktest") return;
    setLoading(true);
    setError(null);
    api.intradayReport()
      .then((reportPayload) => setIntradayReport(reportPayload))
      .catch(() => setIntradayReport(null))
      .finally(() => setLoading(false));
  }, [view]);

  useEffect(() => {
    if (view !== "longbridgePaper") return;
    loadPaperSummary();
  }, [view]);

  const selectedRank = useMemo(() => rank.find((row) => row.symbol === symbol), [rank, symbol]);
  const intradayConfigSymbols = useMemo(() => getIntradayConfigSymbols(config), [config]);
  const t = copy[language];

  function toggleLanguage() {
    const nextLanguage = language === "zh" ? "en" : "zh";
    setLanguage(nextLanguage);
    window.localStorage.setItem("stock_quant_language", nextLanguage);
  }

  function navigate(nextView: View) {
    setView(nextView);
    const nextPath = nextView === "strategy"
      ? "/strategy"
      : nextView === "intraday"
        ? "/intraday"
        : nextView === "intradayBacktest"
          ? "/intraday-backtest"
          : nextView === "longbridgePaper"
            ? "/longbridge-paper"
            : `/stocks/${symbol}`;
    window.history.replaceState(null, "", nextPath);
  }

  function changeSymbol(nextSymbol: string) {
    const normalized = nextSymbol.trim().toUpperCase();
    setSymbol(normalized);
    if (view === "stock") window.history.replaceState(null, "", `/stocks/${normalized}`);
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
    if (selectedBacktestSymbols.length === 0) {
      setError("请至少选择一个日内回测标的");
      return;
    }
    setRunningBacktest(true);
    setError(null);
    try {
      const payload = await api.intradayBacktest(selectedBacktestSymbols);
      setIntradayReport(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Intraday backtest failed");
    } finally {
      setRunningBacktest(false);
    }
  }

  async function loadPaperSummary() {
    setLoadingPaper(true);
    setError(null);
    try {
      const [summaryPayload, autoTradePayload] = await Promise.all([
        api.longbridgePaperSummary(),
        api.intradayAutoTrade()
      ]);
      setPaperSummary(summaryPayload);
      setAutoTrade(autoTradePayload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Longbridge paper summary failed");
    } finally {
      setLoadingPaper(false);
      setLoading(false);
    }
  }

  async function updateAutoTrade(enabled: boolean) {
    setUpdatingAutoTrade(true);
    setError(null);
    try {
      const payload = await api.updateIntradayAutoTrade(enabled);
      setAutoTrade(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update auto trade failed");
    } finally {
      setUpdatingAutoTrade(false);
    }
  }

  async function submitPaperOrder() {
    setSubmittingPaper(true);
    setError(null);
    setPaperOperationResult(null);
    try {
      const payload = await api.longbridgePaperOrder({
        ...paperOrder,
        symbol: paperOrder.symbol.trim().toUpperCase(),
        quantity: Number(paperOrder.quantity),
        price: paperOrder.order_type === "market" ? null : paperOrder.price
      });
      setPaperOperationResult(payload);
      await loadPaperSummary();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Longbridge paper order failed");
    } finally {
      setSubmittingPaper(false);
    }
  }

  async function cancelPaperOrder() {
    const orderId = paperCancelOrderId.trim();
    if (!orderId) return;
    setSubmittingPaper(true);
    setError(null);
    setPaperOperationResult(null);
    try {
      const payload = await api.longbridgePaperCancel(orderId);
      setPaperOperationResult(payload);
      setPaperCancelOrderId("");
      await loadPaperSummary();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Longbridge paper cancel failed");
    } finally {
      setSubmittingPaper(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><TrendingUp size={24} /><div><strong>Stock Quant</strong><span>{t.appSubtitle}</span></div></div>
        <button className={view === "stock" ? "nav active" : "nav"} onClick={() => navigate("stock")}><LineChart size={18} />{t.stockAnalysis}</button>
        <button className={view === "strategy" ? "nav active" : "nav"} onClick={() => navigate("strategy")}><BarChart3 size={18} />{t.strategyBacktest}</button>
        <button className={view === "intraday" ? "nav active" : "nav"} onClick={() => navigate("intraday")}><Zap size={18} />{t.intradayTrading}</button>
        <button className={view === "intradayBacktest" ? "nav active" : "nav"} onClick={() => navigate("intradayBacktest")}><BarChart3 size={18} />{t.intradayBacktest}</button>
        <button className={view === "longbridgePaper" ? "nav active" : "nav"} onClick={() => navigate("longbridgePaper")}><Activity size={18} />{t.longbridgePaper}</button>
        <div className="cache-note"><Database size={16} /><span>{symbols?.cached.length ?? 0} {t.cachedSymbols}</span></div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div className="symbol-picker">
            <Search size={18} />
            <input value={symbol} onChange={(event) => changeSymbol(event.target.value)} list="symbols" aria-label="Symbol" />
            <datalist id="symbols">{symbols?.cached.map((cachedSymbol) => <option key={cachedSymbol} value={cachedSymbol} />)}</datalist>
          </div>
          <div className="topbar-actions">
            <button className="text-button" onClick={toggleLanguage} title={t.languageTitle}><Languages size={17} />{t.languageToggle}</button>
            <button className="icon-button" onClick={refreshSymbol} disabled={refreshing} title={t.refreshCachedData}>{refreshing ? <Loader2 className="spin" size={18} /> : <RefreshCw size={18} />}</button>
          </div>
        </header>

        {error && <div className="alert">{error}</div>}
        {loading && <div className="loading"><Loader2 className="spin" size={20} /> {t.loadingMarketData}</div>}
        {!loading && view === "stock" && summary && <StockView t={t} summary={summary} klines={klines} rankRow={selectedRank} benchmark={config?.benchmark ?? "SPY.US"} />}
        {!loading && view === "strategy" && backtest && <StrategyView t={t} rank={rank} backtest={backtest} topN={Number(config?.strategy.top_n ?? 10)} />}
        {!loading && view === "intraday" && intraday && <IntradayView t={t} state={intraday} evaluating={evaluating} onEvaluate={evaluateIntraday} />}
        {!loading && view === "intradayBacktest" && (
          <IntradayBacktestView
            t={t}
            report={intradayReport}
            configuredSymbols={intradayConfigSymbols}
            selectedSymbols={selectedBacktestSymbols}
            onSelectedSymbolsChange={setSelectedBacktestSymbols}
            runningBacktest={runningBacktest}
            onRunBacktest={runIntradayBacktest}
          />
        )}
        {!loading && view === "longbridgePaper" && (
          <LongbridgePaperView
            t={t}
            summary={paperSummary}
            autoTrade={autoTrade}
            order={paperOrder}
            cancelOrderId={paperCancelOrderId}
            operationResult={paperOperationResult}
            loading={loadingPaper}
            submitting={submittingPaper}
            updatingAutoTrade={updatingAutoTrade}
            onRefresh={loadPaperSummary}
            onAutoTradeChange={updateAutoTrade}
            onOrderChange={setPaperOrder}
            onSubmitOrder={submitPaperOrder}
            onCancelOrderIdChange={setPaperCancelOrderId}
            onCancelOrder={cancelPaperOrder}
          />
        )}
      </main>
    </div>
  );
}

function StockView({ t, summary, klines, rankRow, benchmark }: { t: Copy; summary: StockSummary; klines: KlinePoint[]; rankRow?: RankRow; benchmark: string }) {
  const recentPerformance = [
    { label: "5D", value: summary.return5 },
    { label: "20D", value: summary.return20 },
    { label: "60D", value: summary.return60 },
    { label: "120D", value: summary.return120 }
  ];

  return (
    <section className="stack">
      <div className="title-row"><div><p className="eyebrow">{t.stockAnalysis}</p><h1>{summary.symbol}</h1></div><div className="quote"><span>{formatNumber(summary.last)}</span><strong className={signedClass(summary.change_percent)}>{formatPercent(summary.change_percent)}</strong></div></div>
      <div className="metric-grid"><Metric label={t.open} value={formatNumber(summary.open)} /><Metric label={t.highLow} value={`${formatNumber(summary.high)} / ${formatNumber(summary.low)}`} /><Metric label={t.volume} value={formatCompact(summary.volume)} /><Metric label={t.lastDate} value={summary.date} /></div>
      <div className="panel chart-panel"><div className="panel-header"><h2>{t.price}</h2><span>{t.ohlcCachedHistory}</span></div><KlineChart data={klines} /></div>
      <div className="two-column">
        <div className="panel"><div className="panel-header"><h2>{t.technicalSnapshot}</h2><span>{t.trendAndVolatility}</span></div><div className="metric-list"><Metric label="SMA 20" value={formatNumber(summary.sma20)} /><Metric label="SMA 50" value={formatNumber(summary.sma50)} /><Metric label="SMA 200" value={formatNumber(summary.sma200)} /><Metric label="RSI 14" value={formatNumber(summary.rsi14)} /><Metric label={t.annualizedVol60D} value={formatPercent(summary.annualized_volatility60)} /><Metric label={t.benchmarkFilter} value={benchmark} /></div></div>
        <div className="panel"><div className="panel-header"><h2>{t.recentPerformance}</h2><span>{t.trailingReturns}</span></div><ResponsiveContainer width="100%" height={260}><BarChart data={recentPerformance}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="label" /><YAxis tickFormatter={(value) => `${Math.round(Number(value) * 100)}%`} /><Tooltip formatter={(value) => formatPercent(Number(value))} /><Bar dataKey="value" radius={[4, 4, 0, 0]} fill="#2563eb" /></BarChart></ResponsiveContainer></div>
      </div>
      <div className="panel"><div className="panel-header"><h2>{t.factorRank}</h2><span>{t.defaultUniverseScore}</span></div>{rankRow ? <div className="metric-grid compact"><Metric label={t.rank} value={`#${rankRow.rank}`} /><Metric label={t.score} value={formatNumber(rankRow.score, 4)} /><Metric label={t.momentum} value={formatPercent(rankRow.momentum)} /><Metric label={t.quality} value={formatNumber(rankRow.quality, 4)} /></div> : <p className="muted">{t.loadRanksHint}</p>}</div>
    </section>
  );
}

function StrategyView({ t, rank, backtest, topN }: { t: Copy; rank: RankRow[]; backtest: BacktestResult; topN: number }) {
  const weights = Object.entries(backtest.weights).map(([symbol, weight]) => ({ symbol, weight }));
  const riskStatus = backtest.risk_status === "full" ? t.full : backtest.risk_status === "defensive" ? t.defensive : backtest.risk_status;

  return (
    <section className="stack">
      <div className="title-row"><div><p className="eyebrow">{t.strategyBacktest}</p><h1>{t.multiFactorRotation}</h1></div><div className="risk-pill"><Activity size={16} />{riskStatus} {t.exposure} {formatPercent(backtest.exposure)}</div></div>
      <div className="metric-grid"><Metric label={t.cagr} value={formatPercent(backtest.metrics.cagr)} /><Metric label={t.sharpe} value={formatNumber(backtest.metrics.sharpe)} /><Metric label={t.maxDrawdown} value={formatPercent(backtest.metrics.max_drawdown)} /><Metric label={t.volatility} value={formatPercent(backtest.metrics.volatility)} /></div>
      <div className="panel chart-panel"><div className="panel-header"><h2>{t.equityCurve}</h2><span>{t.currentCachedWindowBacktest}</span></div><ResponsiveContainer width="100%" height={360}><AreaChart data={backtest.equity_curve}><defs><linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#2563eb" stopOpacity={0.28} /><stop offset="95%" stopColor="#2563eb" stopOpacity={0.02} /></linearGradient></defs><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="date" minTickGap={32} /><YAxis domain={["auto", "auto"]} /><Tooltip formatter={(value) => formatNumber(Number(value), 4)} /><Area type="monotone" dataKey="equity" stroke="#2563eb" fill="url(#equityFill)" strokeWidth={2} /></AreaChart></ResponsiveContainer></div>
      <div className="two-column"><div className="panel"><div className="panel-header"><h2>{t.targetWeights}</h2><span>Top {topN} {t.topSelectedSymbols}</span></div><ResponsiveContainer width="100%" height={300}><BarChart data={weights} layout="vertical" margin={{ left: 20 }}><CartesianGrid strokeDasharray="3 3" horizontal={false} /><XAxis type="number" tickFormatter={(value) => `${Math.round(Number(value) * 100)}%`} /><YAxis type="category" dataKey="symbol" width={78} /><Tooltip formatter={(value) => formatPercent(Number(value))} /><Bar dataKey="weight" fill="#0f766e" radius={[0, 4, 4, 0]} /></BarChart></ResponsiveContainer></div><div className="panel"><div className="panel-header"><h2>{t.selectedSymbols}</h2><span>{t.currentFactorWinners}</span></div><div className="symbol-chips">{backtest.selected_symbols.map((selected) => <span key={selected}>{selected}</span>)}</div></div></div>
      <div className="panel table-panel"><div className="panel-header"><h2>{t.factorRanking}</h2><span>{rank.length} {t.symbols}</span></div><div className="table-scroll"><table><thead><tr><th>{t.rank}</th><th>{t.symbol}</th><th>{t.score}</th><th>{t.momentum}</th><th>{t.value}</th><th>{t.quality}</th><th>{t.lowVol}</th></tr></thead><tbody>{rank.map((row) => <tr key={row.symbol}><td>{row.rank}</td><td>{row.symbol}</td><td>{formatNumber(row.score, 4)}</td><td>{formatPercent(row.momentum)}</td><td>{formatNumber(row.value, 4)}</td><td>{formatNumber(row.quality, 4)}</td><td>{formatNumber(row.low_volatility, 4)}</td></tr>)}</tbody></table></div></div>
    </section>
  );
}

function IntradayView({ t, state, evaluating, onEvaluate }: { t: Copy; state: IntradayState; evaluating: boolean; onEvaluate: () => void }) {
  const positions = Object.values(state.positions);
  const latestSignals = state.last_signals.slice(-25).reverse();
  const recentTrades = state.trades.slice(-20).reverse();

  return (
    <section className="stack">
      <div className="title-row"><div><p className="eyebrow">{t.intradayTrading}</p><h1>{t.paperPortfolio}</h1></div><button className="text-button wide" onClick={onEvaluate} disabled={evaluating}>{evaluating ? <Loader2 className="spin" size={17} /> : <Zap size={17} />}{t.evaluateIntraday}</button></div>
      <div className="metric-grid"><Metric label={t.equity} value={formatNumber(state.equity)} /><Metric label={t.cash} value={formatNumber(state.cash)} /><Metric label={t.dailyLoss} value={formatPercent(state.daily_loss_pct)} /><Metric label={t.dailyStop} value={state.daily_stop ? t.active : t.normal} /></div>
      <div className="metric-grid compact"><Metric label={t.realizedPnl} value={formatNumber(state.realized_pnl)} /><Metric label={t.unrealizedPnl} value={formatNumber(state.unrealized_pnl)} /><Metric label="Day" value={state.day} /><Metric label={t.startEquity} value={formatNumber(state.day_start_equity)} /></div>
      <div className="panel table-panel"><div className="panel-header"><h2>{t.latestSignals}</h2><span>{latestSignals.length} {t.symbols}</span></div><SignalTable t={t} signals={latestSignals} /></div>
      <div className="two-column"><div className="panel table-panel"><div className="panel-header"><h2>{t.positions}</h2><span>{positions.length} {t.symbols}</span></div><div className="table-scroll"><table className="compact-table"><thead><tr><th>{t.symbol}</th><th>{t.quantity}</th><th>{t.avgPrice}</th><th>{t.lastPrice}</th><th>{t.unrealizedPnl}</th></tr></thead><tbody>{positions.map((position) => <tr key={position.symbol}><td>{position.symbol}</td><td>{position.quantity}</td><td>{formatNumber(position.avg_price)}</td><td>{formatNumber(position.last_price)}</td><td className={signedClass(position.unrealized_pnl)}>{formatNumber(position.unrealized_pnl)}</td></tr>)}</tbody></table></div></div><div className="panel table-panel"><div className="panel-header"><h2>{t.recentTrades}</h2><span>{recentTrades.length}</span></div><TradeTable t={t} trades={recentTrades} /></div></div>
    </section>
  );
}

function IntradayBacktestView({ t, report, configuredSymbols, selectedSymbols, onSelectedSymbolsChange, runningBacktest, onRunBacktest }: { t: Copy; report: IntradayReport | null; configuredSymbols: string[]; selectedSymbols: string[]; onSelectedSymbolsChange: (symbols: string[]) => void; runningBacktest: boolean; onRunBacktest: () => void }) {
  return (
    <section className="stack">
      <div className="title-row"><div><p className="eyebrow">{t.intradayBacktest}</p><h1>{t.intradayBacktestReport}</h1></div></div>
      <BacktestSymbolFilter t={t} symbols={configuredSymbols} selectedSymbols={selectedSymbols} onChange={onSelectedSymbolsChange} />
      <IntradayReportView t={t} report={report} selectedSymbols={selectedSymbols} runningBacktest={runningBacktest} onRunBacktest={onRunBacktest} />
    </section>
  );
}

function BacktestSymbolFilter({ t, symbols, selectedSymbols, onChange }: { t: Copy; symbols: string[]; selectedSymbols: string[]; onChange: (symbols: string[]) => void }) {
  function toggleSymbol(symbol: string) {
    if (selectedSymbols.includes(symbol)) {
      onChange(selectedSymbols.filter((item) => item !== symbol));
    } else {
      onChange([...selectedSymbols, symbol].sort());
    }
  }

  return (
    <div className="panel">
      <div className="panel-header"><h2>{t.backtestStockFilter}</h2><span>{selectedSymbols.length} / {symbols.length}</span></div>
      <p className="muted">{t.autoFetchHint}</p>
      <div className="symbol-chips">
        {symbols.map((item) => (
          <label key={item} className="text-button">
            <input type="checkbox" checked={selectedSymbols.includes(item)} onChange={() => toggleSymbol(item)} /> {item}
          </label>
        ))}
      </div>
      <div className="topbar-actions">
        <button className="text-button" onClick={() => onChange(symbols)}>{t.selectAll}</button>
        <button className="text-button" onClick={() => onChange([])}>{t.clearSelection}</button>
      </div>
    </div>
  );
}

function LongbridgePaperView({ t, summary, autoTrade, order, cancelOrderId, operationResult, loading, submitting, updatingAutoTrade, onRefresh, onAutoTradeChange, onOrderChange, onSubmitOrder, onCancelOrderIdChange, onCancelOrder }: { t: Copy; summary: LongbridgePaperSummary | null; autoTrade: IntradayAutoTradeState | null; order: LongbridgePaperOrderPayload; cancelOrderId: string; operationResult: unknown; loading: boolean; submitting: boolean; updatingAutoTrade: boolean; onRefresh: () => void; onAutoTradeChange: (enabled: boolean) => void; onOrderChange: (order: LongbridgePaperOrderPayload) => void; onSubmitOrder: () => void; onCancelOrderIdChange: (value: string) => void; onCancelOrder: () => void }) {
  const account = unwrapPaperPayload(summary?.account);
  const positions = rowsFromPayload(unwrapPaperPayload(summary?.positions));
  const orders = rowsFromPayload(unwrapPaperPayload(summary?.orders));
  const accountRows = rowsFromPayload(account);
  const accountRecord = accountRows[0] ?? (isRecord(account) ? account : {});
  const accountMetrics = buildAccountMetrics(accountRecord, positions);

  return (
    <section className="stack">
      <div className="title-row"><div><p className="eyebrow">{t.longbridgePaper}</p><h1>{t.paperTradingConsole}</h1></div><button className="text-button wide" onClick={onRefresh} disabled={loading}>{loading ? <Loader2 className="spin" size={17} /> : <RefreshCw size={17} />}{t.refreshPaper}</button></div>
      <div className="alert">{t.paperTradingRiskNote}</div>
      <AutoTradeSwitch state={autoTrade} updating={updatingAutoTrade} onChange={onAutoTradeChange} />
      <PaperAccountPanel metrics={accountMetrics} raw={summary?.account} />
      <div className="two-column">
        <div className="panel">
          <div className="panel-header"><h2>{t.orderForm}</h2><span>{t.submitPaperOrder}</span></div>
          <div className="metric-list">
            <label>{t.symbol}<input value={order.symbol} onChange={(event) => onOrderChange({ ...order, symbol: event.target.value.toUpperCase() })} /></label>
            <label>{t.side}<select value={order.side} onChange={(event) => onOrderChange({ ...order, side: event.target.value as "buy" | "sell" })}><option value="buy">{t.buy}</option><option value="sell">{t.sell}</option></select></label>
            <label>{t.quantity}<input type="number" min="1" value={order.quantity} onChange={(event) => onOrderChange({ ...order, quantity: Number(event.target.value) })} /></label>
            <label>{t.orderType}<select value={order.order_type} onChange={(event) => onOrderChange({ ...order, order_type: event.target.value })}><option value="market">Market</option><option value="limit">Limit</option></select></label>
            <label>{t.price}<input type="number" min="0" step="0.01" disabled={order.order_type === "market"} value={order.price ?? ""} onChange={(event) => onOrderChange({ ...order, price: event.target.value ? Number(event.target.value) : null })} /></label>
            <label>{t.timeInForce}<input value={order.time_in_force} onChange={(event) => onOrderChange({ ...order, time_in_force: event.target.value })} /></label>
          </div>
          <button className="text-button wide" onClick={onSubmitOrder} disabled={submitting}>{submitting ? <Loader2 className="spin" size={17} /> : <Zap size={17} />}{t.submitPaperOrder}</button>
        </div>
        <div className="panel">
          <div className="panel-header"><h2>{t.cancelPaperOrder}</h2><span>{t.orderId}</span></div>
          <div className="symbol-picker"><input value={cancelOrderId} onChange={(event) => onCancelOrderIdChange(event.target.value)} placeholder={t.orderId} /></div>
          <button className="text-button wide" onClick={onCancelOrder} disabled={submitting || !cancelOrderId.trim()}>{submitting ? <Loader2 className="spin" size={17} /> : <RefreshCw size={17} />}{t.cancelPaperOrder}</button>
          {operationResult !== null && <OperationResultView title={t.orderResult} payload={operationResult} />}
        </div>
      </div>
      <div className="two-column">
        <PaperPositionsPanel title={t.paperPositions} positions={positions} raw={summary?.positions} />
        <PaperOrdersPanel title={t.paperOrders} orders={orders} raw={summary?.orders} />
      </div>
    </section>
  );
}

function AutoTradeSwitch({ state, updating, onChange }: { state: IntradayAutoTradeState | null; updating: boolean; onChange: (enabled: boolean) => void }) {
  const enabled = Boolean(state?.enabled);
  return (
    <div className="panel">
      <div className="panel-header"><h2>盘中自动交易</h2><span>{enabled ? "已开启" : "已关闭"}</span></div>
      <p className="muted">开启后，日内交易轮询在开盘期间遇到 BUY / SELL 信号，会自动向当前 Longbridge CLI 模拟账户提交买卖委托；关闭时只生成信号，不下单。</p>
      <div className="metric-grid compact"><Metric label="状态" value={enabled ? "开启" : "关闭"} /><Metric label="模式" value={state?.mode ?? "longbridge_paper"} /><Metric label="更新时间" value={formatDateTime(state?.updated_at)} /></div>
      <button className="text-button wide" onClick={() => onChange(!enabled)} disabled={updating}>{updating ? <Loader2 className="spin" size={17} /> : <Zap size={17} />}{enabled ? "关闭自动交易" : "开启自动交易"}</button>
    </div>
  );
}

function PaperAccountPanel({ metrics, raw }: { metrics: Array<{ label: string; value: number | null }>; raw: unknown }) {
  const error = paperError(raw);
  const chartData = metrics.filter((metric) => metric.value !== null).map((metric) => ({ label: metric.label, value: Math.abs(Number(metric.value)) }));
  return (
    <div className="panel">
      <div className="panel-header"><h2>账户信息</h2><span>{error ? "读取失败" : "资产概览"}</span></div>
      {error && <p className="muted">{error}</p>}
      <div className="metric-grid compact">{metrics.map((metric) => <Metric key={metric.label} label={metric.label} value={formatNumber(metric.value)} />)}</div>
      {chartData.length > 0 && <ResponsiveContainer width="100%" height={260}><BarChart data={chartData}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="label" /><YAxis /><Tooltip formatter={(value) => formatNumber(Number(value))} /><Bar dataKey="value" radius={[4, 4, 0, 0]} fill="#2563eb" /></BarChart></ResponsiveContainer>}
    </div>
  );
}

function PaperPositionsPanel({ title, positions, raw }: { title: string; positions: AnyRecord[]; raw: unknown }) {
  const error = paperError(raw);
  const rows = positions.map((row) => ({
    symbol: valueText(row, ["symbol", "代码", "标的"]),
    quantity: valueNumber(row, ["quantity", "qty", "持仓", "数量"]),
    cost: valueNumber(row, ["cost_price", "avg_price", "average_cost", "成本价"]),
    price: valueNumber(row, ["last_price", "market_price", "current_price", "最新价"]),
    marketValue: valueNumber(row, ["market_value", "marketvalue", "持仓市值", "市值"]),
    pnl: valueNumber(row, ["unrealized_pnl", "unrealizedpl", "pnl", "盈亏", "未实现盈亏"])
  }));
  const chartData = rows.map((row) => ({ label: row.symbol, value: Math.abs(row.marketValue ?? 0) })).filter((row) => row.value > 0);
  return (
    <div className="panel table-panel">
      <div className="panel-header"><h2>{title}</h2><span>{error ? "读取失败" : `${rows.length} 个持仓`}</span></div>
      {error && <p className="muted">{error}</p>}
      {chartData.length > 0 && <ResponsiveContainer width="100%" height={240}><BarChart data={chartData} layout="vertical" margin={{ left: 20 }}><CartesianGrid strokeDasharray="3 3" horizontal={false} /><XAxis type="number" /><YAxis dataKey="label" type="category" width={76} /><Tooltip formatter={(value) => formatNumber(Number(value))} /><Bar dataKey="value" fill="#0f766e" radius={[0, 4, 4, 0]} /></BarChart></ResponsiveContainer>}
      <div className="table-scroll"><table className="compact-table"><thead><tr><th>标的</th><th>数量</th><th>成本价</th><th>最新价</th><th>市值</th><th>未实现盈亏</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.symbol}-${index}`}><td>{row.symbol}</td><td>{formatNumber(row.quantity, 0)}</td><td>{formatNumber(row.cost)}</td><td>{formatNumber(row.price)}</td><td>{formatNumber(row.marketValue)}</td><td className={signedClass(row.pnl)}>{formatNumber(row.pnl)}</td></tr>)}</tbody></table></div>
    </div>
  );
}

function PaperOrdersPanel({ title, orders, raw }: { title: string; orders: AnyRecord[]; raw: unknown }) {
  const error = paperError(raw);
  const rows = orders.map((row) => ({
    orderId: valueText(row, ["order_id", "orderid", "Order ID", "订单 ID"]),
    symbol: valueText(row, ["symbol", "代码", "标的"]),
    side: valueText(row, ["side", "方向"]),
    type: valueText(row, ["order_type", "ordertype", "Order Type", "类型"]),
    status: valueText(row, ["status", "状态"]),
    quantity: valueNumber(row, ["qty", "quantity", "submitted_quantity", "数量"]),
    price: valueNumber(row, ["price", "submitted_price", "价格"]),
    execQuantity: valueNumber(row, ["exec_qty", "executed_quantity", "filled_quantity", "Exec Qty", "成交数量"]),
    execPrice: valueNumber(row, ["exec_price", "executed_price", "avg_exec_price", "Exec Price", "成交价"]),
    createdAt: valueText(row, ["created_at", "createdAt", "Created At", "创建时间"])
  }));
  const statusCounts = Object.entries(rows.reduce<Record<string, number>>((counts, row) => {
    const status = row.status || "Unknown";
    counts[status] = (counts[status] ?? 0) + 1;
    return counts;
  }, {})).map(([label, value]) => ({ label, value }));
  return (
    <div className="panel table-panel">
      <div className="panel-header"><h2>{title}</h2><span>{error ? "读取失败" : `${rows.length} 条委托`}</span></div>
      {error && <p className="muted">{error}</p>}
      {statusCounts.length > 0 && <ResponsiveContainer width="100%" height={220}><BarChart data={statusCounts}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="label" /><YAxis allowDecimals={false} /><Tooltip formatter={(value) => formatNumber(Number(value), 0)} /><Bar dataKey="value" fill="#2563eb" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer>}
      <div className="table-scroll"><table className="compact-table"><thead><tr><th>订单 ID</th><th>标的</th><th>方向</th><th>类型</th><th>状态</th><th>数量</th><th>价格</th><th>成交量</th><th>成交价</th><th>创建时间</th></tr></thead><tbody>{rows.map((row, index) => <tr key={`${row.orderId}-${index}`}><td>{row.orderId}</td><td>{row.symbol}</td><td>{row.side}</td><td>{row.type}</td><td>{row.status}</td><td>{formatNumber(row.quantity, 0)}</td><td>{formatNumber(row.price)}</td><td>{formatNumber(row.execQuantity, 0)}</td><td>{formatNumber(row.execPrice)}</td><td>{row.createdAt}</td></tr>)}</tbody></table></div>
    </div>
  );
}

function OperationResultView({ title, payload }: { title: string; payload: unknown }) {
  const rows = rowsFromPayload(payload);
  const record = rows[0] ?? (isRecord(payload) ? payload : {});
  return <div className="panel"><div className="panel-header"><h2>{title}</h2></div><div className="metric-grid compact">{Object.entries(record).slice(0, 8).map(([key, value]) => <Metric key={key} label={key} value={String(value ?? "-")} />)}</div></div>;
}

function IntradayReportView({ t, report, selectedSymbols, runningBacktest, onRunBacktest }: { t: Copy; report: IntradayReport | null; selectedSymbols: string[]; runningBacktest: boolean; onRunBacktest: () => void }) {
  const [dailyPage, setDailyPage] = useState(1);
  const [tradePage, setTradePage] = useState(1);
  const [signalPage, setSignalPage] = useState(1);
  const runButton = <button className="text-button wide" onClick={onRunBacktest} disabled={runningBacktest || selectedSymbols.length === 0}>{runningBacktest ? <Loader2 className="spin" size={17} /> : <BarChart3 size={17} />}{runningBacktest ? t.runningIntradayBacktest : t.runIntradayBacktest}</button>;

  useEffect(() => {
    setDailyPage(1);
    setTradePage(1);
    setSignalPage(1);
  }, [report?.generated_at, report?.report_dir]);

  if (!report) {
    return <div className="panel"><div className="panel-header"><h2>{t.intradayBacktestReport}</h2>{runButton}</div><p className="muted">{t.noIntradayReport}</p><p className="muted">{t.selectedForBacktest}: {selectedSymbols.join(", ") || "-"}</p></div>;
  }

  const dailyRowsAll = report.daily_summary.slice().reverse();
  const tradesAll = report.trades.slice().reverse();
  const signalsAll = report.signals.filter((signal) => signal.action !== "HOLD").slice().reverse();
  const dailyRows = paginate(dailyRowsAll, dailyPage);
  const trades = paginate(tradesAll, tradePage);
  const signals = paginate(signalsAll, signalPage);

  return (
    <>
      <div className="panel"><div className="panel-header"><h2>{t.intradayBacktestReport}</h2>{runButton}</div><p className="muted">{t.reportDirectory}: {report.report_dir}</p><p className="muted">{t.selectedForBacktest}: {(report.symbols ?? selectedSymbols).join(", ") || "-"}</p>{report.auto_fetched_symbols && report.auto_fetched_symbols.length > 0 && <p className="muted">{t.autoFetchedSymbols}: {report.auto_fetched_symbols.join(", ")} · {report.auto_fetch_count ?? 1000}</p>}<div className="metric-grid compact"><Metric label={t.generatedAt} value={formatDateTime(report.generated_at)} /><Metric label={t.finalEquity} value={formatNumber(report.metrics.final_equity)} /><Metric label={t.totalReturn} value={formatPercent(report.metrics.total_return)} /><Metric label={t.maxDrawdown} value={formatPercent(report.metrics.max_drawdown)} /><Metric label={t.winRate} value={formatPercent(report.metrics.win_rate)} /><Metric label={t.profitFactor} value={formatNumber(report.metrics.profit_factor)} /><Metric label={t.tradeCount} value={formatNumber(report.metrics.trade_count, 0)} /></div></div>
      <div className="panel chart-panel"><div className="panel-header"><h2>{t.equityCurve}</h2><span>{t.intradayBacktestReport}</span></div><ResponsiveContainer width="100%" height={320}><AreaChart data={report.equity_curve}><defs><linearGradient id="intradayEquityFill" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#0f766e" stopOpacity={0.28} /><stop offset="95%" stopColor="#0f766e" stopOpacity={0.02} /></linearGradient></defs><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="timestamp" minTickGap={32} tickFormatter={(value) => formatShortTime(String(value))} /><YAxis domain={["auto", "auto"]} /><Tooltip labelFormatter={(value) => formatDateTime(String(value))} formatter={(value) => formatNumber(Number(value), 2)} /><Area type="monotone" dataKey="equity" stroke="#0f766e" fill="url(#intradayEquityFill)" strokeWidth={2} /></AreaChart></ResponsiveContainer></div>
      <div className="panel table-panel"><div className="panel-header"><h2>{t.dailySummary}</h2><span>{dailyRowsAll.length}</span></div><div className="table-scroll"><table className="compact-table"><thead><tr><th>Day</th><th>{t.startEquity}</th><th>{t.endEquity}</th><th>{t.dailyReturn}</th><th>{t.maxDrawdown}</th><th>{t.tradeCount}</th></tr></thead><tbody>{dailyRows.map((row, index) => <tr key={`${recordString(row, "day")}-${index}`}><td>{recordString(row, "day")}</td><td>{formatNumber(recordNumber(row, "start_equity"))}</td><td>{formatNumber(recordNumber(row, "end_equity"))}</td><td>{formatPercent(recordNumber(row, "daily_return"))}</td><td>{formatPercent(recordNumber(row, "max_drawdown"))}</td><td>{formatNumber(recordNumber(row, "trade_count"), 0)}</td></tr>)}</tbody></table></div><Pagination page={dailyPage} total={dailyRowsAll.length} onChange={setDailyPage} /></div>
      <div className="two-column"><div className="panel table-panel"><div className="panel-header"><h2>{t.latestBacktestTrades}</h2><span>{tradesAll.length}</span></div><TradeTable t={t} trades={trades} /><Pagination page={tradePage} total={tradesAll.length} onChange={setTradePage} /></div><div className="panel table-panel"><div className="panel-header"><h2>{t.backtestSignals}</h2><span>{signalsAll.length}</span></div><SignalTable t={t} signals={signals} /><Pagination page={signalPage} total={signalsAll.length} onChange={setSignalPage} /></div></div>
    </>
  );
}

function SignalTable({ t, signals }: { t: Copy; signals: IntradaySignal[] }) {
  return <div className="table-scroll"><table><thead><tr><th>{t.time}</th><th>{t.symbol}</th><th>{t.action}</th><th>{t.reason}</th><th>{t.price}</th><th>VWAP</th><th>EMA9</th><th>EMA21</th></tr></thead><tbody>{signals.map((signal, index) => <tr key={`${signal.symbol}-${signal.timestamp ?? signal.evaluated_at}-${index}`}><td>{formatDateTime(signal.timestamp ?? signal.evaluated_at)}</td><td>{signal.symbol}</td><td><span className={`action-badge ${signal.action.toLowerCase()}`}>{signal.action}</span></td><td>{signal.reason}</td><td>{formatNumber(signal.execution_price ?? signal.price)}</td><td>{formatNumber(signal.indicators?.vwap)}</td><td>{formatNumber(signal.indicators?.ema9)}</td><td>{formatNumber(signal.indicators?.ema21)}</td></tr>)}</tbody></table></div>;
}

function TradeTable({ t, trades }: { t: Copy; trades: Array<Record<string, string | number | null>> }) {
  return <div className="table-scroll"><table className="compact-table"><thead><tr><th>{t.time}</th><th>{t.symbol}</th><th>{t.action}</th><th>{t.quantity}</th><th>{t.price}</th><th>{t.reason}</th></tr></thead><tbody>{trades.map((trade, index) => <tr key={`${recordString(trade, "symbol")}-${recordString(trade, "timestamp")}-${index}`}><td>{formatDateTime(recordString(trade, "timestamp"))}</td><td>{recordString(trade, "symbol")}</td><td>{recordString(trade, "side")}</td><td>{formatNumber(recordNumber(trade, "quantity"), 0)}</td><td>{formatNumber(recordNumber(trade, "price"))}</td><td>{recordString(trade, "reason")}</td></tr>)}</tbody></table></div>;
}

function Pagination({ page, total, onChange }: { page: number; total: number; onChange: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / REPORT_PAGE_SIZE));
  if (total <= REPORT_PAGE_SIZE) return null;
  return (
    <div className="pagination">
      <button className="text-button" disabled={page <= 1} onClick={() => onChange(Math.max(1, page - 1))}>上一页</button>
      <span>{page} / {pages} · {total} 条 · 每页 {REPORT_PAGE_SIZE} 条</span>
      <button className="text-button" disabled={page >= pages} onClick={() => onChange(Math.min(pages, page + 1))}>下一页</button>
    </div>
  );
}

function paginate<T>(records: T[], page: number): T[] {
  const start = (page - 1) * REPORT_PAGE_SIZE;
  return records.slice(start, start + REPORT_PAGE_SIZE);
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>;
}

function recordNumber(record: Record<string, unknown>, key: string): number | null {
  const value = record[key];
  if (typeof value === "number") return value;
  if (typeof value === "string") {
    const parsed = Number(value.replace(/,/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function recordString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (value === null || value === undefined) return "-";
  return String(value);
}

function getIntradayConfigSymbols(config: AppConfig | null): string[] {
  const raw = config?.intraday.symbols;
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => String(item).trim().toUpperCase()).filter(Boolean).sort();
}

function unwrapPaperPayload(payload: unknown): unknown {
  if (isRecord(payload) && "ok" in payload) {
    return payload.ok === false ? null : payload.data;
  }
  return payload;
}

function paperError(payload: unknown): string | null {
  if (isRecord(payload) && payload.ok === false) return String(payload.error ?? "读取失败");
  return null;
}

function rowsFromPayload(payload: unknown): AnyRecord[] {
  if (Array.isArray(payload)) return payload.filter(isRecord);
  if (!isRecord(payload)) return [];
  for (const key of ["data", "items", "list", "records", "rows", "orders", "positions"]) {
    const value = payload[key];
    if (Array.isArray(value)) return value.filter(isRecord);
  }
  return [payload];
}

function buildAccountMetrics(account: AnyRecord, positions: AnyRecord[]): Array<{ label: string; value: number | null }> {
  const positionValue = sumByAlias(positions, ["market_value", "marketvalue", "持仓市值", "市值"]);
  return [
    { label: "总资产", value: valueNumber(account, ["total_assets", "totalasset", "net_assets", "nav", "总资产", "资产净值"]) },
    { label: "可用现金", value: valueNumber(account, ["cash", "available_cash", "availablecash", "buying_power", "available_funds", "现金", "可用现金", "购买力"]) },
    { label: "持仓市值", value: valueNumber(account, ["market_value", "stock_value", "holding_value", "securities_value", "持仓市值"]) ?? positionValue },
    { label: "盈亏", value: valueNumber(account, ["pnl", "profit", "unrealized_pnl", "daily_pnl", "盈亏", "未实现盈亏"]) }
  ];
}

function sumByAlias(records: AnyRecord[], aliases: string[]): number | null {
  const values = records.map((record) => valueNumber(record, aliases)).filter((value): value is number => value !== null);
  if (!values.length) return null;
  return values.reduce((total, value) => total + value, 0);
}

function valueNumber(record: AnyRecord, aliases: string[]): number | null {
  for (const key of findKeys(record, aliases)) {
    const value = recordNumber(record, key);
    if (value !== null) return value;
  }
  return null;
}

function valueText(record: AnyRecord, aliases: string[]): string {
  for (const key of findKeys(record, aliases)) {
    const value = record[key];
    if (value !== null && value !== undefined && String(value).trim() !== "") return String(value);
  }
  return "-";
}

function findKeys(record: AnyRecord, aliases: string[]): string[] {
  const normalizedAliases = aliases.map(normalizeKey);
  return Object.keys(record).filter((key) => normalizedAliases.includes(normalizeKey(key)));
}

function normalizeKey(key: string): string {
  return key.toLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5]/g, "");
}

function isRecord(value: unknown): value is AnyRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function formatDateTime(value: string | null | undefined): string {
  if (!value || value === "-") return "-";
  return value.replace("T", " ").slice(0, 16);
}

function formatShortTime(value: string): string {
  return value.replace("T", " ").slice(11, 16) || value;
}

createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
