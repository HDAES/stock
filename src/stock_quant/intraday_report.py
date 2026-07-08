from __future__ import annotations

import json
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


def _write_records_csv(records: Any, path: Path) -> None:
    if not records:
        path.write_text("")
        return

    frame = pd.DataFrame(records)
    for column in frame.columns:
        frame[column] = frame[column].map(_serialize_cell)
    frame.to_csv(path, index=False)


def _serialize_cell(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True)
    return value
