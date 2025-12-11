from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt, QRectF
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QColor, QPainter, QFont


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
        self.setObjectName("sessionLogWidget")

        # text content (replaces QLabels)
        self._title_text: str = ""
        self._body_text: str = ""

        # live tracking
        self._live_total_pulses: int = 0
        self._live_delivered_pulses: int = 0
        self._last_rem_pulses: Optional[int] = None

        # theme
        self.theme_name = "dark"
        self.theme_manager = None
        self._colors = {
            "BACKGROUND_COLOR": "#3c3c3c",
            "TEXT_COLOR": "#ffffff",
            "TEXT_COLOR_SECONDARY": "#becedd",
            "DANGER_COLOR": "#CC3333",
        }

        self.setMinimumSize(200, 70)

        # initial state for QSS (if any)
        self._apply_colors()

    # ---------- theme integration ----------

    def applyTheme(self, tm, theme_name: str):
        """
        Hook for ThemeManager JSON (similar to CoilTemperatureWidget).
        """
        self.theme_manager = tm
        self.theme_name = theme_name

        if tm is None:
            self._apply_colors()
            self.update()
            return

        g = tm.get_color

        self._colors = {
            "BACKGROUND_COLOR": g(
                theme_name, "BACKGROUND_COLOR", self._colors["BACKGROUND_COLOR"]
            ),
            "TEXT_COLOR": g(
                theme_name, "TEXT_COLOR", self._colors["TEXT_COLOR"]
            ),
            "TEXT_COLOR_SECONDARY": g(
                theme_name,
                "TEXT_COLOR_SECONDARY",
                self._colors["TEXT_COLOR_SECONDARY"],
            ),
            "DANGER_COLOR": g(
                theme_name,
                "DISCONNECTED_RED",  # or ALERT_RED etc.
                self._colors["DANGER_COLOR"],
            ),
        }

        self._apply_colors()
        self.update()

    def _update_state_property(self):
        """
        Lets QSS differentiate error vs normal if you want.
        """
        self.setProperty("state", "error" if self._is_error else "normal")
        self.style().unpolish(self)
        self.style().polish(self)

    def _apply_colors(self):
        # We don't use palettes; just keep state for QSS and repaint.
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
        self._title_text = f"{source} session"
        self._body_text = (
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
            self._last_rem_pulses = rem_pulses
            self._live_delivered_pulses = max(
                0, self._live_total_pulses - rem_pulses
            )
        else:
            if rem_pulses < self._last_rem_pulses:
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

        self._title_text = "Stimulation"
        self._body_text = f"{pulses_text}\n{time_text}"

        self._apply_colors()

    def show_blank(self) -> None:
        """
        Used for MT / Settings etc. Blank == not in error.
        """
        self._is_error = False
        self._title_text = ""
        self._body_text = ""
        self._apply_colors()

    def show_error(self, message: str) -> None:
        """
        Error mode: over-temperature, coil issues, etc.
        """
        self._is_error = True
        self._title_text = "ERROR"
        self._body_text = message
        self._apply_colors()

    def reset_live_state(self) -> None:
        self._live_total_pulses = 0
        self._live_delivered_pulses = 0
        self._last_rem_pulses = None
        self.show_blank()

    # ---------- painting ----------

    def paintEvent(self, event):
        c = self._colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(0, 0, -1, -1)

        # Soft background, NO border
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(c["BACKGROUND_COLOR"]))
        painter.drawRoundedRect(rect, 6, 6)

        # Pick colors
        if self._is_error:
            title_color = QColor(c["DANGER_COLOR"])
            body_color = QColor(c["DANGER_COLOR"])
        else:
            title_color = QColor(c["TEXT_COLOR"])
            body_color = QColor(c["TEXT_COLOR_SECONDARY"])

        # Title font
        title_font = QFont("Tw Cen MT Condensed", 13)
        title_font.setBold(True)

        # Body font
        body_font = QFont("Tw Cen MT Condensed", 16)
        body_font.setBold(False)

        # Layout areas
        margin = 8
        top_h = self.height() * 0.35

        title_rect = QRectF(
            margin,
            margin,
            self.width() - 2 * margin,
            top_h - margin,
        )

        body_rect = QRectF(
            margin,
            top_h,
            self.width() - 2 * margin,
            self.height() - top_h - margin,
        )

        # Draw title
        painter.setPen(title_color)
        painter.setFont(title_font)
        painter.drawText(
            title_rect,
            Qt.AlignHCenter | Qt.AlignVCenter,
            self._title_text,
        )

        # Draw body
        painter.setPen(body_color)
        painter.setFont(body_font)
        painter.drawText(
            body_rect,
            Qt.AlignHCenter | Qt.AlignVCenter | Qt.TextWordWrap,
            self._body_text,
        )

    def sizeHint(self):
        return self.minimumSizeHint()
