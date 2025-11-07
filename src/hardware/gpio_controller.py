from __future__ import annotations

from typing import Callable, Dict, Optional
from gpiozero import Device, Button
from gpiozero.pins.lgpio import LGPIOFactory


class GPIOController:
    """
    Thin adapter over gpiozero (LGPIO backend).
    - Preserves your RPi.GPIO-like methods so higher layers don't change.
    - Edge detection is emulated by wiring the same callback to press+release.
    - `bouncetime_ms` is respected (converted to seconds for gpiozero).
    """

    def __init__(self) -> None:
        # pin -> Button
        self._btn: Dict[int, Button] = {}
        # pin -> whether we configured pull-up for it
        self._pull_up: Dict[int, bool] = {}

    # --- setup / teardown -----------------------------------------------------
    def setmode_bcm(self) -> None:
        """
        gpiozero doesn't need setmode; we use this call to ensure the lgpio backend.
        Call this early, before setup_input().
        """
        Device.pin_factory = LGPIOFactory()

    def setup_input(self, pin: int, *, pull_up: bool = True) -> None:
        # Re-create the Button if it already exists (in case pull changes)
        if pin in self._btn:
            try:
                self._btn[pin].close()
            except Exception:
                pass
        self._pull_up[pin] = pull_up
        # bounce_time set later in add_event_detect (seconds)
        self._btn[pin] = Button(pin, pull_up=pull_up, bounce_time=None)

    def add_event_detect(self, pin: int, callback: Callable[[int], None], *, bouncetime_ms: int = 200) -> None:
        """
        Matches RPi.GPIO.add_event_detect on BOTH edges: callback(pin).
        """
        if pin not in self._btn:
            # default to pull-up if not set up yet
            self.setup_input(pin, pull_up=True)

        dev = self._btn[pin]
        # convert ms -> seconds (gpiozero expects seconds)
        dev.bounce_time = (bouncetime_ms / 1000.0) if bouncetime_ms is not None else None

        # clear any previous handlers
        dev.when_pressed = None
        dev.when_released = None

        # gpiozero doesn't pass the channel arg, so capture it
        def _cb() -> None:
            try:
                callback(pin)
            except Exception:
                # keep callbacks robust — don't kill the internal thread
                pass

        # BOTH edges
        dev.when_pressed = _cb
        dev.when_released = _cb

    def remove_event_detect(self, pin: int) -> None:
        dev = self._btn.get(pin)
        if dev:
            dev.when_pressed = None
            dev.when_released = None

    def cleanup(self) -> None:
        for dev in list(self._btn.values()):
            try:
                dev.close()
            except Exception:
                pass
        self._btn.clear()
        self._pull_up.clear()

    # --- io -------------------------------------------------------------------
    def input(self, pin: int) -> int:
        """
        Return the *raw logic level* (like RPi.GPIO.input):
        - With pull_up=True: not pressed -> 1 (high), pressed -> 0 (low)
        - With pull_up=False: high -> 1, low -> 0
        """
        dev = self._btn.get(pin)
        if dev is None:
            raise RuntimeError(f"Pin {pin} not set up; call setup_input first.")

        pull_up = self._pull_up.get(pin, True)
        # Button.is_pressed is "active" (pressed), which is inverted when pull_up=True.
        if pull_up:
            return 0 if dev.is_pressed else 1
        else:
            return 1 if dev.is_pressed else 0

    # expose constants for callers (service) to compare levels
    @property
    def LOW(self) -> int:
        return 0

    @property
    def HIGH(self) -> int:
        return 1
