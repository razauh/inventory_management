from PySide6.QtWidgets import QTableView

class TableView(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableView.SelectRows)
        self.setSelectionMode(QTableView.SingleSelection)
        self.horizontalHeader().setStretchLastSection(True)
