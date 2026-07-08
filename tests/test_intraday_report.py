from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from stock_quant.intraday_report import write_intraday_report


def test_write_intraday_report_creates_expected_files(tmp_path: Path) -> None:
    result = {
        "metrics": {"final_equity": 101000.0, "total_return": 0.01},
        "equity_curve": [
            {
                "timestamp": "2024-01-02T09:30:00",
                "equity": 100000.0,
                "positions": {"AAPL.US": {"quantity": 10}},
            }
        ],
        "daily_summary": [
            {
                "day": "2024-01-02",
                "start_equity": 100000.0,
                "end_equity": 101000.0,
            }
        ],
        "trades": [
            {
                "timestamp": "2024-01-02T09:35:00",
                "symbol": "AAPL.US",
                "side": "BUY",
                "quantity": 10,
            }
        ],
        "signals": [
            {
                "evaluated_at": "2024-01-02T09:30:00",
                "symbol": "AAPL.US",
                "action": "BUY",
            }
        ],
    }

    written = write_intraday_report(result, tmp_path)

    assert set(written) == {"metrics", "equity_curve", "daily_summary", "trades", "signals"}
    assert json.loads((tmp_path / "metrics.json").read_text()) == result["metrics"]
    assert (tmp_path / "equity_curve.csv").exists()
    assert (tmp_path / "daily_summary.csv").exists()
    assert (tmp_path / "trades.csv").exists()
    assert (tmp_path / "signals.csv").exists()

    equity = pd.read_csv(tmp_path / "equity_curve.csv")
    assert equity.loc[0, "timestamp"] == "2024-01-02T09:30:00"
    assert "AAPL.US" in equity.loc[0, "positions"]


def test_write_intraday_report_writes_empty_csv_for_empty_sections(tmp_path: Path) -> None:
    written = write_intraday_report({"metrics": {}}, tmp_path)

    assert written["trades"].read_text() == ""
    assert written["signals"].read_text() == ""
