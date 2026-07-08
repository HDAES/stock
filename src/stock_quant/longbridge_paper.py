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
            "account": self.account(),
            "positions": self.positions(),
            "orders": self.orders(),
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
            ["orders"],
            ["order-list"],
            ["today-orders"],
        ])

    def submit_order(self, request: PaperOrderRequest) -> Any:
        args = [
            "submit-order",
            request.symbol.upper(),
            "--side",
            request.side.lower(),
            "--quantity",
            str(request.quantity),
            "--order-type",
            request.order_type.lower(),
            "--time-in-force",
            request.time_in_force.lower(),
        ]
        if request.price is not None:
            args.extend(["--price", str(request.price)])
        return self.client.run_json(args)

    def cancel_order(self, order_id: str) -> Any:
        return self._run_first_json([
            ["cancel-order", order_id],
            ["order-cancel", order_id],
        ])

    def _run_first_json(self, candidates: list[list[str]]) -> Any:
        errors: list[str] = []
        for args in candidates:
            try:
                return self.client.run_json(args)
            except LongbridgeError as exc:
                errors.append(f"longbridge {' '.join(args)}: {exc}")
        raise LongbridgeError("; ".join(errors))
