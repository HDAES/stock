from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import AppConfig
from .longbridge import LongbridgeClient, LongbridgeError
from .longbridge_paper import LongbridgePaperTradingClient, PaperOrderRequest


DEFAULT_MODE = "longbridge_paper"


def load_auto_trade_state(config: AppConfig) -> dict[str, Any]:
    path = auto_trade_state_path(config)
    if not path.exists():
        return _default_state()
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return _default_state(error="invalid_state_file")
    if not isinstance(payload, dict):
        return _default_state(error="invalid_state_payload")
    return {
        "enabled": bool(payload.get("enabled", False)),
        "mode": str(payload.get("mode") or DEFAULT_MODE),
        "updated_at": payload.get("updated_at"),
    }


def save_auto_trade_state(config: AppConfig, enabled: bool, mode: str = DEFAULT_MODE) -> dict[str, Any]:
    state = {
        "enabled": bool(enabled),
        "mode": mode or DEFAULT_MODE,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    path = auto_trade_state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))
    return state


def maybe_execute_auto_trade(
    config: AppConfig,
    client: LongbridgeClient,
    signal: dict[str, Any],
    trade: dict[str, Any] | None,
    logger: Any | None = None,
) -> dict[str, Any]:
    state = load_auto_trade_state(config)
    symbol = str(signal.get("symbol") or "").upper()
    action = str(signal.get("action") or "").upper()
    result: dict[str, Any] = {
        "enabled": state["enabled"],
        "mode": state["mode"],
        "submitted": False,
        "symbol": symbol,
        "action": action,
    }

    if not state["enabled"]:
        result["reason"] = "auto_trade_disabled"
        return result
    if action not in {"BUY", "SELL"}:
        result["reason"] = "not_trade_signal"
        return result
    if not trade:
        result["reason"] = "no_local_trade"
        return result

    quantity = _safe_int(trade.get("quantity"))
    if quantity is None or quantity < 1:
        result["reason"] = "invalid_quantity"
        return result

    price = _safe_float(signal.get("execution_price") or signal.get("price") or trade.get("price"))
    order_price = _round_price(price) if price is not None and price > 0 else None
    request = PaperOrderRequest(
        symbol=symbol,
        side=action.lower(),
        quantity=quantity,
        order_type="limit" if order_price is not None else "market",
        price=order_price,
        time_in_force="day",
    )

    try:
        order_payload = LongbridgePaperTradingClient(client).submit_order(request)
        result.update(
            {
                "submitted": True,
                "reason": "submitted",
                "quantity": quantity,
                "price": order_price,
                "order": order_payload,
            }
        )
        _log(logger, f"auto trade submitted {action} {symbol} qty={quantity} price={order_price}")
    except LongbridgeError as exc:
        result.update({"reason": "submit_failed", "error": str(exc)})
        _log(logger, f"auto trade failed {action} {symbol}: {exc}")
    except Exception as exc:  # defensive: keep signal loop alive
        result.update({"reason": "submit_failed", "error": str(exc)})
        _log(logger, f"auto trade failed {action} {symbol}: {exc}")

    record_auto_trade_event(config, {**result, "bar_id": signal.get("bar_id"), "timestamp": signal.get("timestamp")})
    return result


def record_auto_trade_event(config: AppConfig, event: dict[str, Any]) -> None:
    path = auto_trade_log_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"created_at": datetime.now().isoformat(timespec="seconds"), **event}
    with path.open("a") as handle:
        handle.write(json.dumps(payload) + "\n")


def auto_trade_state_path(config: AppConfig) -> Path:
    return _intraday_dir(config) / "auto_trade_state.json"


def auto_trade_log_path(config: AppConfig) -> Path:
    return _intraday_dir(config) / "auto_trades.jsonl"


def _intraday_dir(config: AppConfig) -> Path:
    return config.data.cache_dir.parent / "intraday"


def _default_state(error: str | None = None) -> dict[str, Any]:
    state: dict[str, Any] = {"enabled": False, "mode": DEFAULT_MODE, "updated_at": None}
    if error:
        state["error"] = error
    return state


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _safe_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _round_price(value: float) -> float:
    if value >= 1:
        return round(value, 2)
    return round(value, 4)


def _log(logger: Any | None, message: str) -> None:
    if logger is None:
        return
    line = f"[auto-trade] {datetime.now().isoformat(timespec='seconds')} {message}"
    try:
        logger(line, flush=True)
    except TypeError:
        logger(line)
