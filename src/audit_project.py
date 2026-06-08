"""Completion audit for the final ECG joint-design submission package."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pandas as pd
from docx import Document
from pypdf import PdfReader

from project_core import FIGURES_DIR, PROJECT_ROOT, REPORT_DIR, RESULTS_DIR


AUDIT_JSON = PROJECT_ROOT / "FINAL_AUDIT.json"
AUDIT_MD = PROJECT_ROOT / "FINAL_AUDIT.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def check(name: str, condition: bool, evidence: str) -> dict:
    return {"requirement": name, "passed": bool(condition), "evidence": evidence}


def main() -> None:
    checks = []
    validation = json.loads((RESULTS_DIR / "data_validation_summary.json").read_text(encoding="utf-8"))
    clean = pd.read_csv(RESULTS_DIR / "per_record_clean.csv")
    noise = pd.read_csv(RESULTS_DIR / "per_record_noise.csv")
    clean_agg = pd.read_csv(RESULTS_DIR / "aggregate_clean.csv")
    noise_agg = pd.read_csv(RESULTS_DIR / "aggregate_noise_by_snr.csv")
    candidates = pd.read_csv(RESULTS_DIR / "candidate_summary.csv")
    recommended = json.loads((RESULTS_DIR / "recommended_config.json").read_text(encoding="utf-8"))

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
    ]]
    checks.append(
        check(
            "Required result figures",
            all(path.exists() and path.stat().st_size > 20_000 for path in expected_figures),
            f"{sum(path.exists() for path in expected_figures)}/8 figures exist",
        )
    )
    pdf_path = REPORT_DIR / "final_report.pdf"
    reader = PdfReader(pdf_path)
    page_text = [(page.extract_text() or "").strip() for page in reader.pages]
    checks.append(
        check(
            "Final PDF report and visual content",
            len(reader.pages) == 9
            and all(len(text) > 20 for text in page_text)
            and all(keyword in "\n".join(page_text) for keyword in ["引言", "系统设计", "方法", "结果展示", "讨论", "结论", "参考文献", "附录"]),
            f"pages={len(reader.pages)}, nonempty_pages={sum(bool(text) for text in page_text)}, sha256={sha256(pdf_path)}",
        )
    )
    docx_path = REPORT_DIR / "final_report.docx"
    doc = Document(docx_path)
    with zipfile.ZipFile(docx_path) as archive:
        images = [name for name in archive.namelist() if name.startswith("word/media/")]
    checks.append(
        check(
            "Editable DOCX report",
            len(doc.paragraphs) >= 70 and len(doc.tables) >= 5 and len(images) >= 8,
            f"paragraphs={len(doc.paragraphs)}, tables={len(doc.tables)}, embedded_images={len(images)}, sha256={sha256(docx_path)}",
        )
    )
    required_scripts = [
        "download_data.py",
        "validate_data.py",
        "run_experiments.py",
        "analyze_results.py",
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
            "Course-guide scoring coverage",
            all(
                keyword in "\n".join(page_text)
                for keyword in ["医学应用背景", "系统设计原理", "方法与实现过程", "结果展示与性能评价", "讨论与改进分析", "参考文献", "复现说明"]
            ),
            "All required course-report sections found in final PDF text",
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
