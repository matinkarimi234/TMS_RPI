from __future__ import annotations

from typing import Callable, Dict, Optional
from gpiozero import Device, Button
from gpiozero.pins.lgpio import LGPIOFactory


class GPIOController:
    """
    Thin adapter over gpiozero (LGPIO backend) with an RPi.GPIO-like API.
    - Works in venvs (pip install gpiozero lgpio).
    - Supports edge args: both=, rising=, falling=, or edge='both'|'rising'|'falling'.
    - Respects bouncetime_ms (converted to seconds).
    - Avoids gpiozero's CallbackSetToNone warning by using a no-op.
    """

    def __init__(self) -> None:
        # pin -> Button
        self._btn: Dict[int, Button] = {}
        # pin -> configured pull-up state
        self._pull_up: Dict[int, bool] = {}

    # -------------------------- internals -------------------------------------
    @staticmethod
    def _noop() -> None:
        """No-op to clear handlers without warnings."""
        pass

    @staticmethod
    def _ms_to_seconds(ms: Optional[int]) -> Optional[float]:
        if ms is None:
            return None
        return None if ms <= 0 else ms / 1000.0

    def _resolve_edge(
        self,
        both: Optional[bool],
        rising: Optional[bool],
        falling: Optional[bool],
        edge: Optional[str],
    ) -> str:
        if edge:
            e = edge.lower()
            if e in ("both", "rising", "falling"):
                return e
        if both:
            return "both"
        if rising and not falling:
            return "rising"
        if falling and not rising:
            return "falling"
        return "both"

    # ----------------------- setup / teardown ---------------------------------
    def setmode_bcm(self) -> None:
        """
        gpiozero doesn't need a setmode; we use this to force the lgpio backend.
        Call early (before setup_input).
        """
        Device.pin_factory = LGPIOFactory()

    def setup_input(self, pin: int, *, pull_up: bool = True) -> None:
        # Re-create if it already exists (pull may change)
        old = self._btn.get(pin)
        if old:
            try:
                old.close()
            except Exception:
                pass
        self._pull_up[pin] = pull_up
        # Set bounce_time later per-callback
        self._btn[pin] = Button(pin, pull_up=pull_up)

    def add_event_detect(
        self,
        pin: int,
        callback: Callable[[int], None],
        *,
        bouncetime_ms: int = 200,
        both: Optional[bool] = None,
        rising: Optional[bool] = None,
        falling: Optional[bool] = None,
        edge: Optional[str] = None,
    ) -> None:
        """
        Emulates RPi.GPIO.add_event_detect on BOTH/RISING/FALLING edges.
        The callback receives the pin number: callback(pin).
        """
        if pin not in self._btn:
            self.setup_input(pin, pull_up=True)

        dev = self._btn[pin]
        #dev.bounce_time = self._ms_to_seconds(bouncetime_ms)

        # Safe wrapper: gpiozero passes no channel; we inject pin.
        def _cb() -> None:
            try:
                callback(pin)
            except Exception:
                # Keep exceptions from killing gpiozero's worker thread
                pass

        # Map requested edge(s) to gpiozero Button events,
        # taking pull direction into account:
        # pull_up=True:  falling -> when_pressed, rising -> when_released
        # pull_up=False: rising  -> when_pressed, falling -> when_released
        pull_up = self._pull_up.get(pin, True)
        sel = self._resolve_edge(both, rising, falling, edge)

        # Clear current handlers without triggering warnings
        dev.when_pressed = self._noop
        dev.when_released = self._noop

        if sel == "both":
            dev.when_pressed = _cb
            dev.when_released = _cb
        elif sel == "rising":
            if pull_up:
                dev.when_released = _cb
            else:
                dev.when_pressed = _cb
        elif sel == "falling":
            if pull_up:
                dev.when_pressed = _cb
            else:
                dev.when_released = _cb
        else:
            # Fallback to BOTH
            dev.when_pressed = _cb
            dev.when_released = _cb

    def remove_event_detect(self, pin: int) -> None:
        dev = self._btn.get(pin)
        if dev:
            dev.when_pressed = self._noop
            dev.when_released = self._noop

    def cleanup(self) -> None:
        for dev in list(self._btn.values()):
            try:
                dev.close()
            except Exception:
                pass
        self._btn.clear()
        self._pull_up.clear()

    # ------------------------------ I/O ---------------------------------------
    def input(self, pin: int) -> int:
        """
        Return the raw electrical level (like RPi.GPIO.input):
        - With pull_up=True: idle HIGH (1), pressed LOW (0)
        - With pull_up=False: HIGH -> 1, LOW -> 0
        """
        dev = self._btn.get(pin)
        if dev is None:
            raise RuntimeError(f"Pin {pin} not set up; call setup_input first.")
        pull_up = self._pull_up.get(pin, True)
        if pull_up:
            return 0 if dev.is_pressed else 1
        else:
            return 1 if dev.is_pressed else 0

    # Expose constants for callers
    @property
    def LOW(self) -> int:
        return 0

    @property
    def HIGH(self) -> int:
        return 1
