import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase, QFont
from app.theme_manager import ThemeManager
from ui.main_window import MainWindow

ROOT = Path(__file__).parent
SRC = ROOT / "src"

def main():
    app = QApplication(sys.argv)
    font_dir = ROOT / "assets/fonts/Ubuntu-Regular.ttf"
    font_id = QFontDatabase.addApplicationFont(str(font_dir))
    fam = QFontDatabase.applicationFontFamilies(font_id)
    if fam:
        app.setFont(QFont(fam[0]))

    theme_tpl   = ROOT / "assets/styles/template.qss"
    theme_dir   = ROOT / "config"
    protocol_js = ROOT / "protocols.json"

    theme_mgr = ThemeManager(template_path=theme_tpl, themes_dir=theme_dir)
    win = MainWindow(protocol_json=protocol_js, theme_manager=theme_mgr)
    win.set_coil_temp(20.1)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()