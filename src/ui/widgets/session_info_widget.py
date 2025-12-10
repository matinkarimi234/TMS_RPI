# ui/widgets/session_info_widget.py

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout


class SessionInfoWidget(QWidget):
    """
    Small 3-row info widget, suitable for the top-left of the page.

      Row 1: Protocol: cTBS
      Row 2: [ICON] USER
      Row 3: MT: 20
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.setObjectName("SessionInfoWidget")

        # Fixed overall height so it doesn't get squashed
        self.setFixedHeight(90)

        # Protocol row
        self._protocol_label = QLabel("Protocol: -", self)
        self._protocol_label.setObjectName("sessionInfoProtocolLabel")
        self._protocol_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # MT row
        self._mt_label = QLabel("MT: -", self)
        self._mt_label.setObjectName("sessionInfoMtLabel")
        self._mt_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # User row: icon + text
        self._user_icon_label = QLabel(self)
        self._user_icon_label.setObjectName("sessionInfoUserIcon")
        self._user_icon_label.setFixedSize(20, 20)  # small icon is fine
        self._user_icon_label.setAlignment(Qt.AlignCenter)

        self._user_text_label = QLabel("USER", self)
        self._user_text_label.setObjectName("sessionInfoUserText")
        self._user_text_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        user_row = QHBoxLayout()
        user_row.setContentsMargins(0, 0, 0, 0)
        user_row.setSpacing(8)
        user_row.addWidget(self._user_icon_label)
        user_row.addWidget(self._user_text_label)
        user_row.addStretch(1)



        # Main layout
        main = QVBoxLayout(self)
        # extra top/bottom margin so rows are not glued to edges
        main.setContentsMargins(10, 3, 10, 10)  # left, top, right, bottom
        main.setSpacing(4)                       # vertical spacing between rows
        main.addWidget(self._protocol_label)
        main.addWidget(self._mt_label)
        main.addLayout(user_row)

        self.setMinimumWidth(160)

    # -------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------
    def setProtocolName(self, name: str) -> None:
        if len(name) > 20:
            name = name[0:20]
            name += "..."
        self._protocol_label.setText(f"Protocol: {name}")

    def setUserLabel(self, text: str) -> None:
        self._user_text_label.setText(text)

    def setUserIcon(self, pix: QPixmap) -> None:
        if not pix.isNull():
            size = self._user_icon_label.size()
            if size.width() <= 0 or size.height() <= 0:
                size = QSize(18, 18)
            scaled = pix.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._user_icon_label.setPixmap(scaled)
    

    def clearUserIcon(self) -> None:
        self._user_icon_label.clear()

    def setMtValue(self, value: int) -> None:
        self._mt_label.setText(f"MT: {int(value)}")

    def applyTextColor(self, color: QColor) -> None:
        col_str = color.name()
        self._protocol_label.setStyleSheet(f"color: {col_str};")
        self._user_text_label.setStyleSheet(f"color: {col_str};")
        self._mt_label.setStyleSheet(f"color: {col_str};")
