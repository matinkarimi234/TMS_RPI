# theme_manager.py
from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Optional
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication, QWidget

class ThemeManager:
    """
    Loads a QSS template + theme json and can:
      - generate a stylesheet
      - build a QPalette
      - apply palette app-wide and stylesheet to a single widget (e.g., your main window)
      - call .applyTheme(self, theme_name) on custom widgets recursively
    """
    def __init__(self, template_path: Path, themes_dir: Path):
        self.template_path = Path(template_path)
        self.themes_dir = Path(themes_dir)
        self.template_content = self.template_path.read_text(encoding="utf-8")
        self._cache: Dict[str, Dict[str, str]] = {}

    def _load_theme_data(self, theme_name: str) -> Dict[str, str]:
        if theme_name in self._cache:
            return self._cache[theme_name]
        theme_file = self.themes_dir / f"{theme_name}_theme.json"
        data = json.loads(theme_file.read_text(encoding="utf-8"))
        self._cache[theme_name] = data
        return data

    # NEW: for your widgets' applyTheme() hooks
    def get_color(self, theme_name: str, key: str, default: Optional[str] = None) -> Optional[str]:
        return self._load_theme_data(theme_name).get(key, default)

    def generate_stylesheet(self, theme_name: str) -> str:
        theme = self._load_theme_data(theme_name)
        ss = self.template_content
        for k, v in theme.items():
            ss = ss.replace(f"{{{{{k}}}}}", v)
        return ss

    def generate_palette(self, theme_name: str) -> QPalette:
        t = self._load_theme_data(theme_name)
        pal = QPalette()
        pal.setColor(QPalette.Window,          QColor(t["BACKGROUND_COLOR"]))
        pal.setColor(QPalette.WindowText,      QColor(t["TEXT_COLOR"]))
        pal.setColor(QPalette.Base,            QColor(t["BACKGROUND_COLOR"]))
        pal.setColor(QPalette.AlternateBase,   QColor(t["BORDER_COLOR"]))
        pal.setColor(QPalette.Text,            QColor(t["TEXT_COLOR"]))
        pal.setColor(QPalette.Button,          QColor(t["BACKGROUND_COLOR"]))
        pal.setColor(QPalette.ButtonText,      QColor(t["TEXT_COLOR"]))
        pal.setColor(QPalette.Highlight,       QColor(t["ACCENT_COLOR"]))
        pal.setColor(QPalette.HighlightedText, QColor(t["TEXT_COLOR_SELECTED"]))
        try:  # Qt6 only; harmless in older builds
            pal.setColor(QPalette.Accent, QColor(t["ACCENT_COLOR"]))
        except Exception:
            pass
        return pal

    def apply(
        self,
        *,
        theme_name: str,
        app: Optional[QApplication] = None,
        stylesheet_target: Optional[QWidget] = None,
        also_call_applyTheme_on: Optional[QWidget] = None,
    ) -> None:
        """Palette -> app; QSS -> stylesheet_target (e.g., main only); call .applyTheme on custom widgets."""
        if app is not None:
            app.setPalette(self.generate_palette(theme_name))
        if stylesheet_target is not None:
            stylesheet_target.setStyleSheet(self.generate_stylesheet(theme_name))
        if also_call_applyTheme_on is not None:
            self._propagate_applyTheme(also_call_applyTheme_on, theme_name)

    def _propagate_applyTheme(self, root: QWidget, theme_name: str) -> None:
        # call on root if present
        if hasattr(root, "applyTheme"):
            try:
                root.applyTheme(self, theme_name)  # type: ignore[attr-defined]
            except Exception:
                pass
        # then on children
        for child in root.findChildren(QWidget):
            if hasattr(child, "applyTheme"):
                try:
                    child.applyTheme(self, theme_name)  # type: ignore[attr-defined]
                except Exception:
                    pass
