from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtGui import QColor, QPalette


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

        # --- Theme state (similar to CoilTemperatureWidget) ---
        self.theme_name = "dark"
        self.theme_manager = None
        self._colors = {
            "TEXT_COLOR": "#ffffff",
            "TEXT_COLOR_SECONDARY": "#becedd",
            "DANGER_COLOR": "#CC3333",
        }

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)

        # live tracking
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

        # apply initial (default) colors
        self._apply_colors()

    # ---------- theme integration (like temp widget) ----------

    def applyTheme(self, tm, theme_name: str):
        """
        Hook for ThemeManager JSON (same pattern as CoilTemperatureWidget).
        """
        self.theme_manager = tm
        self.theme_name = theme_name

        g = tm.get_color if tm is not None else (lambda *args, **kwargs: kwargs.get("default"))

        self._colors = {
            "TEXT_COLOR": g(theme_name, "TEXT_COLOR", self._colors["TEXT_COLOR"]),
            "TEXT_COLOR_SECONDARY": g(
                theme_name,
                "TEXT_COLOR_SECONDARY",
                self._colors["TEXT_COLOR_SECONDARY"],
            ),
            # reuse whatever key you use for red in your JSON
            "DANGER_COLOR": g(
                theme_name,
                "DISCONNECTED_RED",   # or "ALERT_RED" / whatever you have
                self._colors["DANGER_COLOR"],
            ),
        }

        self._apply_colors()

    def _update_state_property(self):
        """
        Optional: lets QSS differentiate error vs normal.
        """
        self.setProperty("state", "error" if self._is_error else "normal")
        self.style().unpolish(self)
        self.style().polish(self)

    def _apply_colors(self):
        self._update_state_property()
        self.update()
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

    def show_preview(
        self,
        total_pulses: int,
        total_time_s: float,
        source: str = "Current",
    ) -> None:
        """
        Preview of the whole session for a set of parameters / protocol.
        """
        self._is_error = False
        self._title_label.setText(f"{source} session")
        self._text_label.setText(
            f"Pulses: {int(total_pulses)}\n"
            f"Duration: {self._fmt_time(total_time_s)}"
        )
        self._apply_colors()

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
        ITI may change time, but NOT pulses.
        """
        self._is_error = False

        # --- pulses ---
        self._live_total_pulses = max(0, int(total_pulses))
        rem_pulses = max(0, int(rem_pulses))

        if self._last_rem_pulses is None:
            # first call for this run
            self._last_rem_pulses = rem_pulses
            self._live_delivered_pulses = max(
                0, self._live_total_pulses - rem_pulses
            )
        else:
            if rem_pulses < self._last_rem_pulses:
                # real pulses fired → increment by delta
                delta = self._last_rem_pulses - rem_pulses
                self._live_delivered_pulses += delta
                self._last_rem_pulses = rem_pulses
            elif rem_pulses > self._last_rem_pulses:
                # new session / reset
                self._live_delivered_pulses = max(
                    0, self._live_total_pulses - rem_pulses
                )
                self._last_rem_pulses = rem_pulses
            # equal → ITI, don't touch pulse counter

        # clamp
        if self._live_delivered_pulses < 0:
            self._live_delivered_pulses = 0
        if self._live_delivered_pulses > self._live_total_pulses:
            self._live_delivered_pulses = self._live_total_pulses

        # --- time ---
        rem_s = max(0.0, rem_s)
        total_s = max(rem_s, total_s)
        elapsed_s = max(0.0, total_s - rem_s)

        pulses_text = f"Pulses: {self._live_delivered_pulses}/{self._live_total_pulses}"
        time_text = f"Time: {self._fmt_time(elapsed_s)} / {self._fmt_time(total_s)}"

        self._title_label.setText("Stimulation")
        self._text_label.setText(f"{pulses_text}\n{time_text}")

        self._apply_colors()

    def show_blank(self) -> None:
        """
        Used for MT / Settings etc. Blank == not in error.
        """
        self._is_error = False
        self._title_label.setText("")
        self._text_label.setText("")
        self._apply_colors()

    def show_error(self, message: str) -> None:
        """
        Error mode: over-temperature, coil issues, etc.
        """
        self._is_error = True
        self._title_label.setText("ERROR")
        self._text_label.setText(message)
        
        self._apply_colors()

    def reset_live_state(self) -> None:
        self._live_total_pulses = 0
        self._live_delivered_pulses = 0
        self._last_rem_pulses = None
        self.show_blank()