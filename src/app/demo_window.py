import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from app.theme_manager import ThemeManager
from hardware.uart_manager import UARTManager
from services.gpio_service import GPIOService, EncoderSpec  # <<< NEW import
from services.uart_service import UARTService
from services.command_manager import CommandManager
from services.rx_manager import RxManager

from PySide6.QtWidgets import (
    QWidget, QPushButton, QTextEdit,
    QVBoxLayout, QLabel, QHBoxLayout
)
from ui.widgets.connection_indicator import ConnectionIndicator


class MainWindow(QWidget):
    def __init__(self, uart_service, cmd_mgr, rx_mgr, gpio_svc):
        super().__init__()
        self.uart = uart_service
        self.cmd_mgr = cmd_mgr
        self.rx_mgr = rx_mgr
        self.gpio = gpio_svc

        self.setWindowTitle("TMS Neuro Control")

        # top row: indicator + connect/disconnect
        self.conn_indicator = ConnectionIndicator()
        self.btn_connect    = QPushButton("Connect UART")
        self.btn_disconnect = QPushButton("Disconnect UART")

        # status display
        self.lbl_status    = QLabel("TMS OFF")
        self.lbl_intensity = QLabel("Intensity: 0")

        # log area
        self.log = QTextEdit(readOnly=True)

        top_layout = QHBoxLayout()
        top_layout.addWidget(self.conn_indicator)
        top_layout.addWidget(self.btn_connect)
        top_layout.addWidget(self.btn_disconnect)

        info_layout = QHBoxLayout()
        info_layout.addWidget(self.lbl_status)
        info_layout.addWidget(self.lbl_intensity)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(top_layout)
        main_layout.addLayout(info_layout)
        main_layout.addWidget(self.log)

        # wire buttons
        self.btn_connect.clicked.connect(self.uart.connect)
        self.btn_disconnect.clicked.connect(self.uart.disconnect)

        # when command ready, send via UARTService
        self.cmd_mgr.packet_ready.connect(self.uart.send)

        # GPIO → build commands
        self.gpio.button_pressed.connect(self._on_button_press)

        # OPTIONAL: log encoder steps (A=5, B=6)
        if hasattr(self.gpio, "encoder_step"):
            self.gpio.encoder_step.connect(self._on_encoder_step)

        # update indicator & blink on RX
        self.uart.connection_status_changed.connect(self.conn_indicator.set_connected)
        self.uart.data_received.connect(lambda _: self.conn_indicator.blink())

        # parse telemetry → update UI
        self.rx_mgr.tms_status.connect(self._update_status)
        self.rx_mgr.intensity_reading.connect(self._update_intensity)

        # log errors
        self.uart.error.connect(self._on_error)
        if hasattr(self.gpio, "error"):
            self.gpio.error.connect(lambda msg: self.log.append(f"GPIO ERROR: {msg}"))

    def _on_button_press(self, pin: int):
        if pin == 17:
            self.log.append("Start button pressed")
            self.cmd_mgr.build_start_tms(intensity=120, duration_ms=200)
        elif pin == 22:
            self.log.append("Stop button pressed")
            self.cmd_mgr.build_stop_tms()

    def _on_encoder_step(self, enc_id: int, step: int):
        # step: +1 (CW) / -1 (CCW)
        direction = "CW" if step > 0 else "CCW"
        self.log.append(f"Encoder {enc_id}: step {step} ({direction})")

    def _update_status(self, on: bool):
        txt = "TMS ON" if on else "TMS OFF"
        self.lbl_status.setText(txt)
        self.log.append(f"Status: {txt}")

    def _update_intensity(self, val: int):
        self.lbl_intensity.setText(f"Intensity: {val}")
        self.log.append(f"Intensity reading: {val}")

    def _on_error(self, msg: str):
        self.log.append(f"ERROR: {msg}")


if __name__ == "__main__":
    app = QApplication(sys.argv)

    ROOT = Path(__file__).parent
    tpl = ROOT / "assets" / "styles" / "template.qss"
    cfg = ROOT / "config"
    theme_mgr = ThemeManager(template_path=tpl, themes_dir=cfg)
    # if your ThemeManager needs applying, do it here (API depends on your implementation):
    theme_mgr.apply(app, "dark")

    # low‐level
    uart_m = UARTManager()
    uart_s = UARTService(uart_m)

    # GPIO (buttons on 17/22; encoder A=5, B=6)
    gpio_s = GPIOService(
        pins=[17, 22],
        encoders=[EncoderSpec(a_pin=5, b_pin=6, id=1, invert=False, edge_rising_only=True, debounce_ms=1)],
        pull_up=True,
        button_bouncetime_ms=200,
    )
    gpio_s.start()  # <<< start the background GPIO thread
    app.aboutToQuit.connect(gpio_s.stop)

    # command + parser
    cmd_m = CommandManager()
    rx_m  = RxManager(uart_s)

    # main UI
    w = MainWindow(uart_s, cmd_m, rx_m, gpio_s)
    w.resize(400, 300)
    w.show()

    # auto‐connect UART
    uart_s.connect()

    sys.exit(app.exec())
