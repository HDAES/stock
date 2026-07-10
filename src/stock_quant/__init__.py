"""Stock quant research system."""

__version__ = "0.1.0"

# Phase 0: install the safety boundary before analysis, API, or CLI modules import
# legacy auto-trading callables. Market data, strategy, reporting, and backtests
# remain available; legacy order writes are disabled.
from .legacy_trading_freeze import install_legacy_trading_freeze

install_legacy_trading_freeze()
