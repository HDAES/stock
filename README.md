# Stock Quant System

First version of a US equity quant research system using Longbridge data.

The initial strategy is a monthly S&P 500 multi-factor rotation:

- Universe: S&P 500 constituents, optionally limited to the most liquid names.
- Factors: 60-day momentum, value, quality, and low volatility.
- Rebalance: monthly.
- Risk filter: reduce exposure when SPY is below its 200-day moving average.
- Output: ranked candidates, target portfolio, and backtest metrics.

This project is research-only. It does not place live orders.

> [!WARNING]
> **当前旧交易模块不得用于真实账户自动交易。**
>
> Phase 0 freezes the legacy trading implementation in `READ_ONLY` mode while
> `trading-core-v2` is under development. Account, position, order, execution,
> market-data, strategy, report, and backtest reads remain available. Legacy
> order submission, cancellation, and auto-trade enabling are blocked.
>
> The frozen entry points include `intraday_auto_trade.py`,
> `POST /api/longbridge-paper/order`, `POST /api/longbridge-paper/cancel`, and
> `POST /api/intraday/auto-trade`. A stale enabled state is rewritten as disabled
> when the application starts, so restarting the service cannot restore legacy
> auto trading.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
longbridge auth login
```

## Useful Commands

Check Longbridge access:

```bash
longbridge quote TSLA.US --format json
```

Fetch a small sample:

```bash
stock-quant fetch --symbols AAPL.US MSFT.US NVDA.US SPY.US --count 500
```

Run a backtest from cached data:

```bash
stock-quant backtest --config config/default.json
```

Generate the latest ranking from cached data:

```bash
stock-quant rank --config config/default.json
```

Send an account summary to the configured Feishu robot:

```bash
stock-quant account-report --config config/default.json --send
```

The Feishu webhook is read from `FEISHU_WEBHOOK_URL`. Keep the real value in a local `.env` file:

```bash
cp .env.example .env
# edit .env and fill FEISHU_WEBHOOK_URL
```

For US-market checks, schedule the command in New York time so daylight saving time is handled by the system timezone database. The two entries below run 10 minutes before the regular US equity open and 10 minutes after the regular close:

```cron
TZ=America/New_York
20 9 * * 1-5 cd /Users/hades/Documents/stock && .venv/bin/stock-quant account-report --config config/default.json --send
10 16 * * 1-5 cd /Users/hades/Documents/stock && .venv/bin/stock-quant account-report --config config/default.json --send
```

Start the API server:

```bash
uvicorn stock_quant.web.api:app --reload
```

Start both the API server and React web app with one command:

```bash
npm run dev:all
```

Start the React web app in another terminal:

```bash
npm install
npm run dev
```

Build the web app:

```bash
npm run build
```

## Project Layout

```text
config/              Strategy parameters.
frontend/            React web application for analysis and backtest views.
src/stock_quant/     Data, factors, strategy, and backtest code.
tests/               Focused tests for core calculations.
data/                Local cache, ignored by git.
reports/             Generated reports, ignored by git.
```

## First Milestone

1. Fetch 500 daily bars for SPY plus 20-50 liquid stocks.
2. Run the factor ranking.
3. Run a monthly backtest with transaction costs.
4. Compare performance against SPY.
