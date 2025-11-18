import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QStackedWidget,
    QSizePolicy
)



# ─── allow imports from src/ ────────────────────────────────────
# PROJECT_ROOT = Path(__file__).parent.resolve()
# SRC = PROJECT_ROOT / "src"
# if str(SRC) not in sys.path:
#     sys.path.insert(0, str(SRC))


from app.theme_manager import ThemeManager
from core.protocol_manager_revised import ProtocolManager
from ui.pages.Main_Page import ParamsPage
from services.gpio_service import GPIOService, EncoderSpec
from ui.pages.Protocol_Page import ProtocolListPage
#from workers.mock_gpio_service import MockGPIOService
from services.uart_backend import Uart_Backend

from config.settings import UART_PORT, UART_BAUDRATE, UART_TIMEOUT, UART_RX_SIZE
from config.settings import SCREEN_RESOLUTION_W, SCREEN_RESOLUTION_H

from config.settings import RED_LED_PIN, GREEN_LED_PIN
from config.settings import BUTTONS
from config.settings import CONTROL_ENC_P_PIN, CONTROL_ENC_N_PIN

encoders = [EncoderSpec(a_pin=CONTROL_ENC_P_PIN, b_pin=CONTROL_ENC_N_PIN, id=1, invert=False, edge_rising_only=True, debounce_ms=1)]
gpio = GPIOService(pins=BUTTONS, encoders=encoders, pull_up=True, button_bouncetime_ms=200)

class MainWindow(QMainWindow):
    def __init__(self, protocol_json: Path, theme_manager: ThemeManager, initial_theme="dark"):
        super().__init__()
        self.setWindowTitle("TMS Control Interface")
        self.resize(320, 480)

        # ---------------- UART stack (single instance) ----------------
        # Adjust port/baud/timeout as needed
        self.uart_backend = Uart_Backend(
            port = UART_PORT,
            baudrate=UART_BAUDRATE,
            timeout=UART_TIMEOUT,
            rx_trigger_bytes=UART_RX_SIZE,
        )
        self.uart_backend.open()   # or expose a button later

        # (optional) log errors / connection
        self.uart_backend.connectionChanged.connect(self._on_backend_conn)
        self.uart_backend.errorOccurred.connect(self._on_backend_error)
        # --------------------------------------------------------------
        # existing protocol/theme/gui setup
        self.pm = ProtocolManager()
        self.pm.load_from_json(protocol_json)

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCentralWidget(self.stack)
        
        gpio_mock = MockGPIOService()
        self.params = ParamsPage(theme_manager, gpio_mock, initial_theme)
        self.params.request_protocol_list.connect(self._show_list)

        self.params.bind_backend(self.backend)

        self.plist = ProtocolListPage(self.pm)
        self.plist.accepted.connect(self._choose)
        self.plist.canceled.connect(self._show_params)

        self.stack.addWidget(self.params)
        self.stack.addWidget(self.plist)
        self._show_params()

        self.resize(SCREEN_RESOLUTION_W, SCREEN_RESOLUTION_H)
        self.setMinimumSize(SCREEN_RESOLUTION_W, SCREEN_RESOLUTION_H)

        # load first protocol by default
        names = self.pm.list_protocols()
        if names:
            self._load(names[0])

    def _on_backend_conn(self, ok: bool):
        print("[BACKEND]", "Connected" if ok else "Disconnected")

    def _on_backend_error(self, msg: str):
        print("[BACKEND ERROR]", msg)


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

    def set_coil_temp(self, temp: float):
        self.params.set_coil_temperature(temp)


__all__ = ["MainWindow"]
