from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import tempfile
import urllib.error
import urllib.request

from constants import APP_UPDATE_TEMP_PREFIX, APP_UPDATER_USER_AGENT
from .models import ReleaseAsset


class DownloadError(RuntimeError):
    pass


def download_asset(
    asset: ReleaseAsset,
    *,
    dest_dir: Path | None = None,
    timeout: float = 1800.0,
    progress_callback: Callable[[int, int | None], None] | None = None,
) -> Path:
    if not asset.download_url.startswith("https://"):
        raise DownloadError("Only HTTPS downloads are allowed.")
    target_dir = dest_dir or Path(tempfile.mkdtemp(prefix=APP_UPDATE_TEMP_PREFIX))
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / Path(asset.name).name
    part = target.with_suffix(target.suffix + ".part")

    request = urllib.request.Request(asset.download_url, headers={"User-Agent": APP_UPDATER_USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_length = response.info().get("Content-Length")
            total_bytes = int(content_length) if content_length is not None else asset.size
            bytes_written = 0
            with part.open("wb") as handle:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    bytes_written += len(chunk)
                    if progress_callback is not None:
                        progress_callback(bytes_written, total_bytes)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        part.unlink(missing_ok=True)
        raise DownloadError(f"Download failed: {exc}") from exc

    part.replace(target)
    return target


def download_text(asset: ReleaseAsset, *, timeout: float = 1800.0) -> str:
    if not asset.download_url.startswith("https://"):
        raise DownloadError("Only HTTPS downloads are allowed.")
    request = urllib.request.Request(asset.download_url, headers={"User-Agent": APP_UPDATER_USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except (OSError, UnicodeDecodeError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise DownloadError(f"Checksum download failed: {exc}") from exc
