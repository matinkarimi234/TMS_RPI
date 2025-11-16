from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRectF, Property
from PySide6.QtGui import QPainter, QColor, QFont, QPen


class CoilTemperatureWidget(QWidget):
    NORMAL = 0
    WARNING = 1
    DANGER = 2

    def __init__(self, warning_threshold, danger_threshold, parent=None):
        super().__init__(parent)
        self.theme_name = "dark"
        self.theme_manager = None
        self.temperature = 34.3
        self.mode = self.NORMAL
        self.warning_threshold = warning_threshold
        self.danger_threshold = danger_threshold

        # --- Font sizes controlled via QSS ---
        self._headerFontSize = 16
        self._tempFontSize = 40
        self._modeFontSize = 20

        self._colors = {
            "BACKGROUND_COLOR": "#3c3c3c",
            "TEXT_COLOR": "#ffffff",
            "TEXT_COLOR_SECONDARY": "#becedd",
            "BORDER_COLOR": "#444444",
            "NORMAL_COLOR": "#00B060",
            "WARNING_COLOR": "#E6B800",
            "DANGER_COLOR": "#CC3333",
        }

        self.setMinimumSize(200, 90)
        self.setObjectName("CoilTemperatureWidget")

    # ------------------------------
    # QSS Properties
    # ------------------------------
    def getHeaderFontSize(self): return self._headerFontSize
    def setHeaderFontSize(self, v): self._headerFontSize = v; self.update()
    headerFontSize = Property(int, getHeaderFontSize, setHeaderFontSize)

    def getTempFontSize(self): return self._tempFontSize
    def setTempFontSize(self, v): self._tempFontSize = v; self.update()
    tempFontSize = Property(int, getTempFontSize, setTempFontSize)

    def getModeFontSize(self): return self._modeFontSize
    def setModeFontSize(self, v): self._modeFontSize = v; self.update()
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
        }
        self.update()

    # ------------------------------------------------------------------
    # Logic
    # ------------------------------------------------------------------
    def updateMode(self):
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
        mode_color = {
            self.NORMAL: QColor(c["NORMAL_COLOR"]),
            self.WARNING: QColor(c["WARNING_COLOR"]),
            self.DANGER: QColor(c["DANGER_COLOR"]),
        }[self.mode]

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)

        # background
        painter.setBrush(QColor(c["BACKGROUND_COLOR"]))
        painter.setPen(QPen(QColor(c["BORDER_COLOR"]), 1))
        painter.drawRoundedRect(rect, 6, 6)

        # bottom status bar
        bar_height = self.height() * 0.2
        painter.setBrush(mode_color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, self.height() - bar_height,
                                self.width(), bar_height, 0, 0)

        # --- Header label ---
        painter.setPen(QColor(c["TEXT_COLOR_SECONDARY"]))
        header_font = QFont("Tw Cen MT Condensed", self._headerFontSize)
        header_font.setBold(True)
        painter.setFont(header_font)
        painter.drawText(QRectF(10, self.height() * 0.05, self.width() - 20, self.height() * 0.18),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         "COIL TEMPERATURE")

        # --- Main temperature ---
        painter.setPen(QColor(c["TEXT_COLOR"]))
        temp_font = QFont("Tw Cen MT Condensed", self._tempFontSize)
        temp_font.setBold(True)
        painter.setFont(temp_font)
        painter.drawText(QRectF(10, self.height() * 0.33, self.width() - 20, self.height() * 0.5),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         f"{self.temperature:.1f} °C")

        # --- Mode indicator ---
        painter.setPen(mode_color)
        mode_font = QFont("Tw Cen MT Condensed", self._modeFontSize, QFont.Bold)
        painter.setFont(mode_font)
        mode_text = {self.NORMAL: "NORMAL", self.WARNING: "WARNING", self.DANGER: "DANGER"}[self.mode]
        painter.drawText(QRectF(0, self.height() * 0.33,
                                self.width() - 12, self.height() * 0.5),
                         Qt.AlignRight | Qt.AlignVCenter,
                         mode_text)

    def sizeHint(self):
        return self.minimumSizeHint()


from pathlib import Path
import sys
ROOT = Path(__file__).parent.parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from app.theme_manager import ThemeManager
from PySide6.QtGui import QFontDatabase, QFont

if __name__ == "__main__":
    app = QApplication(sys.argv)

    font_dir = SRC / "assets/fonts/Tw-Cen-MT-Condensed.ttf"
    font_id = QFontDatabase.addApplicationFont(str(font_dir))
    fam = QFontDatabase.applicationFontFamilies(font_id)
    if fam:
        app.setFont(QFont(fam[0]))

    # Initialize theme manager
    tm = ThemeManager(Path(SRC / "assets" / "styles" / "template.qss"), Path(SRC / "config"))

    win = QWidget()
    layout = QVBoxLayout(win)

    coil_temp = CoilTemperatureWidget(warning_threshold=30, danger_threshold=40)
    layout.addWidget(coil_temp)

    # apply dark theme via ThemeManager
    tm.apply(theme_name="light", app=app, stylesheet_target=win, also_call_applyTheme_on=win)

    coil_temp.setTemperature(20)

    win.resize(70, 50)
    win.show()
    sys.exit(app.exec())
