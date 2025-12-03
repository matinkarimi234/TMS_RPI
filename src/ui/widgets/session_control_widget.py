from __future__ import annotations
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QFrame, QHBoxLayout, QLabel, QSizePolicy


class FrameButton(QFrame):
    """
    Simple clickable frame used instead of QPushButton.
    Emits `clicked` when pressed with the mouse.
    """
    clicked = Signal()

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)

        self._label = QLabel(text, self)
        self._label.setAlignment(Qt.AlignCenter)

        lay = QHBoxLayout(self)
        # No internal padding so the frame can visually touch edges if needed
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._label)

        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setCursor(Qt.PointingHandCursor)

        # Button keeps its natural size, does not eat all extra space
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

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
      - Protocol   (pinned to left edge)
      - MT
      - Settings
      - Stop
      - Start/Pause (pinned to right edge)

    MT / Settings / Stop are centered as a group.
    """

    startRequested = Signal()
    stopRequested = Signal()
    pauseRequested = Signal()

    protocolRequested = Signal()
    mtRequested = Signal()
    settingsRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._running = False
        self._paused = False

        # Let this widget expand horizontally so first/last can reach edges
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # --- Create all buttons ---
        self.protocol_frame = FrameButton("Protocol", self)
        self.mt_frame = FrameButton("MT", self)
        self.settings_frame = FrameButton("Settings", self)
        self.stop_frame = FrameButton("Stop", self)
        self.start_pause_frame = FrameButton("Start", self)

        for btn in (
            self.protocol_frame,
            self.mt_frame,
            self.settings_frame,
            self.stop_frame,
            self.start_pause_frame,
        ):
            btn.setMinimumWidth(100)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # === MAIN LAYOUT ===
        main_lay = QHBoxLayout(self)
        main_lay.setContentsMargins(0, 0, 0, 0)  # no outer margins
        main_lay.setSpacing(0)                   # spacing handled by inner layout

        # First and last: pinned to left/right
        first_btn = self.protocol_frame
        last_btn = self.start_pause_frame

        # Middle group: centered
        center_buttons = [self.mt_frame, self.settings_frame, self.stop_frame]
        center_lay = QHBoxLayout()
        center_lay.setContentsMargins(0, 0, 0, 0)
        center_lay.setSpacing(63)  # distance between middle buttons
        for btn in center_buttons:
            center_lay.addWidget(btn)

        # Left, center, right layout:
        # [ first_btn ][ stretch ][ center_lay ][ stretch ][ last_btn ]
        main_lay.addWidget(first_btn)
        main_lay.addSpacing(15)
        main_lay.addStretch(1)
        

        if center_buttons:
            main_lay.addLayout(center_lay)
            main_lay.addStretch(1)
            
        

        main_lay.addWidget(last_btn)
        #main_lay.setSpacing(20)
        # --- Connections ---
        self.stop_frame.clicked.connect(self._on_stop_clicked)
        self.start_pause_frame.clicked.connect(self._on_start_pause_clicked)
        self.protocol_frame.clicked.connect(self._on_protocol_clicked)
        self.mt_frame.clicked.connect(self._on_mt_clicked)
        self.settings_frame.clicked.connect(self._on_settings_clicked)

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

    def get_state(self) -> str:
        """
        Returns the current label of the start/pause control:
        'Start' or 'Pause'.
        """
        return self.start_pause_frame.text()

    def setStartStopEnabled(self, enabled: bool):
        """
        Enable/disable ONLY Stop + Start/Pause.
        Protocol / MT / Settings are never touched here.
        This is intended to be called from EN logic.
        """
        self.stop_frame.setEnabled(enabled)
        self.start_pause_frame.setEnabled(enabled)

    # ----- internal slots -----

    def _on_stop_clicked(self):
        self.stopRequested.emit()

    def _on_start_pause_clicked(self):
        if self._running:
            self.pauseRequested.emit()
        else:
            self.startRequested.emit()

    def _on_protocol_clicked(self):
        self.protocolRequested.emit()

    def _on_mt_clicked(self):
        self.mtRequested.emit()

    def _on_settings_clicked(self):
        self.settingsRequested.emit()


# Optional: tiny test harness
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout

    app = QApplication(sys.argv)
    w = QMainWindow()

    central = QWidget()
    lay = QVBoxLayout(central)
    lay.setContentsMargins(0, 0, 0, 0)

    sc = SessionControlWidget()
    # IMPORTANT: don't do alignment=Qt.AlignCenter here,
    # or youÃ¢â‚¬â„¢ll break the edge hugging.
    lay.addWidget(sc)

    w.setCentralWidget(central)
    w.resize(800, 120)
    w.show()
    sys.exit(app.exec())
