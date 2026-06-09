"""Extend the ECG design study from R-peak detection to RR/HRV monitoring metrics."""

from __future__ import annotations

import argparse
import json
import shutil
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import wfdb

from analyze_results import COLORS, add_panel_label, configure_matplotlib, save_figure, style_axis
from project_core import (
    DATA_DIR,
    FIGURES_DIR,
    RESULTS_DIR,
    detect_r_peaks,
    ensure_project_dirs,
    front_end_filter,
    interval_mask,
    load_config,
    quantize_fixed_range,
    read_reference_beats,
    resample_signal,
)


matplotlib.use("Agg")
from matplotlib import pyplot as plt


MONITORING_CACHE_DIR = RESULTS_DIR / "monitoring_cache"

REPRESENTATIVE_CONFIGS = [
    (360, 11),
    (360, 8),
    (360, 7),
    (360, 6),
    (180, 8),
    (125, 8),
    (100, 6),
]


def match_pairs(
    reference_s: np.ndarray, detected_s: np.ndarray, tolerance_s: float
) -> tuple[np.ndarray, np.ndarray]:
    """Return one-to-one matched reference and detected indices."""
    i = j = 0
    ref_indices: list[int] = []
    det_indices: list[int] = []
    while i < len(reference_s) and j < len(detected_s):
        delta = detected_s[j] - reference_s[i]
        if abs(delta) <= tolerance_s:
            ref_indices.append(i)
            det_indices.append(j)
            i += 1
            j += 1
        elif detected_s[j] < reference_s[i] - tolerance_s:
            j += 1
        else:
            i += 1
    return np.asarray(ref_indices, dtype=int), np.asarray(det_indices, dtype=int)


def rmssd(rr_s: np.ndarray) -> float:
    if len(rr_s) < 2:
        return float("nan")
    return float(np.sqrt(np.mean(np.diff(rr_s) ** 2)))


def relative_error_pct(candidate: float, reference: float) -> float:
    if not np.isfinite(candidate) or not np.isfinite(reference) or reference == 0:
        return float("nan")
    return abs(candidate - reference) / abs(reference) * 100


def monitoring_metrics_for_scope(
    reference_s: np.ndarray,
    detected_s: np.ndarray,
    intervals: list[tuple[float, float]],
    tolerance_ms: int,
) -> dict:
    ref = reference_s[interval_mask(reference_s, intervals)]
    det = detected_s[interval_mask(detected_s, intervals)]
    ref_idx, det_idx = match_pairs(ref, det, tolerance_ms / 1000.0)

    possible_rr_pairs = max(len(ref) - 1, 0)
    valid_pair_mask = (np.diff(ref_idx) == 1) & (np.diff(det_idx) == 1) if len(ref_idx) >= 2 else np.asarray([], dtype=bool)
    valid_ref_start = ref_idx[:-1][valid_pair_mask] if len(ref_idx) >= 2 else np.asarray([], dtype=int)
    valid_det_start = det_idx[:-1][valid_pair_mask] if len(det_idx) >= 2 else np.asarray([], dtype=int)

    ref_rr = ref[valid_ref_start + 1] - ref[valid_ref_start] if len(valid_ref_start) else np.asarray([])
    det_rr = det[valid_det_start + 1] - det[valid_det_start] if len(valid_det_start) else np.asarray([])
    rr_errors_ms = np.abs(det_rr - ref_rr) * 1000

    valid_hr = (ref_rr > 0) & (det_rr > 0) if len(ref_rr) else np.asarray([], dtype=bool)
    hr_errors_bpm = np.abs(60 / det_rr[valid_hr] - 60 / ref_rr[valid_hr]) if len(ref_rr) else np.asarray([])

    ref_sdnn = float(np.std(ref_rr, ddof=1)) if len(ref_rr) >= 2 else float("nan")
    det_sdnn = float(np.std(det_rr, ddof=1)) if len(det_rr) >= 2 else float("nan")
    ref_rmssd = rmssd(ref_rr)
    det_rmssd = rmssd(det_rr)
    sdnn_error = relative_error_pct(det_sdnn, ref_sdnn)
    rmssd_error = relative_error_pct(det_rmssd, ref_rmssd)
    valid_rr_pair_pct = len(ref_rr) / possible_rr_pairs * 100 if possible_rr_pairs else float("nan")

    hrv_usable = (
        np.isfinite(valid_rr_pair_pct)
        and valid_rr_pair_pct >= 98
        and np.isfinite(sdnn_error)
        and sdnn_error <= 5
        and np.isfinite(rmssd_error)
        and rmssd_error <= 5
    )

    return {
        "reference_beats": int(len(ref)),
        "detected_beats": int(len(det)),
        "matched_beats": int(len(ref_idx)),
        "valid_rr_pairs": int(len(ref_rr)),
        "valid_rr_pair_pct": float(valid_rr_pair_pct),
        "rr_median_abs_error_ms": float(np.median(rr_errors_ms)) if len(rr_errors_ms) else float("nan"),
        "rr_p95_abs_error_ms": float(np.percentile(rr_errors_ms, 95)) if len(rr_errors_ms) else float("nan"),
        "hr_median_abs_error_bpm": float(np.median(hr_errors_bpm)) if len(hr_errors_bpm) else float("nan"),
        "hr_p95_abs_error_bpm": float(np.percentile(hr_errors_bpm, 95)) if len(hr_errors_bpm) else float("nan"),
        "sdnn_reference_ms": ref_sdnn * 1000 if np.isfinite(ref_sdnn) else float("nan"),
        "sdnn_candidate_ms": det_sdnn * 1000 if np.isfinite(det_sdnn) else float("nan"),
        "sdnn_relative_error_pct": sdnn_error,
        "rmssd_reference_ms": ref_rmssd * 1000 if np.isfinite(ref_rmssd) else float("nan"),
        "rmssd_candidate_ms": det_rmssd * 1000 if np.isfinite(det_rmssd) else float("nan"),
        "rmssd_relative_error_pct": rmssd_error,
        "hrv_usable": bool(hrv_usable),
    }


