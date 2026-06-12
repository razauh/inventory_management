from __future__ import annotations

import re
from dataclasses import dataclass


_VERSION_RE = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?$"
)


@dataclass(frozen=True, order=True)
class ParsedVersion:
    major: int
    minor: int
    patch: int
    prerelease: str = ""

    @property
    def normalized(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return f"{base}-{self.prerelease}" if self.prerelease else base


def parse_version(raw: str) -> ParsedVersion | None:
    match = _VERSION_RE.match((raw or "").strip())
    if not match:
        return None
    return ParsedVersion(
        major=int(match.group("major")),
        minor=int(match.group("minor")),
        patch=int(match.group("patch")),
        prerelease=match.group("pre") or "",
    )


def _prerelease_key(prerelease: str) -> tuple:
    key = []
    for part in (prerelease or "").split("."):
        for chunk in re.findall(r"\d+|\D+", part):
            if chunk.isdigit():
                key.append((0, int(chunk)))
            else:
                key.append((1, chunk))
    return tuple(key)


def is_newer(remote: str, local: str, *, include_prerelease: bool = False) -> bool:
    remote_version = parse_version(remote)
    local_version = parse_version(local)
    if remote_version is None or local_version is None:
        return False
    if remote_version.prerelease and not include_prerelease:
        return False
    remote_key = (remote_version.major, remote_version.minor, remote_version.patch)
    local_key = (local_version.major, local_version.minor, local_version.patch)
    if remote_key != local_key:
        return remote_key > local_key
    if not local_version.prerelease:
        return False
    if not remote_version.prerelease:
        return True
    return _prerelease_key(remote_version.prerelease) > _prerelease_key(local_version.prerelease)
