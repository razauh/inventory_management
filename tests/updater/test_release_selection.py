from inventory_management.modules.updater.models import ReleaseAsset, ReleaseInfo
from inventory_management.modules.updater.service import select_checksum_asset, select_installer_asset


def _release(*assets: ReleaseAsset) -> ReleaseInfo:
    return ReleaseInfo(
        tag_name="v1.2.3",
        version="1.2.3",
        title="v1.2.3",
        body="",
        html_url="https://github.com/example/repo/releases/tag/v1.2.3",
        prerelease=False,
        draft=False,
        assets=assets,
    )


def test_select_installer_prefers_setup_exe_on_windows(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Windows")
    release = _release(
        ReleaseAsset("AlHusnain.msi", "https://example.com/AlHusnain.msi"),
        ReleaseAsset("AlHusnain-Setup-v1.2.3.exe", "https://example.com/AlHusnain-Setup-v1.2.3.exe"),
    )

    selected = select_installer_asset(release)

    assert selected is not None
    assert selected.name == "AlHusnain-Setup-v1.2.3.exe"


def test_select_installer_rejects_non_windows(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    release = _release(ReleaseAsset("AlHusnain-Setup-v1.2.3.exe", "https://example.com/app.exe"))

    assert select_installer_asset(release) is None


def test_select_checksum_asset_finds_sha256sums():
    release = _release(
        ReleaseAsset("AlHusnain-Setup-v1.2.3.exe", "https://example.com/app.exe"),
        ReleaseAsset("SHA256SUMS.txt", "https://example.com/SHA256SUMS.txt"),
    )

    selected = select_checksum_asset(release)

    assert selected is not None
    assert selected.name == "SHA256SUMS.txt"
