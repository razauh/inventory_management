from types import SimpleNamespace

from inventory_management.modules.purchase.form import PurchaseForm


class _Vendors:
    def list_vendors(self):
        return [SimpleNamespace(vendor_id=7, name="Vendor")]


class _Products:
    def list_products(self):
        return [SimpleNamespace(product_id=11, name="Product")]

    def get_base_uom(self, product_id):
        return {"uom_id": 3}

    def list_uoms(self):
        return [{"uom_id": 3}]


def test_edit_payload_preserves_loaded_discounts_and_new_rows_default_to_zero(
    qtbot, monkeypatch
):
    monkeypatch.setattr(PurchaseForm, "_reload_company_accounts", lambda self: None)
    monkeypatch.setattr(PurchaseForm, "_reload_vendor_accounts", lambda self: None)
    monkeypatch.setattr(PurchaseForm, "_update_vendor_advance_display", lambda self: None)

    form = PurchaseForm(
        vendors=_Vendors(),
        products=_Products(),
        initial={
            "vendor_id": 7,
            "date": "2026-06-10",
            "order_discount": 12.5,
            "notes": "original",
            "items": [
                {
                    "item_id": 23,
                    "product_id": 11,
                    "uom_id": 3,
                    "quantity": 2,
                    "purchase_price": 50,
                    "sale_price": 60,
                    "item_discount": 4.25,
                }
            ],
        },
    )
    qtbot.addWidget(form)

    form.txt_notes.setText("edited note")
    form._add_row()
    new_product = form.tbl.cellWidget(1, 1)
    new_product.setCurrentIndex(new_product.findData(11))
    form.tbl.item(1, 2).setText("1")
    form.tbl.item(1, 3).setText("20")
    form.tbl.item(1, 4).setText("25")

    payload = form.get_payload()

    assert payload["order_discount"] == 12.5
    assert payload["items"][0]["item_id"] == 23
    assert payload["items"][0]["item_discount"] == 4.25
    assert payload["items"][1]["item_id"] is None
    assert payload["items"][1]["item_discount"] == 0.0

    valid, errors, validated_items = form._validate_items()
    assert valid, errors
    assert [item["item_discount"] for item in validated_items] == [4.25, 0.0]
