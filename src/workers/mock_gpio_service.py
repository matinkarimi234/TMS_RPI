# services/gpio_mock.py
from __future__ import annotations

from typing import Any, List, Optional

from PySide6.QtCore import QObject, Signal, QTimer, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from config.settings import (
    ARROW_UP_BUTTON_PIN,
    ARROW_DOWN_BUTTON_PIN,
    START_PAUSE_BUTTON_PIN,
)

# This mock ignores the 'pins', 'encoders', 'controller' arguments,
# but keeps the same signature as the real GPIOService so the backend
# can use it transparently.


class MockGPIOService(QObject):
    """
    Desktop-safe simulation of the real GPIOService.

    - Maps keyboard keys to "pins":
        ↑  -> ARROW_UP_BUTTON_PIN
        ↓  -> ARROW_DOWN_BUTTON_PIN
        Space -> START_PAUSE_BUTTON_PIN
    - Left / Right arrow keys simulate encoder steps.
    """

    # mimic real GPIOService signals
    encoder_step = Signal(int, int)  # (encoder_id, step)
    button_pressed = Signal(int)     # pin
    button_released = Signal(int)    # pin

    error = Signal(str)
    ready = Signal()
    stopped = Signal()

    def __init__(
        self,
        *,
        pins: Optional[List[int]] = None,
        encoders: Optional[List[Any]] = None,
        pull_up: bool = True,
        button_bouncetime_ms: int = 200,
        controller: Any = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._pins = pins or []
        self._encoders = encoders or []
        self._pull_up = pull_up
        self._bouncetime = button_bouncetime_ms
        self._controller = controller

        # map keyboard keys to *real* pins from config
        self._key_to_pin = {
            Qt.Key_Up: ARROW_UP_BUTTON_PIN,
            Qt.Key_Down: ARROW_DOWN_BUTTON_PIN,
            Qt.Key_Space: START_PAUSE_BUTTON_PIN,
        }

        self._last_keys = set()
        self._running = False

        self._attach_keyboard_event_filter()

    # ----------------------------------------------------------------
    #   Lifecycle
    # ----------------------------------------------------------------
    def start(self) -> None:
        """Simulate starting the service; emit ready shortly after."""
        if self._running:
            return
        self._running = True
        # Tiny delay so UI that connects after start() still sees ready
        QTimer.singleShot(10, self.ready.emit)

    def stop(self) -> None:
        """Simulate stopping the service."""
        if not self._running:
            return
        self._running = False
        self.stopped.emit()

    # ----------------------------------------------------------------
    #   Keyboard mapping
    # ----------------------------------------------------------------
    def _attach_keyboard_event_filter(self):
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self)

    def eventFilter(self, obj, event):
        if not self._running:
            return super().eventFilter(obj, event)

        if isinstance(event, QKeyEvent):
            if event.type() == QKeyEvent.KeyPress and not event.isAutoRepeat():
                self._on_key_press(event.key())
            elif event.type() == QKeyEvent.KeyRelease and not event.isAutoRepeat():
                self._on_key_release(event.key())
        return super().eventFilter(obj, event)

    def _on_key_press(self, key: int) -> None:
        if key in self._key_to_pin and key not in self._last_keys:
            self._last_keys.add(key)
            pin = self._key_to_pin[key]
            self.button_pressed.emit(pin)
        elif key == Qt.Key_Right:
            # simulate encoder clockwise step; use encoder id 0
            self.encoder_step.emit(0, +1)
        elif key == Qt.Key_Left:
            # simulate encoder counter-clockwise step
            self.encoder_step.emit(0, -1)

    def _on_key_release(self, key: int) -> None:
        if key in self._last_keys:
            self._last_keys.remove(key)
            pin = self._key_to_pin.get(key)
            if pin is not None:
                self.button_released.emit(pin)

    # ----------------------------------------------------------------
    #   Manual Simulation Helpers (optional)
    # ----------------------------------------------------------------
    def simulate_encoder_turn(self, encoder_id: int = 0, step: int = +1, interval_ms: int = 0):
        """Emit an encoder step immediately or after a delay."""
        if interval_ms <= 0:
            self.encoder_step.emit(encoder_id, step)
        else:
            QTimer.singleShot(interval_ms, lambda: self.encoder_step.emit(encoder_id, step))

    def simulate_button_press(self, pin: int, interval_ms: int = 0):
        """Emit a button press immediately or after a delay."""
        if interval_ms <= 0:
            self.button_pressed.emit(pin)
        else:
            QTimer.singleShot(interval_ms, lambda: self.button_pressed.emit(pin))

    def simulate_button_release(self, pin: int, interval_ms: int = 0):
        """Emit a button release immediately or after a delay."""
        if interval_ms <= 0:
            self.button_released.emit(pin)
        else:
            QTimer.singleShot(interval_ms, lambda: self.button_released.emit(pin))
