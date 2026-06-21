from __future__ import annotations

from pathlib import Path
import shutil

from PySide6.QtCore import QRectF, QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPainter
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class InvoicePreviewDialog(QDialog):
    def __init__(self, pdf_path: str | Path, *, title: str, parent=None):
        super().__init__(parent)
        self.pdf_path = Path(pdf_path)
        self.setWindowTitle(title)
        self.resize(900, 700)

        layout = QVBoxLayout(self)

        self.document = QPdfDocument(self)
        error = self.document.load(str(self.pdf_path))
        if error == QPdfDocument.Error.None_:
            self.preview = QPdfView(self)
            self.preview.setDocument(self.document)
            self.preview.setPageMode(QPdfView.PageMode.MultiPage)
            self.preview.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            layout.addWidget(self.preview, 1)
        else:
            label = QLabel(f"Preview unavailable.\nPDF saved at:\n{self.pdf_path}", self)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)

        self.btn_print = QPushButton("Print", self)
        self.btn_save = QPushButton("Save PDF", self)
        self.btn_open = QPushButton("Open PDF", self)
        self.btn_close = QPushButton("Close", self)

        self.btn_print.clicked.connect(self._print_pdf)
        self.btn_save.clicked.connect(self._save_pdf)
        self.btn_open.clicked.connect(self._open_pdf)
        self.btn_close.clicked.connect(self.accept)

        actions.addWidget(self.btn_print)
        actions.addWidget(self.btn_save)
        actions.addWidget(self.btn_open)
        actions.addWidget(self.btn_close)
        layout.addLayout(actions)

    def _save_pdf(self) -> None:
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save Invoice PDF",
            self.pdf_path.name,
            "PDF Files (*.pdf)",
        )
        if not target:
            return
        if not target.lower().endswith(".pdf"):
            target += ".pdf"
        try:
            shutil.copyfile(self.pdf_path, target)
        except OSError as exc:
            QMessageBox.warning(self, "Save PDF", f"Could not save PDF:\n{exc}")

    def _open_pdf(self) -> None:
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.pdf_path))):
            QMessageBox.information(self, "Open PDF", f"PDF saved at:\n{self.pdf_path}")

    def _print_pdf(self) -> None:
        page_count = self.document.pageCount()
        if page_count <= 0:
            QMessageBox.warning(self, "Print", "PDF preview is not ready.")
            return

        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(self.windowTitle())
        printer.setFromTo(1, page_count)

        dialog = QPrintDialog(printer, self)
        dialog.setFromTo(1, page_count)
        if dialog.exec() != QDialog.Accepted:
            return

        first_page = max(1, printer.fromPage() or 1)
        last_page = printer.toPage() or page_count
        first_page = min(first_page, page_count)
        last_page = min(max(first_page, last_page), page_count)

        painter = QPainter(printer)
        if not painter.isActive():
            QMessageBox.warning(self, "Print", "Could not start printer.")
            return
        try:
            for page in range(first_page - 1, last_page):
                if page > first_page - 1:
                    printer.newPage()
                self._paint_page(painter, printer, page)
        finally:
            painter.end()

    def _paint_page(self, painter: QPainter, printer: QPrinter, page: int) -> None:
        page_points = self.document.pagePointSize(page)
        dpi = max(72, printer.resolution())
        image_size = QSize(
            max(1, int(page_points.width() * dpi / 72)),
            max(1, int(page_points.height() * dpi / 72)),
        )
        image = self.document.render(page, image_size)
        if image.isNull():
            return

        page_rect = printer.pageRect(QPrinter.DevicePixel)
        target = QRectF(page_rect)
        source_ratio = image.width() / image.height()
        target_ratio = target.width() / target.height()
        if source_ratio > target_ratio:
            height = target.width() / source_ratio
            target.setY(target.y() + (target.height() - height) / 2)
            target.setHeight(height)
        else:
            width = target.height() * source_ratio
            target.setX(target.x() + (target.width() - width) / 2)
            target.setWidth(width)
        painter.drawImage(target, image)


def show_invoice_preview(parent, pdf_path: str | Path, title: str) -> None:
    dialog = InvoicePreviewDialog(pdf_path, title=title, parent=parent)
    dialog.exec()
