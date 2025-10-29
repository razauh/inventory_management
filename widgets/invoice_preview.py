from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QToolBar, QComboBox, QPushButton, QTextBrowser, QFileDialog, QMessageBox
from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QPageLayout, QPageSize
from PySide6.QtPrintSupport import QPrinter, QPrintDialog, QPrintPreviewDialog
import os
import sqlite3
import sys


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
            
            # Fetch purchase header data
            header_query = """
            SELECT p.*, v.name AS vendor_name, v.contact_info AS vendor_contact_info, v.address AS vendor_address
            FROM purchases p
            JOIN vendors v ON p.vendor_id = v.vendor_id
            WHERE p.purchase_id = ?
            """
            header_row = self.conn.execute(header_query, (purchase_id,)).fetchone()
            
            if header_row:
                doc_data = dict(header_row)
                enriched_data['doc'] = doc_data
                enriched_data['vendor'] = {
                    'name': doc_data.get('vendor_name', ''),
                    'contact_info': doc_data.get('vendor_contact_info', ''),
                    'address': doc_data.get('vendor_address', '')
                }
                
                # Fetch purchase items
                items_query = """
                SELECT 
                    pi.item_id,
                    pi.product_id,
                    p.name AS product_name,
                    pi.quantity,
                    u.unit_name AS uom_name,
                    pi.purchase_price AS unit_price,
                    pi.sale_price,
                    pi.item_discount,
                    (pi.quantity * pi.purchase_price) AS line_total,
                    ROW_NUMBER() OVER (ORDER BY pi.item_id) AS idx
                FROM purchase_items pi
                JOIN products p ON pi.product_id = p.product_id
                JOIN uoms u ON pi.uom_id = u.uom_id
                WHERE pi.purchase_id = ?
                ORDER BY pi.item_id
                """
                items_rows = self.conn.execute(items_query, (purchase_id,)).fetchall()
                
                items = []
                for row in items_rows:
                    item_dict = dict(row)
                    items.append(item_dict)
                
                enriched_data['items'] = items
                
                # Calculate totals
                subtotal = sum(item['line_total'] for item in items)
                total = subtotal  # For purchases, total = subtotal (no discount for now)
                
                enriched_data['totals'] = {
                    'subtotal_before_order_discount': subtotal,
                    'line_discount_total': 0,  # No line discounts in purchase for now
                    'order_discount': 0,  # No order discount in purchase for now
                    'total': total
                }
                
                # Get initial payment details if exists
                payment_query = """
                SELECT 
                    pp.amount,
                    pp.method,
                    pp.date,
                    pp.bank_account_id,
                    pp.vendor_bank_account_id,
                    pp.instrument_type,
                    pp.instrument_no,
                    pp.instrument_date,
                    pp.deposited_date,
                    pp.cleared_date,
                    pp.ref_no,
                    pp.notes,
                    pp.clearing_state,
                    ca.label AS bank_account_label,
                    va.label AS vendor_bank_account_label
                FROM purchase_payments pp
                LEFT JOIN company_bank_accounts ca ON ca.account_id = pp.bank_account_id
                LEFT JOIN vendor_bank_accounts va ON va.vendor_bank_account_id = pp.vendor_bank_account_id
                WHERE pp.purchase_id = ?
                ORDER BY pp.payment_id DESC
                LIMIT 1
                """
                payment_row = self.conn.execute(payment_query, (purchase_id,)).fetchone()
                
                if payment_row:
                    enriched_data['initial_payment'] = dict(payment_row)
                else:
                    enriched_data['initial_payment'] = None
                
                # Add company info
                enriched_data['company'] = {
                    'name': 'Your Company Name',  # This would come from a company settings table
                    'logo_path': None  # This would come from company settings
                }
                
                # Add payment status
                enriched_data['doc']['payment_status'] = doc_data.get('payment_status', 'Unpaid')
        
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