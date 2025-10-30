from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QSortFilterProxyModel, QRegularExpression
import sqlite3, datetime
from typing import Optional
import logging

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
    def __init__(self, conn: sqlite3.Connection, current_user: dict | None):
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
        self.view.search.textChanged.connect(self._apply_filter)

    def _build_model(self):
        rows = self.repo.list_purchases()
        self.base = PurchasesTableModel(rows)
        self.proxy = QSortFilterProxyModel(self.view)
        self.proxy.setSourceModel(self.base)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.view.tbl.setModel(self.proxy)
        self.view.tbl.resizeColumnsToContents()
        sel = self.view.tbl.selectionModel()
        try:
            sel.selectionChanged.disconnect(self._sync_details)
        except (TypeError, RuntimeError):
            pass
        sel.selectionChanged.connect(self._sync_details)

    def _reload(self):
        self._build_model()
        if self.proxy.rowCount() > 0:
            self.view.tbl.selectRow(0)
        else:
            self.view.details.set_data(None)
            self.view.items.set_rows([])
            try:
                self.view.details.clear_payment_summary()
            except Exception:
                pass

    def _apply_filter(self, text: str):
        self.proxy.setFilterRegularExpression(QRegularExpression(text))

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
        sql = """
        SELECT
          pi.item_id,
          CAST(pi.quantity AS REAL) -
          COALESCE((
            SELECT SUM(CAST(it.quantity AS REAL))
            FROM inventory_transactions it
            WHERE it.transaction_type='purchase_return'
              AND it.reference_table='purchases'
              AND it.reference_id = pi.purchase_id
              AND it.reference_item_id = pi.item_id
          ), 0.0) AS returnable
        FROM purchase_items pi
        WHERE pi.purchase_id=?
        """
        rows = self.conn.execute(sql, (purchase_id,)).fetchall()
        return {int(r["item_id"]): float(r["returnable"]) for r in rows}

    def _get_payment(self, payment_id: int) -> Optional[dict]:
        row = self._selected_row_dict()
        if not row:
            return None
        sql = """
        SELECT *
        FROM purchase_payments
        WHERE payment_id=? AND purchase_id=?
        """
        r = self.conn.execute(sql, (payment_id, row["purchase_id"])).fetchone()
        return dict(r) if r is not None else None

    def _fetch_purchase_financials(self, purchase_id: str) -> dict:
        row = self.conn.execute(
            """
            SELECT
              p.total_amount,
              COALESCE(p.paid_amount, 0.0)              AS paid_amount,
              COALESCE(p.advance_payment_applied, 0.0)  AS advance_payment_applied,
              COALESCE(pdt.calculated_total_amount, p.total_amount) AS calculated_total_amount
            FROM purchases p
            LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
            WHERE p.purchase_id = ?;
            """,
            (purchase_id,),
        ).fetchone()
        if not row:
            return {
                "total_amount": 0.0,
                "paid_amount": 0.0,
                "advance_payment_applied": 0.0,
                "calculated_total_amount": 0.0,
                "remaining_due": 0.0,
            }
        calc = float(row["calculated_total_amount"] or 0.0)
        paid = float(row["paid_amount"] or 0.0)
        adv = float(row["advance_payment_applied"] or 0.0)
        rem = max(0.0, calc - paid - adv)
        return {
            "total_amount": float(row["total_amount"] or 0.0),
            "paid_amount": paid,
            "advance_payment_applied": adv,
            "calculated_total_amount": calc,
            "remaining_due": rem,
        }

    def _remaining_due_header(self, purchase_id: str) -> float:
        row = self.conn.execute(
            """
            SELECT
                CAST(total_amount AS REAL) AS total_amount,
                CAST(paid_amount AS REAL) AS paid_amount,
                CAST(advance_payment_applied AS REAL) AS advance_payment_applied
            FROM purchases
            WHERE purchase_id = ?
            """,
            (purchase_id,),
        ).fetchone()
        if not row:
            return 0.0
        total = float(row["total_amount"] or 0.0)
        paid = float(row["paid_amount"] or 0.0)
        applied = float(row["advance_payment_applied"] or 0.0)
        remaining = total - paid - applied
        return max(0.0, remaining)

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
        r_pay = self.conn.execute(
            """
            SELECT COALESCE(SUM(CAST(amount AS REAL)), 0.0) AS cleared_paid
            FROM purchase_payments
            WHERE purchase_id = ?
              AND COALESCE(clearing_state, 'posted') = 'cleared'
            """,
            (purchase_id,),
        ).fetchone()
        cleared_paid = float(r_pay["cleared_paid"] if r_pay and "cleared_paid" in r_pay.keys() else 0.0)

        row = self.conn.execute(
            """
            SELECT
              COALESCE(pdt.calculated_total_amount, p.total_amount) AS total_calc,
              COALESCE(p.advance_payment_applied, 0.0) AS adv_applied
            FROM purchases p
            LEFT JOIN purchase_detailed_totals pdt ON pdt.purchase_id = p.purchase_id
            WHERE p.purchase_id = ?
            """,
            (purchase_id,),
        ).fetchone()
        total_calc = float(row["total_calc"] if row and "total_calc" in row.keys() else 0.0)
        adv_applied = float(row["adv_applied"] if row and "adv_applied" in row.keys() else 0.0)

        self.conn.execute("UPDATE purchases SET paid_amount = ? WHERE purchase_id = ?;", (cleared_paid, purchase_id))
        remaining = max(0.0, total_calc - cleared_paid - adv_applied)
        if remaining <= _EPS:
            self.conn.execute("UPDATE purchases SET payment_status = 'paid' WHERE purchase_id = ?;", (purchase_id,))

    def _add(self):
        dlg = PurchaseForm(self.view, vendors=self.vendors, products=self.products)
        if not dlg.exec():
            return
        p = dlg.payload()
        if not p:
            return

        # Check if this was called from print or PDF export button
        should_print_after_save = p.get('_should_print', False)
        should_export_pdf_after_save = p.get('_should_export_pdf', False)

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
                        if method.lower() == "cash":
                            clearing_state = "cleared"
                            cleared_date = ip.get("date") or p["date"]
                        else:
                            clearing_state = "posted"
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
                        if (method or "").lower() == "cash":
                            clearing_state = "cleared"
                            cleared_date = p.get("date")
                        else:
                            clearing_state = "posted"

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
            from jinja2 import Template
            from PySide6.QtCore import QStandardPaths
            import tempfile
            
            # Load the template file
            template_path = "resources/templates/invoices/purchase_invoice.html"
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            full_template_path = os.path.join(project_root, template_path)
            
            with open(full_template_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
            
            # Prepare data for the template
            enriched_data = {"purchase_id": purchase_id}
            
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
            
            # Create Jinja2 template and render
            template = Template(template_content, autoescape=True)
            html_content = template.render(**enriched_data)
            
            # Create temporary HTML file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as temp_html_file:
                temp_html_file.write(html_content)
                temp_html_path = temp_html_file.name
            
            # Use WeasyPrint to convert HTML to PDF, then print
            from weasyprint import HTML, CSS
            from weasyprint.text.fonts import FontConfiguration
            
            # Create PDF in temporary location with proper naming
            import tempfile
            temp_pdf_fd, temp_pdf_path = tempfile.mkstemp(suffix='.pdf', prefix=f'{purchase_id}_')
            os.close(temp_pdf_fd)  # Close the file descriptor
            
            # Convert HTML to PDF with custom CSS for proper margins
            from weasyprint import CSS
            # Define custom CSS to override default margins
            custom_css = CSS(string='''
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
                    box-sizing: border-box !important;
                }
                .header {
                    width: 100% !important;
                }
                table {
                    width: 100% !important;
                }
            ''')
            
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
            from jinja2 import Template
            from PySide6.QtCore import QStandardPaths
            from weasyprint import HTML, CSS
            
            # Load the template file
            template_path = "resources/templates/invoices/purchase_invoice.html"
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            full_template_path = os.path.join(project_root, template_path)
            
            with open(full_template_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
            
            # Prepare data for the template
            enriched_data = {"purchase_id": purchase_id}
            
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
            
            # Create Jinja2 template and render
            template = Template(template_content, autoescape=True)
            html_content = template.render(**enriched_data)
            
            # Determine the desktop path and create PIs subdirectory
            desktop_path = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
            pdfs_dir = os.path.join(desktop_path, "PIs")
            
            # Create the directory if it doesn't exist
            os.makedirs(pdfs_dir, exist_ok=True)
            
            # Construct the file path
            file_name = f"{purchase_id}.pdf"
            file_path = os.path.join(pdfs_dir, file_name)
            
            # Convert HTML to PDF using WeasyPrint with custom CSS for proper margins
            from weasyprint import CSS
            import os
            # Define custom CSS to override default margins
            custom_css = CSS(string='''
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
                    box-sizing: border-box !important;
                }
                .header {
                    width: 100% !important;
                }
                table {
                    width: 100% !important;
                }
            ''')
            
            html_doc = HTML(string=html_content)
            html_doc.write_pdf(file_path, stylesheets=[custom_css])
                
            info(self.view, "Export Successful", f"Invoice exported to: {file_path}")
            
        except ImportError:
            info(self.view, "WeasyPrint Not Available", "Please install WeasyPrint: pip install weasyprint")
        except Exception as e:
            info(self.view, "Error", f"Could not export invoice to PDF: {e}")

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

        dlg = PurchaseReturnForm(self.view, items_for_form)
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
        vendor_display = str(row.get("vendor_name") or vendor_id)

        try:
            from ...vendor.payment_dialog import open_vendor_money_form
            payload = open_vendor_money_form(
                mode="payment",
                vendor_id=vendor_id,
                purchase_id=purchase_id,
                defaults={
                    "list_company_bank_accounts": self._list_company_bank_accounts,
                    "list_vendor_bank_accounts": self._list_vendor_bank_accounts,
                    "list_open_purchases_for_vendor": self._list_open_purchases_for_vendor,
                    "vendor_display": vendor_display,
                },
            )
            if payload:
                try:
                    amt = float(payload.get("amount"))
                except (TypeError, ValueError):
                    info(self.view, "Payment not recorded", "Incomplete form data returned from Vendor dialog.")
                    return

                method = (payload.get("method") or "").strip()
                remaining = self._remaining_due_header(str(payload.get("purchase_id") or purchase_id))
                if method.lower() != "cash" and amt - remaining > _EPS:
                    info(self.view, "Payment not recorded", f"Amount exceeds remaining due ({remaining:.2f}).")
                    return

                try:
                    self.payments.record_payment(
                        purchase_id=str(payload.get("purchase_id") or purchase_id),
                        amount=amt,
                        method=payload.get("method"),
                        bank_account_id=payload.get("bank_account_id"),
                        vendor_bank_account_id=payload.get("vendor_bank_account_id"),
                        instrument_type=payload.get("instrument_type"),
                        instrument_no=payload.get("instrument_no"),
                        instrument_date=payload.get("instrument_date"),
                        deposited_date=payload.get("deposited_date"),
                        cleared_date=payload.get("cleared_date"),
                        clearing_state=payload.get("clearing_state"),
                        ref_no=payload.get("ref_no"),
                        notes=payload.get("notes"),
                        date=payload.get("date") or today_str(),
                        created_by=(self.user["user_id"] if self.user else None),
                        temp_vendor_bank_name=payload.get("temp_vendor_bank_name"),
                        temp_vendor_bank_number=payload.get("temp_vendor_bank_number"),
                    )
                except Exception as e:
                    if OverpayPurchaseError and isinstance(e, OverpayPurchaseError):
                        info(self.view, "Payment not recorded", str(e))
                        return
                    if isinstance(e, (sqlite3.IntegrityError, sqlite3.OperationalError)):
                        info(self.view, "Payment not recorded", f"Could not record payment:\n{e}")
                        return
                    info(self.view, "Payment not recorded", str(e))
                    return

                info(self.view, "Saved", "Payment recorded.")
                self._reload()
                return
        except Exception:
            pass

        dlg = PurchasePaymentDialog(
            self.view,
            current_paid=float(row["paid_amount"]),
            total=float(row["total_amount"]),
        )
        if not dlg.exec():
            return
        amount = dlg.payload()
        if not amount:
            return

        remaining = self._remaining_due_header(purchase_id)
        try:
            amt = float(amount)
        except (TypeError, ValueError):
            info(self.view, "Payment not recorded", "Invalid amount.")
            return
        if amt - remaining > _EPS:
            info(self.view, "Payment not recorded", f"Amount exceeds remaining due ({remaining:.2f}).")
            return

        method = "Cash"
        bank_account_id = None
        vendor_bank_account_id = None
        instrument_type = None
        instrument_no = None
        instrument_date = None
        deposited_date = None
        cleared_date = None
        clearing_state = None
        ref_no = None
        notes = None
        pay_date = today_str()

        try:
            self.payments.record_payment(
                purchase_id=purchase_id,
                amount=amt,
                method=method,
                bank_account_id=bank_account_id,
                vendor_bank_account_id=vendor_bank_account_id,
                instrument_type=instrument_type,
                instrument_no=instrument_no,
                instrument_date=instrument_date,
                deposited_date=deposited_date,
                cleared_date=cleared_date,
                clearing_state=clearing_state,
                ref_no=ref_no,
                notes=notes,
                date=pay_date,
                created_by=(self.user["user_id"] if self.user else None),
                temp_vendor_bank_name=None,
                temp_vendor_bank_number=None,
            )
        except Exception as e:
            if OverpayPurchaseError and isinstance(e, OverpayPurchaseError):
                info(self.view, "Payment not recorded", str(e))
                return
            if isinstance(e, (sqlite3.IntegrityError, sqlite3.OperationalError)):
                info(self.view, "Payment not recorded", f"Could not record payment:\n{e}")
                return
            info(self.view, "Payment not recorded", str(e))
            return

        info(self.view, "Saved", f"Transaction of {float(amount):g} recorded.")
        self._reload()

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
            from ...database.repositories.bank_accounts_repo import BankAccountsRepo
            repo = BankAccountsRepo(self.conn)
            for attr in ("list_accounts", "list", "list_all", "all"):
                if hasattr(repo, attr):
                    rows = list(getattr(repo, attr)())
                    out = []
                    for r in rows:
                        d = dict(r)
                        _id = d.get("id") or d.get("account_id") or d.get("bank_account_id")
                        _name = d.get("name") or d.get("account_name") or d.get("title")
                        if _id is not None and _name is not None:
                            out.append({"id": int(_id), "name": str(_name)})
                    if out:
                        return out
        except Exception:
            pass
        return []

    def _list_vendor_bank_accounts(self, vendor_id: int) -> list[dict]:
        try:
            from ...database.repositories.vendor_bank_accounts_repo import VendorBankAccountsRepo
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
