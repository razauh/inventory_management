"""
modules/backup_restore/views.py

Purpose
-------
All PySide6 UI components (dialogs + simple progress window). No business logic here.

Dialogs
-------
1) BackupDialog
   - Inputs: destination folder + file name (default AppName_YYYY-MM-DD_HH-mm.imsdb)
   - Computed labels: estimated DB size (provided/set by controller) and free space
   - Buttons: Create Backup, Cancel
   - Signals: start_backup(dest_path: str), closed()

2) RestoreDialog
   - Inputs: backup file picker (*.imsdb)
   - Computed labels: file size; basic "readable" indicator (not a DB quick_check)
   - Warning text: This will replace the current database. A safety copy is created first.
   - Buttons: Restore, Cancel
   - Signals: start_restore(backup_file: str), closed()

3) ProgressDialog
   - UI: phase label + progress bar + rolling log area
   - Buttons: Close (disabled while running)
   - Slots: on_phase, on_progress, on_log, on_finished
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, Slot, QCoreApplication
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QTextEdit,
    QProgressBar,
    QMessageBox,
    QSizePolicy,
)


# ----------------------------
# Helpers (UI-only, no business)
# ----------------------------

def _app_name_fallback() -> str:
    name = QCoreApplication.applicationName()
    return name if name else "App"

def _default_backup_filename() -> str:
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    return f"{_app_name_fallback()}_{stamp}.imsdb"

def _human_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for u in units:
        if size < 1024.0 or u == units[-1]:
            return f"{size:.1f} {u}"
        size /= 1024.0


# ----------------------------
# Backup Dialog
# ----------------------------

class BackupDialog(QDialog):
    """
    Lets the user choose where to write the *.imsdb file. Shows estimated DB size and free space.
    Emits start_backup(dest_path: str) when confirmed.
    """

    start_backup = Signal(str)
    closed = Signal()

    def __init__(self, parent: Optional[QWidget] = None, estimated_db_size_bytes: Optional[int] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Backup Database")
        self.setModal(True)
        self.setMinimumWidth(520)

        self._estimated_db_size: Optional[int] = estimated_db_size_bytes
        self._chosen_dir = Path.home()
        self._build_ui()
        self._wire_events()
        self._recompute_labels()

    # --- Public API (view-level only) ---

    def set_estimated_db_size(self, num_bytes: Optional[int]) -> None:
        """Controller may call this to set/update the estimated DB size shown to the user."""
        self._estimated_db_size = num_bytes
        self._recompute_labels()

    # --- UI ---

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        intro = QLabel("Create a consistent snapshot of the live SQLite database (.imsdb).")
        intro.setWordWrap(True)
        root.addWidget(intro)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        # Destination folder selector
        self._dir_edit = QLineEdit(str(self._chosen_dir))
        self._browse_btn = QPushButton("Browse…")

        grid.addWidget(QLabel("Destination folder:"), 0, 0)
        grid.addWidget(self._dir_edit, 0, 1)
        grid.addWidget(self._browse_btn, 0, 2)

        # File name
        self._name_edit = QLineEdit(_default_backup_filename())
        grid.addWidget(QLabel("File name:"), 1, 0)
        grid.addWidget(self._name_edit, 1, 1, 1, 2)

        # Info row: estimated size + free space
        self._size_label = QLabel("Estimated DB size: —")
        self._free_label = QLabel("Free space: —")

        grid.addWidget(self._size_label, 2, 0, 1, 2)
        grid.addWidget(self._free_label, 2, 2)

        root.addLayout(grid)

        # Buttons
        btns = QHBoxLayout()
        btns.addStretch(1)
        self._cancel_btn = QPushButton("Cancel")
        self._create_btn = QPushButton("Create Backup")
        self._create_btn.setDefault(True)
        btns.addWidget(self._cancel_btn)
        btns.addWidget(self._create_btn)
        root.addLayout(btns)

    def _wire_events(self) -> None:
        self._browse_btn.clicked.connect(self._choose_dir)
        self._dir_edit.textChanged.connect(self._recompute_labels)
        self._name_edit.textChanged.connect(self._recompute_labels)
        self._cancel_btn.clicked.connect(self.reject)
        self._create_btn.clicked.connect(self._try_emit)

    # --- Validation & updates ---

    def _choose_dir(self) -> None:
        start = str(self._dir_edit.text().strip() or Path.home())
        directory = QFileDialog.getExistingDirectory(self, "Choose Destination Folder", start)
        if directory:
            self._dir_edit.setText(directory)

    def _dest_path(self) -> Path:
        folder = Path(self._dir_edit.text().strip())
        name = self._name_edit.text().strip()
        return folder / name if name else folder / _default_backup_filename()

    def _check_writable_dir(self, p: Path) -> bool:
        try:
            return p.exists() and p.is_dir() and os.access(str(p), os.W_OK | os.X_OK)
        except Exception:
            return False

    def _recompute_labels(self) -> None:
        # Estimated DB size
        if self._estimated_db_size is not None:
            self._size_label.setText(f"Estimated DB size: {_human_size(self._estimated_db_size)}")
        else:
            self._size_label.setText("Estimated DB size: —")

        # Free space (for selected folder or its parent if not exists)
        folder = Path(self._dir_edit.text().strip()) or Path.home()
        probe = folder if folder.exists() else folder.parent
        try:
            usage = shutil.disk_usage(probe)
            self._free_label.setText(f"Free space: {_human_size(usage.free)}")
        except Exception:
            self._free_label.setText("Free space: —")

        # Enable/disable Create
        dest = self._dest_path()
        valid = self._check_writable_dir(dest.parent)
        enough_space = True
        if self._estimated_db_size is not None:
            try:
                usage = shutil.disk_usage(dest.parent if dest.parent.exists() else dest.parent.parent)
                # Require 1.5x the estimated size
                enough_space = usage.free >= int(self._estimated_db_size * 1.5)
            except Exception:
                enough_space = True  # If we cannot determine, don't block here.

        self._create_btn.setEnabled(valid and bool(dest.name.strip()) and enough_space)

    def _try_emit(self) -> None:
        dest = self._dest_path()
        if not self._check_writable_dir(dest.parent):
            QMessageBox.critical(self, "Destination Not Writable",
                                 "Please choose a folder that exists and is writable.")
            return
        # Enforce .imsdb extension
        if not dest.suffix.lower() == ".imsdb":
            dest = dest.with_suffix(".imsdb")
        self.start_backup.emit(str(dest))
        self.accept()

    # --- Dialog lifecycle ---

    def reject(self) -> None:  # Cancel
        super().reject()
        self.closed.emit()

    def accept(self) -> None:  # OK
        super().accept()
        self.closed.emit()


# ----------------------------
# Restore Dialog
# ----------------------------

class RestoreDialog(QDialog):
    """
    Lets the user pick a *.imsdb backup file. Shows file size and simple readability indicator.
    Emits start_restore(backup_file: str) when confirmed.
    """

    start_restore = Signal(str)
    closed = Signal()

    def __init__(self, parent: Optional[Widget] = None) -> None:  # type: ignore[name-defined]
        super().__init__(parent)
        self.setWindowTitle("Restore Database")
        self.setModal(True)
        self.setMinimumWidth(520)

        self._build_ui()
        self._wire_events()
        self._update_info()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        warn = QLabel(
            "This will replace the current database. "
            "A safety copy is created first."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #a15c00;")  # subtle warning tone
        root.addWidget(warn)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        self._file_edit = QLineEdit()
        self._browse_btn = QPushButton("Browse…")

        grid.addWidget(QLabel("Backup file:"), 0, 0)
        grid.addWidget(self._file_edit, 0, 1)
        grid.addWidget(self._browse_btn, 0, 2)

        self._size_label = QLabel("File size: —")
        self._status_label = QLabel("Status: —")
        grid.addWidget(self._size_label, 1, 0, 1, 2)
        grid.addWidget(self._status_label, 1, 2)

        root.addLayout(grid)

        # Buttons
        btns = QHBoxLayout()
        btns.addStretch(1)
        self._cancel_btn = QPushButton("Cancel")
        self._restore_btn = QPushButton("Restore")
        self._restore_btn.setDefault(True)
        btns.addWidget(self._cancel_btn)
        btns.addWidget(self._restore_btn)
        root.addLayout(btns)

    def _wire_events(self) -> None:
        self._browse_btn.clicked.connect(self._choose_file)
        self._file_edit.textChanged.connect(self._update_info)
        self._cancel_btn.clicked.connect(self.reject)
        self._restore_btn.clicked.connect(self._try_emit)

    def _choose_file(self) -> None:
        start = self._file_edit.text().strip() or str(Path.home())
        fname, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Backup File",
            start,
            "Backup files (*.imsdb);;All files (*.*)",
        )
        if fname:
            self._file_edit.setText(fname)

    def _update_info(self) -> None:
        path = Path(self._file_edit.text().strip())
        ok = path.exists() and path.is_file() and path.suffix.lower() == ".imsdb"
        self._restore_btn.setEnabled(ok)

        if ok:
            try:
                size = path.stat().st_size
                self._size_label.setText(f"File size: {_human_size(size)}")
                # Simple readability indicator (UI-only; real quick_check is done in service):
                readable = os.access(str(path), os.R_OK)
                self._status_label.setText("Status: Ready" if readable else "Status: Not readable")
            except Exception:
                self._size_label.setText("File size: —")
                self._status_label.setText("Status: —")
        else:
            self._size_label.setText("File size: —")
            self._status_label.setText("Status: —")

    def _try_emit(self) -> None:
        path = Path(self._file_edit.text().strip())
        if not (path.exists() and path.is_file() and path.suffix.lower() == ".imsdb"):
            QMessageBox.critical(self, "Invalid File", "Please choose a valid *.imsdb file.")
            return
        if not os.access(str(path), os.R_OK):
            QMessageBox.critical(self, "Unreadable File", "The selected file is not readable.")
            return
        self.start_restore.emit(str(path))
        self.accept()

    # Dialog lifecycle
    def reject(self) -> None:
        super().reject()
        self.closed.emit()

    def accept(self) -> None:
        super().accept()
        self.closed.emit()


# ----------------------------
# Progress Dialog
# ----------------------------

class ProgressDialog(QDialog):
    """
    Lightweight progress UI used by the controller during backup/restore jobs.
    Exposes slots to update text/progress/log and to finish the dialog state.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Working…")
        self.setModal(True)
        self.setMinimumWidth(560)

        self._build_ui()
        self._set_running(True)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        self._phase_label = QLabel("Starting…")
        self._phase_label.setWordWrap(True)
        root.addWidget(self._phase_label)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)  # indeterminate initially
        root.addWidget(self._bar)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(160)
        self._log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self._log)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self._close_btn = QPushButton("Close")
        btns.addWidget(self._close_btn)
        root.addLayout(btns)

        self._close_btn.clicked.connect(self.close)

    def _set_running(self, running: bool) -> None:
        self._close_btn.setEnabled(not running)

    # ---- Slots used by controller/service ----

    @Slot(str)
    def on_phase(self, text: str) -> None:
        self._phase_label.setText(text)

    @Slot(int)
    def on_progress(self, pct: int) -> None:
        if pct < 0:
            self._bar.setRange(0, 0)  # indeterminate
        else:
            if self._bar.minimum() == 0 and self._bar.maximum() == 0:
                self._bar.setRange(0, 100)
            self._bar.setValue(max(0, min(100, pct)))

    @Slot(str)
    def on_log(self, line: str) -> None:
        self._log.append(line.rstrip())

    @Slot(bool, str, object)
    def on_finished(self, success: bool, message: str, path: Optional[str]) -> None:
        self._set_running(False)
        self.on_log("")
        self.on_log("—" * 40)
        self.on_log("Completed successfully." if success else "Failed.")
        if message:
            self.on_log(message)
        if path:
            self.on_log(f"Path: {path}")
        if success:
            self.on_phase("Done")
            self.on_progress(100)
        else:
            self.on_phase("Finished with errors")
