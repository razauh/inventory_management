from PySide6.QtCore import QAbstractTableModel, Qt, QModelIndex
from ...utils.helpers import fmt_money

class SalesTableModel(QAbstractTableModel):
    QUOTATION_STATUS_LABELS = {
        "draft": "Draft",
        "sent": "Sent",
        "accepted": "Accepted",
        "expired": "Expired",
        "cancelled": "Cancelled",
    }

    def __init__(self, rows: list, doc_type: str = "sale"):
        super().__init__()
        self._rows = rows
        self._row_by_sale_id = self._build_row_index()
        self._doc_type = doc_type
        self._update_headers()

    def _build_row_index(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for row_index, row in enumerate(self._rows):
            try:
                sale_id = str(row.get("sale_id") or "")
            except AttributeError:
                try:
                    sale_id = str(row["sale_id"] or "")
                except (KeyError, IndexError, TypeError):
                    sale_id = ""
            if sale_id:
                out[sale_id] = row_index
        return out

    def _update_headers(self):
        if self._doc_type == "quotation":
            self.HEADERS = ["ID", "Date", "Customer", "Total", "Status"]
        else:  # sale
            self.HEADERS = ["ID", "Date", "Customer", "Total", "Paid", "Status"]

    def set_doc_type(self, doc_type: str):
        """Update document type and refresh headers."""
        if self._doc_type != doc_type:
            self._doc_type = doc_type
            self._update_headers()
            self.headerDataChanged.emit(Qt.Horizontal, 0, len(self.HEADERS) - 1)

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r = self._rows[index.row()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            c = index.column()
            # Mapping depends on document type
            if self._doc_type == "quotation":
                quotation_status = str(r.get("quotation_status") or "").lower()
                mapping = [
                    r["sale_id"],
                    r["date"],
                    r["customer_name"],
                    fmt_money(r["total_amount"]),
                    self.QUOTATION_STATUS_LABELS.get(
                        quotation_status,
                        quotation_status.replace("_", " ").title(),
                    ),
                ]
            else:  # sale
                mapping = [
                    r["sale_id"],
                    r["date"],
                    r["customer_name"],
                    fmt_money(r["total_amount"]),
                    fmt_money(r["paid_amount"]),
                    r["payment_status"]
                ]
            return mapping[c] if c < len(mapping) else None
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section] if section < len(self.HEADERS) else None
        return super().headerData(section, orientation, role)

    def at(self, row: int) -> dict:
        return self._rows[row]

    def row_for_sale_id(self, sale_id: str | None) -> int | None:
        sale_id = str(sale_id or "")
        if not sale_id:
            return None
        return self._row_by_sale_id.get(sale_id)

    def replace(self, rows: list):
        self.beginResetModel()
        self._rows = rows
        self._row_by_sale_id = self._build_row_index()
        self.endResetModel()


class SaleItemsModel(QAbstractTableModel):
    HEADERS = ["#", "Product", "Qty", "Unit Price", "Discount", "Line Total"]
    
    def __init__(self, rows: list): 
        super().__init__()
        self._rows = rows
        
    def rowCount(self, parent=QModelIndex()): 
        return len(self._rows)
        
    def columnCount(self, parent=QModelIndex()): 
        return len(self.HEADERS)
        
    def data(self, idx, role=Qt.DisplayRole):
        if not idx.isValid(): 
            return None
        r = self._rows[idx.row()]
        if role in (Qt.DisplayRole, Qt.EditRole):
            lt = float(r["quantity"]) * (float(r["unit_price"]) - float(r["item_discount"]))
            m = [r["item_id"], r["product_name"], f'{float(r["quantity"]):g}',
                 fmt_money(r["unit_price"]), fmt_money(r["item_discount"]), fmt_money(lt)]
            return m[idx.column()]
        return None
        
    def headerData(self, s, o, role=Qt.DisplayRole):
        return self.HEADERS[s] if o==Qt.Horizontal and role==Qt.DisplayRole else super().headerData(s,o,role)
        
    def replace(self, rows: list): 
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
