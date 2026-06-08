"""Download the official PhysioNet records required by the final project."""

from __future__ import annotations

import csv
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from project_core import (
    DATA_DIR,
    MITDB_BASE_URL,
    NSTDB_BASE_URL,
    ensure_project_dirs,
    sha256_file,
)


def read_remote_lines(url: str) -> list[str]:
    with urllib.request.urlopen(url, timeout=60) as response:
        return [
            line.strip()
            for line in response.read().decode("utf-8").splitlines()
            if line.strip()
        ]


def download_file(url: str, path: Path, retries: int = 6) -> tuple[str, Path, bool]:
    if path.exists() and path.stat().st_size > 0:
        return url, path, False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            if temporary.exists():
                temporary.unlink()
            request = urllib.request.Request(url, headers={"User-Agent": "ecg-joint-design/1.0"})
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as handle:
                while chunk := response.read(1024 * 1024):
                    handle.write(chunk)
            temporary.replace(path)
            return url, path, True
        except Exception:
            if attempt == retries:
                raise
            time.sleep(min(2**attempt, 30))
    raise RuntimeError(f"Unreachable retry state for {url}")


def dataset_jobs(base_url: str, destination: Path, records: list[str]) -> list[tuple[str, Path]]:
    jobs: list[tuple[str, Path]] = []
    for record in records:
        for extension in ("hea", "dat", "atr"):
            jobs.append((f"{base_url}/{record}.{extension}", destination / f"{record}.{extension}"))
    jobs.append((f"{base_url}/RECORDS", destination / "RECORDS"))
    return jobs


def main() -> None:
    ensure_project_dirs()
    mit_records = read_remote_lines(f"{MITDB_BASE_URL}/RECORDS")
    nst_records = [
        record
        for record in read_remote_lines(f"{NSTDB_BASE_URL}/RECORDS")
        if record.startswith(("118e", "119e"))
    ]
    jobs = dataset_jobs(MITDB_BASE_URL, DATA_DIR / "mitdb", mit_records)
    jobs += dataset_jobs(NSTDB_BASE_URL, DATA_DIR / "nstdb", nst_records)

    print(f"Downloading/verifying {len(jobs)} files...")
    failures: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(download_file, url, path) for url, path in jobs]
        for index, future in enumerate(as_completed(futures), 1):
            try:
                url, path, downloaded = future.result()
                action = "downloaded" if downloaded else "present"
                print(f"[{index:3d}/{len(jobs)}] {action}: {path.name}")
            except Exception as exc:
                failures.append((str(futures[index - 1]) if index - 1 < len(futures) else "unknown", str(exc)))
                print(f"[{index:3d}/{len(jobs)}] FAILED: {exc}")
    if failures:
        raise RuntimeError(f"{len(failures)} downloads failed after retries; rerun the script")

    manifest_path = DATA_DIR / "data_manifest.csv"
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("dataset", "file", "size_bytes", "sha256", "official_url"),
        )
        writer.writeheader()
        for base_url, folder in (
            (MITDB_BASE_URL, DATA_DIR / "mitdb"),
            (NSTDB_BASE_URL, DATA_DIR / "nstdb"),
        ):
            for path in sorted(folder.iterdir()):
                if path.is_file():
                    writer.writerow(
                        {
                            "dataset": folder.name,
                            "file": path.name,
                            "size_bytes": path.stat().st_size,
                            "sha256": sha256_file(path),
                            "official_url": f"{base_url}/{path.name}",
                        }
                    )
    print(f"Manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
