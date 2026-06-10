from __future__ import annotations

from pathlib import Path

import pytest

from modules.backup_restore import fsops


def _swap_files_for(target: Path) -> list[Path]:
    return list(target.parent.glob(f".{target.name}.*.swap"))


def test_replace_db_with_preserves_target_when_swap_copy_fails(monkeypatch, tmp_path):
    source = tmp_path / "backup.imsdb"
    target = tmp_path / "live.db"
    wal = tmp_path / "live.db-wal"
    shm = tmp_path / "live.db-shm"
    source.write_bytes(b"replacement")
    target.write_bytes(b"current")
    wal.write_bytes(b"wal")
    shm.write_bytes(b"shm")

    def fail_copy(src: Path, dst: Path) -> None:
        assert src == source.resolve()
        assert dst.parent == target.parent.resolve()
        assert target.exists()
        raise OSError("copy failed")

    monkeypatch.setattr(fsops, "_copy_file_fsync", fail_copy)

    with pytest.raises(OSError, match="copy failed"):
        fsops.replace_db_with(str(source), str(target))

    assert target.read_bytes() == b"current"
    assert wal.read_bytes() == b"wal"
    assert shm.read_bytes() == b"shm"
    assert _swap_files_for(target) == []


def test_replace_db_with_rejects_same_file_before_copy_or_unlink(monkeypatch, tmp_path):
    target = tmp_path / "live.db"
    target.write_bytes(b"current")
    copied = False

    def record_copy(src: Path, dst: Path) -> None:
        nonlocal copied
        copied = True

    monkeypatch.setattr(fsops, "_copy_file_fsync", record_copy)

    with pytest.raises(RuntimeError, match="active database"):
        fsops.replace_db_with(str(target), str(target))

    assert copied is False
    assert target.read_bytes() == b"current"
    assert _swap_files_for(target) == []


def test_replace_db_with_stages_swap_before_removing_target_family(tmp_path):
    source = tmp_path / "backup.imsdb"
    target = tmp_path / "live.db"
    wal = tmp_path / "live.db-wal"
    shm = tmp_path / "live.db-shm"
    source.write_bytes(b"replacement")
    target.write_bytes(b"current")
    wal.write_bytes(b"wal")
    shm.write_bytes(b"shm")

    fsops.replace_db_with(str(source), str(target))

    assert target.read_bytes() == b"replacement"
    assert not wal.exists()
    assert not shm.exists()
    assert _swap_files_for(target) == []
