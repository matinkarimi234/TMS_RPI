from PySide6.QtCore import QObject, Signal, QTimer, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication


class MockGPIOService(QObject):
    """
    Desktop-safe simulation of the real GPIOService.

    Emits:
        encoder_step(int id, int step)
        button_pressed(int pin)
        button_released(int pin)
    """

    encoder_step = Signal(int, int)
    button_pressed = Signal(int)
    button_released = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._key_to_pin = {
            Qt.Key_Up: 17,       # map keyboard UP to pin 17 (List Up)
            Qt.Key_Down: 22,     # DOWN to pin 22 (List Down)
            Qt.Key_Space: 23,    # SPACE for a “select” or other function
        }
        self._last_keys = set()
        self._attach_keyboard_event_filter()

    # ----------------------------------------------------------------
    #   Keyboard mapping
    # ----------------------------------------------------------------
    def _attach_keyboard_event_filter(self):
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self)

    def eventFilter(self, obj, event):
        if isinstance(event, QKeyEvent):
            if event.type() == QKeyEvent.KeyPress and not event.isAutoRepeat():
                self._on_key_press(event.key())
            elif event.type() == QKeyEvent.KeyRelease and not event.isAutoRepeat():
                self._on_key_release(event.key())
        return super().eventFilter(obj, event)

    def _on_key_press(self, key):
        if key in self._key_to_pin and key not in self._last_keys:
            self._last_keys.add(key)
            pin = self._key_to_pin[key]
            self.button_pressed.emit(pin)
        elif key == Qt.Key_Right:
            self.encoder_step.emit(1, +1)   # simulate clockwise step
        elif key == Qt.Key_Left:
            self.encoder_step.emit(1, -1)   # simulate counterclockwise step

    def _on_key_release(self, key):
        if key in self._last_keys:
            self._last_keys.remove(key)
            pin = self._key_to_pin.get(key)
            if pin:
                self.button_released.emit(pin)

    # ----------------------------------------------------------------
    #   Automated Simulation (optional)
    # ----------------------------------------------------------------
    def simulate_encoder_turn(self, encoder_id: int = 1, step: int = +1, interval_ms: int = 0):
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
