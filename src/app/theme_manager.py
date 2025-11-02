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
        self.template_content = self.template_path.read_text()

    def _load_theme_data(self, theme_name: str) -> dict:
        theme_file = self.themes_dir / f"{theme_name}_theme.json"
        data = json.loads(theme_file.read_text())
        return data

    def generate_stylesheet(self, theme_name: str) -> str:
        theme = self._load_theme_data(theme_name)
        ss = self.template_content
        for k,v in theme.items():
            ss = ss.replace(f"{{{{{k}}}}}", v)
        return ss

    def generate_palette(self, theme_name: str) -> QPalette:
        theme = self._load_theme_data(theme_name)
        pal = QPalette()
        pal.setColor(QPalette.Window,        QColor(theme["BACKGROUND_COLOR"]))
        pal.setColor(QPalette.WindowText,    QColor(theme["TEXT_COLOR"]))
        pal.setColor(QPalette.Base,          QColor(theme["BACKGROUND_COLOR"]))
        pal.setColor(QPalette.AlternateBase, QColor(theme["BORDER_COLOR"]))
        pal.setColor(QPalette.Text,          QColor(theme["TEXT_COLOR"]))
        pal.setColor(QPalette.Button,        QColor(theme["BACKGROUND_COLOR"]))
        pal.setColor(QPalette.ButtonText,    QColor(theme["TEXT_COLOR"]))
        pal.setColor(QPalette.Highlight,     QColor(theme["ACCENT_COLOR"]))
        pal.setColor(QPalette.HighlightedText, QColor(theme["TEXT_COLOR_SELECTED"]))
        try:
            pal.setColor(QPalette.Accent, QColor(theme["ACCENT_COLOR"]))
        except Exception:
            pass
        return pal
