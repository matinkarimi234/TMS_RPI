from __future__ import annotations

import sys
from functools import partial
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QSpinBox, QCheckBox, QLineEdit
)

from hardware.uart_manager import UARTManager
from services.uart_service import UARTService
from services.command_manager import CommandManager
from services.rx_manager import RxManager


def add_checksum(frame15: bytes) -> bytes:
    if len(frame15) != 15:
        raise ValueError("Payload must be exactly 15 bytes before checksum")
    chk = sum(frame15) & 0xFF
    return frame15 + bytes([chk])


def make_telemetry(status_on: bool, intensity: int) -> bytes:
    intensity = max(0, min(65535, int(intensity)))
    hi = (intensity >> 8) & 0xFF
    lo = intensity & 0xFF
    payload = bytearray(15)
    payload[0] = 0x01 if status_on else 0x00
    payload[1] = hi
    payload[2] = lo
    return add_checksum(bytes(payload))


class UARTTestApp(QWidget):
    def __init__(self, port: str = "loop://", baud: int = 9600, timeout: float = 0.1):
        super().__init__()
        self.setWindowTitle("UART Unit Test App")

        # --- UI ----------------------------------------------------------------
        self.log = QTextEdit(readOnly=True)

        self.lbl_conn = QLabel("Disconnected")
        self.btn_open = QPushButton("Open")
        self.btn_close = QPushButton("Close")

        self.btn_start = QPushButton("Send START cmd")
        self.btn_stop = QPushButton("Send STOP cmd")

        self.intensity_spin = QSpinBox()
        self.intensity_spin.setRange(0, 65535)
        self.intensity_spin.setValue(120)
        self.chk_status_on = QCheckBox("Status ON")
        self.chk_status_on.setChecked(True)
        self.btn_send_telemetry = QPushButton("Inject Telemetry")

        self.btn_send_bad = QPushButton("Send BAD checksum")

        self.chk_auto = QCheckBox("Auto telemetry (10 Hz)")
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._send_auto_telemetry)

        self.port_edit = QLineEdit(port)
        self.baud_edit = QLineEdit(str(baud))
        self.timeout_edit = QLineEdit(str(timeout))

        # NEW: live RX trigger control
        self.rx_trig_spin = QSpinBox()
        self.rx_trig_spin.setRange(1, 256)
        self.rx_trig_spin.setValue(16)
        self.btn_apply_rx_trig = QPushButton("Apply RX Trigger")

        # layouts
        cn_lay = QHBoxLayout()
        cn_lay.addWidget(QLabel("Port:"))
        cn_lay.addWidget(self.port_edit)
        cn_lay.addWidget(QLabel("Baud:"))
        cn_lay.addWidget(self.baud_edit)
        cn_lay.addWidget(QLabel("Timeout:"))
        cn_lay.addWidget(self.timeout_edit)
        cn_lay.addWidget(QLabel("RX trig:"))
        cn_lay.addWidget(self.rx_trig_spin)
        cn_lay.addWidget(self.btn_apply_rx_trig)
        cn_lay.addWidget(self.btn_open)
        cn_lay.addWidget(self.btn_close)
        cn_lay.addWidget(self.lbl_conn)

        cmd_lay = QHBoxLayout()
        cmd_lay.addWidget(self.btn_start)
        cmd_lay.addWidget(self.btn_stop)

        tel_lay = QHBoxLayout()
        tel_lay.addWidget(QLabel("Intensity:"))
        tel_lay.addWidget(self.intensity_spin)
        tel_lay.addWidget(self.chk_status_on)
        tel_lay.addWidget(self.btn_send_telemetry)
        tel_lay.addWidget(self.btn_send_bad)
        tel_lay.addWidget(self.chk_auto)

        lay = QVBoxLayout(self)
        lay.addLayout(cn_lay)
        lay.addLayout(cmd_lay)
        lay.addLayout(tel_lay)
        lay.addWidget(self.log)

        # --- Managers ----------------------------------------------------------
        self.uart_m = UARTManager(port=port, baudrate=baud, timeout=timeout, rx_trigger_bytes=self.rx_trig_spin.value())
        self.uart_s = UARTService(self.uart_m)
        self.cmd_m = CommandManager()
        self.rx_m = RxManager(self.uart_s)

        # wiring: connection + errors + raw telemetry
        self.uart_s.connection_status_changed.connect(self._on_conn)
        self.uart_s.error.connect(self._on_error)
        self.uart_s.telemetry_updated.connect(self._on_rx_raw)

        # decoded telemetry
        self.rx_m.tms_status.connect(self._on_status)
        self.rx_m.intensity_reading.connect(self._on_intensity)

        # commands (15B -> add checksum -> send)
        self.cmd_m.packet_ready.connect(self._send_with_checksum)

        # buttons
        self.btn_open.clicked.connect(self._open_clicked)
        self.btn_close.clicked.connect(self.uart_s.close)
        self.btn_start.clicked.connect(partial(self.cmd_m.build_start_tms, self.intensity_spin.value(), 200))
        self.btn_stop.clicked.connect(self.cmd_m.build_stop_tms)
        self.btn_send_telemetry.clicked.connect(self._send_one_telemetry)
        self.btn_send_bad.clicked.connect(self._send_bad)
        self.chk_auto.toggled.connect(self._toggle_auto)
        self.btn_apply_rx_trig.clicked.connect(self._apply_rx_trigger)

    # --- connection & logging -------------------------------------------------
    def _open_clicked(self):
        try:
            port = self.port_edit.text().strip()
            baud = int(self.baud_edit.text().strip())
            timeout = float(self.timeout_edit.text().strip())
        except Exception:
            self._append("Invalid port/baud/timeout inputs.")
            return

        try:
            self.uart_s.close()
        except Exception:
            pass

        # Recreate with current UI values, including RX trigger
        self.uart_m = UARTManager(port=port, baudrate=baud, timeout=timeout, rx_trigger_bytes=self.rx_trig_spin.value())
        self.uart_s = UARTService(self.uart_m)

        # rewire
        self.uart_s.connection_status_changed.connect(self._on_conn)
        self.uart_s.error.connect(self._on_error)
        self.uart_s.telemetry_updated.connect(self._on_rx_raw)

        self.rx_m = RxManager(self.uart_s)
        self.rx_m.tms_status.connect(self._on_status)
        self.rx_m.intensity_reading.connect(self._on_intensity)

        try:
            self.cmd_m.packet_ready.disconnect()
        except Exception:
            pass
        self.cmd_m.packet_ready.connect(self._send_with_checksum)

        self.uart_s.open()

    def _on_conn(self, ok: bool):
        self.lbl_conn.setText("Connected" if ok else "Disconnected")
        self._append(f"[conn] {'Connected' if ok else 'Disconnected'}")

    def _on_error(self, msg: str):
        self._append(f"[ERROR] {msg}")

    def _on_rx_raw(self, pkt: bytes):
        self._append(f"[rx] {pkt.hex(' ')}")

    def _on_status(self, on: bool):
        self._append(f"[decoded] TMS status: {'ON' if on else 'OFF'}")

    def _on_intensity(self, val: int):
        self._append(f"[decoded] Intensity: {val}")

    def _append(self, line: str):
        self.log.append(line)

    # --- config actions -------------------------------------------------------
    def _apply_rx_trigger(self):
        val = self.rx_trig_spin.value()
        self.uart_m.rx_trigger_bytes = val
        self._append(f"[cfg] rx_trigger_bytes = {self.uart_m.rx_trigger_bytes}")

    # --- sending helpers ------------------------------------------------------
    def _send_with_checksum(self, frame15: bytes):
        try:
            frame16 = add_checksum(frame15)
            self.uart_s.send(frame16)
            self._append(f"[tx cmd] {frame16.hex(' ')}")
        except Exception as e:
            self._append(f"[ERROR] send_with_checksum: {e}")

    def _send_one_telemetry(self):
        frame16 = make_telemetry(self.chk_status_on.isChecked(), self.intensity_spin.value())
        self.uart_s.send(frame16)
        self._append(f"[tx tel] {frame16.hex(' ')}")

    def _send_bad(self):
        good = make_telemetry(True, self.intensity_spin.value())
        bad = good[:-1] + b"\x00"
        self.uart_s.send(bad)
        self._append(f"[tx BAD] {bad.hex(' ')}")

    def _toggle_auto(self, on: bool):
        if on:
            self.timer.start()
        else:
            self.timer.stop()

    def _send_auto_telemetry(self):
        v = (self.intensity_spin.value() + 50) % 1000
        self.intensity_spin.setValue(v)
        self._send_one_telemetry()

    def closeEvent(self, e):
        try:
            self.timer.stop()
            self.uart_s.close()
        except Exception:
            pass
        super().closeEvent(e)


if __name__ == "__main__":
    port = "loop://"
    baud = 9600
    if len(sys.argv) >= 2:
        port = sys.argv[1]
    if len(sys.argv) >= 3:
        baud = int(sys.argv[2])

    app = QApplication(sys.argv)
    w = UARTTestApp(port=port, baud=baud, timeout=0.1)
    w.resize(780, 520)
    w.show()
    sys.exit(app.exec())
