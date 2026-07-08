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
            "executions": self._safe_call(self.executions),
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
        return self.client.run_json(["order"])

    def executions(self) -> Any:
        return self.client.run_json(["order", "executions"])

    def submit_order(self, request: PaperOrderRequest) -> Any:
        side_command = request.side.strip().lower()
        if side_command not in {"buy", "sell"}:
            raise LongbridgeError(f"Unsupported order side: {request.side}")

        args = ["order", side_command, request.symbol.upper(), str(request.quantity)]
        if request.price is not None:
            args.extend(["--price", str(request.price)])

        return self.client.run_json(args, input_text="y\n", timeout=30)

    def cancel_order(self, order_id: str) -> Any:
        return self._run_first_json([
            ["order", "cancel", order_id, "-y"],
            ["order", "cancel", "-y", order_id],
            ["order", "cancel", order_id],
        ], input_text="y\n")

    def _safe_call(self, fn: Any) -> dict[str, Any]:
        try:
            return {"ok": True, "data": fn()}
        except LongbridgeError as exc:
            return {"ok": False, "error": str(exc)}

    def _run_first_json(
        self,
        candidates: list[list[str]],
        input_text: str | None = None,
    ) -> Any:
        errors: list[str] = []
        for args in candidates:
            try:
                return self.client.run_json(args, input_text=input_text, timeout=30)
            except LongbridgeError as exc:
                errors.append(f"longbridge {' '.join(args)}: {exc}")
        raise LongbridgeError("; ".join(errors))
