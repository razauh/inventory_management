from __future__ import annotations

import sqlite3

from PySide6.QtWidgets import QWidget

from ..base_module import BaseModule
from ..reporting.controller import PaymentsTabHost


class PaymentsController(BaseModule):
    def __init__(self, conn: sqlite3.Connection, current_user: dict | None = None):
        super().__init__()
        self.view = PaymentsTabHost(conn)

    def get_widget(self) -> QWidget:
        return self.view
