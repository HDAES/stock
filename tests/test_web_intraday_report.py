from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from stock_quant.intraday_data import intraday_history_path
from stock_quant.intraday_report import write_intraday_report
from stock_quant.web.api import create_app


def test_intraday_report_endpoint_reads_saved_report(tmp_path: Path) -> None:
    write_intraday_report(
        {
            "metrics": {"final_equity": 101000.0, "total_return": 0.01},
            "equity_curve": [{"timestamp": "2024-01-02T09:30:00", "equity": 100000.0}],
            "daily_summary": [],
            "trades": [],
            "signals": [],
        },
        tmp_path,
    )
    app = create_app(auto_intraday=False)
    client = TestClient(app)

    response = client.get("/api/intraday/report", params={"report_dir": str(tmp_path)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"]["final_equity"] == 101000.0
    assert payload["equity_curve"][0]["timestamp"] == "2024-01-02T09:30:00"


def test_intraday_report_endpoint_returns_404_when_missing(tmp_path: Path) -> None:
    app = create_app(auto_intraday=False)
    client = TestClient(app)

    response = client.get("/api/intraday/report", params={"report_dir": str(tmp_path)})

    assert response.status_code == 404


def test_intraday_backtest_endpoint_runs_and_saves_report(tmp_path: Path) -> None:
    data_dir = tmp_path / "intraday"
    report_dir = tmp_path / "report"
    data_dir.mkdir()
    intraday_history_path(data_dir, "TEST.US", "5m").write_text(
        json.dumps(
            [
                {"date": "2024-01-02 09:30:00", "open": 100, "high": 100, "low": 100, "close": 100, "volume": 100},
                {"date": "2024-01-02 09:35:00", "open": 100.4, "high": 100.4, "low": 100.4, "close": 100.4, "volume": 100},
                {"date": "2024-01-02 09:40:00", "open": 100.8, "high": 100.8, "low": 100.8, "close": 100.8, "volume": 100},
                {"date": "2024-01-02 09:45:00", "open": 102, "high": 102, "low": 102, "close": 102, "volume": 300},
                {"date": "2024-01-02 09:50:00", "open": 102.2, "high": 102.2, "low": 102.2, "close": 102.2, "volume": 100},
            ]
        )
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "benchmark": "SPY.US",
                "universe": ["TEST.US"],
                "data": {"cache_dir": str(tmp_path / "cache"), "history_count": 500},
                "strategy": {
                    "top_n": 10,
                    "rebalance": "M",
                    "momentum_window": 60,
                    "volatility_window": 60,
                    "risk_ma_window": 200,
                    "full_exposure": 1.0,
                    "defensive_exposure": 0.4,
                    "transaction_cost_bps": 10,
                },
                "intraday": {
                    "enabled": True,
                    "period": "5m",
                    "session": "intraday",
                    "poll_seconds": 60,
                    "initial_cash": 100000,
                    "max_position_pct": 0.2,
                    "stop_loss_pct": 0.02,
                    "take_profit_pct": 0.04,
                    "max_daily_loss_pct": 0.04,
                    "breakout_lookback": 3,
                    "volume_lookback": 3,
                    "volume_multiplier": 1.5,
                    "history_count": 500,
                    "data_dir": str(data_dir),
                    "commission_bps": 0,
                    "slippage_bps": 0,
                    "symbols": ["TEST.US"],
                },
                "factor_weights": {"momentum": 1.0},
            }
        )
    )
    app = create_app(config_path=config_path, auto_intraday=False)
    client = TestClient(app)

    response = client.post("/api/intraday/backtest", params={"report_dir": str(report_dir)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbols"] == ["TEST.US"]
    assert payload["metrics"]["final_equity"] > 0
    assert (report_dir / "metrics.json").exists()
