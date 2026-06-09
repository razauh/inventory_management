#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.metadata as md
from pathlib import Path


def load_pinned_versions(requirements_in: Path) -> dict[str, str]:
    pinned = {}
    for line in requirements_in.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            continue
        name, version = line.split("==", 1)
        pinned[name.strip()] = version.strip()
    return pinned


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", default="requirements.in")
    args = parser.parse_args()

    requirements = Path(args.requirements).resolve()
    if not requirements.is_file():
        raise SystemExit(f"Missing requirements file: {requirements}")

    mismatches = []
    for name, expected in load_pinned_versions(requirements).items():
        try:
            actual = md.version(name)
        except md.PackageNotFoundError:
            mismatches.append(f"{name}: missing (expected {expected})")
            continue
        if actual != expected:
            mismatches.append(f"{name}: {actual} != {expected}")

    if mismatches:
        raise SystemExit("Environment verification failed:\n  - " + "\n  - ".join(mismatches))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
