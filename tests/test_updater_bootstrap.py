import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import main


def test_run_updater_bootstrap_launches_installer_with_install_dir(monkeypatch):
    captured = {}

    monkeypatch.setattr(main, "_wait_for_process_exit", lambda parent_pid: captured.update({"parent_pid": parent_pid}))
    monkeypatch.setattr(
        main.subprocess,
        "Popen",
        lambda args, close_fds=True: captured.update({"args": args, "close_fds": close_fds}),
    )

    argv = [
        "InventoryManagement.exe",
        "--updater-bootstrap",
        "--updater-installer",
        r"C:\Temp\InventoryManagement-Setup-v1.2.3.exe",
        "--updater-install-dir",
        r"C:\Program Files\Inventory Management",
        "--updater-parent-pid",
        "4242",
    ]

    assert main._run_updater_bootstrap(argv) is True
    assert captured["parent_pid"] == 4242
    assert captured["args"][0] == r"C:\Temp\InventoryManagement-Setup-v1.2.3.exe"
    assert captured["args"][1] == r"/DIR=C:\Program Files\Inventory Management"
    assert captured["close_fds"] is True
