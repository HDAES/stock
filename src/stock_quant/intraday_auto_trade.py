from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import AppConfig
from .longbridge import LongbridgeClient, LongbridgeError
from .longbridge_paper import LongbridgePaperTradingClient, PaperOrderRequest


DEFAULT_MODE = "longbridge_paper"


@dataclass(frozen=True)
class BrokerPosition:
    symbol: str
    quantity: int
    avg_price: float | None = None


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
    trade: dict[str, Any] | None = None,
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

    price = _safe_float(signal.get("execution_price") or signal.get("price") or (trade or {}).get("price"))
    order_price = _round_price(price) if price is not None and price > 0 else None
    paper_client = LongbridgePaperTradingClient(client)

    try:
        request = build_broker_order_request(config, paper_client, symbol, action, order_price)
        order_payload = paper_client.submit_order(request)
        result.update(
            {
                "submitted": True,
                "reason": "submitted",
                "quantity": request.quantity,
                "price": order_price,
                "order": order_payload,
            }
        )
        record_pending_auto_trade_order(config, request, order_payload, signal)
        _log(logger, f"auto trade submitted {action} {symbol} qty={request.quantity} price={order_price}")
    except LongbridgeError as exc:
        result.update({"reason": "submit_failed", "error": str(exc)})
        _log(logger, f"auto trade failed {action} {symbol}: {exc}")
    except Exception as exc:  # defensive: keep signal loop alive
        result.update({"reason": "submit_failed", "error": str(exc)})
        _log(logger, f"auto trade failed {action} {symbol}: {exc}")

    record_auto_trade_event(config, {**result, "bar_id": signal.get("bar_id"), "timestamp": signal.get("timestamp")})
    return result


