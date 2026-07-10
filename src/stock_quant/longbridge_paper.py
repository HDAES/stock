from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .longbridge import LongbridgeClient, LongbridgeError


LEGACY_TRADING_MODE = "READ_ONLY"
LEGACY_TRADING_DISABLED_MESSAGE = (
    "Legacy trading is frozen in READ_ONLY mode while trading-core-v2 is under development."
)


class LegacyTradingReadOnlyError(LongbridgeError):
    """Raised when legacy code attempts to mutate the broker account."""


@dataclass(frozen=True)
class PaperOrderRequest:
    symbol: str
    side: str
    quantity: int
    order_type: str = "market"
    price: float | None = None
    time_in_force: str = "day"


class LongbridgePaperTradingClient:
    """Read-only wrapper for the currently authenticated Longbridge CLI account.

    Account, position, order, and execution queries remain available so the
    existing dashboard and reports keep working.  All order mutations are
    blocked until trading-core-v2 provides a replacement execution boundary.
    """

    def __init__(self, client: LongbridgeClient | None = None) -> None:
        self.client = client or LongbridgeClient()

    def summary(self) -> dict[str, Any]:
        return {
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "mode": LEGACY_TRADING_MODE,
            "read_only": True,
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
        del request
        raise LegacyTradingReadOnlyError(LEGACY_TRADING_DISABLED_MESSAGE)

    def cancel_order(self, order_id: str) -> Any:
        del order_id
        raise LegacyTradingReadOnlyError(LEGACY_TRADING_DISABLED_MESSAGE)

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
