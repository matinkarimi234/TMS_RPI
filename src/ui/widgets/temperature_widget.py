from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRectF, Property
from PySide6.QtGui import QPainter, QColor, QFont, QPen


class CoilTemperatureWidget(QWidget):
    NORMAL = 0
    WARNING = 1
    DANGER = 2
    DISCONNECTED = 3  # NEW

    def __init__(self, warning_threshold, danger_threshold, parent=None):
        super().__init__(parent)
        self.theme_name = "dark"
        self.theme_manager = None

        self.temperature = 34.3
        self.mode = self.NORMAL
        self.warning_threshold = warning_threshold
        self.danger_threshold = danger_threshold

        # track coil connection state
        self.coil_connected = True

        # --- Font sizes controlled via QSS (baseline for "connected") ---
        self._headerFontSize = 10
        self._tempFontSize = 40
        self._modeFontSize = 20

        # store "normal" font sizes, so we can restore them when coil reconnects
        self._normal_header_size = self._headerFontSize
        self._normal_temp_size = self._tempFontSize
        self._normal_mode_size = self._modeFontSize

        self._colors = {
            "BACKGROUND_COLOR": "#3c3c3c",
            "TEXT_COLOR": "#ffffff",
            "TEXT_COLOR_SECONDARY": "#becedd",
            "BORDER_COLOR": "#444444",
            "NORMAL_COLOR": "#00B060",
            "WARNING_COLOR": "#E6B800",
            "DANGER_COLOR": "#CC3333",
            "DISCONNECTED_COLOR": "#808080",  # optional
        }

        self.setMinimumSize(255, 90)
        self.setObjectName("CoilTemperatureWidget")

    # ------------------------------
    # QSS Properties
    # ------------------------------
    def getHeaderFontSize(self): return self._headerFontSize
    def setHeaderFontSize(self, v):
        self._headerFontSize = v
        # also update the "normal" reference (for when we reconnect)
        self._normal_header_size = v
        self.update()
    headerFontSize = Property(int, getHeaderFontSize, setHeaderFontSize)

    def getTempFontSize(self): return self._tempFontSize
    def setTempFontSize(self, v):
        self._tempFontSize = v
        self._normal_temp_size = v
        self.update()
    tempFontSize = Property(int, getTempFontSize, setTempFontSize)

    def getModeFontSize(self): return self._modeFontSize
    def setModeFontSize(self, v):
        self._modeFontSize = v
        self._normal_mode_size = v
        self.update()
    modeFontSize = Property(int, getModeFontSize, setModeFontSize)

    # ------------------------------------------------------------------
    # ThemeManager hook
    # ------------------------------------------------------------------
    def applyTheme(self, tm, theme_name: str):
        """Load relevant colors from ThemeManager JSON."""
        self.theme_manager = tm
        self.theme_name = theme_name

        g = tm.get_color
        self._colors = {
            "BACKGROUND_COLOR": g(theme_name, "BACKGROUND_COLOR", self._colors["BACKGROUND_COLOR"]),
            "TEXT_COLOR": g(theme_name, "TEXT_COLOR", self._colors["TEXT_COLOR"]),
            "TEXT_COLOR_SECONDARY": g(theme_name, "TEXT_COLOR_SECONDARY", self._colors["TEXT_COLOR_SECONDARY"]),
            "BORDER_COLOR": g(theme_name, "BORDER_COLOR", self._colors["BORDER_COLOR"]),
            "NORMAL_COLOR": g(theme_name, "CONNECTED_GREEN", "#00CC00"),
            "WARNING_COLOR": g(theme_name, "ACCENT_GRADIENT_END", "#fadb5a"),
            "DANGER_COLOR": g(theme_name, "DISCONNECTED_RED", "#CC0000"),
            "COIL_DISCONNECTED": g(theme_name, "COIL_DISCONNECTED", "#808080"),
        }
        self.update()

    # ------------------------------------------------------------------
    # Logic
    # ------------------------------------------------------------------
    def setCoilConnected(self, connected: bool):
        self.coil_connected = bool(connected)
        self.updateMode()

        # JUST update the state so QSS can do its thing
        self.setProperty("state", "connected" if self.coil_connected else "disconnected")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def updateMode(self):
        # If coil is not connected, force DISCONNECTED mode
        if not self.coil_connected:
            self.mode = self.DISCONNECTED
            return

        # Normal temperature-based modes
        if self.temperature < self.warning_threshold:
            self.mode = self.NORMAL
        elif self.temperature < self.danger_threshold:
            self.mode = self.WARNING
        else:
            self.mode = self.DANGER

    def setTemperature(self, value: float):
        self.temperature = max(0.0, value)
        self.updateMode()
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def paintEvent(self, event):
        c = self._colors

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)

        # background + border (always)
        painter.setBrush(QColor(c["BACKGROUND_COLOR"]))
        painter.setPen(QPen(QColor(c["BORDER_COLOR"]), 1))
        painter.drawRoundedRect(rect, 6, 6)

        # Choose bar/mode color
        if self.mode == self.NORMAL:
            mode_color = QColor(c["NORMAL_COLOR"])
            mode_text = "NORMAL"
        elif self.mode == self.WARNING:
            mode_color = QColor(c["WARNING_COLOR"])
            mode_text = "WARNING"
        elif self.mode == self.DANGER:
            mode_color = QColor(c["DANGER_COLOR"])
            mode_text = "DANGER"
        else:  # DISCONNECTED
            mode_color = QColor(c["COIL_DISCONNECTED"])
            mode_text = "DISCONNECTED"

        # bottom status bar (always drawn)
        bar_height = self.height() * 0.2
        painter.setBrush(mode_color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(
            0,
            self.height() - bar_height,
            self.width(),
            bar_height,
            0,
            0,
        )

        # -----------------------------
        # SPECIAL CASE: DISCONNECTED
        # -----------------------------
        if self.mode == self.DISCONNECTED:
            # Only show "COIL NOT CONNECTED" in the middle area above the bar
            painter.setPen(QColor(c["COIL_DISCONNECTED"]))
            temp_font = QFont("Tw Cen MT Condensed", self._tempFontSize)
            temp_font.setBold(True)
            painter.setFont(temp_font)

            main_text = "COIL\nNOT CONNECTED"

            painter.drawText(
                QRectF(10, 0, self.width() - 20, self.height() - bar_height),
                Qt.AlignCenter,
                main_text,
            )
            return  # skip normal drawing

        # -----------------------------
        # NORMAL / WARNING / DANGER
        # -----------------------------
        # --- Header label ---
        painter.setPen(QColor(c["TEXT_COLOR_SECONDARY"]))
        header_font = QFont("Tw Cen MT Condensed", self._headerFontSize)
        header_font.setBold(True)
        painter.setFont(header_font)
        painter.drawText(
            QRectF(10, self.height() * 0.05, self.width() - 20, self.height() * 0.18),
            Qt.AlignLeft | Qt.AlignVCenter,
            "COIL TEMPERATURE",
        )

        # --- Main temperature text ---
        painter.setPen(QColor(c["TEXT_COLOR"]))
        temp_font = QFont("Tw Cen MT Condensed", self._tempFontSize)
        temp_font.setBold(True)
        painter.setFont(temp_font)

        main_text = f"{self.temperature:.1f} °C"
        painter.drawText(
            QRectF(10, self.height() * 0.33, self.width() - 20, self.height() * 0.5),
            Qt.AlignLeft | Qt.AlignVCenter,
            main_text,
        )

        # --- Mode indicator (right side) ---
        painter.setPen(mode_color)
        mode_font = QFont("Tw Cen MT Condensed", self._modeFontSize, QFont.Bold)
        painter.setFont(mode_font)
        painter.drawText(
            QRectF(0, self.height() * 0.33, self.width() - 12, self.height() * 0.5),
            Qt.AlignRight | Qt.AlignVCenter,
            mode_text,
        )

    def sizeHint(self):
        return self.minimumSizeHint()