def analyze_record(record_name: str, config: dict) -> list[dict]:
    record_path = DATA_DIR / "mitdb" / record_name
    source_fs = int(config["source_fs_hz"])
    record = wfdb.rdrecord(str(record_path), channels=[0])
    if int(record.fs) != source_fs:
        raise ValueError(f"{record_name}: expected {source_fs} Hz, found {record.fs}")

    filtered = front_end_filter(
        record.p_signal[:, 0],
        source_fs,
        tuple(config["front_end_band_hz"]),
        int(config["front_end_order"]),
    )
    reference_s, _ = read_reference_beats(record_path, source_fs)
    duration_s = len(filtered) / source_fs
    intervals = [(float(config["clean_eval_start_s"]), duration_s)]

    rows: list[dict] = []
    resampled_by_fs: dict[int, np.ndarray] = {}
    for target_fs, bits in REPRESENTATIVE_CONFIGS:
        if target_fs not in resampled_by_fs:
            resampled_by_fs[target_fs] = resample_signal(filtered, source_fs, target_fs)
        quantized = quantize_fixed_range(resampled_by_fs[target_fs], bits, float(config["full_scale_mv_pp"]))
        detected_s = detect_r_peaks(quantized.values_mv, target_fs)
        metrics = monitoring_metrics_for_scope(reference_s, detected_s, intervals, tolerance_ms=150)
        rows.append(
            {
                "dataset": "mitdb",
                "record": record_name,
                "target_fs_hz": target_fs,
                "bits": bits,
                "raw_bitrate_bps": target_fs * bits,
                **metrics,
            }
        )
    return rows


def aggregate_monitoring(metrics: pd.DataFrame) -> pd.DataFrame:
    grouped = metrics.groupby(["target_fs_hz", "bits"], as_index=False)
    summary = grouped.agg(
        records=("record", "nunique"),
        rr_median_abs_error_ms=("rr_median_abs_error_ms", "median"),
        rr_p95_abs_error_ms=("rr_p95_abs_error_ms", "median"),
        hr_median_abs_error_bpm=("hr_median_abs_error_bpm", "median"),
        hr_p95_abs_error_bpm=("hr_p95_abs_error_bpm", "median"),
        valid_rr_pair_pct=("valid_rr_pair_pct", "median"),
        sdnn_relative_error_median_pct=("sdnn_relative_error_pct", "median"),
        rmssd_relative_error_median_pct=("rmssd_relative_error_pct", "median"),
        hrv_usable_record_pct=("hrv_usable", lambda values: float(np.mean(values) * 100)),
        raw_bitrate_bps=("raw_bitrate_bps", "first"),
    )
    return summary.sort_values(["raw_bitrate_bps", "target_fs_hz", "bits"])


