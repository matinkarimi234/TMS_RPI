# services/gpio_backend.py
from __future__ import annotations

from enum import IntEnum, auto
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from config.settings import (
    RED_LED_PIN,
    GREEN_LED_PIN,
    EN_BUTTON_PIN,
    MT_BUTTON_PIN,
    PROTOCOL_BUTTON_PIN,
    RESERVED_BUTTON_PIN,
    STOP_BUTTON_PIN,
    START_PAUSE_BUTTON_PIN,
    SINGLE_PULSE_BUTTON_PIN,
    ARROW_DOWN_BUTTON_PIN,
    ARROW_UP_BUTTON_PIN,
    BUTTONS,
    CONTROL_ENC_P_PIN,
    CONTROL_ENC_N_PIN,
)

# ----------------------------------------------------------------------
#   Hardware vs mock selection
# ----------------------------------------------------------------------
HAVE_GPIO = False
GPIOService = None          # type: ignore
EncoderSpec = None          # type: ignore
GPIOControllerBase = None   # type: ignore
MockGPIOService = None      # type: ignore

try:
    # On Raspberry Pi with GPIO stack installed
    from hardware.gpio_controller import GPIOController as _RealGPIOController
    from services.gpio_service import GPIOService as _RealGPIOService, EncoderSpec as _RealEncoderSpec

    GPIOControllerBase = _RealGPIOController
    GPIOService = _RealGPIOService      # type: ignore
    EncoderSpec = _RealEncoderSpec      # type: ignore
    MockGPIOService = None              # explicit: no mock here by default
    HAVE_GPIO = True
except Exception:
    # On PC: no real GPIO stack, fall back to mock
    HAVE_GPIO = False

    # Dummy controller so LED API still exists but does nothing
    class _DummyGPIOController:
        HIGH = 1
        LOW = 0

        def setmode_bcm(self) -> None:
            pass

        def setup_output(self, pin: int) -> None:
            pass

        def output(self, pin: int, value: int) -> None:
            pass

    GPIOControllerBase = _DummyGPIOController  # type: ignore

    # Import your mock; this should NOT import any GPIO libraries
    from workers.mock_gpio_service import MockGPIOService  # type: ignore


class ButtonId(IntEnum):
    EN = auto()
    MT = auto()
    PROTOCOL = auto()
    RESERVED = auto()
    STOP = auto()
    START_PAUSE = auto()
    SINGLE_PULSE = auto()
    ARROW_DOWN = auto()
    ARROW_UP = auto()


