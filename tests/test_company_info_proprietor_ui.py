from PySide6.QtCore import Qt

from inventory_management.modules.company_info.form import ProprietorForm
from inventory_management.modules.company_info.model import CompanyProprietorsTableModel
from inventory_management.modules.company_info.view import CompanyInfoView


def test_company_info_view_has_proprietor_controls(qtbot):
    view = CompanyInfoView()
    qtbot.addWidget(view)

    assert view.btn_add_proprietor.text() == "Add Proprietor"
    assert view.btn_edit_proprietor.text() == "Edit Proprietor"
    assert view.btn_delete_proprietor.text() == "Delete Proprietor"


def test_proprietor_form_payload_allows_phone_and_order(qtbot):
    form = ProprietorForm()
    qtbot.addWidget(form)
    form.name.setText("Owner A")
    form.phone.setText("111")
    form.sort_order.setValue(2)

    form.accept()

    assert form.payload() == {
        "name": "Owner A",
        "phone": "111",
        "sort_order": 2,
        "is_active": 1,
    }


def test_proprietor_model_exposes_rows():
    model = CompanyProprietorsTableModel(
        [{"proprietor_id": 7, "name": "Owner A", "phone": "111", "sort_order": 1, "is_active": 1}]
    )

    assert model.data(model.index(0, 0), Qt.DisplayRole) == "Owner A"
    assert model.data(model.index(0, 1), Qt.DisplayRole) == "111"
    assert model.data(model.index(0, 0), Qt.UserRole) == 7
