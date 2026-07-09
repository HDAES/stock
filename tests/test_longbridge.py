from __future__ import annotations

import json
import subprocess
from pathlib import Path

from stock_quant.longbridge import LongbridgeClient


def test_longbridge_client_logs_cli_steps(monkeypatch, tmp_path: Path) -> None:
    messages: list[str] = []

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    log_path = tmp_path / "longbridge.jsonl"
    client = LongbridgeClient(binary="lb", logger=messages.append, log_path=log_path)

    payload = client.run_json(["quote", "AAPL.US"], input_text="secret\n")

    assert payload == {"ok": True}
    assert len(messages) == 2
    assert "start lb quote AAPL.US" in messages[0]
    assert "success lb quote AAPL.US" in messages[1]
    assert "secret" not in "\n".join(messages)

    rows = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert [row["event"] for row in rows] == ["start", "success"]
    assert rows[0]["command"] == ["lb", "quote", "AAPL.US"]
    assert rows[1]["output_shape"] == "dict[ok]"
