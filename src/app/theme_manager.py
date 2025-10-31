import json
from pathlib import Path
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication

class ThemeManager:
    """
    Manages loading and applying themes by combining a QSS template
    with color values from JSON configuration files.  Also builds
    a QPalette for widgets that draw from the palette instead of style sheets.
    """
    def __init__(self, template_path: Path, themes_dir: Path):
        self.template_path = template_path
        self.themes_dir = themes_dir

        try:
            self.template_content = self.template_path.read_text()
        except FileNotFoundError:
            raise RuntimeError(f"Theme template not found at {self.template_path}")

    def _load_theme_data(self, theme_name: str) -> dict:
        theme_config_path = self.themes_dir / f"{theme_name}_theme.json"
        try:
            return json.loads(theme_config_path.read_text())
        except FileNotFoundError:
            raise RuntimeError(f"Theme config not found: {theme_config_path}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON in {theme_config_path}: {e}")

    def generate_stylesheet(self, theme_name: str) -> str:
        """
        Generates a complete QSS string for a given theme.
        """
        theme_data = self._load_theme_data(theme_name)

        ss = self.template_content
        for key, value in theme_data.items():
            placeholder = f"{{{{{key}}}}}"
            ss = ss.replace(placeholder, value)

        return ss

    def generate_palette(self, theme_name: str) -> QPalette:
        """
        Builds a QPalette from the same JSON data.  You can
        adjust which roles you want to set here.
        """
        theme_data = self._load_theme_data(theme_name)
        pal = QPalette()

        # fill in the standard roles from JSON keys
        pal.setColor(QPalette.Window,        QColor(theme_data["BACKGROUND_COLOR"]))
        pal.setColor(QPalette.WindowText,    QColor(theme_data["TEXT_COLOR"]))
        pal.setColor(QPalette.Base,          QColor(theme_data["BACKGROUND_COLOR"]))
        pal.setColor(QPalette.AlternateBase, QColor(theme_data["BORDER_COLOR"]))
        pal.setColor(QPalette.Text,          QColor(theme_data["TEXT_COLOR"]))
        pal.setColor(QPalette.Button,        QColor(theme_data["BACKGROUND_COLOR"]))
        pal.setColor(QPalette.ButtonText,    QColor(theme_data["TEXT_COLOR"]))
        pal.setColor(QPalette.Highlight,     QColor(theme_data["ACCENT_COLOR"]))
        pal.setColor(QPalette.HighlightedText, QColor(theme_data["TEXT_COLOR_SELECTED"]))

        # if you really are on Qt ≥ 6.2 and want to set the new Accent role:
        try:
            pal.setColor(QPalette.Accent, QColor(theme_data["ACCENT_COLOR"]))
        except AttributeError:
            # Accent role may not exist on older Qt versions
            pass

        return pal
