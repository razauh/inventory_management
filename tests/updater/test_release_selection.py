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
        ReleaseAsset("InventoryManagement.msi", "https://example.com/InventoryManagement.msi"),
        ReleaseAsset("InventoryManagement-Setup-v1.2.3.exe", "https://example.com/InventoryManagement-Setup-v1.2.3.exe"),
    )

    selected = select_installer_asset(release)

    assert selected is not None
    assert selected.name == "InventoryManagement-Setup-v1.2.3.exe"


def test_select_installer_prefers_exact_release_name_when_multiple_setups_exist(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Windows")
    release = _release(
        ReleaseAsset("InventoryManagement-Setup-v1.2.2.exe", "https://example.com/InventoryManagement-Setup-v1.2.2.exe"),
        ReleaseAsset("InventoryManagement-Setup.exe", "https://example.com/InventoryManagement-Setup.exe"),
        ReleaseAsset("InventoryManagement-Setup-v1.2.3.exe", "https://example.com/InventoryManagement-Setup-v1.2.3.exe"),
        ReleaseAsset("InventoryManagement.msi", "https://example.com/InventoryManagement.msi"),
    )

    selected = select_installer_asset(release)

    assert selected is not None
    assert selected.name == "InventoryManagement-Setup-v1.2.3.exe"


def test_select_installer_rejects_non_windows(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    release = _release(ReleaseAsset("InventoryManagement-Setup-v1.2.3.exe", "https://example.com/app.exe"))

    assert select_installer_asset(release) is None


def test_select_checksum_asset_finds_sha256sums():
    release = _release(
        ReleaseAsset("InventoryManagement-Setup-v1.2.3.exe", "https://example.com/app.exe"),
        ReleaseAsset("SHA256SUMS.txt", "https://example.com/SHA256SUMS.txt"),
    )

    selected = select_checksum_asset(release)

    assert selected is not None
    assert selected.name == "SHA256SUMS.txt"


def test_check_for_update_skips_release_without_checksum(monkeypatch):
    from inventory_management.modules.updater.service import UpdaterService
    
    release = ReleaseInfo(
        tag_name="v1.2.4",
        version="1.2.4",
        title="v1.2.4",
        body="",
        html_url="https://github.com/example/repo/releases/tag/v1.2.4",
        prerelease=False,
        draft=False,
        assets=[
            ReleaseAsset("InventoryManagement-Setup-v1.2.4.exe", "https://example.com/InventoryManagement-Setup-v1.2.4.exe"),
            # No checksum asset here!
        ],
    )
    
    monkeypatch.setattr("inventory_management.modules.updater.service.has_internet", lambda: True)
    monkeypatch.setattr("inventory_management.modules.updater.service.fetch_releases", lambda owner, repo: [release])
    
    service = UpdaterService(local_version="1.2.3")
    update_info = service.check_for_update()
    
    assert update_info is None
