# Updater and Windows Packaging Plan

## Current findings

Graphify was run through `./.conda/bin/graphify` before this plan was written. Code inspection confirmed the application is a Python/PySide6 desktop app started by `main.py`. `MainWindow` lazy-loads modules into a left navigation list and `QStackedWidget`.

The existing backup/recovery module is `modules/backup_restore`. It exposes `create_module()`, `BackupRestoreController`, menu actions for `File -> Backup Database...` and `File -> Restore Database...`, and a service layer with `BackupJob` and `RestoreJob`. Backups are `.imsdb` SQLite snapshots created with the SQLite backup API, validated with `quick_check`, and saved atomically. Restore creates a safety copy first and swaps database files through the app DB manager.

The current live database path is configured in `config.py` as `data/myshop.db` under the project root. For packaged Windows builds, this must move to a per-user data folder so app upgrades never overwrite user data. The database schema version is `SCHEMA_VERSION` in `constants.py`; this is not an app version and must stay separate.

No packaging files, GitHub Actions release workflow, or app version file currently exist. The Git remote points to `razauh/inventory_management`, so GitHub Releases for that repository are the planned update source.

## Updater architecture

Add `modules/updater` with a thin PySide6 controller and standard-library network code. The updater uses GitHub Releases, not a hosted updater service.

Public API:

- `UpdaterController.check_now(manual=True)` checks for updates and shows user feedback.
- `UpdaterController.check_on_startup()` schedules a short delayed startup check.
- `UpdaterService.check_for_update()` returns `UpdateInfo | None`.

Flow:

1. Detect connectivity with a short TCP connection to `api.github.com:443`.
2. Fetch `https://api.github.com/repos/razauh/inventory_management/releases`.
3. Ignore drafts, invalid SemVer tags, same versions, older versions, and prereleases by default.
4. Compare local `version.APP_VERSION` against release tags named `vMAJOR.MINOR.PATCH`.
5. Select a Windows installer asset, preferring `*Setup*.exe`, then `.msi`.
6. Require a checksum asset named `SHA256SUMS.txt`, `checksums.txt`, or `*.sha256`.
7. Show an update dialog with release notes, current version, target version, and backup warning.
8. Download installer to a temp folder only after user confirms.
9. Verify SHA-256 before launching anything.
10. Launch installer and close the app.

Offline and failure behavior:

- Startup checks fail silently and log the reason.
- Manual checks show a clear warning.
- GitHub timeout or bad JSON never crashes the app.
- Downloads require HTTPS.
- Missing checksum blocks installation.

## Backup-before-update behavior

The update dialog always warns the user to create a backup before installing. The install button stays disabled until the user acknowledges the warning.

The first implementation reuses the existing Backup & Restore screen. If `BackupRestoreController.create_backup_for_update()` is available, the updater can call it before download/install. If the wrapper is unavailable or fails, the updater opens the existing backup dialog and requires the user to decide whether to continue.

Required behavior:

- Show backup warning before any installer launch.
- Pause update install until warning is acknowledged.
- Offer `Create Backup Now`.
- Use existing `.imsdb` backup creation where supported.
- Confirm backup success from the backup API result or `backup_completed` signal.
- If backup fails, block install by default.
- Allow `Continue Without Backup` only after a second warning.
- Log backup and update failures separately.
- Keep database and config in per-user data folders, not in the install directory.

## Windows packaging

Recommended first build:

- PyInstaller builds the app executable.
- Inno Setup builds the `.exe` installer.
- MSI is deferred unless an enterprise deployment need appears.

Why:

- The app is a local PySide6 desktop app.
- PyInstaller supports PySide6 and bundled resources well.
- Inno Setup gives simple shortcuts, upgrade behavior, uninstall behavior, and GitHub Release assets.
- MSI/WiX adds more complexity and is not needed for the first updater path.

Installer behavior:

- Install to `%LOCALAPPDATA%\Programs\Al Husnain` by default.
- Store DB/config/logs under `%LOCALAPPDATA%\Al Husnain`.
- Create Start Menu and optional desktop shortcuts.
- Do not remove user data on uninstall by default.
- Use stable `AppId` in Inno Setup so upgrades replace app files.
- Code signing is recommended before public release.

## GitHub release workflow

Release process:

1. Update `version.APP_VERSION`.
2. Commit changes.
3. Tag release as `vMAJOR.MINOR.PATCH`.
4. GitHub Actions builds on `windows-latest`.
5. PyInstaller creates the app folder or single executable.
6. Inno Setup creates `AlHusnain-Setup-vMAJOR.MINOR.PATCH.exe`.
7. Workflow writes `SHA256SUMS.txt`.
8. Assets are uploaded to the GitHub Release.
9. Installed apps detect the release through GitHub Releases.
10. User is warned to create a backup.
11. Installer is downloaded, verified, and launched.

## Versioning strategy

- Store app version in `version.py`.
- Keep database schema version in `constants.py`.
- Tag releases as `v1.2.3`.
- Use SemVer ordering.
- Reject invalid tags.
- Prevent downgrades.
- Ignore prereleases unless `updater/include_prerelease` is enabled in `QSettings`.

## Files created or changed

- `version.py`
- `modules/updater/`
- `main.py`
- `config.py`
- `modules/backup_restore/controller.py`
- `packaging/pyinstaller/al_husnain.spec`
- `packaging/inno/al_husnain.iss`
- `.github/workflows/windows-release.yml`
- `docs/updater_and_windows_packaging_plan.md`

## Test cases

- Version comparison accepts newer stable tags.
- Version comparison rejects invalid, same, older, and prerelease tags by default.
- GitHub release parsing ignores drafts and bad assets.
- Windows asset selection prefers setup `.exe`.
- Missing checksum blocks install.
- Bad checksum blocks install.
- Offline startup check logs and does not crash.
- Manual offline check shows a message.
- Backup warning disables install until acknowledged.
- Backup screen opens from update dialog.
- Installer launches only after warning and checksum verification.
- Packaged app preserves `%LOCALAPPDATA%\Al Husnain\myshop.db` across upgrade.
