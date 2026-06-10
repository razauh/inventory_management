import pytest

from inventory_management.database.repositories.purchases_repo import (
    PurchaseHeader,
    PurchaseItem,
    PurchasesRepo,
)


def _header(ids, purchase_id="PO-EDIT-RETURN"):
    return PurchaseHeader(
        purchase_id=purchase_id,
        vendor_id=ids["vendor_id"],
        date="2023-01-01",
        total_amount=0.0,
        order_discount=0.0,
        payment_status="unpaid",
        paid_amount=0.0,
        advance_payment_applied=0.0,
        notes="Test",
        created_by=ids["user_ops"],
    )


def _create_returned_purchase(conn, ids):
    repo = PurchasesRepo(conn)
    header = _header(ids)
    repo.create_purchase(
        header,
        [
            PurchaseItem(None, header.purchase_id, ids["prod_A"], 10.0, ids["uom_piece"], 10.0, 15.0, 0.0),
            PurchaseItem(None, header.purchase_id, ids["prod_B"], 4.0, ids["uom_piece"], 20.0, 25.0, 0.0),
        ],
    )
    items = repo.list_items(header.purchase_id)
    returned_item_id = int(items[0]["item_id"])
    unaffected_item_id = int(items[1]["item_id"])
    repo.record_return(
        pid=header.purchase_id,
        date="2023-01-02",
        created_by=ids["user_ops"],
        lines=[{"item_id": returned_item_id, "qty_return": 3.0}],
        notes="Return",
    )
    return repo, header, returned_item_id, unaffected_item_id


def test_edit_preserves_returned_item_identity_and_return_totals(conn, ids):
    repo, header, returned_item_id, unaffected_item_id = _create_returned_purchase(conn, ids)

    repo.update_purchase(
        header,
        [
            PurchaseItem(returned_item_id, header.purchase_id, ids["prod_A"], 8.0, ids["uom_piece"], 10.0, 15.0, 0.0),
            PurchaseItem(None, header.purchase_id, ids["prod_B"], 2.0, ids["uom_piece"], 20.0, 25.0, 0.0),
        ],
    )

    item_ids = {int(row["item_id"]) for row in repo.list_items(header.purchase_id)}
    assert returned_item_id in item_ids
    assert unaffected_item_id not in item_ids
    assert repo.purchase_return_totals(header.purchase_id) == {"qty": 3.0, "value": 30.0}
    assert repo.get_returnable_map(header.purchase_id)[returned_item_id] == 5.0
    return_txn = conn.execute(
        "SELECT reference_item_id FROM inventory_transactions WHERE transaction_type='purchase_return' AND reference_id=?",
        (header.purchase_id,),
    ).fetchone()
    assert int(return_txn["reference_item_id"]) == returned_item_id


def test_edit_rejects_quantity_below_already_returned(conn, ids):
    repo, header, returned_item_id, unaffected_item_id = _create_returned_purchase(conn, ids)

    with pytest.raises(ValueError, match="below already returned quantity"):
        repo.update_purchase(
            header,
            [
                PurchaseItem(returned_item_id, header.purchase_id, ids["prod_A"], 2.0, ids["uom_piece"], 10.0, 15.0, 0.0),
                PurchaseItem(unaffected_item_id, header.purchase_id, ids["prod_B"], 4.0, ids["uom_piece"], 20.0, 25.0, 0.0),
            ],
        )


def test_edit_rejects_removing_or_reidentifying_returned_item(conn, ids):
    repo, header, returned_item_id, unaffected_item_id = _create_returned_purchase(conn, ids)

    with pytest.raises(ValueError, match="Cannot remove returned purchase item"):
        repo.update_purchase(
            header,
            [
                PurchaseItem(unaffected_item_id, header.purchase_id, ids["prod_B"], 4.0, ids["uom_piece"], 20.0, 25.0, 0.0),
            ],
        )

    with pytest.raises(ValueError, match="Cannot change product or UoM"):
        repo.update_purchase(
            header,
            [
                PurchaseItem(returned_item_id, header.purchase_id, ids["prod_B"], 10.0, ids["uom_piece"], 10.0, 15.0, 0.0),
                PurchaseItem(unaffected_item_id, header.purchase_id, ids["prod_B"], 4.0, ids["uom_piece"], 20.0, 25.0, 0.0),
            ],
        )
