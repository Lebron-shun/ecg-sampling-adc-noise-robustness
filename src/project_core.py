"""Shared processing and evaluation functions for the ECG joint-design project."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import wfdb
from scipy import signal
from wfdb import processing


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.json"
DATA_DIR = PROJECT_ROOT / "data"
RESULTS_DIR = PROJECT_ROOT / "results"
FIGURES_DIR = PROJECT_ROOT / "figures"
REPORT_DIR = PROJECT_ROOT / "report"

MITDB_BASE_URL = "https://physionet.org/files/mitdb/1.0.0"
NSTDB_BASE_URL = "https://physionet.org/files/nstdb/1.0.0"

BEAT_SYMBOLS = frozenset(
    {
        "N",
        "L",
        "R",
        "B",
        "A",
        "a",
        "J",
        "S",
        "V",
        "r",
        "F",
        "e",
        "j",
        "n",
        "E",
        "/",
        "f",
        "Q",
        "?",
    }
)


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def ensure_project_dirs() -> None:
    for path in (DATA_DIR / "mitdb", DATA_DIR / "nstdb", RESULTS_DIR, FIGURES_DIR, REPORT_DIR):
        path.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def interval_mask(times_s: np.ndarray, intervals: Iterable[tuple[float, float]]) -> np.ndarray:
    mask = np.zeros(len(times_s), dtype=bool)
    for start_s, end_s in intervals:
        mask |= (times_s >= start_s) & (times_s < end_s)
    return mask


def trim_intervals(
    intervals: Iterable[tuple[float, float]], margin_s: float
) -> list[tuple[float, float]]:
    return [
        (start_s + margin_s, end_s - margin_s)
        for start_s, end_s in intervals
        if end_s - start_s > 2 * margin_s
    ]


def make_noise_intervals(
    duration_s: float, start_s: float, on_s: float, off_s: float
) -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    cursor = start_s
    while cursor < duration_s:
        intervals.append((cursor, min(cursor + on_s, duration_s)))
        cursor += on_s + off_s
    return intervals


def front_end_filter(x_mv: np.ndarray, fs_hz: int, band_hz: tuple[float, float], order: int) -> np.ndarray:
    sos = signal.butter(order, band_hz, btype="bandpass", fs=fs_hz, output="sos")
    return signal.sosfiltfilt(sos, x_mv)


def resample_signal(x_mv: np.ndarray, source_fs_hz: int, target_fs_hz: int) -> np.ndarray:
    if target_fs_hz == source_fs_hz:
        return x_mv.copy()
    common = math.gcd(source_fs_hz, target_fs_hz)
    return signal.resample_poly(
        x_mv,
        target_fs_hz // common,
        source_fs_hz // common,
        padtype="line",
    )


@dataclass(frozen=True)
class QuantizedSignal:
    values_mv: np.ndarray
    unclipped_mv: np.ndarray
    clipping_mask: np.ndarray
    lsb_mv: float


def quantize_fixed_range(x_mv: np.ndarray, bits: int, full_scale_mv_pp: float) -> QuantizedSignal:
    half_scale = full_scale_mv_pp / 2.0
    lsb_mv = full_scale_mv_pp / (2**bits)
    clipping_mask = (x_mv < -half_scale) | (x_mv > half_scale - lsb_mv)
    clipped = np.clip(x_mv, -half_scale, half_scale - lsb_mv)
    codes = np.round((clipped + half_scale) / lsb_mv)
    quantized = codes * lsb_mv - half_scale
    quantized = np.clip(quantized, -half_scale, half_scale - lsb_mv)
    return QuantizedSignal(quantized, x_mv, clipping_mask, lsb_mv)


def read_reference_beats(record_path: Path, source_fs_hz: int) -> tuple[np.ndarray, np.ndarray]:
    annotation = wfdb.rdann(str(record_path), "atr")
    symbols = np.asarray(annotation.symbol)
    beat_mask = np.asarray([symbol in BEAT_SYMBOLS for symbol in symbols])
    return annotation.sample[beat_mask] / source_fs_hz, symbols[beat_mask]


def detect_r_peaks(x_mv: np.ndarray, fs_hz: int) -> np.ndarray:
    samples = processing.xqrs_detect(sig=x_mv, fs=fs_hz, learn=True, verbose=False)
    return samples / fs_hz


def one_to_one_match(
    reference_s: np.ndarray, detected_s: np.ndarray, tolerance_s: float
) -> tuple[int, int, int, np.ndarray]:
    i = j = tp = 0
    errors: list[float] = []
    while i < len(reference_s) and j < len(detected_s):
        delta = detected_s[j] - reference_s[i]
        if abs(delta) <= tolerance_s:
            tp += 1
            errors.append(abs(delta))
            i += 1
            j += 1
        elif detected_s[j] < reference_s[i] - tolerance_s:
            j += 1
        else:
            i += 1
    return tp, len(detected_s) - tp, len(reference_s) - tp, np.asarray(errors)


def safe_ratio(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator else float("nan")


def evaluate_scope(
    reference_s: np.ndarray,
    detected_s: np.ndarray,
    target_fs_hz: int,
    quantized: QuantizedSignal,
    intervals: list[tuple[float, float]],
    tolerance_ms: int,
) -> dict:
    ref = reference_s[interval_mask(reference_s, intervals)]
    det = detected_s[interval_mask(detected_s, intervals)]
    tp, fp, fn, errors = one_to_one_match(ref, det, tolerance_ms / 1000.0)

    sample_times = np.arange(len(quantized.values_mv)) / target_fs_hz
    sample_mask = interval_mask(sample_times, intervals)
    before = quantized.unclipped_mv[sample_mask]
    after = quantized.values_mv[sample_mask]
    clipping = quantized.clipping_mask[sample_mask]
    error = after - before
    rmse_mv = float(np.sqrt(np.mean(error**2))) if len(error) else float("nan")
    signal_rms_mv = float(np.sqrt(np.mean(before**2))) if len(before) else float("nan")
    quant_snr_db = (
        float(20 * np.log10(signal_rms_mv / rmse_mv))
        if rmse_mv > 0 and signal_rms_mv > 0
        else float("inf")
    )

    sensitivity = safe_ratio(tp, tp + fn)
    ppv = safe_ratio(tp, tp + fp)
    f1 = safe_ratio(2 * sensitivity * ppv, sensitivity + ppv)
    return {
        "tolerance_ms": tolerance_ms,
        "reference_beats": len(ref),
        "detected_beats": len(det),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "sensitivity_pct": sensitivity * 100,
        "ppv_pct": ppv * 100,
        "f1_pct": f1 * 100,
        "median_abs_timing_error_ms": float(np.median(errors) * 1000) if len(errors) else float("nan"),
        "p95_abs_timing_error_ms": float(np.percentile(errors, 95) * 1000) if len(errors) else float("nan"),
        "clipping_rate_pct": float(np.mean(clipping) * 100) if len(clipping) else float("nan"),
        "quantization_rmse_uv": rmse_mv * 1000,
        "quantization_snr_db": quant_snr_db,
        "evaluated_duration_s": float(sum(end - start for start, end in intervals)),
    }


def parse_noise_record_name(record_name: str) -> tuple[str, int]:
    base_record = record_name[:3]
    suffix = record_name[4:]
    snr_db = -6 if suffix == "_6" else int(suffix)
    return base_record, snr_db
