import sqlite3

from inventory_management.modules.payments.controller import PaymentsController
from inventory_management.modules.reporting.controller import PaymentsTabHost


def test_payments_controller_wraps_reporting_payments(qtbot):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    controller = PaymentsController(conn)
    qtbot.addWidget(controller.get_widget())

    assert isinstance(controller.get_widget(), PaymentsTabHost)
