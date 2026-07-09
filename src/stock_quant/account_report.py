from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Protocol
from urllib import request


class AccountReportClient(Protocol):
    def assets(self, currency: str = "USD") -> dict | list[dict]: ...

    def positions(self) -> dict | list[dict]: ...

    def quote(self, *symbols: str) -> list[dict]: ...


def build_account_report(
    client: AccountReportClient,
    currency: str = "USD",
    fetched_at: datetime | None = None,
) -> dict[str, Any]:
    """Fetch account assets and positions, then summarize current exposure."""
    assets_payload = client.assets(currency=currency)
    positions_payload = client.positions()
    positions = _normalize_positions(positions_payload)
    quote_prices = _quote_prices(client, [position["symbol"] for position in positions])

    enriched_positions: list[dict[str, Any]] = []
    holding_market_value = 0.0
    holding_cost_value = 0.0
    total_quantity = 0.0
    for position in positions:
        symbol = position["symbol"]
        quantity = position["quantity"]
        cost_price = position["cost_price"]
        current_price = quote_prices.get(symbol)
        market_value = _first_number(
            position.get("market_value"),
            _multiply(quantity, current_price),
            _multiply(quantity, cost_price),
        )
        cost_value = _first_number(position.get("cost_value"), _multiply(quantity, cost_price))
        unrealized_pnl = _first_number(position.get("unrealized_pnl"), _subtract(market_value, cost_value))
        if market_value is not None:
            holding_market_value += market_value
        if cost_value is not None:
            holding_cost_value += cost_value
        total_quantity += quantity
        enriched_positions.append(
            {
                **position,
                "current_price": current_price,
                "market_value": market_value,
                "cost_value": cost_value,
                "unrealized_pnl": unrealized_pnl,
            }
        )

    assets = _normalize_assets(assets_payload, currency.upper())
    total_assets = _first_number(assets.get("net_assets"), assets.get("total_assets"), assets.get("asset"))
    cash = _first_number(assets.get("total_cash"), assets.get("cash"), assets.get("cash_balance"))
    buy_power = _first_number(assets.get("buy_power"), assets.get("buying_power"))
    return {
        "fetched_at": (fetched_at or datetime.now()).isoformat(timespec="seconds"),
        "currency": currency.upper(),
        "total_assets": total_assets,
        "cash": cash,
        "buy_power": buy_power,
        "holding_market_value": holding_market_value,
        "holding_cost_value": holding_cost_value,
        "position_count": len(enriched_positions),
        "total_quantity": total_quantity,
        "positions": enriched_positions,
        "raw_assets": assets_payload,
    }


def format_account_report(report: dict[str, Any]) -> str:
    currency = report.get("currency", "")
    lines = [
        "账户统计",
        f"时间: {report.get('fetched_at', '')}",
        f"币种: {currency}",
        f"当前总资金: {_money(report.get('total_assets'), currency)}",
        f"现金: {_money(report.get('cash'), currency)}",
        f"可用购买力: {_money(report.get('buy_power'), currency)}",
        f"持仓资金: {_money(report.get('holding_market_value'), currency)}",
        f"持仓成本: {_money(report.get('holding_cost_value'), currency)}",
        f"持仓数量: {report.get('position_count', 0)} 个标的 / {_number(report.get('total_quantity'))} 股",
    ]
    positions = report.get("positions", [])
    if positions:
        lines.append("")
        lines.append("持仓明细:")
        for position in positions:
            lines.append(
                " - "
                f"{position.get('symbol')} "
                f"数量={_number(position.get('quantity'))} "
                f"可用={_number(position.get('available_quantity'))} "
                f"现价={_money(position.get('current_price'), position.get('currency') or currency)} "
                f"市值={_money(position.get('market_value'), position.get('currency') or currency)} "
                f"成本价={_money(position.get('cost_price'), position.get('currency') or currency)}"
            )
    else:
        lines.append("持仓明细: 无")
    return "\n".join(lines)


