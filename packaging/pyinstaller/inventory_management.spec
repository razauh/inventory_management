# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]


a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT), str(ROOT.parent)],
    binaries=[],
    datas=[
        (str(ROOT / "resources"), "resources"),
    ],
    hiddenimports=[
        "inventory_management.modules.dashboard.controller",
        "inventory_management.modules.product.controller",
        "inventory_management.modules.inventory.controller",
        "inventory_management.modules.purchase.controller",
        "inventory_management.modules.sales.controller",
        "inventory_management.modules.customer.controller",
        "inventory_management.modules.vendor.controller",
        "inventory_management.modules.company_info.controller",
        "inventory_management.modules.expense.controller",
        "inventory_management.modules.reporting.controller",
        "inventory_management.modules.backup_restore",
        "inventory_management.modules.updater",
    ] + collect_submodules("inventory_management.modules.reporting"),
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
