from __future__ import annotations

import json
import subprocess
from typing import Any


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
        return self.run_json(
            ["kline", symbol, "--period", period, "--count", str(count), "--session", session]
        )

    def quote(self, *symbols: str) -> list[dict]:
        return self.run_json(["quote", *symbols])

    def calc_index(self, symbol: str) -> list[dict]:
        return self.run_json(["calc-index", symbol])

    def constituent(self, index_symbol: str) -> dict | list[dict]:
        return self.run_json(["constituent", index_symbol])

    def watchlist(self) -> dict | list[dict]:
        return self.run_json(["watchlist"])

    def market_status(self) -> dict | list[dict]:
        return self.run_json(["market-status"])

    def run_json(
        self,
        args: list[str],
        input_text: str | None = None,
        timeout: float | None = 30,
    ) -> Any:
        """Run a Longbridge CLI command and parse its JSON output."""
        return self._run(args, input_text=input_text, timeout=timeout)

    def run_text(
        self,
        args: list[str],
        input_text: str | None = None,
        timeout: float | None = 30,
    ) -> str:
        """Run a Longbridge CLI command and return raw stdout/stderr text."""
        try:
            result = subprocess.run(
                [self.binary, *args],
                input=input_text,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise LongbridgeError(f"Longbridge CLI timed out after {timeout} seconds: {' '.join(args)}") from exc
        output = result.stdout.strip() or result.stderr.strip()
        if result.returncode != 0:
            raise LongbridgeError(output)
        return output

    def _run(
        self,
        args: list[str],
        input_text: str | None = None,
        timeout: float | None = 30,
    ) -> Any:
        command = [self.binary, *args, "--format", "json"]
        try:
            result = subprocess.run(
                command,
                input=input_text,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise LongbridgeError(f"Longbridge CLI timed out after {timeout} seconds: {' '.join(args)}") from exc
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise LongbridgeError(message)
        return _parse_json_output(result.stdout)


def _parse_json_output(output: str) -> Any:
    text = output.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            return json.loads(text[index:])
        except json.JSONDecodeError:
            continue
    raise LongbridgeError("Invalid JSON from Longbridge")
