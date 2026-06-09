#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path


LOCK_LINE_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s]+)\s+--hash=sha256:(?P<sha256>[a-fA-F0-9]{64})$"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_required_hashes(lock_file: Path) -> list[tuple[str, str, str]]:
    required = []
    for line in lock_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = LOCK_LINE_RE.match(line)
        if not match:
            raise SystemExit(f"Unrecognized lock entry: {line}")
        required.append((match.group("name"), match.group("version"), match.group("sha256").lower()))
    return required


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock-file", default="requirements.lock.txt")
    parser.add_argument("--wheelhouse", default=".wheelhouse-app")
    args = parser.parse_args()

    lock_file = Path(args.lock_file).resolve()
    wheelhouse = Path(args.wheelhouse).resolve()

    if not lock_file.is_file():
        raise SystemExit(f"Missing lock file: {lock_file}")
    if not wheelhouse.is_dir():
        raise SystemExit(f"Missing wheelhouse directory: {wheelhouse}")

    wheel_hashes: dict[str, Path] = {}
    for wheel in wheelhouse.glob("*.whl"):
        wheel_hashes[sha256_file(wheel)] = wheel

    if not wheel_hashes:
        raise SystemExit(f"No wheel files found in {wheelhouse}")

    missing = []
    expected_hashes = set()
    for name, version, expected_hash in load_required_hashes(lock_file):
        expected_hashes.add(expected_hash)
        if expected_hash not in wheel_hashes:
            missing.append(f"{name}=={version} (sha256:{expected_hash})")

    if missing:
        raise SystemExit(
            "Wheelhouse verification failed; missing locked artifacts:\n  - "
            + "\n  - ".join(missing)
        )

    unexpected = []
    for actual_hash, wheel in sorted(wheel_hashes.items(), key=lambda item: item[1].name):
        if actual_hash not in expected_hashes:
            unexpected.append(wheel.name)

    if unexpected:
        raise SystemExit(
            "Wheelhouse verification failed; unexpected wheels present:\n  - "
            + "\n  - ".join(unexpected)
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