def config_label(row: pd.Series | dict) -> str:
    return f"{int(row['target_fs_hz'])} Hz / {int(row['bits'])} bit"


def row_to_config(row: pd.Series | None) -> dict | None:
    if row is None:
        return None
    return {
        "target_fs_hz": int(row["target_fs_hz"]),
        "bits": int(row["bits"]),
        "label": config_label(row),
    }


def evidence_from_row(row: pd.Series, monitoring: bool = True) -> list[str]:
    evidence = [
        f"Clean F1 {row['pooled_f1_pct']:.3f}%",
        f"原始码率 {int(row['raw_bitrate_bps'])} bit/s",
    ]
    if monitoring:
        evidence.extend(
            [
                f"RR误差中位数 {row['rr_median_abs_error_ms']:.2f} ms",
                f"心率误差中位数 {row['hr_median_abs_error_bpm']:.3f} bpm",
                f"连续RR对比例 {row['valid_rr_pair_pct']:.2f}%",
            ]
        )
    if "worst_noise_f1_drop_pp" in row:
        evidence.append(f"SNR>=6 dB最坏F1下降 {row['worst_noise_f1_drop_pp']:.3f} pp")
    return evidence


def build_scenarios(summary: pd.DataFrame, candidates: pd.DataFrame) -> list[dict]:
    merged = candidates.merge(summary, on=["target_fs_hz", "bits", "raw_bitrate_bps"], how="left")

    hr_rr = merged[
        merged["meets_all"]
        & (merged["rr_median_abs_error_ms"] <= 20)
        & (merged["hr_median_abs_error_bpm"] <= 1)
        & (merged["valid_rr_pair_pct"] >= 98)
    ].sort_values("raw_bitrate_bps")
    hr_rr_row = hr_rr.iloc[0] if len(hr_rr) else None

    hrv = merged[
        merged["meets_all"]
        & (merged["sdnn_relative_error_median_pct"] <= 5)
        & (merged["rmssd_relative_error_median_pct"] <= 5)
        & (merged["hrv_usable_record_pct"] >= 90)
    ].sort_values("raw_bitrate_bps")
    hrv_row = hrv.iloc[0] if len(hrv) else None

    noise = merged[
        (merged["worst_noise_f1_drop_pp"] <= 0.1)
        & merged["meets_clean_absolute"]
        & merged["analog_practical"]
    ].sort_values("raw_bitrate_bps")
    noise_row = noise.iloc[0] if len(noise) else None

    teaching = merged[
        (merged["pooled_f1_pct"] >= 98.5)
        & merged["analog_practical"]
        & (~merged["meets_noise_relative"])
    ].sort_values("raw_bitrate_bps")
    teaching_row = teaching.iloc[0] if len(teaching) else None

    scenarios = [
        {
            "id": "hr_rr_monitoring",
            "title": "HR/RR long-term monitoring",
            "title_zh": "HR/RR 长时监护",
            "status": "recommended" if hr_rr_row is not None else "caution",
            "config": row_to_config(hr_rr_row),
            "evidence": evidence_from_row(hr_rr_row) if hr_rr_row is not None else ["没有配置同时满足全部HR/RR监护阈值。"],
            "boundary": "适合心率与RR间期趋势监护，不作为诊断系统。",
        },
        {
            "id": "hrv_trend",
            "title": "HRV trend observation",
            "title_zh": "HRV 趋势观察",
            "status": "recommended" if hrv_row is not None else "caution",
            "config": row_to_config(hrv_row),
            "evidence": (
                evidence_from_row(hrv_row)
                + [
                    f"SDNN相对误差 {hrv_row['sdnn_relative_error_median_pct']:.2f}%",
                    f"RMSSD相对误差 {hrv_row['rmssd_relative_error_median_pct']:.2f}%",
                ]
                if hrv_row is not None
                else ["没有低数据率配置同时满足全部HRV趋势阈值。"]
            ),
            "boundary": "HRV仅作为技术信号质量指标，不解释疾病风险。",
        },
        {
            "id": "motion_noise",
            "title": "Motion/noise-priority monitoring",
            "title_zh": "运动/噪声优先监护",
            "status": "recommended" if noise_row is not None else "caution",
            "config": row_to_config(noise_row),
            "evidence": evidence_from_row(noise_row, monitoring=False) if noise_row is not None else ["没有配置满足严格噪声优先阈值。"],
            "boundary": "适合把标准运动伪影鲁棒性放在最低码率之前的场景。",
        },
        {
            "id": "low_bitrate_teaching",
            "title": "Ultra-low-bitrate teaching/static exploration",
            "title_zh": "极低数据率教学/静息探索",
            "status": "limited",
            "config": row_to_config(teaching_row),
            "evidence": evidence_from_row(teaching_row, monitoring=False) if teaching_row is not None else ["没有选出候选配置。"],
            "boundary": "可用于展示参数权衡，不适合运动场景或鲁棒监护。",
        },
        {
            "id": "clinical_diagnosis",
            "title": "ST morphology / clinical diagnosis",
            "title_zh": "ST/形态/临床诊断",
            "status": "out_of_scope",
            "config": None,
            "evidence": ["本项目不评价ST段、形态诊断、心律失常分类或临床决策。"],
            "boundary": "设计范围外。",
        },
    ]
    return scenarios


