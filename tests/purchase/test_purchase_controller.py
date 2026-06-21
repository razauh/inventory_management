import pytest
from unittest.mock import MagicMock, patch
import sqlite3
import sys
from pathlib import Path
from types import ModuleType
from inventory_management.modules.purchase.controller import PurchaseController
from inventory_management.database.repositories.purchases_repo import PurchasesRepo

class StubConn:
    def __init__(self, real_conn):
        self.real_conn = real_conn
        self.row_factory = real_conn.row_factory

    def execute(self, sql, parameters=()):
        if isinstance(sql, str) and sql.strip().upper() in ("BEGIN", "COMMIT", "ROLLBACK"):
            return
        return self.real_conn.execute(sql, parameters)
    
    def commit(self):
        pass
        
    def rollback(self):
        pass
        
    def __getattr__(self, name):
        return getattr(self.real_conn, name)

@pytest.fixture
def controller(conn, current_user):
    """Fixture for PurchaseController."""
    conn.row_factory = sqlite3.Row
    return PurchaseController(StubConn(conn), current_user)

def test_controller_add_flow(controller, monkeypatch, ids):
    """Test adding a new purchase via controller."""
    # Mock PurchaseForm to return a valid payload immediately
    payload = {
        "vendor_id": ids["vendor_id"],
        "date": "2023-01-01",
        "items": [
            {
                "product_id": ids["prod_A"],
                "uom_id": ids["uom_piece"],
                "quantity": 5,
                "purchase_price": 10.0,
                "sale_price": 15.0,
                "item_discount": 0.0
            }
        ],
        "total_amount": 50.0,
        "order_discount": 0.0,
        "notes": "Test PO",
        "initial_payment": None
    }
    
    # We need to mock the dialog class used in _add
    with patch("inventory_management.modules.purchase.controller.PurchaseForm") as MockForm:
        instance = MockForm.return_value
        instance.exec.return_value = True  # Accepted
        instance.payload.return_value = payload
        
        # Call _add
        controller._add()
        controller._handle_add_dialog_accept()
        
        # Verify DB insertion
        repo = PurchasesRepo(controller.conn)
        purchases = repo.list_purchases()
        assert len(purchases) == 1
        assert purchases[0]["vendor_id"] == ids["vendor_id"]
        assert float(purchases[0]["total_amount"]) == 50.0

def test_controller_delete_not_implemented(controller, monkeypatch):
    """DB-INT-004: Verify delete is not implemented or exposed."""
    assert not hasattr(controller.view, "btn_del")
    assert not hasattr(controller, "_delete")

def test_auto_apply_vendor_credit(controller, ids, conn):
    """DB-INT-006: Test auto-application of vendor credit."""
    # 1. Create a vendor credit (advance)
    conn.execute("""
        INSERT INTO vendor_advances (vendor_id, amount, source_type, notes)
        VALUES (?, ?, 'deposit', 'Test Credit')
    """, (ids["vendor_id"], 100.0))
    
    # 2. Create a purchase for 50.0
    payload = {
        "vendor_id": ids["vendor_id"],
        "date": "2023-01-01",
        "items": [
            {
                "product_id": ids["prod_A"],
                "uom_id": ids["uom_piece"],
                "quantity": 5,
                "purchase_price": 10.0,
                "sale_price": 15.0,
                "item_discount": 0.0
            }
        ],
        "total_amount": 50.0,
        "order_discount": 0.0,
        "notes": "PO with Credit",
        "initial_payment": None
    }
    
    with patch("inventory_management.modules.purchase.controller.PurchaseForm") as MockForm:
        instance = MockForm.return_value
        instance.exec.return_value = True
        instance.payload.return_value = payload
        
        controller._add()
        controller._handle_add_dialog_accept()
        
    # 3. Verify purchase is paid (via credit)
    repo = PurchasesRepo(controller.conn)
    purchases = repo.list_purchases()
    assert len(purchases) == 1
    po = purchases[0]
    
    # Should be fully paid
    assert po["payment_status"] == "paid"
    assert float(po["advance_payment_applied"]) == 50.0
    
    # 4. Verify vendor credit reduced
    remaining_credit = controller.vadv.get_balance(ids["vendor_id"])
    assert remaining_credit == 50.0  # 100 - 50


def test_vendor_credit_can_be_skipped_for_new_purchase(controller, ids, conn, monkeypatch):
    """Available vendor credit is not applied when user skips it."""
    from PySide6.QtWidgets import QMessageBox

    conn.execute("""
        INSERT INTO vendor_advances (vendor_id, amount, source_type, notes)
        VALUES (?, ?, 'deposit', 'Test Credit')
    """, (ids["vendor_id"], 100.0))
    monkeypatch.setattr(
        "inventory_management.modules.purchase.controller.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.No,
    )

    payload = {
        "vendor_id": ids["vendor_id"],
        "date": "2023-01-01",
        "items": [
            {
                "product_id": ids["prod_A"],
                "uom_id": ids["uom_piece"],
                "quantity": 5,
                "purchase_price": 10.0,
                "sale_price": 15.0,
                "item_discount": 0.0
            }
        ],
        "total_amount": 50.0,
        "order_discount": 0.0,
        "notes": "PO with skipped credit",
        "initial_payment": None
    }

    with patch("inventory_management.modules.purchase.controller.PurchaseForm") as MockForm:
        instance = MockForm.return_value
        instance.payload.return_value = payload

        controller._add()
        controller._handle_add_dialog_accept()

    repo = PurchasesRepo(controller.conn)
    po = repo.list_purchases()[0]
    assert po["payment_status"] == "unpaid"
    assert float(po["advance_payment_applied"]) == 0.0
    assert controller.vadv.get_balance(ids["vendor_id"]) == 100.0


