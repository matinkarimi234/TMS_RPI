from __future__ import annotations

import RPi.GPIO as GPIO


class GPIOController:
    """
    Thin adapter over RPi.GPIO.
    - No Qt, no threads, no signals.
    - The services layer owns threading/signals and calls into this.
    """

    # --- setup / teardown -----------------------------------------------------
    def setmode_bcm(self) -> None:
        GPIO.setmode(GPIO.BCM)

    def setup_input(self, pin: int, *, pull_up: bool = True) -> None:
        pud = GPIO.PUD_UP if pull_up else GPIO.PUD_DOWN
        GPIO.setup(pin, GPIO.IN, pull_up_down=pud)

    def add_event_detect(self, pin: int, callback, *, bouncetime_ms: int = 200) -> None:
        GPIO.add_event_detect(pin, GPIO.BOTH, callback=callback, bouncetime=bouncetime_ms)

    def remove_event_detect(self, pin: int) -> None:
        try:
            GPIO.remove_event_detect(pin)
        except Exception:
            pass

    def cleanup(self) -> None:
        GPIO.cleanup()

    # --- io -------------------------------------------------------------------
    def input(self, pin: int) -> int:
        return GPIO.input(pin)

    # expose constants for callers (service) to compare levels
    @property
    def LOW(self) -> int:
        return GPIO.LOW

    @property
    def HIGH(self) -> int:
        return GPIO.HIGH