class GPIO_Backend(QObject):
    """
    Single façade for physical GPIO inputs/outputs.

    - On Pi: owns GPIOService + real GPIOController.
    - On PC: owns MockGPIOService + dummy GPIOController (LEDs are no-op).
    - Translates raw pins → semantic ButtonId.
    - Provides slots for LED control and exposes signals for UI.
    """

    # ---- signals to UI ----
    buttonPressed = Signal(int)         # ButtonId as int
    buttonReleased = Signal(int)        # ButtonId as int
    encoderStep = Signal(int)           # step (+1 / -1) from main encoder

    # Optional dedicated signals for convenience in UI
    startPausePressed = Signal()
    stopPressed = Signal()
    singlePulsePressed = Signal()
    protocolPressed = Signal()
    enPressed = Signal()
    mtPressed = Signal()
    reservedPressed = Signal()
    arrowUpPressed = Signal()
    arrowDownPressed = Signal()

    errorOccurred = Signal(str)
    ready = Signal()
    stopped = Signal()

    def __init__(
        self,
        *,
        parent: Optional[QObject] = None,
        pull_up: bool = True,
        button_bouncetime_ms: int = 200,
        use_mock: bool = False,  # you can force mock even if HAVE_GPIO=True
    ) -> None:
        super().__init__(parent)

        # Shared controller for inputs + LEDs
        self._ctl = GPIOControllerBase()  # real on Pi, dummy on PC

        # Map pins -> logical ButtonId
        self._pin_to_button_id = {
            EN_BUTTON_PIN: ButtonId.EN,
            MT_BUTTON_PIN: ButtonId.MT,
            PROTOCOL_BUTTON_PIN: ButtonId.PROTOCOL,
            RESERVED_BUTTON_PIN: ButtonId.RESERVED,
            STOP_BUTTON_PIN: ButtonId.STOP,
            START_PAUSE_BUTTON_PIN: ButtonId.START_PAUSE,
            SINGLE_PULSE_BUTTON_PIN: ButtonId.SINGLE_PULSE,
            ARROW_DOWN_BUTTON_PIN: ButtonId.ARROW_DOWN,
            ARROW_UP_BUTTON_PIN: ButtonId.ARROW_UP,
        }

        # Encoder spec only makes sense if we actually have the real class
        encoder = None
        if HAVE_GPIO and EncoderSpec is not None:
            encoder = EncoderSpec(
                a_pin=CONTROL_ENC_P_PIN,
                b_pin=CONTROL_ENC_N_PIN,
                id=0,
                invert=False,
                edge_rising_only=True,
                debounce_ms=1,
            )

        encoders = [encoder] if encoder is not None else []

        # --------------------------------------------------------------
        #   Choose real GPIOService vs MockGPIOService
        # --------------------------------------------------------------
        if HAVE_GPIO and not use_mock and GPIOService is not None:
            # Raspberry Pi / real hardware
            self._gpio_svc = GPIOService(
                pins=BUTTONS,
                encoders=encoders,
                pull_up=pull_up,
                button_bouncetime_ms=button_bouncetime_ms,
                controller=self._ctl,
                parent=self,
            )
        else:
            # PC OR forced mock
            if MockGPIOService is None:
                raise RuntimeError("MockGPIOService is not available but GPIO is not usable.")
            # Be tolerant of different mock signatures (parent-only vs full kwargs)
            try:
                self._gpio_svc = MockGPIOService(
                    pins=BUTTONS,
                    encoders=encoders,
                    pull_up=pull_up,
                    button_bouncetime_ms=button_bouncetime_ms,
                    controller=self._ctl,
                    parent=self,
                )
            except TypeError:
                # fallback: older mock that only takes parent
                self._gpio_svc = MockGPIOService(parent=self)

        # Wire service signals up to backend handlers
        self._gpio_svc.button_pressed.connect(self._on_button_pressed_pin)
        self._gpio_svc.button_released.connect(self._on_button_released_pin)
        self._gpio_svc.encoder_step.connect(self._on_encoder_step)

        # passthrough “system” signals (mock also should provide these)
        if hasattr(self._gpio_svc, "error"):
            self._gpio_svc.error.connect(self.errorOccurred)
        if hasattr(self._gpio_svc, "ready"):
            self._gpio_svc.ready.connect(self.ready)
        if hasattr(self._gpio_svc, "stopped"):
            self._gpio_svc.stopped.connect(self.stopped)

        # Flag to know if LEDs are configured yet
        self._leds_setup = False

    # ------------------------------------------------------------------
    #   Lifecycle API (slots for UI)
    # ------------------------------------------------------------------
    @Slot()
    def start(self) -> None:
        self._gpio_svc.start()

    @Slot()
    def stop(self) -> None:
        self._gpio_svc.stop()

    # ------------------------------------------------------------------
    #   LED control API (slots for UI)
    # ------------------------------------------------------------------
    def _ensure_leds_setup(self) -> None:
        if self._leds_setup:
            return
        # On PC, dummy controller just no-ops
        self._ctl.setmode_bcm()
        self._ctl.setup_output(RED_LED_PIN)
        self._ctl.setup_output(GREEN_LED_PIN)
        self._leds_setup = True

    @Slot(bool)
    def set_red_led(self, on: bool) -> None:
        self._ensure_leds_setup()
        self._ctl.output(RED_LED_PIN, self._ctl.HIGH if on else self._ctl.LOW)

    @Slot(bool)
    def set_green_led(self, on: bool) -> None:
        self._ensure_leds_setup()
        self._ctl.output(GREEN_LED_PIN, self._ctl.HIGH if on else self._ctl.LOW)

    # ------------------------------------------------------------------
    #   Internal event handlers (pin -> ButtonId)
    # ------------------------------------------------------------------
    def _pin_to_id(self, pin: int) -> Optional[ButtonId]:
        return self._pin_to_button_id.get(pin)

    @Slot(int)
    def _on_button_pressed_pin(self, pin: int) -> None:
        bid = self._pin_to_id(pin)
        if bid is None:
            return

        # Generic signal
        self.buttonPressed.emit(int(bid))

        # High-level semantic signals
        if bid == ButtonId.START_PAUSE:
            self.startPausePressed.emit()
        elif bid == ButtonId.STOP:
            self.stopPressed.emit()
        elif bid == ButtonId.SINGLE_PULSE:
            self.singlePulsePressed.emit()
        elif bid == ButtonId.PROTOCOL:
            self.protocolPressed.emit()
        elif bid == ButtonId.EN:
            self.enPressed.emit()
        elif bid == ButtonId.MT:
            self.mtPressed.emit()
        elif bid == ButtonId.RESERVED:
            self.reservedPressed.emit()
        elif bid == ButtonId.ARROW_UP:
            self.arrowUpPressed.emit()
        elif bid == ButtonId.ARROW_DOWN:
            self.arrowDownPressed.emit()

    @Slot(int)
    def _on_button_released_pin(self, pin: int) -> None:
        bid = self._pin_to_id(pin)
        if bid is None:
            return
        self.buttonReleased.emit(int(bid))

    @Slot(int, int)
    def _on_encoder_step(self, enc_id: int, step: int) -> None:
        # we ignore enc_id for now, single encoder only
        self.encoderStep.emit(step)
