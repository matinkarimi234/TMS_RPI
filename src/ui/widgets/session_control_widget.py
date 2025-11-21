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
        # FrameButton {
        #     background-color: ...;
        #     border-radius: ...;
        # }
        # or by objectName if you set one.

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
    Bottom control pad for the TMS session.

    Frame "buttons" in this order (left to right):
      - Protocol
      - MT
      - Toggle Theme
      - Stop
      - Start/Pause (toggles label)

    Signals:
      - startRequested
      - stopRequested
      - pauseRequested
      - protocolRequested
      - mtRequested
      - themeToggleRequested
    """
    startRequested = Signal()
    stopRequested = Signal()
    pauseRequested = Signal()

    protocolRequested = Signal()
    mtRequested = Signal()
    themeToggleRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._running = False
        self._paused = False

        # Left side: protocol & MT & theme buttons
        self.protocol_frame = FrameButton("Protocol", self)
        self.mt_frame = FrameButton("MT", self)
        self.theme_frame = FrameButton("Toggle Theme", self)

        # Right side: stop + start/pause
        self.stop_frame = FrameButton("Stop", self)
        self.start_pause_frame = FrameButton("Start", self)

        # Optional object names for styling if you want per-button styles
        self.protocol_frame.setObjectName("protocol_frame")
        self.mt_frame.setObjectName("mt_frame")
        self.theme_frame.setObjectName("theme_frame")
        self.stop_frame.setObjectName("stop_frame")
        self.start_pause_frame.setObjectName("start_pause_frame")

        # Layout: (protocol , MT , Toggle Theme, Stop, Start/Pause)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        lay.addWidget(self.protocol_frame)
        lay.addWidget(self.mt_frame)
        lay.addWidget(self.theme_frame)
        lay.addStretch(1)
        lay.addWidget(self.stop_frame)
        lay.addWidget(self.start_pause_frame)

        # wiring main actions
        self.stop_frame.clicked.connect(self._on_stop_clicked)
        self.start_pause_frame.clicked.connect(self._on_start_pause_clicked)

        # wiring extra actions
        self.protocol_frame.clicked.connect(self._on_protocol_clicked)
        self.mt_frame.clicked.connect(self._on_mt_clicked)
        self.theme_frame.clicked.connect(self._on_theme_clicked)

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

        # You can also tweak styles based on running/paused with stylesheets.

    def get_state(self):
        """
        Returns the current label of the start/pause control:
        'Start' or 'Pause'.
        """
        return self.start_pause_frame.text()

    def setStartStopEnabled(self, enabled: bool):
        """
        Enable/disable ONLY Stop + Start/Pause.
        Protocol / MT / Theme are never touched here.
        This is intended to be called from EN logic.
        """
        self.stop_frame.setEnabled(enabled)
        self.start_pause_frame.setEnabled(enabled)

    # ----- internal slots -----

    def _on_stop_clicked(self):
        self.stopRequested.emit()
        # Owner (ParamsPage) should call set_state() after it processes stop.

    def _on_start_pause_clicked(self):
        if self._running:
            self.pauseRequested.emit()
        else:
            self.startRequested.emit()
        # Owner should update state via set_state() based on outcome.

    def _on_protocol_clicked(self):
        self.protocolRequested.emit()

    def _on_mt_clicked(self):
        self.mtRequested.emit()

    def _on_theme_clicked(self):
        self.themeToggleRequested.emit()
