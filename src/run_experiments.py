"""Run the clean and standardized-noise full-factorial experiments."""

from __future__ import annotations

import argparse
import json
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import wfdb

from project_core import (
    DATA_DIR,
    RESULTS_DIR,
    ensure_project_dirs,
    evaluate_scope,
    front_end_filter,
    load_config,
    make_noise_intervals,
    parse_noise_record_name,
    quantize_fixed_range,
    read_reference_beats,
    resample_signal,
    trim_intervals,
    detect_r_peaks,
)


def read_record_names(folder: Path) -> list[str]:
    return [
        line.strip()
        for line in (folder / "RECORDS").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def experiment_rows(dataset: str, record_name: str) -> list[dict]:
    config = load_config()
    source_fs = int(config["source_fs_hz"])
    record_path = DATA_DIR / dataset / record_name
    record = wfdb.rdrecord(str(record_path), channels=[0])
    duration_s = record.sig_len / record.fs
    if int(record.fs) != source_fs:
        raise ValueError(f"{record_name}: expected {source_fs} Hz, found {record.fs}")

    filtered = front_end_filter(
        record.p_signal[:, 0],
        source_fs,
        tuple(config["front_end_band_hz"]),
        int(config["front_end_order"]),
    )
    references_s, _ = read_reference_beats(record_path, source_fs)

    boundary_margin = float(config["interval_boundary_margin_s"])
    if dataset == "mitdb":
        scopes = {
            "clean_after_5min": trim_intervals(
                [(float(config["clean_eval_start_s"]), duration_s)], boundary_margin
            )
        }
        base_record = record_name
        snr_db = np.nan
    else:
        noise_intervals = make_noise_intervals(
            duration_s,
            float(config["noise_start_s"]),
            float(config["noise_on_s"]),
            float(config["noise_off_s"]),
        )
        scopes = {
            "noise_only": trim_intervals(noise_intervals, boundary_margin),
            "mixed_after_5min": trim_intervals(
                [(float(config["noise_start_s"]), duration_s)], boundary_margin
            ),
        }
        base_record, snr_db = parse_noise_record_name(record_name)

    rows: list[dict] = []
    for target_fs in config["target_fs_hz"]:
        resampled = resample_signal(filtered, source_fs, int(target_fs))
        for bits in config["effective_bits"]:
            quantized = quantize_fixed_range(
                resampled, int(bits), float(config["full_scale_mv_pp"])
            )
            detected_s = detect_r_peaks(quantized.values_mv, int(target_fs))
            for scope, intervals in scopes.items():
                for tolerance_ms in config["match_tolerances_ms"]:
                    metrics = evaluate_scope(
                        references_s,
                        detected_s,
                        int(target_fs),
                        quantized,
                        intervals,
                        int(tolerance_ms),
                    )
                    rows.append(
                        {
                            "dataset": dataset,
                            "record": record_name,
                            "base_record": base_record,
                            "snr_db": snr_db,
                            "eval_scope": scope,
                            "target_fs_hz": int(target_fs),
                            "bits": int(bits),
                            "lsb_uv": quantized.lsb_mv * 1000,
                            "raw_bitrate_bps": int(target_fs) * int(bits),
                            "storage_mib_per_day": int(target_fs)
                            * int(bits)
                            * 86400
                            / 8
                            / 1024**2,
                            **metrics,
                        }
                    )
    return rows


def run_dataset(dataset: str, workers: int) -> Path:
    folder = DATA_DIR / dataset
    records = read_record_names(folder)
    if dataset == "nstdb":
        records = [record for record in records if record.startswith(("118e", "119e"))]

    output = RESULTS_DIR / f"per_record_{'clean' if dataset == 'mitdb' else 'noise'}.csv"
    failures_path = RESULTS_DIR / f"failures_{dataset}.json"
    all_rows: list[dict] = []
    failures: dict[str, str] = {}
    print(f"Running {dataset}: {len(records)} records with {workers} workers")
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(experiment_rows, dataset, record): record for record in records}
        for index, future in enumerate(as_completed(futures), 1):
            record = futures[future]
            try:
                rows = future.result()
                all_rows.extend(rows)
                print(f"[{index:2d}/{len(records)}] completed {record}: {len(rows)} rows")
            except Exception:
                failures[record] = traceback.format_exc()
                print(f"[{index:2d}/{len(records)}] FAILED {record}")

    table = pd.DataFrame(all_rows)
    if not table.empty:
        table.sort_values(
            ["record", "eval_scope", "tolerance_ms", "target_fs_hz", "bits"],
            inplace=True,
        )
        table.to_csv(output, index=False, float_format="%.8f")
    failures_path.write_text(json.dumps(failures, indent=2), encoding="utf-8")
    print(f"Saved {len(table)} rows to {output}; failures: {len(failures)}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("clean", "noise", "all"), default="all")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    ensure_project_dirs()
    if args.mode in ("clean", "all"):
        run_dataset("mitdb", args.workers)
    if args.mode in ("noise", "all"):
        run_dataset("nstdb", args.workers)


if __name__ == "__main__":
    main()
