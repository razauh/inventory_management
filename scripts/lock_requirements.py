#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def build_lock(manifest: Path, wheelhouse: Path, output: Path) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        report_path = Path(tmpdir) / "pip-report.json"
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--ignore-installed",
            "--no-index",
            f"--find-links={wheelhouse}",
            "--only-binary=:all:",
            "--report",
            str(report_path),
            "-r",
            str(manifest),
        ]
        proc = subprocess.run(cmd, text=True, capture_output=True)
        if proc.returncode != 0:
            raise SystemExit(proc.stderr.strip() or proc.stdout.strip() or "pip lock generation failed")

        report = json.loads(report_path.read_text(encoding="utf-8"))
        entries = []
        for item in report.get("install", []):
            metadata = item.get("metadata") or {}
            name = metadata.get("name")
            version = metadata.get("version")
            download_info = item.get("download_info") or {}
            archive_info = download_info.get("archive_info") or {}
            hashes = archive_info.get("hashes") or {}
            sha256 = hashes.get("sha256")
            if not (name and version and sha256):
                raise SystemExit(f"Unable to lock package from pip report: {item!r}")
            entries.append(f"{name}=={version} --hash=sha256:{sha256}")

        if not entries:
            raise SystemExit("No packages were resolved from the wheelhouse.")

        output.write_text(
            "# Generated from requirements.in and .wheelhouse by scripts/lock_requirements.py\n"
            "# Do not edit by hand.\n"
            + "\n".join(entries)
            + "\n",
            encoding="utf-8",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="requirements.in")
    parser.add_argument("--wheelhouse", default=".wheelhouse-app")
    parser.add_argument("--output", default="requirements.lock.txt")
    args = parser.parse_args()

    manifest = Path(args.manifest).resolve()
    wheelhouse = Path(args.wheelhouse).resolve()
    output = Path(args.output).resolve()

    if not manifest.is_file():
        raise SystemExit(f"Missing manifest: {manifest}")
    if not wheelhouse.is_dir():
        raise SystemExit(f"Missing wheelhouse directory: {wheelhouse}")

    build_lock(manifest, wheelhouse, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
