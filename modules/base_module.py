import sqlite3

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget

class BaseModule(QObject):
    def get_widget(self) -> QWidget:
        raise NotImplementedError

    def on_db_closed(self) -> None:
        self._sync_db_connection(None)

    def on_db_reopened(self, conn) -> None:
        self._sync_db_connection(conn)

    def _sync_db_connection(self, conn) -> None:
        seen: set[int] = set()
        for holder in self._db_connection_holders():
            current = getattr(holder, "conn", None)
            if isinstance(current, sqlite3.Connection) and id(current) not in seen:
                seen.add(id(current))
                try:
                    current.close()
                except Exception:
                    pass
            try:
                setattr(holder, "conn", conn)
            except Exception:
                pass

    def _db_connection_holders(self) -> list[object]:
        holders: list[object] = []
        if hasattr(self, "conn"):
            holders.append(self)
        for value in vars(self).values():
            if value is self:
                continue
            if hasattr(value, "conn"):
                holders.append(value)
        return holders
