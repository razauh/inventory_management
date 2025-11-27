from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QSortFilterProxyModel, QRegularExpression, QTimer
import sqlite3, datetime
from typing import Optional
import logging
import re
import uuid

from ..base_module import BaseModule
from .view import PurchaseView
from .model import PurchasesTableModel
from .form import PurchaseForm
from .return_form import PurchaseReturnForm
from .payments import PurchasePaymentDialog
from ...database.repositories.purchases_repo import PurchasesRepo, PurchaseHeader, PurchaseItem
from ...database.repositories.vendors_repo import VendorsRepo
from ...database.repositories.products_repo import ProductsRepo
from ...database.repositories.purchase_payments_repo import PurchasePaymentsRepo
from ...database.repositories.vendor_advances_repo import VendorAdvancesRepo
from ...utils.ui_helpers import info
from ...utils.helpers import today_str

try:
    from ...database.repositories.vendor_advances_repo import OverapplyVendorAdvanceError
except Exception:
    OverapplyVendorAdvanceError = None
try:
    from ...database.repositories.purchase_payments_repo import OverpayPurchaseError
except Exception:
    OverpayPurchaseError = None

_EPS = 1e-9

_log = logging.getLogger(__name__)
if not _log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(asctime)s] %(name)s:%(lineno)d %(levelname)s: %(message)s"))
    _log.addHandler(_h)
    _log.setLevel(logging.INFO)


def new_purchase_id(conn: sqlite3.Connection, date_str: str) -> str:
    d = date_str.replace("-", "")
    prefix = f"PO{d}-"
    row = conn.execute("SELECT MAX(purchase_id) AS m FROM purchases WHERE purchase_id LIKE ?", (prefix + "%",)).fetchone()
    if row and row["m"]:
        try:
            last = int(row["m"].split("-")[-1])
        except Exception:
            last = 0
    else:
        last = 0
    return f"{prefix}{last+1:04d}"


