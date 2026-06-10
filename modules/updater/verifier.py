from __future__ import annotations

import hashlib
from pathlib import Path


class VerificationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_expected_sha256(checksum_text: str, asset_name: str) -> str | None:
    for raw_line in checksum_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.replace("*", " ").split()
        if len(parts) < 2:
            continue
        digest = parts[0].lower()
        name = parts[-1].strip()
        if name == asset_name and len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest):
            return digest
    return None


def verify_sha256(path: Path, expected: str) -> None:
    actual = sha256_file(path)
    if actual.lower() != expected.lower():
        raise VerificationError("Downloaded installer checksum did not match release checksum.")
