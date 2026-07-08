from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


REPORT_FILENAMES = {
    "metrics": "metrics.json",
    "equity_curve": "equity_curve.csv",
    "daily_summary": "daily_summary.csv",
    "trades": "trades.csv",
    "signals": "signals.csv",
}


def write_intraday_report(
    result: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, Path]:
    """Write intraday backtest result artifacts to a report directory."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}
    metrics_path = root / REPORT_FILENAMES["metrics"]
    metrics_path.write_text(json.dumps(result.get("metrics", {}), indent=2, sort_keys=True))
    written["metrics"] = metrics_path

    for key in ("equity_curve", "daily_summary", "trades", "signals"):
        path = root / REPORT_FILENAMES[key]
        _write_records_csv(result.get(key, []), path)
        written[key] = path

    return written


def read_intraday_report(report_dir: str | Path) -> dict[str, Any]:
    """Read a previously written intraday report directory."""
    root = Path(report_dir)
    metrics_path = root / REPORT_FILENAMES["metrics"]
    if not metrics_path.exists():
        raise FileNotFoundError(f"No intraday report found at {root}")

    return {
        "report_dir": str(root),
        "generated_at": datetime.fromtimestamp(metrics_path.stat().st_mtime).isoformat(timespec="seconds"),
        "metrics": json.loads(metrics_path.read_text() or "{}"),
        "equity_curve": _read_records_csv(root / REPORT_FILENAMES["equity_curve"]),
        "daily_summary": _read_records_csv(root / REPORT_FILENAMES["daily_summary"]),
        "trades": _read_records_csv(root / REPORT_FILENAMES["trades"]),
        "signals": _read_records_csv(root / REPORT_FILENAMES["signals"]),
    }


def _write_records_csv(records: Any, path: Path) -> None:
    if not records:
        path.write_text("")
        return

    frame = pd.DataFrame(records)
    for column in frame.columns:
        frame[column] = frame[column].map(_serialize_cell)
    frame.to_csv(path, index=False)


def _read_records_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or not path.read_text().strip():
        return []
    frame = pd.read_csv(path)
    for column in frame.columns:
        frame[column] = frame[column].map(_deserialize_cell)
    records = frame.to_dict(orient="records")
    return [_clean_record(record) for record in records]


def _clean_record(record: dict[str, Any]) -> dict[str, Any]:
    return {key: _clean_value(value) for key, value in record.items()}


def _clean_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _clean_record(value)
    if isinstance(value, list):
        return [_clean_value(item) for item in value]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _serialize_cell(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True)
    return value


def _deserialize_cell(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value
