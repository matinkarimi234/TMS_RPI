from PySide6.QtWidgets import QFrame
from PySide6.QtCore import QTimer, QSize

class ConnectionIndicator(QFrame):
    """
    A tiny circular frame whose color is driven purely by QSS.
    We toggle two dynamic properties:
      - state: "connected" or "disconnected"
      - blink: "true"/"false" (string form is required for QSS matching)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("connectionIndicator")
        self.setProperty("state", "disconnected")
        self.setProperty("blink", "false")

        # fixed size
        self.setFixedSize(self.sizeHint())

        # a timer to end the blink
        self._blink_timer = QTimer(self)
        self._blink_timer.setSingleShot(True)
        self._blink_timer.setInterval(200)
        self._blink_timer.timeout.connect(self._end_blink)

    def sizeHint(self) -> QSize:
        return QSize(16,16)

    def set_connected(self, ok: bool):
        self._blink_timer.stop()
        self.setProperty("blink", "false")
        self.setProperty("state", "connected" if ok else "disconnected")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def blink(self):
        # show accent‐color for a brief moment
        self.setProperty("blink", "true")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
        self._blink_timer.start()

    def _end_blink(self):
        # revert to normal connected/disconnected color
        self.setProperty("blink", "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
