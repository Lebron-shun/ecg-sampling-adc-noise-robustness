"""Generate the static data payload consumed by the GitHub Pages showcase."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from project_core import PROJECT_ROOT, RESULTS_DIR, load_config


WEB_DATA_PATH = PROJECT_ROOT / "web" / "data.js"


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize(item) for item in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    return value


def read_csv_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return pd.read_csv(path).replace({np.nan: None}).to_dict(orient="records")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    payload = {
        "config": load_config(),
        "clean": read_csv_records(RESULTS_DIR / "aggregate_clean.csv"),
        "noise": read_csv_records(RESULTS_DIR / "aggregate_noise_by_snr.csv"),
        "candidates": read_csv_records(RESULTS_DIR / "candidate_summary.csv"),
        "monitoring": read_csv_records(RESULTS_DIR / "monitoring_summary.csv"),
        "scenarios": read_json(RESULTS_DIR / "scenario_recommendations.json", []),
        "recommended": read_json(RESULTS_DIR / "recommended_config.json", {}),
    }
    text = "window.ECG_DATA = "
    text += json.dumps(sanitize(payload), ensure_ascii=False, indent=2, allow_nan=False)
    text += ";\n"
    WEB_DATA_PATH.write_text(text, encoding="utf-8")
    print(f"Wrote {WEB_DATA_PATH}")


if __name__ == "__main__":
    main()
