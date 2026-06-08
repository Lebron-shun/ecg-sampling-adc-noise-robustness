"""Validate local PhysioNet data before running the full experiments."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import wfdb

from project_core import DATA_DIR, RESULTS_DIR, ensure_project_dirs, sha256_file


def validate_dataset(dataset: str, expected_records: int) -> tuple[list[dict], list[dict]]:
    folder = DATA_DIR / dataset
    record_names = [
        line.strip()
        for line in (folder / "RECORDS").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if dataset == "nstdb":
        record_names = [name for name in record_names if name.startswith(("118e", "119e"))]
    if len(record_names) != expected_records:
        raise AssertionError(f"{dataset}: expected {expected_records} records, found {len(record_names)}")

    rows = []
    failures = []
    for name in record_names:
        paths = [folder / f"{name}.{extension}" for extension in ("hea", "dat", "atr")]
        missing = [str(path) for path in paths if not path.exists() or path.stat().st_size == 0]
        if missing:
            failures.append({"dataset": dataset, "record": name, "error": f"missing/empty files: {missing}"})
            continue
        try:
            record = wfdb.rdrecord(str(folder / name), channels=[0])
            annotation = wfdb.rdann(str(folder / name), "atr")
            if record.fs != 360:
                raise AssertionError(f"expected 360 Hz, found {record.fs}")
            if record.sig_len <= 0 or len(annotation.sample) <= 0:
                raise AssertionError("empty signal or annotations")
        except Exception as exc:
            failures.append({"dataset": dataset, "record": name, "error": repr(exc)})
            print(f"FAILED {dataset}/{name}: {exc}")
            continue
        rows.append(
            {
                "dataset": dataset,
                "record": name,
                "fs_hz": record.fs,
                "samples": record.sig_len,
                "duration_min": record.sig_len / record.fs / 60,
                "annotations": len(annotation.sample),
                "signal_name": record.sig_name[0],
                "units": record.units[0],
                "header_sha256": sha256_file(paths[0]),
                "data_sha256": sha256_file(paths[1]),
                "annotation_sha256": sha256_file(paths[2]),
            }
        )
        print(f"Validated {dataset}/{name}")
    return rows, failures


def main() -> None:
    ensure_project_dirs()
    mit_rows, mit_failures = validate_dataset("mitdb", 48)
    nst_rows, nst_failures = validate_dataset("nstdb", 12)
    rows = mit_rows + nst_rows
    failures = mit_failures + nst_failures
    table = pd.DataFrame(rows)
    output = RESULTS_DIR / "data_validation.csv"
    table.to_csv(output, index=False)
    summary = {
        "total_records": len(table),
        "mitdb_records": int((table.dataset == "mitdb").sum()),
        "nstdb_records": int((table.dataset == "nstdb").sum()),
        "all_360_hz": bool(table.fs_hz.eq(360).all()),
        "all_nonempty": bool((table.samples.gt(0) & table.annotations.gt(0)).all()),
        "failures": len(failures),
    }
    (RESULTS_DIR / "data_validation_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (RESULTS_DIR / "data_validation_failures.json").write_text(
        json.dumps(failures, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    if failures:
        raise RuntimeError(f"Data validation failed for {len(failures)} records")


if __name__ == "__main__":
    main()
