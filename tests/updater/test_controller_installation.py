import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT.parent))

from inventory_management.modules.updater.controller import UpdaterController
from inventory_management.modules.updater.models import ReleaseAsset, ReleaseInfo, UpdateInfo
from version import APP_VERSION


class _FakeConn:
    def __init__(self) -> None:
        self.committed = False
        self.closed = False

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


class _FakeSettings:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    def value(self, key, default=None, type=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def remove(self, key):
        self.values.pop(key, None)

    def sync(self):
        pass


class _FakeWindow:
    def __init__(self) -> None:
        self.conn = _FakeConn()


def _update(tag: str) -> UpdateInfo:
    release = ReleaseInfo(
        tag_name=tag,
        version=tag.lstrip("v"),
        title=tag,
        body="",
        html_url=f"https://example.com/{tag}",
        prerelease=False,
        draft=False,
        assets=(
            ReleaseAsset(f"InventoryManagement-Setup-{tag}.exe", f"https://example.com/{tag}.exe"),
            ReleaseAsset("SHA256SUMS.txt", "https://example.com/SHA256SUMS.txt"),
        ),
    )
    return UpdateInfo(
        local_version="1.2.3",
        release=release,
        installer_asset=release.assets[0],
        checksum_asset=release.assets[1],
    )


def test_controller_discards_stale_cached_installer_when_release_changes(tmp_path):
    controller = UpdaterController(_FakeWindow(), service=SimpleNamespace(local_version="1.2.3"))
    old_update = _update("v1.2.2")
    new_update = _update("v1.2.3")
    installer_dir = tmp_path / "cached"
    installer_dir.mkdir()
    installer = installer_dir / old_update.installer_asset.name
    installer.write_text("old")
    controller._downloaded_installer = installer
    controller._download_cache_key = f"{old_update.release.tag_name}|{old_update.installer_asset.name}"

    controller._on_check_finished(new_update, manual=True, error="")

    assert controller._downloaded_installer is None
    assert controller._download_cache_key is None
    assert not installer_dir.exists()


def test_install_downloaded_update_uses_bootstrap_launch_args(monkeypatch, tmp_path):
    controller = UpdaterController(_FakeWindow(), service=SimpleNamespace(local_version="1.2.3"))
    update = _update("v1.2.4")
    installer = tmp_path / update.installer_asset.name
    installer.write_text("installer")
    controller._current_update = update
    controller._downloaded_installer = installer
    controller._download_cache_key = f"{update.release.tag_name}|{update.installer_asset.name}"
    controller._settings = _FakeSettings()

    captured = {}

    monkeypatch.setattr(
        "inventory_management.modules.updater.controller._current_application_executable",
        lambda: Path("/opt/inventory/InventoryManagement.exe"),
    )
    monkeypatch.setattr(
        "inventory_management.modules.updater.controller.subprocess.Popen",
        lambda args, close_fds=True: captured.update({"args": args, "close_fds": close_fds}),
    )
    monkeypatch.setattr(
        "inventory_management.modules.updater.controller.QApplication.quit",
        lambda: captured.update({"quit": True}),
    )

    controller.install_downloaded_update()

    assert captured["args"][0] == "/opt/inventory/InventoryManagement.exe"
    assert "--updater-bootstrap" in captured["args"]
    assert captured["args"][captured["args"].index("--updater-installer") + 1] == str(installer)
    assert captured["args"][captured["args"].index("--updater-install-dir") + 1] == "/opt/inventory"
    assert captured["args"][captured["args"].index("--updater-parent-pid") + 1] == str(os.getpid())
    assert captured["close_fds"] is True
    assert captured["quit"] is True


def test_verify_pending_installation_clears_matching_version_and_keeps_mismatch():
    controller = UpdaterController(_FakeWindow(), service=SimpleNamespace(local_version="1.2.3"))
    controller._settings = _FakeSettings(
        {
            controller.SETTINGS_KEY_PENDING_EXPECTED_VERSION: APP_VERSION,
        }
    )

    assert controller.verify_pending_installation() is True
    assert controller._settings.value(controller.SETTINGS_KEY_PENDING_EXPECTED_VERSION, "") == ""

    controller._settings = _FakeSettings(
        {
            controller.SETTINGS_KEY_PENDING_EXPECTED_VERSION: "9.9.9",
        }
    )

    assert controller.verify_pending_installation() is False
    assert controller._settings.value(controller.SETTINGS_KEY_PENDING_EXPECTED_VERSION, "") == "9.9.9"