def format_feishu_account_report(
    report: dict[str, Any],
    account_status: dict[str, Any],
    auto_trade_state: dict[str, Any],
) -> str:
    currency = report.get("currency", "")
    account_label = account_status.get("account_label") or account_status.get("account_type_label") or "unknown"
    auto_enabled = bool(auto_trade_state.get("enabled"))
    lines = [
        "账户飞书报告",
        f"时间: {report.get('fetched_at', '')}",
        f"账户: {account_label}",
        f"账户类型: {account_status.get('account_type_label') or 'unknown'}",
        f"账号: {account_status.get('account_no_masked') or 'unknown'}",
        f"自动交易状态: {'开启' if auto_enabled else '关闭'}",
        f"币种: {currency}",
        f"当前总资金: {_money(report.get('total_assets'), currency)}",
        f"现金: {_money(report.get('cash'), currency)}",
        f"可用购买力: {_money(report.get('buy_power'), currency)}",
        f"持仓资金: {_money(report.get('holding_market_value'), currency)}",
        f"持仓成本: {_money(report.get('holding_cost_value'), currency)}",
        f"持仓数量: {report.get('position_count', 0)} 个标的 / {_number(report.get('total_quantity'))} 股",
    ]
    positions = report.get("positions", [])
    if positions:
        lines.append("")
        lines.append("持仓明细:")
        for position in positions:
            lines.append(
                " - "
                f"{position.get('symbol')} "
                f"数量={_number(position.get('quantity'))} "
                f"金额={_money(position.get('market_value'), position.get('currency') or currency)} "
                f"现价={_money(position.get('current_price'), position.get('currency') or currency)} "
                f"成本价={_money(position.get('cost_price'), position.get('currency') or currency)} "
                f"盈亏={_money(position.get('unrealized_pnl'), position.get('currency') or currency)}"
            )
    else:
        lines.append("持仓明细: 无")
    return "\n".join(lines)


def send_feishu_text(webhook_url: str, text: str, timeout: float = 10) -> None:
    url = webhook_url.strip()
    if not url:
        return
    payload = json.dumps({"msg_type": "text", "content": {"text": text}}).encode("utf-8")
    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as response:
        response.read()


def _normalize_assets(payload: Any, currency: str) -> dict[str, Any]:
    rows = _extract_records(payload)
    if not rows:
        return {}
    for row in rows:
        row_currency = str(row.get("currency", "")).upper()
        if row_currency == currency:
            return row
    return rows[0]


def _normalize_positions(payload: Any) -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    for row in _extract_records(payload):
        symbol = str(row.get("symbol", "")).upper()
        quantity = _first_number(row.get("quantity"), row.get("qty"), row.get("current_quantity"))
        if not symbol or quantity is None or quantity == 0:
            continue
        positions.append(
            {
                "symbol": symbol,
                "name": row.get("name") or row.get("stock_name") or "",
                "quantity": quantity,
                "available_quantity": _first_number(row.get("available_quantity"), row.get("available_qty")),
                "cost_price": _first_number(row.get("cost_price"), row.get("avg_price"), row.get("average_cost")),
                "currency": str(row.get("currency", "")).upper(),
                "market": row.get("market"),
                "market_value": _first_number(row.get("market_value"), row.get("value"), row.get("market_amount")),
                "cost_value": _first_number(row.get("cost_value"), row.get("cost_amount")),
                "unrealized_pnl": _first_number(
                    row.get("unrealized_pnl"),
                    row.get("unrealized_pl"),
                    row.get("pnl"),
                    row.get("profit_loss"),
                    row.get("pl"),
                ),
            }
        )
    return positions


def _quote_prices(client: AccountReportClient, symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    try:
        payload = client.quote(*symbols)
    except Exception:
        return {}
    prices: dict[str, float] = {}
    for row in _extract_records(payload):
        symbol = str(row.get("symbol", "")).upper()
        price = _first_number(
            row.get("last_done"),
            row.get("last"),
            row.get("last_price"),
            row.get("price"),
            row.get("close"),
        )
        if symbol and price is not None:
            prices[symbol] = price
    return prices


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "items", "list", "positions", "assets", "cash_infos"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            return [value]
    return [payload]


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _to_float(value)
        if number is not None:
            return number
    return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _multiply(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left * right


def _subtract(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _money(value: Any, currency: str) -> str:
    number = _to_float(value)
    if number is None:
        return "N/A"
    return f"{number:,.2f} {currency}".strip()


def _number(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "N/A"
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.4f}"