class PurchaseController(BaseModule):
    # CSS for PDF generation - shared between print and export methods
    _INVOICE_PDF_CSS = '''
        @page {
            margin: 10mm;
            size: A4;
        }
        body {
            margin: 0 !important;
            padding: 0 !important;
            width: 100% !important;
        }
        .page {
            margin: 0 !important;
            padding: 0 !important;
            width: 100% !important;
        }
    '''

    def __init__(self, conn: sqlite3.Connection, current_user: dict | None):
        super().__init__()
        self.conn = conn
        self.user = current_user
        self.view = PurchaseView()
        self.repo = PurchasesRepo(conn)
        self.payments = PurchasePaymentsRepo(conn)
        self.vadv = VendorAdvancesRepo(conn)
        self.vendors = VendorsRepo(conn)
        self.products = ProductsRepo(conn)
        self._wire()
        self._reload()

    def get_widget(self) -> QWidget:
        return self.view

    def _wire(self):
        self.view.btn_add.clicked.connect(self._add)
        self.view.btn_edit.clicked.connect(self._edit)
        self.view.btn_return.clicked.connect(self._return)
        self.view.btn_pay.clicked.connect(self._payment)
        
        # Create a timer for debounced search
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._perform_search)
        
        # Connect search text changes to the debounced handler
        self.view.search.textChanged.connect(self._on_search_text_changed)
        
        # Connect radio buttons to the same filter function since it handles the type
        self.view.rb_all.toggled.connect(self._apply_filter)
        self.view.rb_id.toggled.connect(self._apply_filter)
        self.view.rb_vendor.toggled.connect(self._apply_filter)
        self.view.rb_status.toggled.connect(self._apply_filter)

    def _build_model(self):
        rows = self.repo.list_purchases()
        self.base = PurchasesTableModel(rows)
        self._original_rows = rows  # Cache the original data for fast searching
        self.proxy = QSortFilterProxyModel(self.view)
        self.proxy.setSourceModel(self.base)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.view.tbl.setModel(self.proxy)
        self.view.tbl.resizeColumnsToContents()
        sel = self.view.tbl.selectionModel()
        try:
            sel.selectionChanged.disconnect(self._sync_details)
        except (TypeError, RuntimeError, RuntimeWarning):
            pass
        sel.selectionChanged.connect(self._sync_details)

    def _reload(self):
        # Preserve the current search state
        current_search = self.view.search.text()
        current_radio_button = None
        if self.view.rb_all.isChecked():
            current_radio_button = "all"
        elif self.view.rb_id.isChecked():
            current_radio_button = "id"
        elif self.view.rb_vendor.isChecked():
            current_radio_button = "vendor"
        elif self.view.rb_status.isChecked():
            current_radio_button = "status"
        
        self._build_model()
        
        # Restore the search after reloading the data
        if current_search:
            # Set flag to prevent double search execution
            self._programmatically_setting_search = True
            self.view.search.setText(current_search)
            # Restore the radio button state
            if current_radio_button == "all":
                self.view.rb_all.setChecked(True)
            elif current_radio_button == "id":
                self.view.rb_id.setChecked(True)
            elif current_radio_button == "vendor":
                self.view.rb_vendor.setChecked(True)
            elif current_radio_button == "status":
                self.view.rb_status.setChecked(True)
            
            # Re-apply the search filter
            self._perform_search()
            # Reset the flag
            self._programmatically_setting_search = False
        
        if self.proxy.rowCount() > 0:
            self.view.tbl.selectRow(0)
        else:
            self.view.details.set_data(None)
            self.view.items.set_rows([])
            try:
                self.view.details.clear_payment_summary()
            except Exception:
                pass

    def _on_search_text_changed(self, text):
        """Handle search text changes with adaptive debouncing."""
        # Skip processing if we're programmatically setting the text (avoid double search)
        if hasattr(self, '_programmatically_setting_search') and self._programmatically_setting_search:
            return
        
        # Adjust debounce time based on search text length for better performance
        # Shorter searches get longer debounce to avoid rendering large result sets
        # Longer/more specific queries use shorter debounce since results are fewer
        debounce_time = 500 if len(text) < 3 else 150
        # Restart the timer for each keystroke
        self._search_timer.start(debounce_time)

    def _perform_search(self):
        """Actually perform the search after debounce delay."""
        search_text = self.view.search.text()
        
        if not search_text.strip():
            # If search is empty, show all rows
            self.base.replace(self._original_rows)
            return
            
        # Determine which column to search based on radio button selection
        def safe_lower(value):
            """Convert value to lowercase string, handling None values"""
            if value is None:
                return ""
            return str(value).lower()
        
        if self.view.rb_all.isChecked():
            # Search across all columns - filter in memory for better performance
            filtered_rows = []
            search_lower = search_text.lower()
            for row in self._original_rows:
                # Check each relevant field in the row
                if (search_lower in safe_lower(row["purchase_id"]) or
                    search_lower in safe_lower(row["date"]) or
                    search_lower in safe_lower(row["vendor_name"]) or
                    search_lower in safe_lower(row["total_amount"]) or
                    search_lower in safe_lower(row["paid_amount"]) or
                    search_lower in safe_lower(row["payment_status"])):
                    filtered_rows.append(row)
        elif self.view.rb_id.isChecked():
            # Search only in PO ID column
            search_lower = search_text.lower()
            filtered_rows = [row for row in self._original_rows 
                            if search_lower in safe_lower(row["purchase_id"])]
        elif self.view.rb_vendor.isChecked():
            # Search only in Vendor column
            search_lower = search_text.lower()
            filtered_rows = [row for row in self._original_rows 
                            if search_lower in safe_lower(row["vendor_name"])]
        elif self.view.rb_status.isChecked():
            # Search only in Status column
            search_lower = search_text.lower()
            filtered_rows = [row for row in self._original_rows 
                            if search_lower in safe_lower(row["payment_status"])]
        
        # Update the model with filtered results
        self.base.replace(filtered_rows)

    def _apply_filter(self, _=None):  # parameter can be text or checked state
        """Apply filter when radio button selection changes."""
        # Re-apply the current search with the new filter criteria
        self._perform_search()

    def _selected_row_dict(self) -> dict | None:
        idxs = self.view.tbl.selectionModel().selectedRows()
        if not idxs:
            return None
        src = self.proxy.mapToSource(idxs[0])
        r = self.base.at(src.row())
        try:
            return r if isinstance(r, dict) else dict(r)
        except Exception:
            return r

    def _sync_details(self, *args):
        row = self._selected_row_dict()
        self.view.details.set_data(row)
        if row:
            self.view.items.set_rows(self.repo.list_items(row["purchase_id"]))
        else:
            self.view.items.set_rows([])
        try:
            self._refresh_payment_summary(row["purchase_id"] if row else None)
        except Exception:
            pass

    def _returnable_map(self, purchase_id: str) -> dict[int, float]:
        return self.repo.get_returnable_map(purchase_id)

    def _get_payment(self, payment_id: int) -> Optional[dict]:
        row = self._selected_row_dict()
        if not row:
            return None
        r = self.repo.get_payment(payment_id, row["purchase_id"])
        return dict(r) if r is not None else None

    def _fetch_purchase_financials(self, purchase_id: str) -> dict:
        return self.repo.fetch_purchase_financials(purchase_id)

    def _remaining_due_header(self, purchase_id: str) -> float:
        return self.repo.get_remaining_due_header(purchase_id)

    def _vendor_credit_balance(self, vendor_id: int) -> float:
        try:
            return float(self.vadv.get_balance(vendor_id))
        except Exception:
            return 0.0

    def _latest_purchase_payment(self, purchase_id: str) -> dict | None:
        row = self.conn.execute(
            """
            SELECT payment_id,
                   date,
                   method,
                   CAST(amount AS REAL) AS amount,
                   clearing_state AS status
              FROM purchase_payments
             WHERE purchase_id=?
             ORDER BY date DESC, payment_id DESC
             LIMIT 1
            """,
            (purchase_id,),
        ).fetchone()
        return dict(row) if row else None

    def _overpayment_credited(self, purchase_id: str) -> float:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(CAST(amount AS REAL)), 0.0) AS overpay
              FROM vendor_advances
             WHERE source_type='deposit'
               AND source_id=?
               AND notes LIKE 'Excess payment converted to vendor credit%'
            """,
            (purchase_id,),
        ).fetchone()
        return float(row["overpay"] or 0.0) if row else 0.0

    def _refresh_payment_summary(self, purchase_id: Optional[str]) -> None:
        if not purchase_id:
            try:
                self.view.details.clear_payment_summary()
            except Exception:
                pass
            return
        last = self._latest_purchase_payment(purchase_id)
        if not last:
            try:
                self.view.details.clear_payment_summary()
            except Exception:
                pass
            return
        payload = {
            "method": last.get("method"),
            "amount": float(last.get("amount") or 0.0),
            "status": last.get("status") or "posted",
            "overpayment": self._overpayment_credited(purchase_id),
            "counterparty_label": "Vendor",
        }
        try:
            self.view.details.set_payment_summary(payload)
        except Exception:
            pass

    def _recompute_header_totals_from_rows(self, purchase_id: str) -> None:
        self.repo.update_header_totals(purchase_id)

    def _add(self):
        # Generate purchase ID ahead of time so it can be displayed in the form
        from ...utils.helpers import today_str
        temp_date = today_str()  # Use today's date for initial ID generation
        temp_pid = new_purchase_id(self.conn, temp_date)

        # Create initial data with the temp purchase ID for display
        initial_data = {
            "purchase_id": temp_pid,  # This will be updated after form submission
            "vendor_id": None,
            "date": temp_date,
            "order_discount": 0.0,
            "notes": "",
            "items": [],
        }
        
        self.active_dialog = PurchaseForm(None, vendors=self.vendors, products=self.products, initial=initial_data)
        self.active_dialog.accepted.connect(self._handle_add_dialog_accept)
        self.active_dialog.show()

    def _handle_add_dialog_accept(self):
        if not self.active_dialog:
            return
        p = self.active_dialog.payload()
        if not p:
            return

        # Check if this was called from print or PDF export button
        should_print_after_save = p.get('_should_print', False)
        should_export_pdf_after_save = p.get('_should_export_pdf', False)

        # Use the actual date from the form to generate the final purchase ID
        pid = new_purchase_id(self.conn, p["date"])

        h = PurchaseHeader(
            purchase_id=pid,
            vendor_id=p["vendor_id"],
            date=p["date"],
            total_amount=p.get("total_amount", 0.0),
            order_discount=p.get("order_discount", 0.0),
            payment_status="unpaid",
            paid_amount=0.0,
            advance_payment_applied=0.0,
            notes=p.get("notes"),
            created_by=(self.user["user_id"] if self.user else None),
        )
        items = [
            PurchaseItem(
                None,
                pid,
                it["product_id"],
                it["quantity"],
                it["uom_id"],
                it["purchase_price"],
                it["sale_price"],
                it["item_discount"],
            )
            for it in p["items"]
        ]

        try:

            self.conn.execute("BEGIN")

            self.repo.create_purchase(h, items)

            ip = p.get("initial_payment")
            if isinstance(ip, dict):
                amt = float(ip.get("amount") or 0.0)
                if amt < 0:
                    self.conn.rollback()
                    info(self.view, "Invalid amount", "Initial payment cannot be negative.")
                    return
                if amt > 0:
                    method = (ip.get("method") or "Cash").strip()
                    clearing_state = ip.get("clearing_state")
                    cleared_date = ip.get("cleared_date")
                    if not clearing_state:
                        # For consistency with cash, all payment methods are now cleared by default
                        clearing_state = "cleared"
                        cleared_date = ip.get("date") or p["date"]
                    self.payments.record_payment(
                        purchase_id=pid,
                        amount=amt,
                        method=method,
                        bank_account_id=ip.get("bank_account_id"),
                        vendor_bank_account_id=ip.get("vendor_bank_account_id"),
                        instrument_type=ip.get("instrument_type"),
                        instrument_no=ip.get("instrument_no"),
                        instrument_date=ip.get("instrument_date"),
                        deposited_date=ip.get("deposited_date"),
                        cleared_date=cleared_date,
                        clearing_state=clearing_state,
                        ref_no=ip.get("ref_no"),
                        notes=ip.get("notes") or "Initial payment",
                        date=ip.get("date") or p["date"],
                        created_by=(self.user["user_id"] if self.user else None),
                        temp_vendor_bank_name=ip.get("temp_vendor_bank_name"),
                        temp_vendor_bank_number=ip.get("temp_vendor_bank_number"),
                    )

                    if clearing_state == "cleared":
                        self._recompute_header_totals_from_rows(pid)
            else:
                initial_paid = float(p.get("initial_payment") or 0.0)
                if initial_paid < 0:
                    self.conn.rollback()
                    info(self.view, "Invalid amount", "Initial payment cannot be negative.")
                    return
                if initial_paid > 0:
                    method = p.get("initial_method") or "Cash"
                    bank_account_id = p.get("initial_bank_account_id")
                    vendor_bank_account_id = p.get("initial_vendor_bank_account_id")

                    instrument_type = p.get("initial_instrument_type")
                    if not instrument_type:
                        if method == "Bank Transfer":
                            instrument_type = "online"
                        elif method == "Cheque":
                            instrument_type = "cross_cheque"
                        elif method == "Cash Deposit":
                            instrument_type = "cash_deposit"
                        else:
                            instrument_type = None

                    instrument_no = p.get("initial_instrument_no")
                    instrument_date = p.get("initial_instrument_date")
                    deposited_date = p.get("initial_deposited_date")
                    cleared_date = p.get("initial_cleared_date")
                    clearing_state = p.get("initial_clearing_state")
                    ref_no = p.get("initial_ref_no")
                    pay_notes = p.get("initial_payment_notes")

                    if not clearing_state:
                        # For consistency with cash, all payment methods are now cleared by default
                        clearing_state = "cleared"
                        cleared_date = p.get("date")

                    self.payments.record_payment(
                        purchase_id=pid,
                        amount=initial_paid,
                        method=method,
                        bank_account_id=bank_account_id,
                        vendor_bank_account_id=vendor_bank_account_id if method in ("Bank Transfer", "Cheque", "Cash Deposit") else None,
                        instrument_type=instrument_type,
                        instrument_no=instrument_no,
                        instrument_date=instrument_date,
                        deposited_date=deposited_date,
                        cleared_date=cleared_date,
                        clearing_state=clearing_state,
                        ref_no=ref_no,
                        notes=pay_notes,
                        date=p["date"],
                        created_by=(self.user["user_id"] if self.user else None),
                        temp_vendor_bank_name=p.get("temp_vendor_bank_name"),
                        temp_vendor_bank_number=p.get("temp_vendor_bank_number"),
                    )
                    _log.info(
                        "Inserted initial payment (legacy) for %s amount=%.4f method=%s state=%s",
                        pid, initial_paid, method, clearing_state
                    )
                    if clearing_state == "cleared":
                        self._recompute_header_totals_from_rows(pid)

            init_credit = float(p.get("initial_credit_amount") or 0.0)
            if init_credit > 0:
                remaining = self._remaining_due_header(pid)
                credit_bal = self._vendor_credit_balance(int(p["vendor_id"]))
                allowable = min(credit_bal, remaining)
                if init_credit - allowable > _EPS:
                    self.conn.rollback()
                    info(self.view, "Credit not applied", f"Initial credit exceeds available credit or remaining due (max {allowable:.2f}).")
                    return
                self.vadv.apply_credit_to_purchase(
                    vendor_id=p["vendor_id"],
                    purchase_id=pid,
                    amount=init_credit,
                    date=p["date"],
                    notes=p.get("initial_credit_notes"),
                    created_by=(self.user["user_id"] if self.user else None),
                )
                _log.info("Applied initial vendor credit for %s amount=%.4f", pid, init_credit)
                self._recompute_header_totals_from_rows(pid)

            # After applying any manual credit, automatically apply all remaining available vendor advances to this purchase
            vendor_id = int(p["vendor_id"])
            remaining_after_manual = self._remaining_due_header(pid)  # Recalculate after manual credit applied
            credit_bal = self._vendor_credit_balance(vendor_id)
            auto_apply_amount = min(credit_bal, remaining_after_manual)
            
            if auto_apply_amount > _EPS:  # Apply if there's a meaningful amount available
                try:
                    self.vadv.apply_credit_to_purchase(
                        vendor_id=vendor_id,
                        purchase_id=pid,
                        amount=auto_apply_amount,
                        date=p["date"],
                        notes=f"Auto-applied vendor advance from available credit",
                        created_by=(self.user["user_id"] if self.user else None),
                    )
                    _log.info("Auto-applied vendor credit for %s amount=%.4f", pid, auto_apply_amount)
                    self._recompute_header_totals_from_rows(pid)
                except Exception as e:
                    if OverapplyVendorAdvanceError and isinstance(e, OverapplyVendorAdvanceError):
                        _log.warning("Auto-apply skipped: %s", str(e))
                        # It's okay to skip auto-application if it would exceed limits
                    else:
                        raise

            self.conn.commit()


        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass
            if OverpayPurchaseError and isinstance(e, OverpayPurchaseError):
                _log.exception("ROLLBACK %s due to OverpayPurchaseError", pid)
                info(self.view, "Payment not recorded", str(e))
                return
            if OverapplyVendorAdvanceError and isinstance(e, OverapplyVendorAdvanceError):
                _log.exception("ROLLBACK %s due to OverapplyVendorAdvanceError", pid)
                info(self.view, "Credit not applied", str(e))
                return
            if isinstance(e, (sqlite3.IntegrityError, sqlite3.OperationalError, ValueError)):
                _log.exception("ROLLBACK %s due to DB/Value error", pid)
                info(self.view, "Save failed", f"Purchase could not be saved:\n{e}")
                return
            _log.exception("ROLLBACK %s due to unexpected error", pid)
            info(self.view, "Unexpected error", f"Something went wrong while saving the purchase.\nDetails: {e}")
            return

        info(self.view, "Saved", f"Purchase {pid} created.")
        self._reload()
        
        # Handle print or PDF export request after saving
        if should_print_after_save:
            self._print_purchase_invoice(pid)
        elif should_export_pdf_after_save:
            self._export_purchase_invoice_to_pdf(pid)


    def _print_purchase_invoice(self, purchase_id: str):
        """Print the purchase invoice using WeasyPrint for better rendering"""
        try:
            import os
            import tempfile
            from PySide6.QtCore import QStandardPaths
            from weasyprint import HTML, CSS
            from weasyprint.text.fonts import FontConfiguration
            
            # Generate HTML content using the shared helper
            html_content = self._generate_invoice_html_content(purchase_id)
            
            # Sanitize the purchase_id to prevent path traversal attacks in temp file prefix
            sanitized_purchase_id = self._sanitize_filename(purchase_id, max_length=50)  # Shorter for temp prefix

            # Create PDF in temporary location with proper naming
            temp_pdf_fd, temp_pdf_path = tempfile.mkstemp(suffix='.pdf', prefix=f'{sanitized_purchase_id}_')
            os.close(temp_pdf_fd)  # Close the file descriptor
            
            # Convert HTML to PDF with custom CSS for proper margins
            # Use shared CSS constant from class
            custom_css = CSS(string=self._INVOICE_PDF_CSS)
            
            html_doc = HTML(string=html_content)
            html_doc.write_pdf(temp_pdf_path, stylesheets=[custom_css])
            
            # Open the PDF in default PDF viewer (to allow printing)
            import subprocess
            import sys
            
            try:
                if sys.platform.startswith('win'):
                    os.startfile(temp_pdf_path)
                elif sys.platform.startswith('darwin'):  # macOS
                    subprocess.run(['open', temp_pdf_path])
                else:  # Linux and others
                    subprocess.run(['xdg-open', temp_pdf_path])
            except Exception:
                info(self.view, "Print", f"PDF saved to: {temp_pdf_path}. Please open it to print.")
        
        except ImportError:
            info(self.view, "WeasyPrint Not Available", "Please install WeasyPrint: pip install weasyprint")
        except Exception as e:
            info(self.view, "Error", f"Could not print invoice: {e}")
    
    def _export_purchase_invoice_to_pdf(self, purchase_id: str):
        """Export the purchase invoice to PDF using WeasyPrint for better rendering"""
        try:
            import os
            from PySide6.QtCore import QStandardPaths
            from weasyprint import HTML, CSS
            
            # Generate HTML content using the shared helper
            html_content = self._generate_invoice_html_content(purchase_id)
            
            # Determine the desktop path and create PIs subdirectory
            desktop_path = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
            pdfs_dir = os.path.join(desktop_path, "PIs")
            
            # Create the directory if it doesn't exist
            os.makedirs(pdfs_dir, exist_ok=True)
            
            # Sanitize the purchase_id to prevent path traversal attacks
            sanitized_purchase_id = self._sanitize_filename(purchase_id, max_length=100)

            # Construct the file path using the sanitized identifier
            file_name = f"{sanitized_purchase_id}.pdf"
            file_path = os.path.join(pdfs_dir, file_name)
            
            # Convert HTML to PDF using WeasyPrint with custom CSS for proper margins
            # Use shared CSS constant from class
            custom_css = CSS(string=self._INVOICE_PDF_CSS)
            
            html_doc = HTML(string=html_content)
            html_doc.write_pdf(file_path, stylesheets=[custom_css])
                
            info(self.view, "Export Successful", f"Invoice exported to: {file_path}")
            
        except ImportError:
            info(self.view, "WeasyPrint Not Available", "Please install WeasyPrint: pip install weasyprint")
        except Exception as e:
            info(self.view, "Error", f"Could not export invoice to PDF: {e}")

    def _generate_invoice_html_content(self, purchase_id: str) -> str:
        """Generate HTML content for purchase invoice - shared between print and export methods."""
        import os
        from jinja2 import Template
        
        # Load the template file
        template_path = "resources/templates/invoices/purchase_invoice.html"
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        full_template_path = os.path.join(project_root, template_path)

        try:
            with open(full_template_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
        except FileNotFoundError:
            error_msg = f"Template file not found: {full_template_path}. Please ensure the invoice template exists."
            _log.error(error_msg)
            raise FileNotFoundError(error_msg)
        except OSError as e:
            error_msg = f"Could not read template file {full_template_path}: {e}"
            _log.error(error_msg)
            raise OSError(error_msg)
        
        # Prepare data for the template
        enriched_data = {"purchase_id": purchase_id}
        
        # Fetch purchase header data using repository
        header_row = self.repo.get_header_with_vendor(purchase_id)
        
        if header_row:
            doc_data = dict(header_row)
            enriched_data['doc'] = doc_data
            enriched_data['vendor'] = {
                'name': doc_data.get('vendor_name', ''),
                'contact_info': doc_data.get('vendor_contact_info', ''),
                'address': doc_data.get('vendor_address', '')
            }
            
            # Fetch purchase items using repository
            items_rows = self.repo.list_items(purchase_id)
            
            items = []
            for row in items_rows:
                item_dict = dict(row)
                # Calculate line_total
                quantity = float(item_dict.get('quantity', 0.0))
                purchase_price = float(item_dict.get('purchase_price', 0.0))
                line_total = quantity * purchase_price
                item_dict['line_total'] = line_total
                
                # Calculate idx (row number)
                item_dict['idx'] = len(items) + 1
                
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
            
            # Get latest payment details using repository
            latest_payment = self.payments.get_latest_payment_for_purchase(purchase_id)
            
            if latest_payment:
                enriched_data['initial_payment'] = dict(latest_payment)
            else:
                enriched_data['initial_payment'] = None
            
            # Add company info
            enriched_data['company'] = {
                'name': 'Your Company Name',  # This would come from a company settings table
                'logo_path': None  # This would come from company settings
            }
            
            # Add payment status
            enriched_data['doc']['payment_status'] = doc_data.get('payment_status', 'Unpaid')
        
        # Create Jinja2 template and render
        template = Template(template_content, autoescape=True)
        html_content = template.render(**enriched_data)
        
        return html_content

    def _sanitize_filename(self, filename: str, max_length: int = 100) -> str:
        """
        Sanitize a string for safe use as a filename.
        Removes unsafe characters, truncates to max_length, and provides UUID fallback for empty results.
        """
        # Remove or replace any path separators and other non-filename-safe characters
        sanitized = re.sub(r'[^A-Za-z0-9._-]', '_', filename)
        # Trim to reasonable length to prevent issues with filesystem limits
        sanitized = sanitized[:max_length]
        # Fallback to a safe generated token if the result is empty
        if not sanitized:
            sanitized = f"file_{uuid.uuid4().hex[:8]}"
        return sanitized

    def _edit(self):
        row = self._selected_row_dict()
        if not row:
            info(self.view, "Select", "Select a purchase to edit.")
            return
        items = self.repo.list_items(row["purchase_id"])
        init = {
            "vendor_id": row["vendor_id"],
            "date": row["date"],
            "order_discount": row["order_discount"],
            "notes": row["notes"] if "notes" in row.keys() else None,
            "items": [
                {
                    "product_id": it["product_id"],
                    "uom_id": it["uom_id"],
                    "quantity": it["quantity"],
                    "purchase_price": it["purchase_price"],
                    "sale_price": it["sale_price"],
                    "item_discount": it["item_discount"],
                }
                for it in items
            ],
        }
        
        dlg = PurchaseForm(self.view, vendors=self.vendors, products=self.products, initial=init)
        if not dlg.exec():
            return
        p = dlg.payload()
        if not p:
            return
        pid = row["purchase_id"]
        h = PurchaseHeader(
            purchase_id=pid,
            vendor_id=p["vendor_id"],
            date=p["date"],
            total_amount=p["total_amount"],
            order_discount=p["order_discount"],
            payment_status=row["payment_status"],
            paid_amount=row["paid_amount"],
            advance_payment_applied=row["advance_payment_applied"],
            notes=p["notes"],
            created_by=(self.user["user_id"] if self.user else None),
        )
        items = [
            PurchaseItem(
                None,
                pid,
                it["product_id"],
                it["quantity"],
                it["uom_id"],
                it["purchase_price"],
                it["sale_price"],
                it["item_discount"],
            )
            for it in p["items"]
        ]
        
        # Check if this was called from print or PDF export button
        should_print_after_save = p.get('_should_print', False)
        should_export_pdf_after_save = p.get('_should_export_pdf', False)
        
        # Update the purchase header and items first
        self.repo.update_purchase(h, items)
        
        # Check if this was called from print or PDF export button
        should_print_after_save = p.get('_should_print', False)
        should_export_pdf_after_save = p.get('_should_export_pdf', False)
        
        # Update purchase
        self.repo.update_purchase(h, items)
        
        # After updating the purchase, automatically apply any available vendor advances
        # Skip auto-apply if the user provided manual initial credit
        initial_manual_credit = p.get("initial_credit_amount")
        if initial_manual_credit is None:
            initial_manual_credit = 0.0
        else:
            initial_manual_credit = float(initial_manual_credit)
            
        vendor_id = int(p["vendor_id"])
        credit_bal = self._vendor_credit_balance(vendor_id)
        remaining = self._remaining_due_header(pid)
        auto_apply_amount = min(credit_bal, remaining)
        
        if auto_apply_amount > _EPS and initial_manual_credit <= _EPS:  # Only apply if there's a meaningful amount and no manual credit was provided
            try:
                self.vadv.apply_credit_to_purchase(
                    vendor_id=vendor_id,
                    purchase_id=pid,
                    amount=auto_apply_amount,
                    date=p["date"],
                    notes=f"Auto-applied vendor advance from available credit (after edit)",
                    created_by=(self.user["user_id"] if self.user else None),
                )
                _log.info("Auto-applied vendor credit after edit for %s amount=%.4f", pid, auto_apply_amount)
                # The apply_credit_to_purchase method should update the header totals automatically
            except Exception as e:
                if OverapplyVendorAdvanceError and isinstance(e, OverapplyVendorAdvanceError):
                    _log.warning("Auto-apply after edit skipped: %s", str(e))
                    # It's okay to skip auto-application if it would exceed limits
                else:
                    raise

        info(self.view, "Saved", f"Purchase {pid} updated.")
        
        # Handle print or PDF export request after saving
        if should_print_after_save:
            self._print_purchase_invoice(pid)
        elif should_export_pdf_after_save:
            self._export_purchase_invoice_to_pdf(pid)
        
        self._reload()

    def _delete(self):
        row = self._selected_row_dict()
        if not row:
            info(self.view, "Select", "Select a purchase to delete.")
            return
        self.repo.delete_purchase(row["purchase_id"])
        info(self.view, "Deleted", f'Purchase {row["purchase_id"]} removed.')
        self._reload()

    def _return(self):
        row = self._selected_row_dict()
        if not row:
            info(self.view, "Select", "Select a purchase to return items from.")
            return
        pid = row["purchase_id"]
        items = self.repo.list_items(pid)
        returnable = self._returnable_map(pid)
        items_for_form = []
        for it in items:
            it2 = dict(it)
            it2["returnable"] = float(returnable.get(it["item_id"], 0.0))
            items_for_form.append(it2)

        dlg = PurchaseReturnForm(self.view, items_for_form, vendors=self.vendors, purchases_repo=self.repo)
        # Set the purchase ID to allow remaining calculation
        dlg.set_purchase_id(pid)
        if not dlg.exec():
            return
        payload = dlg.payload()
        if not payload:
            return

        by_id = {it["item_id"]: it for it in items}
        lines = []
        for ln in payload["lines"]:
            it = by_id.get(ln["item_id"])
            if not it:
                continue
            lines.append(
                {
                    "item_id": it["item_id"],
                    "product_id": it["product_id"],
                    "uom_id": it["uom_id"],
                    "qty_return": float(ln["qty_return"]),
                }
            )

        settlement = payload.get("settlement")
        try:
            self.repo.record_return(
                pid=pid,
                date=payload["date"],
                created_by=(self.user["user_id"] if self.user else None),
                lines=lines,
                notes=payload.get("notes"),
                settlement=settlement,
            )
            
            # Update the purchase header totals to reflect the return
            # This is important for purchase balance calculations
            self._recompute_header_totals_from_rows(pid)
        except (ValueError, sqlite3.IntegrityError, sqlite3.OperationalError) as e:
            info(self.view, "Return not recorded", f"Could not record return:\n{e}")
            return

        info(self.view, "Saved", "Return recorded.")
        self._reload()

    def apply_vendor_credit(self, *, amount: float, date: Optional[str] = None, notes: Optional[str] = None):
        row = self._selected_row_dict()
        if not row:
            info(self.view, "Select", "Select a purchase to apply vendor credit.")
            return
        try:
            amt = float(amount)
        except (TypeError, ValueError):
            info(self.view, "Invalid amount", "Enter a valid positive amount to apply as credit.")
            return
        if amt <= 0:
            info(self.view, "Invalid amount", "Amount must be greater than zero.")
            return

        remaining = self._remaining_due_header(row["purchase_id"])
        credit_bal = self._vendor_credit_balance(int(row["vendor_id"]))
        allowable = min(credit_bal, remaining)
        if amt - allowable > _EPS:
            info(self.view, "Credit not applied", f"Amount exceeds available credit or remaining due (max {allowable:.2f}).")
            return

        when = date or today_str()
        try:
            self.vadv.apply_credit_to_purchase(
                vendor_id=int(row["vendor_id"]),
                purchase_id=row["purchase_id"],
                amount=amt,
                date=when,
                notes=notes,
                created_by=(self.user["user_id"] if self.user else None),
            )
        except Exception as e:
            if OverapplyVendorAdvanceError and isinstance(e, OverapplyVendorAdvanceError):
                info(self.view, "Credit not applied", str(e))
                return
            if isinstance(e, (sqlite3.IntegrityError, sqlite3.OperationalError)):
                info(self.view, "Credit not applied", f"A database error occurred:\n{e}")
                return
            info(self.view, "Credit not applied", str(e))
            return

        info(self.view, "Saved", f"Applied vendor credit of {amt:g} to {row['purchase_id']}.")
        self._reload()

    def _payment(self):
        row = self._selected_row_dict()
        if not row:
            info(self.view, "Select", "Select a purchase to record payment.")
            return

        purchase_id = str(row["purchase_id"])
        vendor_id = int(row.get("vendor_id") or 0)

        from .payment_form import PaymentForm
        dlg = PaymentForm(self.view, vendors=self.vendors, purchase_id=purchase_id, vendor_id=vendor_id)
        
        if dlg.exec():
            payload = dlg.payload()
            if payload:
                try:
                    self.conn.execute("BEGIN")
                    
                    self.payments.record_payment(
                        purchase_id=payload["purchase_id"],
                        amount=payload["amount"],
                        method=payload["method"],
                        bank_account_id=payload["bank_account_id"],
                        vendor_bank_account_id=payload["vendor_bank_account_id"],
                        instrument_type=payload["instrument_type"],
                        instrument_no=payload["instrument_no"],
                        instrument_date=payload["instrument_date"],
                        deposited_date=payload["deposited_date"],
                        cleared_date=payload["cleared_date"],
                        clearing_state=payload["clearing_state"],
                        ref_no=payload["ref_no"],
                        notes=payload["notes"],
                        date=payload["date"],
                        created_by=(self.user["user_id"] if self.user else None),
                        temp_vendor_bank_name=payload["temp_vendor_bank_name"],
                        temp_vendor_bank_number=payload["temp_vendor_bank_number"],
                    )
                    
                    # Update the purchase header totals to reflect the new payment
                    self._recompute_header_totals_from_rows(purchase_id)
                    
                    self.conn.commit()
                    info(self.view, "Saved", "Payment recorded successfully.")
                    self._reload()
                except Exception as e:
                    try:
                        self.conn.rollback()
                    except Exception:
                        pass
                    info(self.view, "Payment not recorded", f"Could not record payment: {str(e)}")
                    return

    def mark_payment_cleared(self, payment_id: int, *, cleared_date: Optional[str] = None, notes: Optional[str] = None):
        pay = self._get_payment(payment_id)
        if not pay:
            info(self.view, "Not found", "Select a purchase and a valid payment to clear.")
            return
        if (pay.get("clearing_state") or "posted") != "pending":
            info(self.view, "Not allowed", "Only pending payments can be marked as cleared.")
            return

        when = cleared_date or today_str()
        try:
            changed = self.payments.update_clearing_state(
                payment_id=payment_id,
                clearing_state="cleared",
                cleared_date=when,
                notes=notes,
            )
            self.conn.commit()  # Commit the transaction to persist the changes
            if not changed:
                info(self.view, "No change", "Payment was not updated.")
                return
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
            info(self.view, "Update failed", f"Could not mark payment cleared:\n{e}")
            return

        info(self.view, "Saved", f"Payment #{payment_id} marked as cleared.")
        self._reload()

    def mark_payment_bounced(self, payment_id: int, *, notes: Optional[str] = None):
        pay = self._get_payment(payment_id)
        if not pay:
            info(self.view, "Not found", "Select a purchase and a valid payment to mark bounced.")
            return
        if (pay.get("clearing_state") or "posted") != "pending":
            info(self.view, "Not allowed", "Only pending payments can be marked as bounced.")
            return

        try:
            changed = self.payments.update_clearing_state(
                payment_id=payment_id,
                clearing_state="bounced",
                cleared_date=None,
                notes=notes,
            )
            self.conn.commit()  # Commit the transaction to persist the changes
            if not changed:
                info(self.view, "No change", "Payment was not updated.")
                return
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
            info(self.view, "Update failed", f"Could not mark payment bounced:\n{e}")
            return

        info(self.view, "Saved", f"Payment #{payment_id} marked as bounced.")
        self._reload()

    def _list_company_bank_accounts(self) -> list[dict]:
        try:
            rows = self.conn.execute(
                "SELECT account_id, label FROM company_bank_accounts WHERE is_active=1 ORDER BY account_id"
            ).fetchall()
            out = []
            for r in rows:
                _id = r["account_id"]
                _name = r["label"]
                if _id is not None and _name is not None:
                    out.append({"id": int(_id), "name": str(_name)})
            return out
        except Exception:
            return []

    def _list_vendor_bank_accounts(self, vendor_id: int) -> list[dict]:
        try:
            from ..database.repositories.vendor_bank_accounts_repo import VendorBankAccountsRepo
            repo = VendorBankAccountsRepo(self.conn)
            rows = []
            for attr in ("list_by_vendor", "list_for_vendor", "list"):
                if hasattr(repo, attr):
                    try:
                        rows = list(getattr(repo, attr)(vendor_id))
                    except TypeError:
                        try:
                            rows = list(getattr(repo, attr)(vendor_id=vendor_id))
                        except Exception:
                            rows = []
                    break
            out = []
            for r in rows:
                d = dict(r)
                _id = d.get("id") or d.get("vendor_bank_account_id") or d.get("account_id")
                _name = d.get("name") or d.get("account_name") or d.get("title") or d.get("iban") or d.get("account_no")
                if _id is not None and _name is not None:
                    out.append({"id": int(_id), "name": str(_name)})
            return out
        except Exception:
            return []

    def _list_open_purchases_for_vendor(self, vendor_id: int) -> list[dict]:
        out: list[dict] = []
        try:
            cur = self.conn.execute(
                "SELECT purchase_id, date, total_amount AS total, COALESCE(paid_amount,0) AS paid, COALESCE(advance_payment_applied,0) AS adv "
                "FROM purchases WHERE vendor_id = ? ORDER BY date DESC, purchase_id DESC LIMIT 300;",
                (vendor_id,),
            )
            for row in cur.fetchall():
                pid = str(row["purchase_id"])
                fin = self._fetch_purchase_financials(pid)
                if fin["remaining_due"] > 1e-9:
                    out.append(
                        {
                            "purchase_id": pid,
                            "date": str(row["date"]),
                            "total": float(fin["calculated_total_amount"]),
                            "paid": float(fin["paid_amount"]),
                            "remaining_due": float(fin["remaining_due"]),
                        }
                    )
        except Exception:
            return []
        return out
