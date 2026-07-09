from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any


class LongbridgeError(RuntimeError):
    """Raised when the Longbridge CLI returns an error."""


class LongbridgeClient:
    def __init__(
        self,
        binary: str = "longbridge",
        logger: Any | None = print,
        log_path: str | Path | None = "data/intraday/longbridge_cli.jsonl",
    ) -> None:
        self.binary = binary
        self.logger = logger
        self.log_path = Path(log_path) if log_path else None

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

    def assets(self, currency: str = "USD") -> dict | list[dict]:
        return self.run_json(["assets", "--currency", currency.upper()])

    def positions(self) -> dict | list[dict]:
        return self.run_json(["positions"])

    def constituent(self, index_symbol: str) -> dict | list[dict]:
        return self.run_json(["constituent", index_symbol])

    def watchlist(self) -> dict | list[dict]:
        return self.run_json(["watchlist"])

    def auth_status(self) -> dict | list[dict]:
        return self.run_json(["auth", "status"])

    def auth_status_text(self) -> str:
        return self.run_text(["auth", "status"])

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
        started = time.monotonic()
        command = [self.binary, *args]
        self._log_event("start", args, timeout=timeout, json_output=False)
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
            self._log_event("timeout", args, timeout=timeout, elapsed_ms=_elapsed_ms(started), json_output=False)
            raise LongbridgeError(f"Longbridge CLI timed out after {timeout} seconds: {' '.join(args)}") from exc
        output = result.stdout.strip() or result.stderr.strip()
        if result.returncode != 0:
            self._log_event("error", args, returncode=result.returncode, elapsed_ms=_elapsed_ms(started), message=_preview(output), json_output=False)
            raise LongbridgeError(output)
        self._log_event("success", args, returncode=result.returncode, elapsed_ms=_elapsed_ms(started), output_preview=_preview(output), json_output=False)
        return output

    def _run(
        self,
        args: list[str],
        input_text: str | None = None,
        timeout: float | None = 30,
    ) -> Any:
        command = [self.binary, *args, "--format", "json"]
        started = time.monotonic()
        self._log_event("start", args, timeout=timeout, json_output=True)
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
            self._log_event("timeout", args, timeout=timeout, elapsed_ms=_elapsed_ms(started), json_output=True)
            raise LongbridgeError(f"Longbridge CLI timed out after {timeout} seconds: {' '.join(args)}") from exc
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            self._log_event("error", args, returncode=result.returncode, elapsed_ms=_elapsed_ms(started), message=_preview(message), json_output=True)
            raise LongbridgeError(message)
        payload = _parse_json_output(result.stdout)
        self._log_event(
            "success",
            args,
            returncode=result.returncode,
            elapsed_ms=_elapsed_ms(started),
            output_shape=_payload_shape(payload),
            json_output=True,
        )
        return payload

    def _log_event(self, event: str, args: list[str], **fields: Any) -> None:
        payload = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            "command": [self.binary, *args],
            **fields,
        }
        line = _format_console_event(payload)
        if self.logger is not None:
            try:
                self.logger(line, flush=True)
            except TypeError:
                self.logger(line)
        if self.log_path is not None:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a") as handle:
                    handle.write(json.dumps(payload) + "\n")
            except OSError:
                pass


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


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _payload_shape(payload: Any) -> str:
    if isinstance(payload, list):
        return f"list[{len(payload)}]"
    if isinstance(payload, dict):
        keys = ",".join(list(payload.keys())[:6])
        return f"dict[{keys}]"
    return type(payload).__name__


def _preview(value: str, limit: int = 240) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= limit else f"{normalized[:limit]}..."


def _format_console_event(payload: dict[str, Any]) -> str:
    command = " ".join(str(part) for part in payload["command"])
    event = payload["event"]
    elapsed = payload.get("elapsed_ms")
    suffix = f" elapsed={elapsed}ms" if elapsed is not None else ""
    if event == "success" and payload.get("output_shape"):
        suffix += f" output={payload['output_shape']}"
    if event == "error" and payload.get("message"):
        suffix += f" error={payload['message']}"
    return f"[longbridge] {payload['timestamp']} {event} {command}{suffix}"
