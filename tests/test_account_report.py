from __future__ import annotations

import json

from stock_quant.account_report import build_account_report, format_account_report, format_feishu_account_report, send_feishu_text


class FakeAccountClient:
    def __init__(self) -> None:
        self.assets_payload = {"currency": "USD", "net_assets": "10500", "total_cash": "500", "buy_power": "1000"}
        self.positions_payload = [
            {"symbol": "AAPL.US", "quantity": "10", "available_quantity": "8", "cost_price": "150", "currency": "USD"},
            {"symbol": "MSFT.US", "quantity": "5", "available_quantity": "5", "cost_price": "200", "currency": "USD"},
        ]
        self.quote_payload = [
            {"symbol": "AAPL.US", "last_done": "180"},
            {"symbol": "MSFT.US", "last_done": "220"},
        ]
        self.quote_symbols: tuple[str, ...] = ()

    def assets(self, currency: str = "USD"):
        return self.assets_payload

    def positions(self):
        return self.positions_payload

    def quote(self, *symbols: str):
        self.quote_symbols = symbols
        return self.quote_payload


def test_build_account_report_summarizes_assets_positions_and_quotes() -> None:
    client = FakeAccountClient()

    report = build_account_report(client)

    assert report["total_assets"] == 10500
    assert report["cash"] == 500
    assert report["buy_power"] == 1000
    assert report["holding_market_value"] == 2900
    assert report["holding_cost_value"] == 2500
    assert report["position_count"] == 2
    assert report["total_quantity"] == 15
    assert client.quote_symbols == ("AAPL.US", "MSFT.US")


def test_format_account_report_includes_core_fields() -> None:
    report = build_account_report(FakeAccountClient())

    text = format_account_report(report)

    assert "账户统计" in text
    assert "当前总资金: 10,500.00 USD" in text
    assert "持仓资金: 2,900.00 USD" in text
    assert "AAPL.US 数量=10" in text


def test_format_feishu_account_report_includes_account_and_auto_trade_state() -> None:
    report = build_account_report(FakeAccountClient())

    text = format_feishu_account_report(
        report,
        {
            "account_label": "Paper Trading",
            "account_type_label": "unknown",
            "account_no_masked": "*****6789",
        },
        {"enabled": True},
    )

    assert "账户: Paper Trading" in text
    assert "自动交易状态: 开启" in text
    assert "持仓数量: 2 个标的 / 15 股" in text
    assert "AAPL.US 数量=10 金额=1,800.00 USD 现价=180.00 USD 成本价=150.00 USD 盈亏=300.00 USD" in text


def test_send_feishu_text_skips_empty_webhook(monkeypatch) -> None:
    called = False

    def fake_urlopen(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("stock_quant.account_report.request.urlopen", fake_urlopen)

    send_feishu_text("", "hello")

    assert called is False


def test_send_feishu_text_posts_text_payload(monkeypatch) -> None:
    sent = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self):
            return b"ok"

    def fake_urlopen(req, timeout):
        sent["url"] = req.full_url
        sent["timeout"] = timeout
        sent["payload"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("stock_quant.account_report.request.urlopen", fake_urlopen)

    send_feishu_text("https://example.test/webhook", "hello", timeout=3)

    assert sent["url"] == "https://example.test/webhook"
    assert sent["timeout"] == 3
    assert sent["payload"] == {"msg_type": "text", "content": {"text": "hello"}}
