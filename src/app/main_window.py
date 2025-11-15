import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QStackedWidget,
    QSizePolicy
)



# ─── allow imports from src/ ────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.resolve()
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from app.theme_manager import ThemeManager
from core._Archive.protocol_manager import ProtocolManager
from app.Main_Page import ParamsPage

class MainWindow(QMainWindow):
    def __init__(self, protocol_json: Path, theme_manager: ThemeManager, initial_theme="dark"):
        super().__init__()
        self.setWindowTitle("TMS Control Interface")
        self.resize(320, 480)

        self.pm = ProtocolManager()
        self.pm.load_from_json(protocol_json)

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCentralWidget(self.stack)

        self.params = ParamsPage(theme_manager, initial_theme)
        self.params.request_protocol_list.connect(self._show_list)

        self.plist = ProtocolListPage(self.pm)
        self.plist.accepted.connect(self._choose)
        self.plist.canceled.connect(self._show_params)

        self.stack.addWidget(self.params)
        self.stack.addWidget(self.plist)
        self._show_params()

        self.resize(800, 600)
        self.setMinimumSize(320, 480)

        # load first protocol by default
        names = self.pm.list_protocols()
        if names:
            self._load(names[0])

    def _show_params(self):
        self.stack.setCurrentWidget(self.params)

    def _show_list(self):
        self.stack.setCurrentWidget(self.plist)

    def _choose(self, name: str):
        self._load(name)
        self._show_params()

    def _load(self, name: str):
        proto = self.pm.get_protocol(name)
        if proto:
            self.params.set_protocol(proto)
