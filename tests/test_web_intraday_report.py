from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

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
