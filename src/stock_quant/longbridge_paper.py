from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .longbridge import LongbridgeClient


@dataclass(frozen=True)
class PaperOrderRequest:
    symbol: str
    side: str
    quantity: int
    order_type: str = "market"
    price: float | None = None
    time_in_force: str = "day"


class LongbridgePaperTradingClient:
    """Thin wrapper for Longbridge CLI simulated-trading operations.

    The project already uses the external ``longbridge`` CLI for market data.
    This wrapper keeps simulated-trading commands isolated from strategy logic
    and exposes only explicit user-triggered operations.
    """

    def __init__(self, client: LongbridgeClient | None = None) -> None:
        self.client = client or LongbridgeClient()

    def summary(self) -> dict[str, Any]:
        return {
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "account": self.account(),
            "positions": self.positions(),
            "orders": self.orders(),
        }

    def account(self) -> Any:
        return self.client.run_json(["paper", "account"])

    def positions(self) -> Any:
        return self.client.run_json(["paper", "positions"])

    def orders(self) -> Any:
        return self.client.run_json(["paper", "orders"])

    def submit_order(self, request: PaperOrderRequest) -> Any:
        args = [
            "paper",
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
        return self.client.run_json(["paper", "cancel-order", order_id])
