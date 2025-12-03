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

        self._live_total_pulses: int = 0
        self._live_delivered_pulses: int = 0
        self._last_rem_pulses: Optional[int] = None

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

    def show_live(
        self,
        rem_pulses: int,
        total_pulses: int,
        rem_s: float,
        total_s: float,
    ) -> None:
        """
        Live mode during stimulation.
        Pulses are ONLY incremented when rem_pulses actually decreases.
        ITI will still update the time, but won't touch the pulse counter.
        """
        # --- pulses ---
        self._live_total_pulses = max(0, int(total_pulses))

        if self._last_rem_pulses is None:
            # first call in this session
            self._last_rem_pulses = rem_pulses
            self._live_delivered_pulses = max(0, self._live_total_pulses - rem_pulses)
        else:
            if rem_pulses < self._last_rem_pulses:
                # some pulses actually fired → increment by the delta
                delta = self._last_rem_pulses - rem_pulses
                self._live_delivered_pulses += delta
                self._last_rem_pulses = rem_pulses
            elif rem_pulses > self._last_rem_pulses:
                # probably a new session or reset: recompute from scratch
                self._live_delivered_pulses = max(
                    0, self._live_total_pulses - rem_pulses
                )
                self._last_rem_pulses = rem_pulses
            # if rem_pulses == _last_rem_pulses → ITI ticking, do NOT touch pulses

        # clamp
        if self._live_delivered_pulses < 0:
            self._live_delivered_pulses = 0
        if self._live_delivered_pulses > self._live_total_pulses:
            self._live_delivered_pulses = self._live_total_pulses

        pulses_text = f"{self._live_delivered_pulses}/{self._live_total_pulses} pulses"

        # --- time (this can still count down smoothly, including ITI) ---
        rem_s = max(0.0, rem_s)
        total_s = max(rem_s, total_s)
        time_text = f"{rem_s:0.1f}s / {total_s:0.1f}s"

        # now push to your labels:
        self._title_label.setText("Stimulation")
        self._pulses_label.setText(pulses_text)
        self._time_label.setText(time_text)

        self._mode = "live"
        self.update()

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

    def reset_live_state(self) -> None:
        self._live_total_pulses = 0
        self._live_delivered_pulses = 0
        self._last_rem_pulses = None