def build_broker_order_request(
    config: AppConfig,
    paper_client: LongbridgePaperTradingClient,
    symbol: str,
    action: str,
    order_price: float | None,
) -> PaperOrderRequest:
    positions = broker_positions(paper_client)
    position = positions.get(symbol)
    if action == "SELL":
        if position is None or position.quantity < 1:
            raise LongbridgeError(f"No Longbridge paper position to sell for {symbol}")
        quantity = position.quantity
    elif action == "BUY":
        if position is not None and position.quantity > 0:
            raise LongbridgeError(f"Longbridge paper already has a position for {symbol}")
        if order_price is None or order_price <= 0:
            raise LongbridgeError(f"Cannot size buy order without a valid price for {symbol}")
        account = paper_client.account()
        buying_power = _extract_account_number(account, ACCOUNT_CASH_KEYS)
        equity = _extract_account_number(account, ACCOUNT_EQUITY_KEYS) or buying_power
        if buying_power is None or buying_power <= 0 or equity is None or equity <= 0:
            raise LongbridgeError("Cannot size buy order from Longbridge paper account")
        allocation = min(buying_power, equity * config.intraday.max_position_pct)
        quantity = int(allocation // order_price)
        if quantity < 1:
            raise LongbridgeError(f"Longbridge paper buying power is insufficient for {symbol}")
    else:
        raise LongbridgeError(f"Unsupported auto trade action: {action}")

    return PaperOrderRequest(
        symbol=symbol,
        side=action.lower(),
        quantity=quantity,
        order_type="limit" if order_price is not None else "market",
        price=order_price,
        time_in_force="day",
    )


def broker_positions(client: LongbridgePaperTradingClient) -> dict[str, BrokerPosition]:
    payload = client.positions()
    positions: dict[str, BrokerPosition] = {}
    for row in _rows_from_payload(payload):
        symbol = _extract_text(row, POSITION_SYMBOL_KEYS)
        quantity = _extract_number(row, POSITION_QUANTITY_KEYS)
        if not symbol or quantity is None:
            continue
        normalized = symbol.upper()
        positions[normalized] = BrokerPosition(
            symbol=normalized,
            quantity=max(0, int(quantity)),
            avg_price=_extract_number(row, POSITION_AVG_PRICE_KEYS),
        )
    return positions


def reconcile_auto_trade_orders(
    config: AppConfig,
    paper_client: LongbridgePaperTradingClient,
    logger: Any | None = None,
) -> list[dict[str, Any]]:
    records = load_auto_trade_orders(config)
    if not records:
        return []

    try:
        broker_rows = _rows_from_payload(paper_client.orders())
    except LongbridgeError as exc:
        _log(logger, f"order lifecycle skipped: {exc}")
        return records

    broker_orders = {
        order_id: row
        for row in broker_rows
        if (order_id := _extract_text(row, ORDER_ID_KEYS))
    }
    now = datetime.now()
    changed = False

    for record in records:
        status = str(record.get("status") or "").lower()
        if status in TERMINAL_ORDER_STATUSES:
            continue

        order_id = str(record.get("order_id") or "")
        broker_order = broker_orders.get(order_id)
        broker_status = _order_status(broker_order) if broker_order else None
        if broker_status in FILLED_ORDER_STATUSES:
            record.update({"status": "filled", "broker_status": broker_status, "updated_at": now.isoformat(timespec="seconds")})
            changed = True
            continue
        if broker_status in CANCELED_ORDER_STATUSES:
            record.update({"status": "canceled", "broker_status": broker_status, "updated_at": now.isoformat(timespec="seconds")})
            changed = True
            continue

        submitted_at = _parse_datetime(record.get("submitted_at"))
        timeout_seconds = _safe_int(record.get("timeout_seconds")) or config.intraday.order_timeout_seconds
        if submitted_at is None or (now - submitted_at).total_seconds() < timeout_seconds:
            if broker_status and broker_status != record.get("broker_status"):
                record.update({"broker_status": broker_status, "updated_at": now.isoformat(timespec="seconds")})
                changed = True
            continue

        if not order_id:
            record.update({"status": "expired_unknown_order_id", "updated_at": now.isoformat(timespec="seconds")})
            changed = True
            continue

        try:
            cancel_payload = paper_client.cancel_order(order_id)
            record.update(
                {
                    "status": "cancel_requested",
                    "broker_status": broker_status,
                    "cancel_requested_at": now.isoformat(timespec="seconds"),
                    "cancel": cancel_payload,
                    "updated_at": now.isoformat(timespec="seconds"),
                }
            )
            _log(logger, f"auto trade canceled stale order {order_id} {record.get('symbol')} age>{timeout_seconds}s")
        except LongbridgeError as exc:
            record.update(
                {
                    "status": "cancel_failed",
                    "broker_status": broker_status,
                    "cancel_error": str(exc),
                    "updated_at": now.isoformat(timespec="seconds"),
                }
            )
            _log(logger, f"auto trade cancel failed {order_id}: {exc}")
        changed = True

    if changed:
        save_auto_trade_orders(config, records)
    return records


def record_pending_auto_trade_order(
    config: AppConfig,
    request: PaperOrderRequest,
    order_payload: Any,
    signal: dict[str, Any],
) -> None:
    order_id = _extract_order_id(order_payload)
    records = load_auto_trade_orders(config)
    now = datetime.now().isoformat(timespec="seconds")
    records.append(
        {
            "order_id": order_id,
            "status": "pending" if order_id else "submitted_unknown_order_id",
            "symbol": request.symbol,
            "side": request.side.upper(),
            "quantity": request.quantity,
            "limit_price": request.price,
            "order_type": request.order_type,
            "time_in_force": request.time_in_force,
            "submitted_at": now,
            "updated_at": now,
            "timeout_seconds": config.intraday.order_timeout_seconds,
            "bar_id": signal.get("bar_id"),
            "signal_timestamp": signal.get("timestamp"),
            "broker_payload": order_payload,
        }
    )
    save_auto_trade_orders(config, records[-100:])


def load_auto_trade_orders(config: AppConfig) -> list[dict[str, Any]]:
    path = auto_trade_orders_path(config)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [record for record in payload if isinstance(record, dict)]


def save_auto_trade_orders(config: AppConfig, records: list[dict[str, Any]]) -> None:
    path = auto_trade_orders_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2))


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


