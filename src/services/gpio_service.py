# services/gpio_service.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from PySide6.QtCore import QObject, Signal, Slot, QThread

from hardware.gpio_controller import GPIOController


@dataclass(frozen=True)
class EncoderSpec:
    """Quadrature encoder using A and B channels."""
    a_pin: int
    b_pin: int
    id: int = 0               # optional identifier if you have multiple encoders
    invert: bool = False      # flip direction if wiring is opposite
    edge_rising_only: bool = True
    debounce_ms: int = 1      # very small debounce for encoders


class GPIOSignals(QObject):
    button_pressed = Signal(int)           # pin
    button_released = Signal(int)          # pin
    encoder_step = Signal(int, int)        # (encoder_id, +1/-1)
    error = Signal(str)
    ready = Signal()
    stopped = Signal()


class _GPIOWorker(QObject):
    """
    Worker running in a dedicated QThread to handle GPIO events.
    """

    def __init__(
        self,
        button_pins: Sequence[int],
        encoders: Sequence[EncoderSpec],
        *,
        pull_up: bool,
        button_bounce_ms: int,
        controller: GPIOController,
    ):
        super().__init__()
        self._buttons = list(button_pins)
        self._encoders = list(encoders)
        self._pull_up = bool(pull_up)
        self._btn_bounce = max(0, int(button_bounce_ms))
        self._ctl = controller
        self.signals = GPIOSignals()
        self._started = False

        # Quick maps for callbacks
        self._enc_by_a: dict[int, EncoderSpec] = {e.a_pin: e for e in self._encoders}

    @Slot()
    def start(self) -> None:
        try:
            self._ctl.setmode_bcm()

            # Buttons
            for pin in self._buttons:
                self._ctl.setup_input(pin, pull_up=self._pull_up)
                self._ctl.add_event_detect(
                    pin,
                    callback=self._button_callback,
                    both=True,
                    bouncetime_ms=self._btn_bounce,
                )

            # Encoders (A/B inputs; trigger on A rising only unless configured otherwise)
            for enc in self._encoders:
                self._ctl.setup_input(enc.a_pin, pull_up=self._pull_up)
                self._ctl.setup_input(enc.b_pin, pull_up=self._pull_up)
                self._ctl.add_event_detect(
                    enc.a_pin,
                    callback=self._encoder_callback,
                    both=False,
                    rising=bool(enc.edge_rising_only),
                    falling=False,
                    bouncetime_ms=max(0, enc.debounce_ms),
                )

            self._started = True
            self.signals.ready.emit()

        except Exception as exc:
            self.signals.error.emit(f"GPIO setup failed: {exc}")

    def _button_callback(self, channel: int) -> None:
        try:
            is_low = (self._ctl.input(channel) == self._ctl.LOW)
        except Exception as exc:
            self.signals.error.emit(f"GPIO read failed on pin {channel}: {exc}")
            return

        if is_low:
            self.signals.button_pressed.emit(channel)
        else:
            self.signals.button_released.emit(channel)

    def _encoder_callback(self, a_channel: int) -> None:
        """Decide direction from B level at the moment A edges."""
        enc = self._enc_by_a.get(a_channel)
        if not enc:
            return
        try:
            b_level = self._ctl.input(enc.b_pin)
        except Exception as exc:
            self.signals.error.emit(
                f"Encoder read failed (A={a_channel}, B={enc.b_pin}): {exc}"
            )
            return

        # With pull-ups, idle is HIGH. On A rising:
        # - if B == LOW → CW; if B == HIGH → CCW (convention; invert to flip)
        step = +1 if b_level == self._ctl.LOW else -1
        if enc.invert:
            step = -step
        self.signals.encoder_step.emit(enc.id, step)

    @Slot()
    def stop(self) -> None:
        try:
            if self._started:
                for pin in self._buttons:
                    self._ctl.remove_event_detect(pin)
                for enc in self._encoders:
                    self._ctl.remove_event_detect(enc.a_pin)
                self._ctl.cleanup()
        except Exception as exc:
            self.signals.error.emit(f"GPIO cleanup failed: {exc}")
        finally:
            self._started = False
            self.signals.stopped.emit()


class GPIOService(QObject):
    """
    Service that owns the GPIO worker thread and exposes simple signals.
    """

    button_pressed = Signal(int)          # pin
    button_released = Signal(int)         # pin
    encoder_step = Signal(int, int)       # (encoder_id, +1/-1)
    error = Signal(str)
    ready = Signal()
    stopped = Signal()

    def __init__(
        self,
        pins: Iterable[int] = (),
        *,
        encoders: Iterable[EncoderSpec] = (),
        pull_up: bool = True,
        button_bouncetime_ms: int = 200,
        controller: Optional[GPIOController] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._pins = list(pins)
        self._encoders = list(encoders)
        self._pull_up = pull_up
        self._btn_bounce = button_bouncetime_ms
        self._ctl = controller or GPIOController()

        self._thread = QThread(self)
        self._worker = _GPIOWorker(
            self._pins,
            self._encoders,
            pull_up=self._pull_up,
            button_bounce_ms=self._btn_bounce,
            controller=self._ctl,
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.start)
        self._thread.finished.connect(self._worker.deleteLater)

        # bubble signals
        self._worker.signals.button_pressed.connect(self.button_pressed)
        self._worker.signals.button_released.connect(self.button_released)
        self._worker.signals.encoder_step.connect(self.encoder_step)
        self._worker.signals.error.connect(self.error)
        self._worker.signals.ready.connect(self.ready)
        self._worker.signals.stopped.connect(self.stopped)

    def start(self) -> None:
        if not self._thread.isRunning():
            self._thread.start(QThread.InheritPriority)

    def stop(self) -> None:
        if self._thread.isRunning():
            self._worker.stop()
            self._thread.quit()
            self._thread.wait()

    def dispose(self) -> None:
        self.stop()
