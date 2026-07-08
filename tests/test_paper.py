from __future__ import annotations

from pathlib import Path

from stock_quant.paper import PaperPortfolio


def test_paper_portfolio_persists_processed_intraday_bars(tmp_path: Path) -> None:
    path = tmp_path / "paper_state.json"
    portfolio = PaperPortfolio.empty(100_000, day="2024-01-02")
    portfolio.processed_intraday_bars["AAPL.US"] = "2024-01-02T09:35:00"

    portfolio.save(path)
    loaded = PaperPortfolio.load(path, 100_000, day="2024-01-02")

    assert loaded.processed_intraday_bars == {"AAPL.US": "2024-01-02T09:35:00"}
    assert loaded.to_dict()["processed_intraday_bars"] == {"AAPL.US": "2024-01-02T09:35:00"}
