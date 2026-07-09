from __future__ import annotations

import json

from stock_quant.config import load_config


def _write_config(tmp_path, webhook_value: str):
    payload = {
        "benchmark": "SPY.US",
        "universe": ["AAPL.US"],
        "data": {"cache_dir": "data/cache", "history_count": 500},
        "strategy": {
            "top_n": 1,
            "rebalance": "M",
            "momentum_window": 60,
            "volatility_window": 60,
            "risk_ma_window": 200,
            "full_exposure": 1.0,
            "defensive_exposure": 0.4,
            "transaction_cost_bps": 10,
        },
        "intraday": {"symbols": ["AAPL.US"]},
        "notifications": {"feishu_webhook_url": webhook_value},
        "factor_weights": {
            "momentum": 0.3,
            "value": 0.25,
            "quality": 0.25,
            "low_volatility": 0.2,
        },
    }
    config_path = tmp_path / "config" / "default.json"
    config_path.parent.mkdir()
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    return config_path


def test_load_config_resolves_notification_secret_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "https://example.test/hook")
    config_path = _write_config(tmp_path, "${FEISHU_WEBHOOK_URL}")

    config = load_config(config_path)

    assert config.notifications.feishu_webhook_url == "https://example.test/hook"


def test_load_config_uses_empty_notification_secret_when_env_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("FEISHU_WEBHOOK_URL", raising=False)
    config_path = _write_config(tmp_path, "${FEISHU_WEBHOOK_URL}")

    config = load_config(config_path)

    assert config.notifications.feishu_webhook_url == ""
