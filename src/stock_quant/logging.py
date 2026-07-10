"""Small logging helpers shared by the CLI, API, and integrations."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

LoggerLike = logging.Logger | Callable[..., Any]


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def emit_log(
    logger: LoggerLike | None,
    message: str,
    *,
    level: int = logging.INFO,
    exc_info: bool = False,
) -> None:
    """Send a message to either a stdlib logger or a legacy callback."""
    if logger is None:
        return
    if isinstance(logger, logging.Logger):
        logger.log(level, message, exc_info=exc_info)
        return
    try:
        logger(message, flush=True)
    except TypeError:
        logger(message)


def configure_cli_logging() -> None:
    level_name = os.getenv("STOCK_QUANT_LOG_LEVEL", "INFO").upper()
    level = logging.getLevelNamesMapping().get(level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("stock_quant").setLevel(level)
