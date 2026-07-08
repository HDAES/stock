# Stock Quant System

First version of a US equity quant research system using Longbridge data.

The initial strategy is a monthly S&P 500 multi-factor rotation:

- Universe: S&P 500 constituents, optionally limited to the most liquid names.
- Factors: 60-day momentum, value, quality, and low volatility.
- Rebalance: monthly.
- Risk filter: reduce exposure when SPY is below its 200-day moving average.
- Output: ranked candidates, target portfolio, and backtest metrics.

This project is research-only. It does not place live orders.

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

Start the API server:

```bash
uvicorn stock_quant.web.api:app --reload
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
