from __future__ import annotations

import logging
import platform

from version import APP_VERSION

from .github_client import fetch_releases, has_internet
from .logging_utils import get_logger, log_event
from .models import ReleaseAsset, ReleaseInfo, UpdateInfo
from .versioning import is_newer


DEFAULT_OWNER = "razauh"
DEFAULT_REPO = "inventory_management"


class UpdaterService:
    def __init__(
        self,
        *,
        owner: str = DEFAULT_OWNER,
        repo: str = DEFAULT_REPO,
        local_version: str = APP_VERSION,
        logger: logging.Logger | None = None,
    ) -> None:
        self.owner = owner
        self.repo = repo
        self.local_version = local_version
        self._log = logger or get_logger()

    def check_for_update(self, *, include_prerelease: bool = False) -> UpdateInfo | None:
        if not has_internet():
            log_event(self._log, "connectivity", "No internet connection detected.")
            return None

        releases = fetch_releases(self.owner, self.repo)
        for release in releases:
            if release.draft:
                continue
            if release.prerelease and not include_prerelease:
                continue
            if not is_newer(release.tag_name, self.local_version, include_prerelease=include_prerelease):
                continue
            installer = select_installer_asset(release)
            if installer is None:
                log_event(self._log, "asset", "No supported Windows installer asset found.", tag=release.tag_name)
                continue
            checksum = select_checksum_asset(release)
            log_event(self._log, "available", "Update available.", tag=release.tag_name, asset=installer.name)
            return UpdateInfo(
                local_version=self.local_version,
                release=release,
                installer_asset=installer,
                checksum_asset=checksum,
            )
        log_event(self._log, "result", "No update available.")
        return None


def select_installer_asset(release: ReleaseInfo) -> ReleaseAsset | None:
    if platform.system().lower() != "windows":
        return None
    assets = sorted(release.assets, key=lambda asset: asset.name.lower())
    exe_assets = [
        asset for asset in assets
        if asset.name.lower().endswith(".exe") and "setup" in asset.name.lower()
    ]
    if exe_assets:
        return exe_assets[0]
    msi_assets = [asset for asset in assets if asset.name.lower().endswith(".msi")]
    return msi_assets[0] if msi_assets else None


def select_checksum_asset(release: ReleaseInfo) -> ReleaseAsset | None:
    for asset in release.assets:
        name = asset.name.lower()
        if name in {"sha256sums.txt", "checksums.txt"} or name.endswith(".sha256"):
            return asset
    return None
