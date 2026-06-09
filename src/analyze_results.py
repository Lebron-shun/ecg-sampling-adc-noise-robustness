"""Aggregate full experiments, select configurations, and generate final figures."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import wfdb
from scipy import stats

from project_core import (
    DATA_DIR,
    FIGURES_DIR,
    RESULTS_DIR,
    ensure_project_dirs,
    front_end_filter,
    load_config,
    quantize_fixed_range,
    resample_signal,
)


matplotlib.use("Agg")
from matplotlib import pyplot as plt

COLORS = {
    "blue_main": "#0F4D92",
    "blue_mid": "#3775BA",
    "blue_soft": "#B4C0E4",
    "teal": "#42949E",
    "green": "#8BCF8B",
    "green_soft": "#DDF3DE",
    "red": "#B64342",
    "red_soft": "#F6CFCB",
    "gold": "#C58A22",
    "neutral_light": "#D8D8D8",
    "neutral_mid": "#767676",
    "neutral_dark": "#4D4D4D",
    "neutral_black": "#272727",
    "panel_bg": "#F7F8FA",
}


def configure_matplotlib() -> None:
    candidates = [
        "Arial",
        "Helvetica",
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "DejaVu Sans",
        "sans-serif",
    ]
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": candidates,
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "font.size": 8,
            "axes.linewidth": 0.8,
            "axes.unicode_minus": False,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "regular",
            "axes.titlecolor": COLORS["neutral_black"],
            "axes.labelcolor": COLORS["neutral_black"],
            "xtick.color": COLORS["neutral_dark"],
            "ytick.color": COLORS["neutral_dark"],
            "grid.color": "#E6E8EC",
            "grid.alpha": 0.75,
            "grid.linewidth": 0.55,
            "legend.frameon": False,
            "legend.fontsize": 7,
            "xtick.major.width": 0.8,
            "ytick.major.width": 0.8,
            "xtick.major.size": 3,
            "ytick.major.size": 3,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
            "savefig.dpi": 600,
        }
    )


def pooled_metrics(group: pd.DataFrame) -> pd.Series:
    tp, fp, fn = group[["tp", "fp", "fn"]].sum()
    sensitivity = tp / (tp + fn) if tp + fn else np.nan
    ppv = tp / (tp + fp) if tp + fp else np.nan
    f1 = 2 * sensitivity * ppv / (sensitivity + ppv) if sensitivity + ppv else np.nan
    return pd.Series(
        {
            "records": group["record"].nunique(),
            "reference_beats": group["reference_beats"].sum(),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "pooled_sensitivity_pct": sensitivity * 100,
            "pooled_ppv_pct": ppv * 100,
            "pooled_f1_pct": f1 * 100,
            "macro_f1_mean_pct": group["f1_pct"].mean(),
            "macro_f1_median_pct": group["f1_pct"].median(),
            "macro_f1_q05_pct": group["f1_pct"].quantile(0.05),
            "median_timing_error_ms": group["median_abs_timing_error_ms"].median(),
            "p95_timing_error_ms_median": group["p95_abs_timing_error_ms"].median(),
            "clipping_rate_pct_mean": group["clipping_rate_pct"].mean(),
            "quantization_rmse_uv_mean": group["quantization_rmse_uv"].mean(),
            "quantization_snr_db_median": group["quantization_snr_db"].replace(np.inf, np.nan).median(),
            "raw_bitrate_bps": group["raw_bitrate_bps"].iloc[0],
            "storage_mib_per_day": group["storage_mib_per_day"].iloc[0],
        }
    )


def aggregate_clean(clean: pd.DataFrame) -> pd.DataFrame:
    selected = clean[
        (clean["eval_scope"] == "clean_after_5min") & (clean["tolerance_ms"] == 150)
    ].copy()
    return (
        selected.groupby(["target_fs_hz", "bits"], sort=True)
        .apply(pooled_metrics, include_groups=False)
        .reset_index()
    )


def aggregate_noise(noise: pd.DataFrame) -> pd.DataFrame:
    selected = noise[
        (noise["eval_scope"] == "noise_only") & (noise["tolerance_ms"] == 150)
    ].copy()
    return (
        selected.groupby(["snr_db", "target_fs_hz", "bits"], sort=True)
        .apply(pooled_metrics, include_groups=False)
        .reset_index()
    )


def add_reference_drops(table: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    reference = table[(table["target_fs_hz"] == 360) & (table["bits"] == 11)]
    if by:
        reference = reference[by + ["pooled_f1_pct"]].rename(
            columns={"pooled_f1_pct": "reference_f1_pct"}
        )
        merged = table.merge(reference, on=by, how="left")
    else:
        merged = table.copy()
        merged["reference_f1_pct"] = float(reference["pooled_f1_pct"].iloc[0])
    merged["f1_drop_from_reference_pp"] = merged["reference_f1_pct"] - merged["pooled_f1_pct"]
    merged["bitrate_reduction_pct"] = (1 - merged["raw_bitrate_bps"] / (360 * 11)) * 100
    return merged


def bootstrap_clean_drops(clean: pd.DataFrame, iterations: int, seed: int) -> pd.DataFrame:
    selected = clean[
        (clean["eval_scope"] == "clean_after_5min") & (clean["tolerance_ms"] == 150)
    ].copy()
    records = np.asarray(sorted(selected["record"].unique()))
    rng = np.random.default_rng(seed)
    configurations = selected[["target_fs_hz", "bits"]].drop_duplicates().sort_values(
        ["target_fs_hz", "bits"]
    )
    ref = selected[(selected["target_fs_hz"] == 360) & (selected["bits"] == 11)].set_index("record")
    rows = []
    for config in configurations.itertuples(index=False):
        candidate = selected[
            (selected["target_fs_hz"] == config.target_fs_hz)
            & (selected["bits"] == config.bits)
        ].set_index("record")
        common = np.asarray(sorted(set(ref.index) & set(candidate.index)))
        ref_values = ref.loc[common, "f1_pct"].to_numpy()
        candidate_values = candidate.loc[common, "f1_pct"].to_numpy()
        observed = float(np.mean(ref_values - candidate_values))
        bootstrap = np.empty(iterations)
        for i in range(iterations):
            indices = rng.integers(0, len(common), size=len(common))
            bootstrap[i] = np.mean(ref_values[indices] - candidate_values[indices])
        rows.append(
            {
                "target_fs_hz": config.target_fs_hz,
                "bits": config.bits,
                "macro_f1_drop_mean_pp": observed,
                "macro_f1_drop_ci_low_pp": np.percentile(bootstrap, 2.5),
                "macro_f1_drop_ci_high_pp": np.percentile(bootstrap, 97.5),
            }
        )
    return pd.DataFrame(rows)


def holm_adjust(p_values: np.ndarray) -> np.ndarray:
    order = np.argsort(p_values)
    adjusted = np.empty(len(p_values), dtype=float)
    running = 0.0
    total = len(p_values)
    for rank, index in enumerate(order):
        candidate = min(1.0, (total - rank) * p_values[index])
        running = max(running, candidate)
        adjusted[index] = running
    return adjusted


def paired_clean_tests(clean: pd.DataFrame) -> pd.DataFrame:
    selected = clean[
        (clean["eval_scope"] == "clean_after_5min") & (clean["tolerance_ms"] == 150)
    ].copy()
    reference = selected[
        (selected["target_fs_hz"] == 360) & (selected["bits"] == 11)
    ][["record", "f1_pct"]].rename(columns={"f1_pct": "reference_f1_pct"})
    rows = []
    for (target_fs, bits), group in selected.groupby(["target_fs_hz", "bits"]):
        paired = reference.merge(
            group[["record", "f1_pct"]].rename(columns={"f1_pct": "candidate_f1_pct"}),
            on="record",
        )
        differences = paired["reference_f1_pct"] - paired["candidate_f1_pct"]
        if np.allclose(differences, 0):
            statistic, p_value = 0.0, 1.0
        else:
            statistic, p_value = stats.wilcoxon(
                paired["reference_f1_pct"],
                paired["candidate_f1_pct"],
                alternative="two-sided",
                zero_method="pratt",
            )
        rows.append(
            {
                "target_fs_hz": target_fs,
                "bits": bits,
                "records": len(paired),
                "mean_f1_drop_pp": differences.mean(),
                "median_f1_drop_pp": differences.median(),
                "wilcoxon_statistic": statistic,
                "p_value": p_value,
            }
        )
    table = pd.DataFrame(rows)
    table["p_holm"] = holm_adjust(table["p_value"].to_numpy())
    return table


def interaction_contrasts(clean: pd.DataFrame, bootstrap_iterations: int, seed: int) -> pd.DataFrame:
    selected = clean[
        (clean["eval_scope"] == "clean_after_5min") & (clean["tolerance_ms"] == 150)
    ][["record", "target_fs_hz", "bits", "f1_pct"]].copy()
    pivot = selected.pivot(index="record", columns=["target_fs_hz", "bits"], values="f1_pct")
    rng = np.random.default_rng(seed + 1)
    rows = []
    for target_fs in sorted(selected["target_fs_hz"].unique()):
        if target_fs == 360:
            continue
        for bits in sorted(selected["bits"].unique()):
            if bits == 11:
                continue
            required = [(360, 11), (target_fs, 11), (360, bits), (target_fs, bits)]
            complete = pivot[required].dropna()
            contrast = (
                complete[(360, 11)]
                - complete[(target_fs, 11)]
                - complete[(360, bits)]
                + complete[(target_fs, bits)]
            ).to_numpy()
            bootstrap = np.empty(bootstrap_iterations)
            for i in range(bootstrap_iterations):
                sample = rng.integers(0, len(contrast), size=len(contrast))
                bootstrap[i] = contrast[sample].mean()
            rows.append(
                {
                    "target_fs_hz": target_fs,
                    "bits": bits,
                    "records": len(contrast),
                    "interaction_mean_pp": contrast.mean(),
                    "interaction_ci_low_pp": np.percentile(bootstrap, 2.5),
                    "interaction_ci_high_pp": np.percentile(bootstrap, 97.5),
                }
            )
    return pd.DataFrame(rows)


def select_recommended(
    clean_agg: pd.DataFrame, noise_agg: pd.DataFrame, config: dict
) -> tuple[pd.DataFrame, dict]:
    constraints = config["recommended_constraints"]
    clean = (
        clean_agg.copy()
        if "f1_drop_from_reference_pp" in clean_agg.columns
        else add_reference_drops(clean_agg, [])
    )
    noise = (
        noise_agg.copy()
        if "f1_drop_from_reference_pp" in noise_agg.columns
        else add_reference_drops(noise_agg, ["snr_db"])
    )
    noise_at_or_above_6 = noise[noise["snr_db"] >= 6].copy()
    noise_summary = (
        noise_at_or_above_6.groupby(["target_fs_hz", "bits"], as_index=False)
        .agg(
            worst_noise_f1_drop_pp=("f1_drop_from_reference_pp", "max"),
            minimum_noise_f1_pct=("pooled_f1_pct", "min"),
            mean_noise_f1_pct=("pooled_f1_pct", "mean"),
        )
    )
    candidates = clean.merge(noise_summary, on=["target_fs_hz", "bits"], how="left")
    candidates["meets_clean_absolute"] = (
        candidates["pooled_f1_pct"] >= constraints["clean_pooled_f1_min_pct"]
    )
    candidates["meets_clean_relative"] = (
        candidates["f1_drop_from_reference_pp"] <= constraints["clean_f1_drop_max_pp"]
    )
    candidates["meets_noise_relative"] = (
        candidates["worst_noise_f1_drop_pp"] <= constraints["noise_f1_drop_max_pp"]
    )
    candidates["meets_timing"] = (
        candidates["median_timing_error_ms"] <= constraints["median_timing_error_max_ms"]
    )
    candidates["meets_all"] = candidates[
        [
            "meets_clean_absolute",
            "meets_clean_relative",
            "meets_noise_relative",
            "meets_timing",
        ]
    ].all(axis=1)
    candidates["analog_transition_band_hz"] = candidates["target_fs_hz"] / 2 - 40
    candidates["analog_practical"] = candidates["analog_transition_band_hz"] >= 20
    feasible = candidates[candidates["meets_all"] & candidates["analog_practical"]].copy()
    if feasible.empty:
        feasible = candidates[candidates["meets_all"]].copy()
    if feasible.empty:
        feasible = candidates.copy()
    feasible.sort_values(
        ["raw_bitrate_bps", "worst_noise_f1_drop_pp", "target_fs_hz", "bits"],
        inplace=True,
    )
    chosen = feasible.iloc[0].to_dict()
    return candidates.sort_values(["raw_bitrate_bps", "target_fs_hz", "bits"]), chosen


def add_panel_label(ax, label: str, x: float = -0.08, y: float = 1.04) -> None:
    ax.text(
        x,
        y,
        label,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=9,
        fontweight="bold",
        color=COLORS["neutral_black"],
    )


def style_axis(ax, grid_axis: str | bool = "y") -> None:
    ax.tick_params(labelsize=7)
    ax.xaxis.label.set_size(8)
    ax.yaxis.label.set_size(8)
    ax.title.set_size(8.5)
    if grid_axis:
        ax.grid(True, axis=grid_axis)
    else:
        ax.grid(False)
    for spine in ax.spines.values():
        spine.set_color(COLORS["neutral_dark"])


def style_colorbar(colorbar) -> None:
    colorbar.ax.tick_params(labelsize=7, width=0.7, length=2.5)
    colorbar.outline.set_linewidth(0.6)
    colorbar.ax.yaxis.label.set_size(7)


def heat_text_color(image, value: float) -> str:
    rgba = image.cmap(image.norm(value))
    r, g, b = rgba[:3]
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return COLORS["neutral_black"] if luminance > 0.58 else "white"


def annotate_heatmap(ax, matrix: pd.DataFrame, fmt: str, image) -> None:
    for y, row in enumerate(matrix.to_numpy()):
        for x, value in enumerate(row):
            ax.text(
                x,
                y,
                format(value, fmt),
                ha="center",
                va="center",
                fontsize=6.3,
                color=heat_text_color(image, float(value)),
            )


def save_figure(fig, name: str) -> None:
    png_path = FIGURES_DIR / name
    stem = png_path.with_suffix("")
    fig.savefig(png_path, bbox_inches="tight", dpi=600)
    fig.savefig(stem.with_suffix(".svg"), bbox_inches="tight")
    fig.savefig(stem.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


def plot_system_diagram() -> None:
    fig, ax = plt.subplots(figsize=(7.2, 2.25))
    ax.axis("off")
    labels = [
        "Surface\nelectrodes",
        "Protection &\ninstrumentation amp",
        "0.5-40 Hz\nfront end",
        "Configurable\nsampling + ADC",
        "Digital\nQRS detector",
        "R peaks, RR,\nheart rate",
    ]
    x_positions = np.linspace(0.075, 0.925, len(labels))
    for index, (x, label) in enumerate(zip(x_positions, labels)):
        edge = COLORS["blue_main"] if index < 4 else COLORS["teal"]
        face = "#F3F6FB" if index < 4 else "#EEF7F6"
        ax.text(
            x,
            0.5,
            label,
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=7.2,
            color=COLORS["neutral_black"],
            bbox=dict(boxstyle="round,pad=0.42", fc=face, ec=edge, lw=0.9),
        )
        if index < len(labels) - 1:
            ax.annotate(
                "",
                xy=(x_positions[index + 1] - 0.055, 0.5),
                xytext=(x + 0.055, 0.5),
                xycoords=ax.transAxes,
                arrowprops=dict(arrowstyle="->", lw=0.9, color=COLORS["neutral_mid"]),
            )
    ax.text(
        0.5,
        0.08,
        "Implemented as a reproducible virtual acquisition and signal-processing system",
        transform=ax.transAxes,
        ha="center",
        color=COLORS["neutral_mid"],
        fontsize=6.8,
    )
    add_panel_label(ax, "a", x=0.0, y=0.93)
    save_figure(fig, "figure_01_system_diagram.png")


def plot_workflow_diagram() -> None:
    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    ax.axis("off")
    labels = [
        "MIT-BIH / NSTDB\npublic ECG",
        "Band-limit\n0.5-40 Hz",
        "Anti-alias\nresampling",
        "Fixed-range\nquantization",
        "Fixed XQRS\ndetection",
        "One-to-one\nannotation match",
        "Metrics +\nPareto selection",
    ]
    xs = np.linspace(0.055, 0.945, len(labels))
    for index, (x, label) in enumerate(zip(xs, labels)):
        ax.text(
            x,
            0.55,
            label,
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=6.7,
            color=COLORS["neutral_black"],
            bbox=dict(boxstyle="round,pad=0.34", fc="#F7F8FA", ec=COLORS["blue_mid"], lw=0.8),
        )
        if index < len(labels) - 1:
            ax.annotate(
                "",
                xy=(xs[index + 1] - 0.046, 0.55),
                xytext=(x + 0.046, 0.55),
                xycoords=ax.transAxes,
                arrowprops=dict(arrowstyle="->", lw=0.8, color=COLORS["blue_mid"]),
            )
    ax.text(
        0.5,
        0.12,
        "Full factorial design: 5 sampling rates x 6 effective resolutions; clean and standardized motion-artifact evaluation",
        transform=ax.transAxes,
        ha="center",
        fontsize=6.7,
        color=COLORS["neutral_mid"],
    )
    add_panel_label(ax, "a", x=0.0, y=0.94)
    save_figure(fig, "figure_02_experiment_workflow.png")


def plot_waveform_comparison() -> None:
    record_path = DATA_DIR / "mitdb" / "118"
    record = wfdb.rdrecord(str(record_path), sampfrom=300 * 360, sampto=305 * 360, channels=[0])
    x = front_end_filter(record.p_signal[:, 0], 360, (0.5, 40.0), 4)
    configurations = [(360, 11), (180, 8), (100, 6)]
    fig, axes = plt.subplots(3, 1, figsize=(7.2, 4.6), sharex=True)
    line_colors = [COLORS["neutral_black"], COLORS["blue_mid"], COLORS["teal"]]
    for idx, (ax, (fs, bits), color) in enumerate(zip(axes, configurations, line_colors)):
        y = resample_signal(x, 360, fs)
        q = quantize_fixed_range(y, bits, 10.0)
        t = np.arange(len(q.values_mv)) / fs
        ax.plot(t, q.values_mv, lw=0.75, color=color)
        ax.set_ylabel("mV")
        ax.set_title(f"{fs} Hz / {bits} bit  |  LSB {q.lsb_mv * 1000:.1f} µV", loc="left", pad=3)
        style_axis(ax, grid_axis="y")
        ax.set_xlim(0.5, 4.5)
        add_panel_label(ax, chr(ord("a") + idx), x=-0.055, y=1.02)
    axes[-1].set_xlabel("Time (s)")
    fig.suptitle("Representative ECG after virtual acquisition", fontsize=9.5, fontweight="regular", y=0.995)
    fig.tight_layout(h_pad=1.05)
    save_figure(fig, "figure_03_waveform_comparison.png")


def plot_clean_heatmaps(clean_agg: pd.DataFrame) -> None:
    f1 = clean_agg.pivot(index="target_fs_hz", columns="bits", values="pooled_f1_pct").sort_index(ascending=False)
    timing = clean_agg.pivot(index="target_fs_hz", columns="bits", values="median_timing_error_ms").sort_index(ascending=False)
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.65))
    for ax, matrix, title, cmap, fmt in (
        (axes[0], f1, "Pooled F1 (%)", "YlGnBu", ".2f"),
        (axes[1], timing, "Median R-peak timing error (ms)", "YlOrBr", ".2f"),
    ):
        image = ax.imshow(matrix.to_numpy(), aspect="auto", cmap=cmap)
        ax.set_xticks(range(len(matrix.columns)), matrix.columns)
        ax.set_yticks(range(len(matrix.index)), matrix.index)
        ax.set_xlabel("Effective resolution (bit)")
        ax.set_ylabel("Sampling rate (Hz)")
        ax.set_title(title, pad=5)
        style_axis(ax, grid_axis=False)
        annotate_heatmap(ax, matrix, fmt, image)
        cbar = fig.colorbar(image, ax=ax, shrink=0.76, pad=0.02)
        cbar.set_label(title.split("(")[-1].replace(")", ""))
        style_colorbar(cbar)
    add_panel_label(axes[0], "a")
    add_panel_label(axes[1], "b")
    fig.suptitle("Clean-condition full-factorial results", fontsize=9.5, fontweight="regular", y=1.01)
    fig.tight_layout(w_pad=2.0)
    save_figure(fig, "figure_04_clean_heatmaps.png")


def plot_noise_curves(noise_agg: pd.DataFrame, configurations: list[tuple[int, int]]) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 3.9))
    palette = [COLORS["neutral_black"], COLORS["blue_main"], COLORS["blue_mid"], COLORS["teal"], COLORS["red"]]
    for color, (fs, bits) in zip(palette, configurations):
        subset = noise_agg[
            (noise_agg["target_fs_hz"] == fs) & (noise_agg["bits"] == bits)
        ].sort_values("snr_db")
        is_recommended = (fs, bits) == (360, 6)
        ax.plot(
            subset["snr_db"],
            subset["pooled_f1_pct"],
            marker="o",
            ms=3.6,
            lw=1.35 if is_recommended else 0.95,
            label=f"{fs} Hz / {bits} bit",
            color=color,
            alpha=1.0 if is_recommended else 0.72,
        )
        if is_recommended or (fs, bits) == (100, 6):
            last = subset.iloc[-1]
            offset = 0.12 if is_recommended else -0.35
            ax.text(
                last["snr_db"] + 0.25,
                last["pooled_f1_pct"] + offset,
                f"{fs}/{bits}",
                fontsize=6.4,
                color=color,
                va="center",
            )
    ax.set_xlabel("Motion-artifact SNR (dB)")
    ax.set_ylabel("Pooled F1 (%)")
    ax.set_title("R-peak detection robustness under standardized motion artifact", pad=5)
    ax.set_ylim(max(0, noise_agg["pooled_f1_pct"].min() - 2), 101)
    ax.set_xlim(noise_agg["snr_db"].min() - 0.6, noise_agg["snr_db"].max() + 2.2)
    style_axis(ax, grid_axis="y")
    ax.legend(ncol=3, loc="lower right", handlelength=1.8, columnspacing=0.9)
    add_panel_label(ax, "a")
    save_figure(fig, "figure_05_noise_robustness.png")


def plot_pareto(candidates: pd.DataFrame, chosen: dict) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.25))
    scatter = ax.scatter(
        candidates["raw_bitrate_bps"],
        candidates["pooled_f1_pct"],
        c=candidates["target_fs_hz"],
        s=28 + 7 * (candidates["bits"] - 6),
        cmap="YlGnBu",
        alpha=0.88,
        edgecolor="white",
        linewidth=0.5,
    )
    ax.axhline(99.0, color=COLORS["neutral_mid"], lw=0.8, ls="--")
    ax.text(
        candidates["raw_bitrate_bps"].min(),
        99.03,
        "F1 threshold",
        fontsize=6.5,
        color=COLORS["neutral_mid"],
        va="bottom",
    )
    ax.scatter(
        [chosen["raw_bitrate_bps"]],
        [chosen["pooled_f1_pct"]],
        marker="*",
        s=180,
        color=COLORS["red"],
        edgecolor=COLORS["neutral_black"],
        linewidth=0.8,
        label="Recommended",
        zorder=5,
    )
    ax.annotate(
        f"{int(chosen['target_fs_hz'])} Hz / {int(chosen['bits'])} bit",
        (chosen["raw_bitrate_bps"], chosen["pooled_f1_pct"]),
        xytext=(10, -20),
        textcoords="offset points",
        fontsize=7,
        color=COLORS["red"],
        arrowprops=dict(arrowstyle="->", color=COLORS["red"], lw=0.8),
    )
    ax.set_xlabel("Raw single-channel data rate (bit/s)")
    ax.set_ylabel("Clean-condition pooled F1 (%)")
    ax.set_title("Performance-resource trade-off", pad=5)
    ax.set_ylim(95.8, 99.65)
    style_axis(ax, grid_axis="y")
    ax.legend(loc="lower right")
    cbar = fig.colorbar(scatter, ax=ax, label="Sampling rate (Hz)", pad=0.02)
    style_colorbar(cbar)
    add_panel_label(ax, "a")
    save_figure(fig, "figure_06_pareto_tradeoff.png")


def plot_noise_degradation_heatmap(noise_agg: pd.DataFrame) -> None:
    lowest = noise_agg[noise_agg["snr_db"] == noise_agg["snr_db"].min()]
    matrix = lowest.pivot(index="target_fs_hz", columns="bits", values="pooled_f1_pct").sort_index(ascending=False)
    fig, ax = plt.subplots(figsize=(5.8, 3.65))
    image = ax.imshow(matrix.to_numpy(), aspect="auto", cmap="YlGnBu", vmin=matrix.to_numpy().min(), vmax=matrix.to_numpy().max())
    ax.set_xticks(range(len(matrix.columns)), matrix.columns)
    ax.set_yticks(range(len(matrix.index)), matrix.index)
    ax.set_xlabel("Effective resolution (bit)")
    ax.set_ylabel("Sampling rate (Hz)")
    ax.set_title(f"Severe motion artifact: pooled F1 at {noise_agg['snr_db'].min():.0f} dB", pad=5)
    style_axis(ax, grid_axis=False)
    annotate_heatmap(ax, matrix, ".2f", image)
    cbar = fig.colorbar(image, ax=ax, label="F1 (%)", pad=0.02)
    style_colorbar(cbar)
    add_panel_label(ax, "a")
    save_figure(fig, "figure_07_severe_noise_heatmap.png")


def plot_record_distribution(clean: pd.DataFrame, chosen: dict) -> None:
    selected = clean[
        (clean["eval_scope"] == "clean_after_5min")
        & (clean["tolerance_ms"] == 150)
        & (
            ((clean["target_fs_hz"] == 360) & (clean["bits"] == 11))
            | (
                (clean["target_fs_hz"] == int(chosen["target_fs_hz"]))
                & (clean["bits"] == int(chosen["bits"]))
            )
        )
    ].copy()
    selected["configuration"] = np.where(
        (selected["target_fs_hz"] == 360) & (selected["bits"] == 11),
        "Reference: 360 Hz / 11 bit",
        f"Recommended: {int(chosen['target_fs_hz'])} Hz / {int(chosen['bits'])} bit",
    )
    groups = [
        selected[selected["configuration"] == label]["f1_pct"].to_numpy()
        for label in selected["configuration"].unique()
    ]
    labels = list(selected["configuration"].unique())
    fig, ax = plt.subplots(figsize=(6.4, 3.9))
    box = ax.boxplot(
        groups,
        tick_labels=["Reference\n360/11", "Recommended\n360/6"],
        patch_artist=True,
        widths=0.48,
        medianprops=dict(color=COLORS["neutral_black"], linewidth=1.0),
        whiskerprops=dict(color=COLORS["neutral_dark"], linewidth=0.8),
        capprops=dict(color=COLORS["neutral_dark"], linewidth=0.8),
        flierprops=dict(marker="o", markerfacecolor="none", markeredgecolor=COLORS["neutral_mid"], markersize=3),
    )
    for patch, color in zip(box["boxes"], [COLORS["blue_soft"], COLORS["teal"]]):
        patch.set_facecolor(color)
        patch.set_alpha(0.72)
        patch.set_edgecolor(COLORS["neutral_dark"])
        patch.set_linewidth(0.8)
    for index, values in enumerate(groups, start=1):
        jitter = np.linspace(-0.10, 0.10, len(values))
        ax.scatter(
            np.full(len(values), index) + jitter,
            values,
            s=9,
            color=COLORS["neutral_dark"],
            alpha=0.42,
            zorder=3,
        )
    ax.set_ylabel("Per-record F1 (%)")
    ax.set_title("Record-level performance distribution", pad=5)
    ax.set_ylim(max(90, selected["f1_pct"].min() - 1), 100.4)
    style_axis(ax, grid_axis="y")
    add_panel_label(ax, "a")
    save_figure(fig, "figure_08_record_distribution.png")


def copy_final_tables(paths: list[Path]) -> None:
    tables_dir = RESULTS_DIR / "final_tables"
    tables_dir.mkdir(exist_ok=True)
    for path in paths:
        shutil.copy2(path, tables_dir / path.name)


def main() -> None:
    ensure_project_dirs()
    configure_matplotlib()
    config = load_config()
    clean_path = RESULTS_DIR / "per_record_clean.csv"
    noise_path = RESULTS_DIR / "per_record_noise.csv"
    if not clean_path.exists() or not noise_path.exists():
        raise FileNotFoundError("Run src/run_experiments.py --mode all before analysis")
    clean = pd.read_csv(clean_path)
    noise = pd.read_csv(noise_path)

    clean_agg = aggregate_clean(clean)
    noise_agg = aggregate_noise(noise)
    clean_agg = add_reference_drops(clean_agg, [])
    noise_agg = add_reference_drops(noise_agg, ["snr_db"])
    bootstrap = bootstrap_clean_drops(
        clean, int(config["bootstrap_iterations"]), int(config["bootstrap_seed"])
    )
    paired_tests = paired_clean_tests(clean)
    interactions = interaction_contrasts(
        clean, int(config["bootstrap_iterations"]), int(config["bootstrap_seed"])
    )
    candidates, chosen = select_recommended(clean_agg, noise_agg, config)

    paths = [
        RESULTS_DIR / "aggregate_clean.csv",
        RESULTS_DIR / "aggregate_noise_by_snr.csv",
        RESULTS_DIR / "clean_bootstrap_drops.csv",
        RESULTS_DIR / "candidate_summary.csv",
        RESULTS_DIR / "clean_paired_tests.csv",
        RESULTS_DIR / "interaction_contrasts.csv",
    ]
    clean_agg.to_csv(paths[0], index=False, float_format="%.8f")
    noise_agg.to_csv(paths[1], index=False, float_format="%.8f")
    bootstrap.to_csv(paths[2], index=False, float_format="%.8f")
    candidates.to_csv(paths[3], index=False, float_format="%.8f")
    paired_tests.to_csv(paths[4], index=False, float_format="%.8f")
    interactions.to_csv(paths[5], index=False, float_format="%.8f")
    (RESULTS_DIR / "recommended_config.json").write_text(
        json.dumps(chosen, indent=2, ensure_ascii=False, default=float), encoding="utf-8"
    )

    plot_system_diagram()
    plot_workflow_diagram()
    plot_waveform_comparison()
    plot_clean_heatmaps(clean_agg)
    plot_noise_curves(
        noise_agg,
        [
            (360, 11),
            (int(chosen["target_fs_hz"]), int(chosen["bits"])),
            (180, 8),
            (125, 8),
            (100, 6),
        ],
    )
    plot_pareto(candidates, chosen)
    plot_noise_degradation_heatmap(noise_agg)
    plot_record_distribution(clean, chosen)
    copy_final_tables(paths)
    print(json.dumps(chosen, indent=2, ensure_ascii=False, default=float))


if __name__ == "__main__":
    main()
