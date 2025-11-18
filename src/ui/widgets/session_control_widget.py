from __future__ import annotations
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QFrame, QHBoxLayout, QLabel, QSizePolicy


class FrameButton(QFrame):
    """
    Simple clickable frame used instead of QPushButton.
    Emits `clicked` when pressed with the mouse (or programmatically later).
    """
    clicked = Signal()

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)

        self._label = QLabel(text, self)
        self._label.setAlignment(Qt.AlignCenter)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.addWidget(self._label)

        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # You can style these via global stylesheet:
        # .FrameButton { background-color: ...; border-radius: ...; }

    def setText(self, text: str):
        self._label.setText(text)

    def text(self) -> str:
        return self._label.text()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class SessionControlWidget(QWidget):
    """
    Bottom-right control pad for the TMS session.

    Two frame "buttons":
      - Pause
      - Start/Stop (toggles)

    Signals:
      - startRequested
      - stopRequested
      - pauseRequested
    """
    startRequested = Signal()
    stopRequested = Signal()
    pauseRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._running = False
        self._paused = False

        self.stop_frame = FrameButton("Stop", self)
        self.start_pause_frame = FrameButton("Start", self)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self.stop_frame)
        lay.addWidget(self.start_pause_frame)

        # wiring
        self.stop_frame.clicked.connect(self._on_stop_clicked)
        self.start_pause_frame.clicked.connect(self._on_start_pause_clicked)

    # ----- public API to keep label in sync with state -----

    def set_state(self, running: bool, paused: bool):
        """
        Update internal state and adjust label.
        Call this if you want to sync UI from the outside.
        """
        self._running = running
        self._paused = paused

        if running:
            self.start_pause_frame.setText("Pause")
        else:
            # when not running, treat as 'Start' even if paused flag is True
            self.start_pause_frame.setText("Start")

    def get_state(self):
        return self.start_pause_frame.text()

        # You can also change style based on paused/running using stylesheets.

    # ----- internal slots -----

    def _on_stop_clicked(self):
        # Let the owner decide what "pause" means.
        self.stopRequested.emit()
        # we won't toggle running flag here; owner should call set_state()

    def _on_start_pause_clicked(self):
        if self._running:
            self.pauseRequested.emit()
        else:
            self.startRequested.emit()
        # Again, owner should call set_state() after action succeeds.
