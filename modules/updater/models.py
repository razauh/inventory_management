from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int | None = None


@dataclass(frozen=True)
class ReleaseInfo:
    tag_name: str
    version: str
    title: str
    body: str
    html_url: str
    prerelease: bool
    draft: bool
    assets: tuple[ReleaseAsset, ...]


@dataclass(frozen=True)
class UpdateInfo:
    local_version: str
    release: ReleaseInfo
    installer_asset: ReleaseAsset
    checksum_asset: ReleaseAsset | None