def plot_monitoring_metrics(summary: pd.DataFrame) -> None:
    order = pd.DataFrame(
        {"target_fs_hz": [fs for fs, _ in REPRESENTATIVE_CONFIGS], "bits": [bits for _, bits in REPRESENTATIVE_CONFIGS]}
    )
    plot_data = order.merge(summary, on=["target_fs_hz", "bits"], how="left")
    labels = [f"{int(row.target_fs_hz)}/{int(row.bits)}" for row in plot_data.itertuples()]
    x = np.arange(len(plot_data))

    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.8))
    bar_colors = [COLORS["neutral_light"], COLORS["blue_soft"], COLORS["blue_soft"], COLORS["teal"], COLORS["blue_mid"], COLORS["gold"], COLORS["red_soft"]]

    axes[0].bar(x, plot_data["rr_median_abs_error_ms"], color=bar_colors, edgecolor=COLORS["neutral_dark"], linewidth=0.4)
    axes[0].axhline(20, color=COLORS["neutral_mid"], lw=0.8, ls="--")
    axes[0].set_title("RR median error")
    axes[0].set_ylabel("ms")

    axes[1].bar(x, plot_data["hr_median_abs_error_bpm"], color=bar_colors, edgecolor=COLORS["neutral_dark"], linewidth=0.4)
    axes[1].axhline(1, color=COLORS["neutral_mid"], lw=0.8, ls="--")
    axes[1].set_title("Heart-rate median error")
    axes[1].set_ylabel("bpm")

    width = 0.38
    axes[2].bar(x - width / 2, plot_data["sdnn_relative_error_median_pct"], width=width, color=COLORS["blue_mid"], label="SDNN")
    axes[2].bar(x + width / 2, plot_data["rmssd_relative_error_median_pct"], width=width, color=COLORS["teal"], label="RMSSD")
    axes[2].axhline(5, color=COLORS["neutral_mid"], lw=0.8, ls="--")
    axes[2].set_title("HRV relative error")
    axes[2].set_ylabel("%")
    axes[2].legend(loc="upper left")

    for idx, ax in enumerate(axes):
        ax.set_xticks(x, labels, rotation=35, ha="right")
        style_axis(ax, grid_axis="y")
        add_panel_label(ax, chr(ord("a") + idx), x=-0.12, y=1.02)
    fig.suptitle("Monitoring-oriented RR, heart-rate, and HRV metrics", fontsize=9.5, fontweight="regular", y=1.02)
    fig.tight_layout(w_pad=1.4)
    save_figure(fig, "figure_09_monitoring_metrics.png")


