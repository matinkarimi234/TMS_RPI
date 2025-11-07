# tools/gpio_test_app.py
from pathlib import Path
from __future__ import annotations
import sys
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QTextEdit, QPushButton, QHBoxLayout

# ─── allow imports from src/ ────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from services.gpio_service import GPIOService, EncoderSpec

# buttons on 17/22, encoder on A=5, B=6 (like your Tk code)
BUTTON_PINS = [17, 22]
ENCODERS = [EncoderSpec(a_pin=5, b_pin=6, id=1, invert=False, edge_rising_only=True, debounce_ms=1)]

class GPIODemo(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GPIO + Encoder Tester")

        self.lbl_status = QLabel("Status: idle")
        self.log = QTextEdit(readOnly=True)
        self.btn_start = QPushButton("Start service")
        self.btn_stop = QPushButton("Stop service")

        row = QHBoxLayout()
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_stop)

        lay = QVBoxLayout(self)
        lay.addWidget(self.lbl_status)
        lay.addLayout(row)
        lay.addWidget(self.log)

        self.gpio = GPIOService(
            pins=BUTTON_PINS,
            encoders=ENCODERS,
            pull_up=True,
            button_bouncetime_ms=200,
        )
        self.gpio.ready.connect(lambda: self._set_status("ready (listening)"))
        self.gpio.stopped.connect(lambda: self._set_status("stopped"))
        self.gpio.error.connect(self._on_error)
        self.gpio.button_pressed.connect(lambda pin: self._append(f"BTN {pin}: PRESSED"))
        self.gpio.button_released.connect(lambda pin: self._append(f"BTN {pin}: RELEASED"))
        self.gpio.encoder_step.connect(self._on_enc)

        self.btn_start.clicked.connect(self.gpio.start)
        self.btn_stop.clicked.connect(self.gpio.stop)

    def _set_status(self, s: str) -> None:
        self.lbl_status.setText(f"Status: {s}")
        self._append(f"[status] {s}")

    def _append(self, text: str) -> None:
        self.log.append(text)

    def _on_error(self, msg: str) -> None:
        self._append(f"ERROR: {msg}")

    def _on_enc(self, enc_id: int, step: int) -> None:
        dir_txt = "CW" if step > 0 else "CCW"
        self._append(f"ENC#{enc_id}: step {step} ({dir_txt})")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = GPIODemo()
    w.resize(480, 320)
    w.show()
    sys.exit(app.exec())
