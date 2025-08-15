from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QSortFilterProxyModel, QRegularExpression
import sqlite3, datetime

from ..base_module import BaseModule
from .view import SalesView
from .model import SalesTableModel
from .form import SaleForm
from .return_form import SaleReturnForm
from ...database.repositories.sales_repo import SalesRepo, SaleHeader, SaleItem
from ...database.repositories.customers_repo import CustomersRepo
from ...database.repositories.products_repo import ProductsRepo
from ...utils.ui_helpers import info
from ...utils.helpers import today_str

def new_sale_id(conn: sqlite3.Connection, date_str: str) -> str:
    d = date_str.replace("-", "")
    prefix = f"SO{d}-"
    row = conn.execute("SELECT MAX(sale_id) AS m FROM sales WHERE sale_id LIKE ?", (prefix+"%",)).fetchone()
    last = int(row["m"].split("-")[-1]) if row and row["m"] else 0
    return f"{prefix}{last+1:04d}"

class SalesController(BaseModule):
    def __init__(self, conn: sqlite3.Connection, current_user: dict | None):
        self.conn = conn; self.user = current_user
        self.view = SalesView()
        self.repo = SalesRepo(conn); self.customers = CustomersRepo(conn); self.products = ProductsRepo(conn)
        self._wire(); self._reload()

    def get_widget(self) -> QWidget: return self.view

    def _wire(self):
        self.view.btn_add.clicked.connect(self._add)
        self.view.btn_edit.clicked.connect(self._edit)
        # self.view.btn_del.clicked.connect(self._delete)
        self.view.btn_return.clicked.connect(self._return)
        self.view.search.textChanged.connect(self._apply_filter)

    def _build_model(self):
        rows = self.repo.list_sales()
        self.base = SalesTableModel(rows)
        self.proxy = QSortFilterProxyModel(self.view)
        self.proxy.setSourceModel(self.base); self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.view.tbl.setModel(self.proxy); self.view.tbl.resizeColumnsToContents()
        self.view.tbl.selectionModel().selectionChanged.connect(self._sync_details)

    def _reload(self):
        self._build_model()
        if self.proxy.rowCount() > 0: self.view.tbl.selectRow(0)
        self._sync_details()

    def _apply_filter(self, text: str):
        self.proxy.setFilterRegularExpression(QRegularExpression(text))

    def _selected_row(self) -> dict | None:
        idxs = self.view.tbl.selectionModel().selectedRows()
        if not idxs: return None
        src = self.proxy.mapToSource(idxs[0])
        return self.base.at(src.row())

    def _sync_details(self, *args):
        r = self._selected_row()
        if r:
            items = self.repo.list_items(r["sale_id"])
            line_disc = sum(float(it["quantity"]) * float(it["item_discount"]) for it in items)
            r = dict(r)
            r["overall_discount"] = float(r["order_discount"]) + line_disc
            self.view.items.set_rows(items)
        else:
            self.view.items.set_rows([])
        self.view.details.set_data(r)

    # ---- CRUD ----
    def _add(self):
        dlg = SaleForm(self.view, customers=self.customers, products=self.products)
        if not dlg.exec(): return
        p = dlg.payload()
        if not p: return
        sid = new_sale_id(self.conn, p["date"])
        paid = float(p.get("initial_payment") or 0.0)
        status = "paid" if paid >= p["total_amount"] else ("partial" if paid > 0 else "unpaid")
        notes = p["notes"]
        if paid > 0:
            tag = f"[Init payment {paid:g} via {p.get('initial_method','Cash')}]"
            notes = f"{notes} {tag}" if notes else tag

        h = SaleHeader(
            sale_id=sid, customer_id=p["customer_id"], date=p["date"],
            total_amount=p["total_amount"], order_discount=p["order_discount"],
            payment_status=status, paid_amount=paid, advance_payment_applied=0.0,
            notes=notes, created_by=(self.user["user_id"] if self.user else None)
        )
        items = [SaleItem(None, sid, it["product_id"], it["quantity"], it["uom_id"],
                          it["unit_price"], it["item_discount"]) for it in p["items"]]
        self.repo.create_sale(h, items)
        info(self.view, "Saved", f"Sale {sid} created.")
        self._reload()

    def _edit(self):
        r = self._selected_row()
        if not r: info(self.view,"Select","Select a sale to edit."); return
        items = self.repo.list_items(r["sale_id"])
        init = {
            "customer_id": r["customer_id"], "date": r["date"],
            "order_discount": r["order_discount"], "notes": r.get("notes"),
            "items": [{"product_id":it["product_id"],"uom_id":it["uom_id"],"quantity":it["quantity"],
                       "unit_price":it["unit_price"],"item_discount":it["item_discount"]} for it in items]
        }
        dlg = SaleForm(self.view, customers=self.customers, products=self.products, initial=init)
        if not dlg.exec(): return
        p = dlg.payload()
        if not p: return
        sid = r["sale_id"]
        h = SaleHeader(
            sale_id=sid, customer_id=p["customer_id"], date=p["date"],
            total_amount=p["total_amount"], order_discount=p["order_discount"],
            payment_status=r["payment_status"], paid_amount=r["paid_amount"],
            advance_payment_applied=0.0, notes=p["notes"],
            created_by=(self.user["user_id"] if self.user else None)
        )
        items = [SaleItem(None, sid, it["product_id"], it["quantity"], it["uom_id"],
                          it["unit_price"], it["item_discount"]) for it in p["items"]]
        self.repo.update_sale(h, items)
        info(self.view, "Saved", f"Sale {sid} updated."); self._reload()

    def _delete(self):
        r = self._selected_row()
        if not r: info(self.view,"Select","Select a sale to delete."); return
        self.repo.delete_sale(r["sale_id"]); info(self.view,"Deleted",f"Sale {r['sale_id']} removed."); self._reload()

    # ---- Returns ----
    def _return(self):
        # If a sale is already selected in the main table, open the return dialog directly for that SO.
        selected = self._selected_row()
        if selected:
            dlg = SaleReturnForm(self.view, repo=self.repo, sale_id=selected["sale_id"])
        else:
            # Fallback to legacy search-first dialog
            dlg = SaleReturnForm(self.view, repo=self.repo)

        if not dlg.exec():
            return
        p = dlg.payload()
        if not p:
            return

        sid = p["sale_id"]
        items = self.repo.list_items(sid)
        by_id = {it["item_id"]: it for it in items}
        lines = []
        for ln in p["lines"]:
            it = by_id.get(ln["item_id"])
            if not it:
                continue
            lines.append({
                "item_id": it["item_id"],
                "product_id": it["product_id"],
                "uom_id": it["uom_id"],
                "qty_return": float(ln["qty_return"]),
            })

        # inventory
        self.repo.record_return(
            sid=sid,
            date=today_str(),
            created_by=(self.user["user_id"] if self.user else None),
            lines=lines,
            notes="[Return]"
        )

        # money: compute capped cash refund and possible credit
        refund_amount = float(p.get("refund_amount") or 0.0)  # already includes order-discount proration
        hdr = self.repo.get_header(sid) or {}
        total_before = float(hdr.get("total_amount") or 0.0)
        paid_before = float(hdr.get("paid_amount") or 0.0)

        cash_refund = 0.0
        credit_part = refund_amount

        if p.get("refund_now"):
            cash_refund = min(refund_amount, paid_before)
            credit_part = max(0.0, refund_amount - cash_refund)
            if cash_refund > 0:
                self.repo.apply_refund(sid=sid, amount=cash_refund)

        # Reduce outstanding balance (never below zero)
        hdr2 = self.repo.get_header(sid) or {}
        paid_after = float(hdr2.get("paid_amount") or 0.0)
        balance_before = max(0.0, total_before - paid_after)
        apply_to_balance = min(credit_part, balance_before)
        new_total = max(0.0, total_before - apply_to_balance)

        with self.conn:
            self.conn.execute("UPDATE sales SET total_amount=? WHERE sale_id=?", (new_total, sid))
            # recompute status from paid_after vs new_total
            status = "paid" if paid_after >= new_total else ("partial" if paid_after > 0 else "unpaid")
            self.conn.execute("UPDATE sales SET payment_status=? WHERE sale_id=?", (status, sid))

            leftover_credit = max(0.0, credit_part - apply_to_balance)
            if leftover_credit > 0:
                self.conn.execute(
                    "UPDATE sales SET notes = COALESCE(notes,'') || ? WHERE sale_id=?",
                    (f" [Credit memo {leftover_credit:g}]", sid)
                )

        # annotate if the whole order was returned (all sold qty fully returned)
        all_back = all(
            (float(next((l["qty_return"] for l in p["lines"] if l["item_id"] == it["item_id"]), 0.0)) >= float(it["quantity"]))
            for it in items
        )
        if all_back:
            with self.conn:
                self.conn.execute(
                    "UPDATE sales SET notes = COALESCE(notes,'') || ' [Full return]' WHERE sale_id=?",
                    (sid,)
                )

        # friendly summary message
        if p.get("refund_now"):
            if credit_part > 0:
                info(self.view, "Saved",
                     f"Return recorded. Refunded {cash_refund:g} (capped by paid {paid_before:g}); "
                     f"{credit_part:g} applied to balance/credit.")
            else:
                info(self.view, "Saved", f"Return recorded. Refunded {cash_refund:g}.")
        else:
            info(self.view, "Saved", f"Return recorded. {refund_amount:g} applied to balance/credit.")

        self._reload()
    