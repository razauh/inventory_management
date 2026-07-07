# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]
for path in (ROOT.parent, ROOT):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)


def _not_tests(module_name):
    return ".test_" not in module_name and not module_name.rsplit(".", 1)[-1].startswith("test_")


a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT), str(ROOT.parent)],
    binaries=[],
    datas=[
        (str(ROOT / "resources"), "resources"),
        (str(ROOT / "modules" / "accounting" / "docs"), "modules/accounting/docs"),
        (
            str(ROOT / "modules" / "accounting" / "docs"),
            "inventory_management/modules/accounting/docs",
        ),
    ],
    hiddenimports=collect_submodules("inventory_management.modules", filter=_not_tests)
    + collect_submodules("modules", filter=_not_tests)
    + collect_submodules("inventory_management.database", filter=_not_tests)
    + collect_submodules("database", filter=_not_tests)
    + collect_submodules("inventory_management.utils", filter=_not_tests)
    + collect_submodules("utils", filter=_not_tests)
    + collect_submodules("inventory_management.widgets", filter=_not_tests)
    + collect_submodules("widgets", filter=_not_tests),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="InventoryManagement",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="InventoryManagement",
)
