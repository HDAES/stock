"""Phase-0 safety freeze for the legacy trading implementation.

The legacy intraday module is still imported by analysis and reporting code.  To
keep those read paths available while trading-core-v2 is developed, this module
replaces only the state-changing and order-execution entry points.
"""

from __future__ import annotations

from typing import Any

READ_ONLY_MODE = "READ_ONLY"
LEGACY_TRADING_DISABLED_REASON = "legacy_trading_frozen_for_trading_core_v2"
LEGACY_TRADING_DISABLED_MESSAGE = (
    "Legacy trading is frozen in READ_ONLY mode while trading-core-v2 is under development."
)

_installed = False


def install_legacy_trading_freeze() -> None:
    """Install process-wide guards before other stock_quant modules are imported."""
    global _installed
    if _installed:
        return

    from . import intraday_auto_trade as legacy

    if getattr(legacy, "_legacy_trading_freeze_installed", False):
        _installed = True
        return

    original_load_auto_trade_state = legacy.load_auto_trade_state
    original_save_auto_trade_state = legacy.save_auto_trade_state

    def read_only_state(previous: dict[str, Any] | None = None) -> dict[str, Any]:
        state = dict(previous or {})
        state.update(
            {
                "enabled": False,
                "mode": READ_ONLY_MODE,
                "confirmed_non_simulated": False,
                "read_only": True,
                "disabled_reason": LEGACY_TRADING_DISABLED_REASON,
            }
        )
        state.setdefault("updated_at", None)
        state.setdefault("account", None)
        return state

    def load_auto_trade_state(config: Any) -> dict[str, Any]:
        previous = original_load_auto_trade_state(config)
        if previous.get("enabled") or previous.get("mode") != READ_ONLY_MODE:
            persisted = original_save_auto_trade_state(
                config,
                False,
                mode=READ_ONLY_MODE,
                account_status=previous.get("account"),
                confirmed_non_simulated=False,
            )
            return read_only_state(persisted)
        return read_only_state(previous)

    def save_auto_trade_state(
        config: Any,
        enabled: bool,
        mode: str = READ_ONLY_MODE,
        account_status: dict[str, Any] | None = None,
        confirmed_non_simulated: bool = False,
    ) -> dict[str, Any]:
        del enabled, mode, confirmed_non_simulated
        persisted = original_save_auto_trade_state(
            config,
            False,
            mode=READ_ONLY_MODE,
            account_status=account_status,
            confirmed_non_simulated=False,
        )
        return read_only_state(persisted)

    def maybe_execute_auto_trade(
        config: Any,
        client: Any,
        signal: dict[str, Any],
        trade: dict[str, Any] | None = None,
        logger: Any | None = None,
    ) -> dict[str, Any]:
        del config, client, trade, logger
        return {
            "enabled": False,
            "mode": READ_ONLY_MODE,
            "submitted": False,
            "symbol": str(signal.get("symbol") or "").upper(),
            "action": str(signal.get("action") or "").upper(),
            "reason": LEGACY_TRADING_DISABLED_REASON,
            "read_only": True,
        }

    legacy.load_auto_trade_state = load_auto_trade_state
    legacy.save_auto_trade_state = save_auto_trade_state
    legacy.maybe_execute_auto_trade = maybe_execute_auto_trade
    legacy._legacy_trading_freeze_installed = True
    _installed = True
