from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from collections.abc import Iterable

from .models import ReleaseAsset, ReleaseInfo
from .versioning import parse_version


GITHUB_API_ROOT = "https://api.github.com"


class UpdateCheckError(RuntimeError):
    pass


def has_internet(timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection(("api.github.com", 443), timeout=timeout):
            return True
    except OSError:
        return False


def fetch_releases(owner: str, repo: str, *, timeout: float = 8.0) -> tuple[ReleaseInfo, ...]:
    url = f"{GITHUB_API_ROOT}/repos/{owner}/{repo}/releases"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Al-Husnain-Updater",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise UpdateCheckError("GitHub API rate limit exceeded. Please try again later.") from exc
        raise UpdateCheckError(f"Unable to fetch GitHub releases: {exc}") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise UpdateCheckError(f"Unable to fetch GitHub releases: {exc}") from exc

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise UpdateCheckError("GitHub release response was not valid JSON.") from exc

    if not isinstance(data, list):
        raise UpdateCheckError("GitHub release response had an unexpected shape.")

    releases: list[ReleaseInfo] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        tag_name = str(item.get("tag_name") or "").strip()
        parsed = parse_version(tag_name)
        if parsed is None:
            continue
        assets = tuple(_assets_from_json(item.get("assets") or []))
        releases.append(
            ReleaseInfo(
                tag_name=tag_name,
                version=parsed.normalized,
                title=str(item.get("name") or tag_name),
                body=str(item.get("body") or ""),
                html_url=str(item.get("html_url") or ""),
                prerelease=bool(item.get("prerelease")),
                draft=bool(item.get("draft")),
                assets=assets,
            )
        )
    return tuple(releases)


def _assets_from_json(items: Iterable[object]) -> Iterable[ReleaseAsset]:
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("browser_download_url") or "").strip()
        if not name or not url.startswith("https://"):
            continue
        size_raw = item.get("size")
        yield ReleaseAsset(
            name=name,
            download_url=url,
            size=int(size_raw) if isinstance(size_raw, int) else None,
        )
