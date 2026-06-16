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
    installer_asset: ReleaseAsset | None
    checksum_asset: ReleaseAsset | None
    availability_message: str = ""

    @property
    def can_download(self) -> bool:
        return self.installer_asset is not None and self.checksum_asset is not None


@dataclass(frozen=True)
class UpdateState:
    status: str
    status_label: str
    detail: str
    local_version: str
    progress: int = 0
    update: UpdateInfo | None = None
    error_text: str = ""
    download_path: str = ""
    install_after_download: bool = False
