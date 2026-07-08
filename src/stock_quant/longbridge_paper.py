from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .longbridge import LongbridgeClient, LongbridgeError


@dataclass(frozen=True)
class PaperOrderRequest:
    symbol: str
    side: str
    quantity: int
    order_type: str = "market"
    price: float | None = None
    time_in_force: str = "day"


class LongbridgePaperTradingClient:
    """Wrapper for trading operations on the currently authenticated Longbridge CLI account.

    In this project the local Longbridge CLI is expected to be authenticated to
    a simulated account. Therefore the wrapper calls the trading subcommands
    directly instead of adding a separate ``paper`` namespace.
    """

    def __init__(self, client: LongbridgeClient | None = None) -> None:
        self.client = client or LongbridgeClient()

    def summary(self) -> dict[str, Any]:
        return {
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "mode": "current_cli_account",
            "account": self._safe_call(self.account),
            "positions": self._safe_call(self.positions),
            "orders": self._safe_call(self.orders),
        }

    def account(self) -> Any:
        return self._run_first_json([
            ["account"],
            ["asset"],
            ["assets"],
        ])

    def positions(self) -> Any:
        return self._run_first_json([
            ["positions"],
            ["position"],
            ["stock-position"],
        ])

    def orders(self) -> Any:
        return self._run_first_json([
            ["order"],
            ["order", "list"],
            ["order", "today"],
            ["order", "history"],
            ["trades"],
        ])

    def submit_order(self, request: PaperOrderRequest) -> Any:
        symbol = request.symbol.upper()
        side = _cli_side(request.side)
        order_type = _cli_order_type(request.order_type)
        time_in_force = _cli_time_in_force(request.time_in_force)
        quantity = str(request.quantity)
        price = str(request.price) if request.price is not None else None

        candidates = [
            [
                "order",
                "--symbol",
                symbol,
                "--side",
                side,
                "--submitted-quantity",
                quantity,
                "--order-type",
                order_type,
                "--time-in-force",
                time_in_force,
            ],
            [
                "order",
                "--symbol",
                symbol,
                "--side",
                side.lower(),
                "--quantity",
                quantity,
                "--order-type",
                request.order_type.lower(),
                "--time-in-force",
                request.time_in_force.lower(),
            ],
            [
                "order",
                "--security-code",
                symbol,
                "--side",
                side,
                "--submitted-quantity",
                quantity,
                "--order-type",
                order_type,
                "--time-in-force",
                time_in_force,
            ],
            [
                "order",
                "--stock-code",
                symbol,
                "--side",
                side,
                "--submitted-quantity",
                quantity,
                "--order-type",
                order_type,
                "--time-in-force",
                time_in_force,
            ],
            [
                "order",
                "--code",
                symbol,
                "--side",
                side,
                "--submitted-quantity",
                quantity,
                "--order-type",
                order_type,
                "--time-in-force",
                time_in_force,
            ],
            [
                "order",
                "place",
                "--symbol",
                symbol,
                "--side",
                side,
                "--submitted-quantity",
                quantity,
                "--order-type",
                order_type,
                "--time-in-force",
                time_in_force,
            ],
            [
                "order",
                "submit",
                "--symbol",
                symbol,
                "--side",
                side,
                "--submitted-quantity",
                quantity,
                "--order-type",
                order_type,
                "--time-in-force",
                time_in_force,
            ],
        ]
        if price is not None:
            enriched: list[list[str]] = []
            for candidate in candidates:
                enriched.append(candidate + ["--submitted-price", price])
                enriched.append(candidate + ["--price", price])
            candidates = enriched
        return self._run_first_json(candidates)

    def cancel_order(self, order_id: str) -> Any:
        return self._run_first_json([
            ["order", "cancel", "--order-id", order_id],
            ["order", "cancel", order_id],
            ["order", "cancel-order", "--order-id", order_id],
            ["order", "--order-id", order_id, "--action", "cancel"],
            ["cancel-order", order_id],
            ["order-cancel", order_id],
        ])

    def _safe_call(self, fn: Any) -> dict[str, Any]:
        try:
            return {"ok": True, "data": fn()}
        except LongbridgeError as exc:
            return {"ok": False, "error": str(exc)}

    def _run_first_json(self, candidates: list[list[str]]) -> Any:
        errors: list[str] = []
        for args in candidates:
            try:
                return self.client.run_json(args)
            except LongbridgeError as exc:
                errors.append(f"longbridge {' '.join(args)}: {exc}")
        raise LongbridgeError("; ".join(errors))


def _cli_side(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "buy":
        return "Buy"
    if normalized == "sell":
        return "Sell"
    return value


def _cli_order_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "limit":
        return "LO"
    if normalized == "market":
        return "MO"
    return value


def _cli_time_in_force(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"day", "0", "1"}:
        return "Day"
    return value
