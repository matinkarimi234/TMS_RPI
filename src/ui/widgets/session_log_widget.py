from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class SessionLogWidget(QWidget):
    """
    Small text-based log for pulses & duration.

    Modes:
      - preview (for a protocol / current params):
          title: "Current session" / "Protocol session"
          body:
              "Pulses: N"
              "Duration: mm:ss"

      - live (during stimulation):
          title: "Stimulation"
          body:
              "Pulses: done/total"
              "Time: mm:ss / mm:ss"

      - blank (MT / Settings, or nothing selected)

      - error:
          title: "ERROR"
          body: "<message>"
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._is_error = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)

        # Title label (separate, QSS-friendly)
        self._title_label = QLabel("", self)
        self._title_label.setObjectName("SessionLogTitleLabel")
        self._title_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)

        # Body label
        self._text_label = QLabel("", self)
        self._text_label.setObjectName("SessionLogBodyLabel")
        self._text_label.setWordWrap(True)
        self._text_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)

        layout.addWidget(self._title_label)
        layout.addWidget(self._text_label, stretch=1)

    # ---------- helpers ----------

    @staticmethod
    def _fmt_time(sec: float) -> str:
        if sec < 0:
            sec = 0.0
        total = int(sec + 0.5)
        m = total // 60
        s = total % 60
        return f"{m:02d}:{s:02d}"

    # ---------- public API ----------

    def show_preview(self, total_pulses: int, total_time_s: float,
                     source: str = "Current") -> None:
        """
        Preview of the whole session for a set of parameters / protocol.
        """
        self._is_error = False
        self._title_label.setText(f"{source} session")
        self._text_label.setText(
            f"Pulses: {int(total_pulses)}\n"
            f"Duration: {self._fmt_time(total_time_s)}"
        )

    def show_live(self,
                  rem_pulses: int,
                  total_pulses: int,
                  rem_s: float,
                  total_s: float) -> None:
        """
        Live mode during stimulation: remaining vs total.
        """
        self._is_error = False

        done_pulses = max(0, total_pulses - rem_pulses)
        self._title_label.setText("Stimulation")
        self._text_label.setText(
            f"Pulses: {done_pulses}/{total_pulses}\n"
            f"Time: {self._fmt_time(total_s - rem_s)} / {self._fmt_time(total_s)}"
        )

    def show_blank(self) -> None:
        """
        Used for MT / Settings etc. Respects error mode (doesn't overwrite it).
        """
        if self._is_error:
            return
        self._title_label.setText("")
        self._text_label.setText("")

    def show_error(self, message: str) -> None:
        """
        Error mode: over-temperature, coil issues, etc.
        """
        self._is_error = True
        self._title_label.setText("ERROR")
        self._text_label.setText(message)
