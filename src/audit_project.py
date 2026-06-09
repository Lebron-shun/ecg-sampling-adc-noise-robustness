"""Completion audit for the final ECG joint-design submission package."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd

from project_core import FIGURES_DIR, PROJECT_ROOT, RESULTS_DIR


AUDIT_JSON = PROJECT_ROOT / "FINAL_AUDIT.json"
AUDIT_MD = PROJECT_ROOT / "FINAL_AUDIT.md"


def check(name: str, condition: bool, evidence: str) -> dict:
    return {"requirement": name, "passed": bool(condition), "evidence": evidence}


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> None:
    checks = []
    validation = json.loads((RESULTS_DIR / "data_validation_summary.json").read_text(encoding="utf-8"))
    clean = pd.read_csv(RESULTS_DIR / "per_record_clean.csv")
    noise = pd.read_csv(RESULTS_DIR / "per_record_noise.csv")
    clean_agg = pd.read_csv(RESULTS_DIR / "aggregate_clean.csv")
    noise_agg = pd.read_csv(RESULTS_DIR / "aggregate_noise_by_snr.csv")
    candidates = pd.read_csv(RESULTS_DIR / "candidate_summary.csv")
    recommended = json.loads((RESULTS_DIR / "recommended_config.json").read_text(encoding="utf-8"))
    monitoring_path = RESULTS_DIR / "monitoring_summary.csv"
    monitoring_metrics_path = RESULTS_DIR / "monitoring_metrics.csv"
    scenarios_path = RESULTS_DIR / "scenario_recommendations.json"
    monitoring = pd.read_csv(monitoring_path) if monitoring_path.exists() else pd.DataFrame()
    monitoring_metrics = pd.read_csv(monitoring_metrics_path) if monitoring_metrics_path.exists() else pd.DataFrame()
    scenarios = json.loads(scenarios_path.read_text(encoding="utf-8")) if scenarios_path.exists() else []

    checks.append(
        check(
            "Open-source data completeness",
            validation == {
                "total_records": 60,
                "mitdb_records": 48,
                "nstdb_records": 12,
                "all_360_hz": True,
                "all_nonempty": True,
                "failures": 0,
            },
            json.dumps(validation, ensure_ascii=False),
        )
    )
    checks.append(
        check(
            "Clean full-factorial coverage",
            len(clean) == 2880
            and clean.record.nunique() == 48
            and clean[["target_fs_hz", "bits"]].drop_duplicates().shape[0] == 30
            and clean[(clean.eval_scope == "clean_after_5min") & (clean.tolerance_ms == 150)]
            .groupby(["target_fs_hz", "bits"])
            .record.nunique()
            .eq(48)
            .all(),
            f"rows={len(clean)}, records={clean.record.nunique()}, configurations=30",
        )
    )
    checks.append(
        check(
            "Noise full-factorial coverage",
            len(noise) == 1440
            and noise.record.nunique() == 12
            and noise[["target_fs_hz", "bits"]].drop_duplicates().shape[0] == 30
            and len(noise_agg) == 180,
            f"rows={len(noise)}, records={noise.record.nunique()}, aggregate SNR-config rows={len(noise_agg)}",
        )
    )
    checks.append(
        check(
            "One-to-one metric count conservation",
            bool(
                ((clean.tp + clean.fn) == clean.reference_beats).all()
                and ((clean.tp + clean.fp) == clean.detected_beats).all()
                and ((noise.tp + noise.fn) == noise.reference_beats).all()
                and ((noise.tp + noise.fp) == noise.detected_beats).all()
            ),
            "All clean and noise rows satisfy TP+FN=reference beats and TP+FP=detected beats",
        )
    )
    checks.append(
        check(
            "No experiment failures",
            json.loads((RESULTS_DIR / "failures_mitdb.json").read_text()) == {}
            and json.loads((RESULTS_DIR / "failures_nstdb.json").read_text()) == {},
            "failures_mitdb.json={} and failures_nstdb.json={}",
        )
    )
    chosen_row = candidates[
        (candidates.target_fs_hz == recommended["target_fs_hz"])
        & (candidates.bits == recommended["bits"])
    ].iloc[0]
    checks.append(
        check(
            "Recommended configuration satisfies declared constraints",
            bool(chosen_row.meets_all and chosen_row.analog_practical),
            f"{int(chosen_row.target_fs_hz)} Hz/{int(chosen_row.bits)} bit; "
            f"clean F1={chosen_row.pooled_f1_pct:.3f}%; "
            f"worst >=6 dB relative noise drop={chosen_row.worst_noise_f1_drop_pp:.3f} pp",
        )
    )
    expected_figures = [FIGURES_DIR / f"figure_{index:02d}_{suffix}.png" for index, suffix in [
        (1, "system_diagram"),
        (2, "experiment_workflow"),
        (3, "waveform_comparison"),
        (4, "clean_heatmaps"),
        (5, "noise_robustness"),
        (6, "pareto_tradeoff"),
        (7, "severe_noise_heatmap"),
        (8, "record_distribution"),
        (9, "monitoring_metrics"),
    ]]
    checks.append(
        check(
            "Required result figures",
            all(path.exists() and path.stat().st_size > 20_000 for path in expected_figures),
            f"{sum(path.exists() for path in expected_figures)}/9 figures exist",
        )
    )
    checks.append(
        check(
            "Monitoring extension outputs",
            monitoring_path.exists()
            and monitoring_metrics_path.exists()
            and scenarios_path.exists()
            and len(monitoring) == 7
            and len(monitoring_metrics) == 48 * 7
            and monitoring[["target_fs_hz", "bits"]].drop_duplicates().shape[0] == 7
            and all(keyword in monitoring.columns for keyword in [
                "rr_median_abs_error_ms",
                "hr_median_abs_error_bpm",
                "valid_rr_pair_pct",
                "sdnn_relative_error_median_pct",
                "rmssd_relative_error_median_pct",
                "hrv_usable_record_pct",
            ])
            and len(scenarios) >= 5,
            f"monitoring_summary_rows={len(monitoring)}, monitoring_metric_rows={len(monitoring_metrics)}, scenarios={len(scenarios)}",
        )
    )
    checks.append(
        check(
            "Figure 9 editable export set",
            all(
                (FIGURES_DIR / f"figure_09_monitoring_metrics.{suffix}").exists()
                and (FIGURES_DIR / f"figure_09_monitoring_metrics.{suffix}").stat().st_size > 5_000
                for suffix in ["png", "svg", "pdf"]
            )
            and "<text" in (FIGURES_DIR / "figure_09_monitoring_metrics.svg").read_text(encoding="utf-8", errors="ignore"),
            "figure_09_monitoring_metrics exported as PNG/SVG/PDF with SVG text elements",
        )
    )
    tracked = tracked_files()
    readme_text = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    web_text = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
    web_js = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")
    web_data = (PROJECT_ROOT / "web" / "data.js").read_text(encoding="utf-8")
    public_text = "\n".join(
        [
            readme_text,
            web_text,
            web_js,
            web_data,
            (PROJECT_ROOT / "index.html").read_text(encoding="utf-8"),
        ]
    )
    checks.append(
        check(
            "Public repository excludes generated course reports",
            not any(path == "report" or path.startswith("report/") for path in tracked)
            and "report/" in (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
            and "private_submission/" in (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8"),
            "No report/ files are tracked; report/ and private_submission/ are ignored",
        )
    )
    checks.append(
        check(
            "Public README and web hide report links",
            all(keyword not in readme_text for keyword in ["final_report", "PDF报告", "DOCX报告", "report/final_report"])
            and all(keyword not in web_text for keyword in ["final_report", "PDF报告", "DOCX报告", "../report/"]),
            "README and web/index.html do not expose final_report PDF/DOCX links",
        )
    )
    checks.append(
        check(
            "Public showcase has no personal-info or scoring UI",
            all(keyword not in public_text for keyword in ["学号：", "班级：", "姓名：", "提交前填写"])
            and all(keyword not in web_text for keyword in ["Course Rubric", "课程评分对照", "5分", "6分", "17/17"]),
            "Public README/web/data do not expose personal-info fields or scoring UI",
        )
    )
    checks.append(
        check(
            "Public project package coverage",
            all(keyword in readme_text for keyword in ["RR/HRV", "GitHub Pages", "FINAL_AUDIT.md", "monitoring_analysis.py"])
            and "https://lebron-shun.github.io/ecg-sampling-adc-noise-robustness/" in readme_text
            and all(keyword in web_text for keyword in ["Project Overview", "Monitoring Scenarios", "医学监护场景", "项目README", "GitHub仓库", "实验图集"])
            and all(keyword in web_data for keyword in ["monitoring", "scenarios", "hr_rr_monitoring", "hrv_trend"]),
            "README, web showcase, and web data expose project materials without report links",
        )
    )
    checks.append(
        check(
            "Public monitoring scope and non-diagnostic boundary",
            all(keyword in public_text for keyword in ["RR", "HRV", "SDNN", "RMSSD"])
            and all(keyword in public_text for keyword in ["不解释疾病风险", "不评价ST段", "临床决策"]),
            "Public materials include monitoring extension and non-diagnostic boundary",
        )
    )
    required_scripts = [
        "download_data.py",
        "validate_data.py",
        "run_experiments.py",
        "analyze_results.py",
        "monitoring_analysis.py",
        "build_web_data.py",
        "build_report.py",
        "build_pdf.py",
        "audit_project.py",
        "project_core.py",
    ]
    checks.append(
        check(
            "Reproducible source code",
            all((PROJECT_ROOT / "src" / script).exists() for script in required_scripts)
            and (PROJECT_ROOT / "config.json").exists()
            and (PROJECT_ROOT / "requirements.txt").exists(),
            f"{len(required_scripts)} required scripts, config.json, and requirements.txt present",
        )
    )
    checks.append(
        check(
            "Interactive web project showcase and figure performance",
            all(keyword in web_text for keyword in ["Project Overview", "Monitoring Scenarios", "医学监护场景", "项目README", "GitHub仓库"])
            and all(keyword in web_text for keyword in ["可穿戴ECG长时监护", "采样率 × ADC位数", "MIT-BIH与NSTDB", "实验图集"])
            and all(keyword in web_js for keyword in ["preloadFigures", "decode", "figureCache", "selectFigure", "renderScenarios", "renderMonitoring"])
            and all(keyword in web_data for keyword in ["monitoring", "scenarios", "hr_rr_monitoring", "hrv_trend"])
            and all(keyword not in web_text for keyword in ["Course Rubric", "课程评分对照", "PDF报告", "DOCX报告", "5分", "6分", "17/17"]),
            "web/index.html presents monitoring scenarios, not scoring; figure gallery preloads decoded PNG images",
        )
    )

    passed = all(item["passed"] for item in checks)
    audit = {
        "passed": passed,
        "checks_passed": sum(item["passed"] for item in checks),
        "checks_total": len(checks),
        "recommended_configuration": {
            "target_fs_hz": int(recommended["target_fs_hz"]),
            "bits": int(recommended["bits"]),
            "raw_bitrate_bps": int(recommended["raw_bitrate_bps"]),
            "bitrate_reduction_pct": recommended["bitrate_reduction_pct"],
            "clean_pooled_f1_pct": recommended["pooled_f1_pct"],
            "worst_noise_f1_drop_pp_at_snr_ge_6": recommended["worst_noise_f1_drop_pp"],
        },
        "checks": checks,
    }
    AUDIT_JSON.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "# Final Project Completion Audit",
        "",
        f"**Overall status:** {'PASS' if passed else 'FAIL'}  ",
        f"**Checks:** {audit['checks_passed']}/{audit['checks_total']} passed  ",
        f"**Recommended configuration:** {int(recommended['target_fs_hz'])} Hz / {int(recommended['bits'])} bit",
        "",
        "| Requirement | Status | Evidence |",
        "|---|---|---|",
    ]
    lines.extend(
        f"| {item['requirement']} | {'PASS' if item['passed'] else 'FAIL'} | {item['evidence'].replace('|', '/')} |"
        for item in checks
    )
    AUDIT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2, ensure_ascii=False))
    if not passed:
        raise RuntimeError("Final project audit failed")


if __name__ == "__main__":
    main()