def auto_trade_orders_path(config: AppConfig) -> Path:
    return _intraday_dir(config) / "auto_trade_orders.json"


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


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _extract_order_id(payload: Any) -> str | None:
    for row in _rows_from_payload(payload):
        order_id = _extract_text(row, ORDER_ID_KEYS)
        if order_id:
            return order_id
    return None


def _order_status(row: dict[str, Any] | None) -> str | None:
    if not row:
        return None
    status = _extract_text(row, ORDER_STATUS_KEYS)
    return status.lower() if status else None


def _log(logger: Any | None, message: str) -> None:
    if logger is None:
        return
    line = f"[auto-trade] {datetime.now().isoformat(timespec='seconds')} {message}"
    try:
        logger(line, flush=True)
    except TypeError:
        logger(line)


ACCOUNT_CASH_KEYS = [
    "cash",
    "available_cash",
    "availablecash",
    "buying_power",
    "buyingpower",
    "available_funds",
    "availablefunds",
    "可用现金",
    "购买力",
]
ACCOUNT_EQUITY_KEYS = [
    "total_assets",
    "totalassets",
    "net_assets",
    "netassets",
    "equity",
    "nav",
    "asset",
    "assets",
    "总资产",
    "资产净值",
]
POSITION_SYMBOL_KEYS = ["symbol", "code", "ticker", "security_code", "标的", "代码"]
POSITION_QUANTITY_KEYS = ["quantity", "qty", "available_quantity", "availableqty", "可用数量", "数量", "持仓数量"]
POSITION_AVG_PRICE_KEYS = ["avg_price", "average_price", "cost_price", "cost", "成本价", "平均价"]
ORDER_ID_KEYS = ["order_id", "orderid", "id", "订单id", "订单号"]
ORDER_STATUS_KEYS = ["status", "state", "order_status", "orderstatus", "状态"]
FILLED_ORDER_STATUSES = {"filled", "executed", "done", "completed", "fullfilled", "全部成交", "已成交"}
CANCELED_ORDER_STATUSES = {"canceled", "cancelled", "cancel", "withdrawn", "rejected", "expired", "已撤销", "撤单", "废单"}
TERMINAL_ORDER_STATUSES = {
    "filled",
    "canceled",
    "cancel_requested",
    "expired_unknown_order_id",
}


def _extract_account_number(payload: Any, aliases: list[str]) -> float | None:
    records = _rows_from_payload(payload)
    if not records and isinstance(payload, dict):
        records = [payload]
    for record in records:
        value = _extract_number(record, aliases)
        if value is not None:
            return value
    return None


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "items", "list", "records", "rows", "positions", "orders", "account"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _rows_from_payload(value)
            return nested or [value]
    return [payload]


def _extract_text(record: dict[str, Any], aliases: list[str]) -> str | None:
    for key in _find_keys(record, aliases):
        value = record.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _extract_number(record: dict[str, Any], aliases: list[str]) -> float | None:
    for key in _find_keys(record, aliases):
        value = record.get(key)
        if isinstance(value, str):
            value = value.replace(",", "")
        number = _safe_float(value)
        if number is not None:
            return number
    return None


def _find_keys(record: dict[str, Any], aliases: list[str]) -> list[str]:
    normalized_aliases = {_normalize_key(alias) for alias in aliases}
    return [key for key in record if _normalize_key(key) in normalized_aliases]


def _normalize_key(key: str) -> str:
    return "".join(char for char in key.lower() if char.isalnum() or "\u4e00" <= char <= "\u9fff")
