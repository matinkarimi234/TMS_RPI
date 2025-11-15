from PySide6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QSizePolicy
)

from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtCore import Signal, Qt

from core.protocol_manager_revised import ProtocolManager


class ProtocolListPage(QWidget):
    accepted = Signal(str)
    canceled = Signal()

    def __init__(self, pm: ProtocolManager, parent=None):
        super().__init__(parent)
        self.pm = pm

        self.list_widget = QListWidget()
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.list_widget.addItems(self.pm.list_protocols())
        self.list_widget.setCurrentRow(0)

        btn_up = QPushButton("Up")
        btn_down = QPushButton("Down")
        btn_up.clicked.connect(self._up)
        btn_down.clicked.connect(self._down)
        nav = QHBoxLayout()
        nav.addWidget(btn_up)
        nav.addWidget(btn_down)

        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancel")
        btn_ok.clicked.connect(self._on_ok)
        btn_cancel.clicked.connect(lambda: self.canceled.emit())
        ctl = QHBoxLayout()
        ctl.addWidget(btn_ok)
        ctl.addWidget(btn_cancel)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(15, 10, 15, 10)
        lay.setSpacing(5)
        lay.addWidget(self.list_widget)
        lay.addLayout(nav)
        lay.addLayout(ctl)
        lay.setStretch(0, 1)

    def _up(self):
        r = self.list_widget.currentRow()
        if r > 0:
            self.list_widget.setCurrentRow(r - 1)

    def _down(self):
        r = self.list_widget.currentRow()
        if r < self.list_widget.count() - 1:
            self.list_widget.setCurrentRow(r + 1)

    def _on_ok(self):
        item = self.list_widget.currentItem()
        if item:
            self.accepted.emit(item.text())


__all__ = ["ProtocolListPage"]