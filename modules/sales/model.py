from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex
from ...utils.helpers import fmt_money

class SalesTableModel(QAbstractTableModel):
    HEADERS = ["ID", "Date", "Customer", "Total", "Paid", "Status"]

    def __init__(self, rows: list[dict]):
        super().__init__(); self._rows = rows

    def rowCount(self, p=QModelIndex()): return len(self._rows)
    def columnCount(self, p=QModelIndex()): return len(self.HEADERS)

    def data(self, idx, role=Qt.DisplayRole):
        if not idx.isValid(): return None
        r = self._rows[idx.row()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            # Fields (with safe defaults)
            sale_id = r.get("sale_id")
            date = r.get("date")
            customer_name = r.get("customer_name")
            total_amount = float(r.get("total_amount", 0.0))

            # NEW: consider credit applied when computing paid & status
            paid_amount = float(r.get("paid_amount", 0.0))
            adv_applied = float(r.get("advance_payment_applied", 0.0))  # repo/query should now provide this
            paid_total = paid_amount + adv_applied

            # Status: prefer existing value when it's clearly a quotation marker (e.g., '—' or quotation statuses)
            existing_status = (r.get("payment_status") or "").strip().lower()
            quotation_marker = existing_status in {"—", "draft", "sent", "accepted", "expired", "cancelled"}
            if quotation_marker:
                status = r.get("payment_status") or "—"
            else:
                EPS = 1e-9
                if paid_total + EPS >= total_amount and total_amount > 0:
                    status = "paid"
                elif paid_total > EPS:
                    status = "partial"
                else:
                    status = "unpaid"

            m = [
                sale_id,
                date,
                customer_name,
                fmt_money(total_amount),
                fmt_money(paid_total),   # NEW: paid = paid_amount + advance_payment_applied
                status,                  # NEW: status based on the new paid_total
            ]
            return m[idx.column()]
        return None

    def headerData(self, s, o, role=Qt.DisplayRole):
        return self.HEADERS[s] if o==Qt.Horizontal and role==Qt.DisplayRole else super().headerData(s,o,role)

    def at(self, row: int) -> dict: return self._rows[row]
    def replace(self, rows: list[dict]):
        self.beginResetModel(); self._rows = rows; self.endResetModel()


class SaleItemsModel(QAbstractTableModel):
    HEADERS = ["#", "Product", "Qty", "Unit Price", "Discount", "Line Total"]
    def __init__(self, rows: list[dict]): super().__init__(); self._rows = rows
    def rowCount(self, p=QModelIndex()): return len(self._rows)
    def columnCount(self, p=QModelIndex()): return len(self.HEADERS)
    def data(self, idx, role=Qt.DisplayRole):
        if not idx.isValid(): return None
        r = self._rows[idx.row()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            lt = float(r["quantity"]) * (float(r["unit_price"]) - float(r["item_discount"]))
            m = [r["item_id"], r["product_name"], f'{float(r["quantity"]):g}',
                 fmt_money(r["unit_price"]), fmt_money(r["item_discount"]), fmt_money(lt)]
            return m[idx.column()]
        return None
    def headerData(self, s, o, role=Qt.DisplayRole):
        return self.HEADERS[s] if o==Qt.Horizontal and role==Qt.DisplayRole else super().headerData(s,o,role)
    def replace(self, rows: list[dict]): self.beginResetModel(); self._rows=rows; self.endResetModel()
