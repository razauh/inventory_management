from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QToolBar, QComboBox, QPushButton, QTextBrowser, QFileDialog, QMessageBox
from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QPageLayout, QPageSize
from PySide6.QtPrintSupport import QPrinter, QPrintDialog, QPrintPreviewDialog
import os
import sqlite3
import sys

from inventory_management.modules.accounting import AccountingService


class InvoicePreview(QWidget):
    def __init__(self, template_path, context_data, conn=None):
        super().__init__()
        self.template_path = template_path
        self.context_data = context_data
        self.conn = conn
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Toolbar
        toolbar = QToolBar()
        layout.addWidget(toolbar)
        
        # Refresh action
        refresh_action = QAction("Refresh", self)
        refresh_action.triggered.connect(self.refresh_preview)
        toolbar.addAction(refresh_action)
        
        # Print action
        print_action = QAction("Print", self)
        print_action.triggered.connect(self.print_invoice)
        toolbar.addAction(print_action)
        
        # Add shortcut for Ctrl+P
        from PySide6.QtGui import QKeySequence, QShortcut
        print_shortcut = QShortcut(QKeySequence("Ctrl+P"), self)
        print_shortcut.activated.connect(self.print_invoice)
        
        # Always use QTextBrowser as it's more reliable across platforms
        from PySide6.QtWidgets import QTextBrowser
        self.web_view = QTextBrowser()
        self.web_view.setAcceptRichText(True)
        self.web_view.setOpenExternalLinks(True)
        
        layout.addWidget(self.web_view)
        
        # Load the invoice
        self.load_invoice()
        
    def load_invoice(self):
        try:
            # Try to import jinja2
            try:
                from jinja2 import Template
            except ImportError:
                html_content = """
                <h3 style="color: red;">Jinja2 not available. Install jinja2 to render invoices properly.</h3>
                <p>Please install jinja2 by running: <code>pip install jinja2</code></p>
                """
                self.web_view.setHtml(html_content)
                return
            
            # Load the template file
            # The template_path is already a path from the project root, so we need to find the project root
            # Find the project root by looking for the main directory structure
            current_dir = os.path.dirname(os.path.abspath(__file__))  # /path/to/inventory_management/widgets
            project_root = os.path.dirname(current_dir)  # This should be /path/to/inventory_management (one level up)
            
            full_template_path = os.path.join(project_root, self.template_path)
            
            with open(full_template_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
            
            # Prepare data for the template
            enriched_context = self._prepare_invoice_data()
            
            # Create Jinja2 template and render
            template = Template(template_content, autoescape=True)
            html_content = template.render(**enriched_context)
            
            # Load HTML into the text browser
            self.web_view.setHtml(html_content)
        except Exception as e:
            error_html = f"""
            <html>
                <body>
                    <h2>Error Loading Invoice</h2>
                    <p>Could not load the invoice template: {str(e)}</p>
                </body>
            </html>
            """
            self.web_view.setHtml(error_html)
    
    def _prepare_invoice_data(self):
        """Prepare data for the invoice template"""
        enriched_data = self.context_data.copy()
        
        if self.conn and 'purchase_id' in self.context_data:
            purchase_id = self.context_data['purchase_id']

            invoice = AccountingService(self.conn).get_purchase_invoice_financials(
                purchase_id
            )
            enriched_data.update(invoice.preview_context)
            if 'doc' in enriched_data:
                from inventory_management.database.repositories.company_info_repo import get_invoice_company_context
                enriched_data['company'] = get_invoice_company_context(self.conn)
        
        return enriched_data
    
    def refresh_preview(self):
        self.load_invoice()
        
    def print_invoice(self):
        """Print the invoice using system print dialog"""
        try:
            from PySide6.QtPrintSupport import QPrinter
            from PySide6.QtGui import QTextDocument
            
            # Create a printer object
            printer = QPrinter(QPrinter.HighResolution)
            
            # Set the document name to the purchase ID if available
            if 'purchase_id' in self.context_data:
                printer.setDocName(f"Purchase_Invoice_{self.context_data['purchase_id']}")
            
            # Show the print dialog to allow user to select printer and options
            print_dialog = QPrintDialog(printer, self)
            if print_dialog.exec() == QPrintDialog.Accepted:
                # Create a QTextDocument from the HTML content
                doc = QTextDocument()
                doc.setHtml(self.web_view.toHtml())
                
                # Use the print method if available, otherwise use drawContents
                if hasattr(doc, 'print'):
                    doc.print(printer)
                else:
                    from PySide6.QtGui import QPainter
                    painter = QPainter(printer)
                    doc.drawContents(painter)
                    painter.end()
        except Exception as e:
            QMessageBox.critical(self, "Print Error", f"Could not print invoice: {str(e)}")
    
    def print_preview(self):
        """Show print preview before printing"""
        try:
            from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
            from PySide6.QtGui import QTextDocument, QPainter
            
            printer = QPrinter(QPrinter.HighResolution)
            
            # Set the document name to the purchase ID if available
            if 'purchase_id' in self.context_data:
                printer.setDocName(f"Purchase_Invoice_{self.context_data['purchase_id']}")
            
            preview_dialog = QPrintPreviewDialog(printer, self)
            
            def print_preview(p):
                doc = QTextDocument()
                doc.setHtml(self.web_view.toHtml())
                painter = QPainter(p)
                doc.drawContents(painter)
                painter.end()
            
            preview_dialog.paintRequested.connect(print_preview)
            preview_dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "Print Preview Error", f"Could not show print preview: {str(e)}")
