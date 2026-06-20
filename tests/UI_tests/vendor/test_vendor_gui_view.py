from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from inventory_management.modules.vendor.model import VendorBankAccountsTableModel, VendorsTableModel

from .conftest import account_text, select_account_row, select_vendor_by_name, table_text, type_search


def test_vendor_view_initial_state_has_toolbar_search_tables_pager_and_selection(vendor_controller):
    view = vendor_controller.view

    assert view.btn_add.text() == "Add Vendor"
    assert view.btn_import.text() == "Import Vendors"
    assert view.btn_edit.text() == "Edit Vendor"
    assert view.btn_apply_advance.text() == "Record Advance…"
    assert view.btn_history.text() == "Vendor History"
    assert view.search.placeholderText() == "Search vendors (name, id, contact, address)…"
    assert view.lbl_page.text() == "Page 1 / 2"
    assert "Showing 100 of 125 vendor(s)" == view.list_status.text()
    assert not view.btn_prev_page.isEnabled()
    assert view.btn_next_page.isEnabled()
    assert view.table.model().rowCount() == 100
    assert [view.table.model().headerData(i, Qt.Horizontal, Qt.DisplayRole) for i in range(4)] == VendorsTableModel.HEADERS
    assert [view.accounts_table.model().headerData(i, Qt.Horizontal, Qt.DisplayRole) for i in range(8)] == VendorBankAccountsTableModel.HEADERS
    assert view.btn_add.isEnabled()
    assert view.btn_import.isEnabled()
    assert view.btn_edit.isEnabled()
    assert view.btn_apply_advance.isEnabled()
    assert view.btn_history.isEnabled()


@pytest.mark.parametrize(
    ("name", "contact", "address", "advance"),
    [
        ("No Account Vendor 500", "nocontact@example.test", "-", "0.00"),
        ("Primary Account Vendor", "primary phone 111", "North Market Road", "0.00"),
        ("Advance Vendor", "advance phone 444", "Credit Avenue", "250.00"),
        ("Long Notes Vendor", "Long contact text", "Long address text", "0.00"),
    ],
)
def test_details_panel_updates_for_vendor_selection_permutations(qtbot, vendor_controller, name, contact, address, advance):
    view = vendor_controller.view

    select_vendor_by_name(qtbot, vendor_controller, name)

    assert view.details.lab_id.text().startswith("Vendor #")
    assert view.details.lab_name.text() == name
    assert contact in view.details.lab_contact.text()
    assert address in view.details.lab_address.text()
    assert view.details.lblAvailableAdvanceValue.text() == advance


@pytest.mark.parametrize(
    ("name", "expected_rows", "first_label", "active_text"),
    [
        ("No Account Vendor 500", 0, "No account selected", "-"),
        ("Primary Account Vendor", 1, "Primary AP", "Yes"),
        ("Multi Account Vendor", 2, "Main", "Yes"),
        ("Inactive Account Vendor", 1, "Inactive", "No"),
    ],
)
def test_accounts_panel_updates_for_account_permutations(qtbot, vendor_controller, name, expected_rows, first_label, active_text):
    view = vendor_controller.view

    select_vendor_by_name(qtbot, vendor_controller, name)

    assert view.accounts_table.model().rowCount() == expected_rows
    if expected_rows == 0:
        assert view.lblAccLabel.text() == first_label
        assert view.btn_acc_edit.isEnabled() is False
        return

    select_account_row(qtbot, view, 0)
    assert account_text(view, 0, 1) == first_label
    assert view.lblAccLabel.text() == first_label
    assert view.lblAccActive.text() == active_text
    assert view.btn_acc_edit.isEnabled()


def test_vendor_and_account_table_render_masked_account_data(qtbot, vendor_controller):
    view = vendor_controller.view

    select_vendor_by_name(qtbot, vendor_controller, "Primary Account Vendor")
    select_account_row(qtbot, view, 0)

    assert table_text(view, 0, 1) == "Primary Account Vendor"
    assert account_text(view, 0, 1) == "Primary AP"
    assert account_text(view, 0, 3).endswith("4444")
    assert "111122223333" not in account_text(view, 0, 3)
    assert account_text(view, 0, 4).endswith("456702")
    assert account_text(view, 0, 6) == "Yes"
    assert account_text(view, 0, 7) == "Yes"


def test_empty_search_clears_details_and_accounts(qtbot, vendor_controller):
    view = vendor_controller.view

    type_search(qtbot, vendor_controller, "zz-no-vendor", expected_total=0)

    assert view.table.model().rowCount() == 0
    assert view.details.lab_id.text() == "No vendor selected"
    assert view.accounts_table.model().rowCount() == 0
    assert view.list_status.text() == "No vendors match this search."
