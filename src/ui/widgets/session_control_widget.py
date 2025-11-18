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
        self.setFixedSize(100, 50)  # Set fixed size for consistency

        # Default styles for different states
        self._update_style()

    def setText(self, text: str):
        self._label.setText(text)

    def text(self) -> str:
        return self._label.text()

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        self._update_style()

    def _update_style(self):
        """Update button style based on current state"""
        if not self.isEnabled():
            self.setStyleSheet("""
                FrameButton {
                    background-color: #6c757d;
                    border: 2px solid #495057;
                    border-radius: 8px;
                    color: #adb5bd;
                }
                FrameButton:hover {
                    background-color: #5a6268;
                }
            """)
        else:
            current_text = self.text().lower()
            if "start" in current_text:
                # Start button style (green)
                self.setStyleSheet("""
                    FrameButton {
                        background-color: #28a745;
                        border: 2px solid #1e7e34;
                        border-radius: 8px;
                        color: white;
                        font-weight: bold;
                    }
                    FrameButton:hover {
                        background-color: #218838;
                    }
                """)
            elif "pause" in current_text or "resume" in current_text:
                # Pause/Resume button style (yellow/orange)
                self.setStyleSheet("""
                    FrameButton {
                        background-color: #ffc107;
                        border: 2px solid #e0a800;
                        border-radius: 8px;
                        color: black;
                        font-weight: bold;
                    }
                    FrameButton:hover {
                        background-color: #e0a800;
                    }
                """)
            elif "stop" in current_text:
                # Stop button style (red)
                self.setStyleSheet("""
                    FrameButton {
                        background-color: #dc3545;
                        border: 2px solid #c82333;
                        border-radius: 8px;
                        color: white;
                        font-weight: bold;
                    }
                    FrameButton:hover {
                        background-color: #c82333;
                    }
                """)
            else:
                # Default style
                self.setStyleSheet("""
                    FrameButton {
                        background-color: #6c757d;
                        border: 2px solid #495057;
                        border-radius: 8px;
                        color: white;
                        font-weight: bold;
                    }
                    FrameButton:hover {
                        background-color: #5a6268;
                    }
                """)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class SessionControlWidget(QWidget):
    """
    Bottom-right control pad for the TMS session.

    Two frame "buttons":
      - Control Button (toggles between Start/Pause/Resume)
      - Stop Button (always Stop)

    Signals:
      - startRequested
      - stopRequested
      - pauseRequested
      - resumeRequested
    """
    startRequested = Signal()
    stopRequested = Signal()
    pauseRequested = Signal()
    resumeRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._running = False
        self._paused = False

        # Control button (Start/Pause/Resume)
        self.control_frame = FrameButton("Start", self)
        # Stop button
        self.stop_frame = FrameButton("Stop", self)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 5, 10, 5)
        lay.setSpacing(10)
        lay.addWidget(self.control_frame)
        lay.addWidget(self.stop_frame)

        # wiring
        self.control_frame.clicked.connect(self._on_control_clicked)
        self.stop_frame.clicked.connect(self._on_stop_clicked)

        # Initial state
        self.update_display()

    # ----- public API to keep labels in sync with state -----

    def set_state(self, running: bool, paused: bool):
        """
        Update internal state and adjust labels.
        Call this if you want to sync UI from the outside.
        """
        self._running = running
        self._paused = paused
        self.update_display()

    def get_state(self) -> str:
        """
        Get current state as string
        Returns: "stopped", "running", "paused"
        """
        if self._running and self._paused:
            return "paused"
        elif self._running and not self._paused:
            return "running"
        else:
            return "stopped"

    def update_display(self):
        """Update button text and visibility based on current state"""
        # Update control button
        if self._running and not self._paused:
            # Running: show "Pause"
            self.control_frame.setText("Pause")
        elif self._running and self._paused:
            # Paused: show "Resume"
            self.control_frame.setText("Resume")
        else:
            # Stopped: show "Start"
            self.control_frame.setText("Start")

        # Update stop button availability
        self.stop_frame.setEnabled(self._running)
        
        # Force style update
        self.control_frame._update_style()
        self.stop_frame._update_style()

    # ----- internal slots -----

    def _on_control_clicked(self):
        """Handle control button clicks based on current state"""
        current_state = self.get_state()
        
        if current_state == "stopped":
            # Request start
            self.startRequested.emit()
        elif current_state == "running":
            # Request pause
            self.pauseRequested.emit()
        elif current_state == "paused":
            # Request resume (which is essentially start again)
            self.resumeRequested.emit()

    def _on_stop_clicked(self):
        """Handle stop button clicks"""
        self.stopRequested.emit()