def copy_outputs(paths: list[Path]) -> None:
    tables_dir = RESULTS_DIR / "final_tables"
    tables_dir.mkdir(exist_ok=True)
    for path in paths:
        if path.exists():
            shutil.copy2(path, tables_dir / path.name)


def read_cached_record(record_name: str) -> pd.DataFrame | None:
    cache_path = MONITORING_CACHE_DIR / f"{record_name}.csv"
    if not cache_path.exists() or cache_path.stat().st_size == 0:
        return None
    cached = pd.read_csv(cache_path)
    expected = {(fs, bits) for fs, bits in REPRESENTATIVE_CONFIGS}
    present = {(int(row.target_fs_hz), int(row.bits)) for row in cached.itertuples()}
    return cached if expected.issubset(present) else None


def analyze_and_cache_record(record_name: str) -> list[dict]:
    config = load_config()
    rows = analyze_record(record_name, config)
    MONITORING_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = MONITORING_CACHE_DIR / f"{record_name}.csv"
    pd.DataFrame(rows).sort_values(["record", "target_fs_hz", "bits"]).to_csv(
        cache_path,
        index=False,
        float_format="%.8f",
    )
    return rows


def collect_monitoring_rows(records: list[str], workers: int, refresh: bool) -> tuple[pd.DataFrame, dict[str, str]]:
    MONITORING_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict] = []
    pending: list[str] = []
    failures: dict[str, str] = {}

    for record_name in records:
        cached = None if refresh else read_cached_record(record_name)
        if cached is None:
            pending.append(record_name)
        else:
            all_rows.extend(cached.to_dict(orient="records"))

    if pending:
        print(f"Computing monitoring metrics for {len(pending)} records with {workers} workers")
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(analyze_and_cache_record, record): record for record in pending}
            for index, future in enumerate(as_completed(futures), start=1):
                record = futures[future]
                try:
                    rows = future.result()
                    all_rows.extend(rows)
                    print(f"[{index:2d}/{len(pending)}] completed {record}: {len(rows)} rows")
                except Exception:
                    failures[record] = traceback.format_exc()
                    print(f"[{index:2d}/{len(pending)}] FAILED {record}")
    else:
        print(f"Using cached monitoring metrics for {len(records)} records")

    table = pd.DataFrame(all_rows)
    if not table.empty:
        table.sort_values(["record", "target_fs_hz", "bits"], inplace=True)
    return table, failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--refresh", action="store_true", help="Ignore per-record monitoring cache")
    args = parser.parse_args()

    ensure_project_dirs()
    configure_matplotlib()
    records = sorted(path.stem for path in (DATA_DIR / "mitdb").glob("*.hea"))
    if not records:
        raise FileNotFoundError("MIT-BIH records not found. Run src/download_data.py first.")

    metrics, failures = collect_monitoring_rows(records, workers=args.workers, refresh=args.refresh)
    failures_path = RESULTS_DIR / "monitoring_failures.json"
    if failures:
        failures_path.write_text(json.dumps(failures, indent=2), encoding="utf-8")
        raise RuntimeError(f"Monitoring analysis failed for {len(failures)} records; see {failures_path}")
    if failures_path.exists():
        failures_path.unlink()

    summary = aggregate_monitoring(metrics)
    candidates = pd.read_csv(RESULTS_DIR / "candidate_summary.csv")
    scenarios = build_scenarios(summary, candidates)

    metrics_path = RESULTS_DIR / "monitoring_metrics.csv"
    summary_path = RESULTS_DIR / "monitoring_summary.csv"
    scenarios_path = RESULTS_DIR / "scenario_recommendations.json"
    metrics.to_csv(metrics_path, index=False, float_format="%.8f")
    summary.to_csv(summary_path, index=False, float_format="%.8f")
    scenarios_path.write_text(json.dumps(scenarios, indent=2, ensure_ascii=False), encoding="utf-8")
    plot_monitoring_metrics(summary)
    copy_outputs([metrics_path, summary_path, scenarios_path])
    print(json.dumps({"records": len(records), "rows": len(metrics), "figure": str(FIGURES_DIR / "figure_09_monitoring_metrics.png")}, indent=2))


if __name__ == "__main__":
    main()
