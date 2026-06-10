from __future__ import annotations

from pathlib import Path
import tempfile
import urllib.error
import urllib.request

from .models import ReleaseAsset


class DownloadError(RuntimeError):
    pass


def download_asset(asset: ReleaseAsset, *, dest_dir: Path | None = None, timeout: float = 30.0) -> Path:
    if not asset.download_url.startswith("https://"):
        raise DownloadError("Only HTTPS downloads are allowed.")
    target_dir = dest_dir or Path(tempfile.mkdtemp(prefix="alhusnain-update-"))
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / asset.name
    part = target.with_suffix(target.suffix + ".part")

    request = urllib.request.Request(asset.download_url, headers={"User-Agent": "Al-Husnain-Updater"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, part.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        part.unlink(missing_ok=True)
        raise DownloadError(f"Download failed: {exc}") from exc

    part.replace(target)
    return target


def download_text(asset: ReleaseAsset, *, timeout: float = 15.0) -> str:
    if not asset.download_url.startswith("https://"):
        raise DownloadError("Only HTTPS downloads are allowed.")
    request = urllib.request.Request(asset.download_url, headers={"User-Agent": "Al-Husnain-Updater"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except (OSError, UnicodeDecodeError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise DownloadError(f"Checksum download failed: {exc}") from exc