def _purchase_row(purchase_id="PO-SEARCH-1", vendor_name="Vendor Search"):
    return {
        "purchase_id": purchase_id,
        "date": "2026-06-16",
        "vendor_id": 1,
        "vendor_name": vendor_name,
        "total_amount": 100.0,
        "returned_value": 0.0,
        "calculated_total_amount": 100.0,
        "order_discount": 0.0,
        "payment_status": "unpaid",
        "paid_amount": 0.0,
        "advance_payment_applied": 0.0,
        "remaining_due": 100.0,
        "notes": None,
    }


def test_perform_search_uses_repo_query_path(controller):
    controller.repo.search_purchases = MagicMock(return_value=[_purchase_row()])
    controller.view.search.setText("vendor")

    controller._perform_search()

    controller.repo.search_purchases.assert_called_once_with(
        "vendor",
        search_field="all",
    )
    assert controller.base.rowCount() == 1


def test_reload_defers_purchase_detail_snapshot(controller):
    row = _purchase_row(purchase_id="PO-DEFER-1")
    controller.repo.list_purchases = MagicMock(return_value=[row])
    controller.repo.get_purchase_detail_snapshot = MagicMock(
        side_effect=AssertionError("detail snapshot should be deferred")
    )

    controller._reload()

    controller.repo.get_purchase_detail_snapshot.assert_not_called()
    assert controller.view.details.lab_id.text() == "PO-DEFER-1"
    assert controller.view.items.model.rowCount() == 0


def test_sync_details_uses_snapshot_once_per_selected_purchase(controller):
    row = _purchase_row(purchase_id="PO-SNAPSHOT-1")
    detail_row = dict(row)
    detail_row["returned_value"] = 5.0
    detail_row["calculated_total_amount"] = 95.0
    detail_row["remaining_due"] = 95.0

    controller.repo.list_purchases = MagicMock(return_value=[row])
    controller.repo.get_purchase_detail_snapshot = MagicMock(
        return_value={
            "row": detail_row,
            "items": [
                {
                    "item_id": 1,
                    "purchase_id": "PO-SNAPSHOT-1",
                    "product_id": 2,
                    "product_name": "Widget",
                    "quantity": 1.0,
                    "unit_name": "Piece",
                    "uom_id": 1,
                    "purchase_price": 95.0,
                    "sale_price": 120.0,
                    "item_discount": 0.0,
                }
            ],
            "payment_summary": {
                "method": "Cash",
                "amount": 0.0,
                "status": "posted",
                "overpayment": 0.0,
                "counterparty_label": "Vendor",
            },
        }
    )

    controller._reload()
    controller._sync_details()
    controller._run_deferred_detail_sync()

    controller.repo.get_purchase_detail_snapshot.assert_called_once_with("PO-SNAPSHOT-1")
    assert controller.view.details.lab_id.text() == "PO-SNAPSHOT-1"


def test_purchase_invoice_render_maps_purchase_price_to_template_fields(controller):
    controller.repo.get_header_with_vendor = MagicMock(return_value={
        "purchase_id": "PO-PRINT-1",
        "date": "2026-06-21",
        "vendor_name": "Vendor Print",
        "vendor_contact_info": "vendor@example.test",
        "vendor_address": "Vendor Road",
        "order_discount": 0.0,
        "total_amount": 190.0,
        "paid_amount": 0.0,
        "advance_payment_applied": 0.0,
        "payment_status": "unpaid",
    })
    controller.repo.list_items = MagicMock(return_value=[
        {
            "item_id": 1,
            "purchase_id": "PO-PRINT-1",
            "product_id": 2,
            "product_name": "Widget",
            "quantity": 2.0,
            "unit_name": "Piece",
            "uom_id": 1,
            "purchase_price": 95.0,
            "sale_price": 120.0,
            "item_discount": 0.0,
        }
    ])
    controller.payments.list_payments = MagicMock(return_value=[])

    html = controller._generate_invoice_html_content("PO-PRINT-1")

    assert "PO-PRINT-1" in html
    assert "Widget" in html
    assert "Piece" in html
    assert "95.00" in html
    assert "190.00" in html


def test_print_purchase_invoice_opens_preview(monkeypatch, controller):
    class FakeHTML:
        def __init__(self, *, string):
            self.string = string

        def write_pdf(self, path, stylesheets=None):
            Path(path).write_bytes(b"%PDF-1.4\n%%EOF\n")

    class FakeCSS:
        def __init__(self, *args, **kwargs):
            pass

    fake_weasyprint = ModuleType("weasyprint")
    fake_weasyprint.HTML = FakeHTML
    fake_weasyprint.CSS = FakeCSS
    monkeypatch.setitem(sys.modules, "weasyprint", fake_weasyprint)

    shown = {}
    monkeypatch.setattr(
        "inventory_management.modules.purchase.controller.show_invoice_preview",
        lambda parent, path, title: shown.update({"path": path, "title": title}),
    )
    controller._generate_invoice_html_content = MagicMock(return_value="<html>PO</html>")

    controller._print_purchase_invoice("PO-PREVIEW-1")

    assert shown["title"] == "Purchase Invoice PO-PREVIEW-1"
    assert Path(shown["path"]).exists()
    assert Path(shown["path"]).name == "PO-PREVIEW-1.pdf"
