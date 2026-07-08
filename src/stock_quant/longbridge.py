from __future__ import annotations

import json
import subprocess


class LongbridgeError(RuntimeError):
    """Raised when the Longbridge CLI returns an error."""


class LongbridgeClient:
    def __init__(self, binary: str = "longbridge") -> None:
        self.binary = binary

    def kline(
        self,
        symbol: str,
        count: int = 500,
        period: str = "day",
        session: str = "intraday",
    ) -> list[dict]:
        return self._run(
            ["kline", symbol, "--period", period, "--count", str(count), "--session", session]
        )

    def quote(self, *symbols: str) -> list[dict]:
        return self._run(["quote", *symbols])

    def calc_index(self, symbol: str) -> list[dict]:
        return self._run(["calc-index", symbol])

    def constituent(self, index_symbol: str) -> dict | list[dict]:
        return self._run(["constituent", index_symbol])

    def watchlist(self) -> dict | list[dict]:
        return self._run(["watchlist"])

    def market_status(self) -> dict | list[dict]:
        return self._run(["market-status"])

    def _run(self, args: list[str]) -> dict | list[dict]:
        command = [self.binary, *args, "--format", "json"]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise LongbridgeError(message)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise LongbridgeError(f"Invalid JSON from Longbridge: {exc}") from exc
