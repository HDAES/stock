from __future__ import annotations

import json
import math
import re
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
        "account": payload.get("account") if isinstance(payload.get("account"), dict) else None,
        "confirmed_non_simulated": bool(payload.get("confirmed_non_simulated", False)),
    }


def save_auto_trade_state(
    config: AppConfig,
    enabled: bool,
    mode: str = DEFAULT_MODE,
    account_status: dict[str, Any] | None = None,
    confirmed_non_simulated: bool = False,
) -> dict[str, Any]:
    state = {
        "enabled": bool(enabled),
        "mode": mode or DEFAULT_MODE,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "account": account_status,
        "confirmed_non_simulated": bool(confirmed_non_simulated),
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

    account_status = _account_status_from_state(state)
    result["account"] = account_status
    _log(logger, f"auto trade account {format_account_status(account_status)}")
    if account_status["requires_confirmation"] and not state.get("confirmed_non_simulated"):
        result["reason"] = "account_confirmation_required"
        _log(logger, "auto trade blocked: non-simulated or unknown account requires explicit confirmation")
        record_auto_trade_event(config, {**result, "bar_id": signal.get("bar_id"), "timestamp": signal.get("timestamp")})
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


def detect_longbridge_account_status(
    client: LongbridgeClient,
    configured_label: str | None = None,
    configured_is_simulated: bool | None = None,
) -> dict[str, Any]:
    """Return a conservative account-risk view from Longbridge auth status."""
    try:
        payload = client.auth_status()
    except LongbridgeError as exc:
        return _configured_or_unknown_account_status(configured_label, configured_is_simulated, error=str(exc))
    except Exception as exc:
        return _configured_or_unknown_account_status(configured_label, configured_is_simulated, error=str(exc))

    account = payload.get("account") if isinstance(payload, dict) and isinstance(payload.get("account"), dict) else {}
    raw_account_type = account.get("account_type")
    account_name = account.get("name") or _pretty_account_name(client)
    account_label = str(account_name or raw_account_type or configured_label or "unknown")
    searchable_account_text = " ".join(
        str(value or "")
        for value in (
            raw_account_type,
            account_name,
            configured_label,
            account.get("account_channel"),
        )
    ).strip().lower()
    detected_simulated = bool(searchable_account_text) and any(
        token in searchable_account_text for token in SIMULATED_ACCOUNT_TYPE_TOKENS
    )
    is_simulated = detected_simulated if detected_simulated or configured_is_simulated is None else configured_is_simulated
    return {
        "account_type": raw_account_type,
        "account_name": account_name,
        "account_label": account_label,
        "account_type_label": str(raw_account_type or "unknown"),
        "account_channel": account.get("account_channel"),
        "account_no_masked": _mask_account_no(account.get("account_no")),
        "is_simulated": is_simulated,
        "requires_confirmation": not is_simulated,
        "source": _account_status_source(account_name, raw_account_type, configured_label),
    }


def format_account_status(status: dict[str, Any] | None) -> str:
    account = status or _unknown_account_status()
    return (
        f"account={account.get('account_label') or account.get('account_type_label') or 'unknown'} "
        f"type={account.get('account_type_label') or 'unknown'} "
        f"channel={account.get('account_channel') or 'unknown'} "
        f"account_no={account.get('account_no_masked') or 'unknown'} "
        f"simulated={bool(account.get('is_simulated'))} "
        f"requires_confirmation={bool(account.get('requires_confirmation', True))}"
    )


def _intraday_dir(config: AppConfig) -> Path:
    return config.data.cache_dir.parent / "intraday"


def _default_state(error: str | None = None) -> dict[str, Any]:
    state: dict[str, Any] = {
        "enabled": False,
        "mode": DEFAULT_MODE,
        "updated_at": None,
        "account": None,
        "confirmed_non_simulated": False,
    }
    if error:
        state["error"] = error
    return state


def _account_status_from_state(state: dict[str, Any]) -> dict[str, Any]:
    account = state.get("account")
    if isinstance(account, dict):
        return {
            "account_type": account.get("account_type"),
            "account_name": account.get("account_name"),
            "account_label": account.get("account_label") or account.get("account_name") or account.get("account_type_label") or str(account.get("account_type") or "unknown"),
            "account_type_label": account.get("account_type_label") or str(account.get("account_type") or "unknown"),
            "account_channel": account.get("account_channel"),
            "account_no_masked": account.get("account_no_masked"),
            "is_simulated": bool(account.get("is_simulated")),
            "requires_confirmation": bool(account.get("requires_confirmation", True)),
            **({"error": account.get("error")} if account.get("error") else {}),
        }
    return _unknown_account_status()


def _unknown_account_status(error: str | None = None) -> dict[str, Any]:
    status: dict[str, Any] = {
        "account_type": None,
        "account_name": None,
        "account_label": "unknown",
        "account_type_label": "unknown",
        "account_channel": None,
        "account_no_masked": None,
        "is_simulated": False,
        "requires_confirmation": True,
        "source": "unknown",
    }
    if error:
        status["error"] = error
    return status


def _configured_or_unknown_account_status(
    configured_label: str | None,
    configured_is_simulated: bool | None,
    error: str | None = None,
) -> dict[str, Any]:
    if not configured_label and configured_is_simulated is None:
        return _unknown_account_status(error)
    account_label = str(configured_label or "unknown")
    is_simulated = bool(configured_is_simulated)
    status = {
        "account_type": None,
        "account_name": configured_label or None,
        "account_label": account_label,
        "account_type_label": "unknown",
        "account_channel": None,
        "account_no_masked": None,
        "is_simulated": is_simulated,
        "requires_confirmation": not is_simulated,
        "source": "config",
    }
    if error:
        status["error"] = error
    return status


def _pretty_account_name(client: LongbridgeClient) -> str | None:
    try:
        text = client.auth_status_text()
    except Exception:
        return None
    for line in _strip_ansi(text).splitlines():
        stripped = line.strip()
        if stripped.startswith("Account"):
            value = stripped[len("Account") :].strip()
            return value or None
    return None


def _account_status_source(account_name: Any, account_type: Any, configured_label: str | None) -> str:
    if account_name:
        return "longbridge_pretty" if configured_label and account_name == configured_label else "longbridge"
    if account_type:
        return "longbridge"
    if configured_label:
        return "config"
    return "unknown"


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def _mask_account_no(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= 4:
        return "*" * len(text)
    return f"{'*' * max(0, len(text) - 4)}{text[-4:]}"


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
SIMULATED_ACCOUNT_TYPE_TOKENS = {"paper", "simulated", "simulation", "virtual", "demo", "mock", "sandbox", "模拟"}
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
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
