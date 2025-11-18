# main_window.py (or wherever your MainWindow class lives)

import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QStackedWidget,
    QSizePolicy
)

from app.theme_manager import ThemeManager
from core.protocol_manager_revised import ProtocolManager
from ui.pages.Main_Page import ParamsPage
from ui.pages.Protocol_Page import ProtocolListPage
from services.uart_backend import Uart_Backend
from services.gpio_backend import GPIO_Backend   # NEW

from config.settings import (
    UART_PORT,
    UART_BAUDRATE,
    UART_TIMEOUT,
    UART_RX_SIZE,
    SCREEN_RESOLUTION_W,
    SCREEN_RESOLUTION_H,
)


class MainWindow(QMainWindow):
    def __init__(self, protocol_json: Path, theme_manager: ThemeManager, initial_theme="dark"):
        super().__init__()
        self.setWindowTitle("TMS Control Interface")
        self.resize(320, 480)

        # ---------------- UART stack (single instance) ----------------
        self.uart_backend = Uart_Backend(
            port=UART_PORT,
            baudrate=UART_BAUDRATE,
            timeout=UART_TIMEOUT,
            rx_trigger_bytes=UART_RX_SIZE,
        )
        self.uart_backend.open()   # or expose a button later

        # (optional) log errors / connection
        self.uart_backend.connectionChanged.connect(self._on_backend_conn)
        self.uart_backend.errorOccurred.connect(self._on_backend_error)
        # --------------------------------------------------------------

        # ---------------- GPIO backend (single instance) --------------
        self.gpio_backend = GPIO_Backend(parent=self)
        # Optional logging
        self.gpio_backend.errorOccurred.connect(self._on_gpio_error)
        self.gpio_backend.ready.connect(self._on_gpio_ready)
        self.gpio_backend.stopped.connect(self._on_gpio_stopped)
        # Start listening for buttons/encoder
        self.gpio_backend.start()
        # --------------------------------------------------------------

        # existing protocol/theme/gui setup
        self.pm = ProtocolManager()
        self.pm.load_from_json(protocol_json)

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCentralWidget(self.stack)

        # Main parameters page, now using GPIO_Backend
        self.params = ParamsPage(theme_manager, gpio_backend=self.gpio_backend, initial_theme=initial_theme)
        self.params.request_protocol_list.connect(self._show_list)

        self.params.bind_backend(self.uart_backend)

        # Protocol list page
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

    # ------------------------------------------------------------------
    #   UART backend logging
    # ------------------------------------------------------------------
    def _on_backend_conn(self, ok: bool):
        print("[BACKEND]", "Connected" if ok else "Disconnected")

    def _on_backend_error(self, msg: str):
        print("[BACKEND ERROR]", msg)

    # ------------------------------------------------------------------
    #   GPIO backend logging
    # ------------------------------------------------------------------
    def _on_gpio_ready(self):
        print("[GPIO] Ready")

    def _on_gpio_error(self, msg: str):
        print("[GPIO ERROR]", msg)

    def _on_gpio_stopped(self):
        print("[GPIO] Stopped")

    # ------------------------------------------------------------------
    #   Navigation & protocol load
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    #   Clean shutdown (optional but recommended)
    # ------------------------------------------------------------------
    def closeEvent(self, event):
        try:
            # Close GPIO backend
            if self.gpio_backend is not None:
                self.gpio_backend.stop()
        except Exception:
            pass
        try:
            # Close UART backend
            if self.uart_backend is not None:
                self.uart_backend.close()
        except Exception:
            pass
        super().closeEvent(event)


__all__ = ["MainWindow"]
