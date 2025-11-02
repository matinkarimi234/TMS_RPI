import RPi.GPIO as GPIO
from PySide6.QtCore import QObject, Signal

class GPIOService(QObject):
    button_pressed = Signal(int)    # emits pin number
    button_released = Signal(int)

    def __init__(self, pins: list[int], pull_up: bool = True):
        super().__init__()
        GPIO.setmode(GPIO.BCM)
        pud = GPIO.PUD_UP if pull_up else GPIO.PUD_DOWN
        for pin in pins:
            GPIO.setup(pin, GPIO.IN, pull_up_down=pud)
            GPIO.add_event_detect(
                pin,
                GPIO.BOTH,
                callback=self._gpio_callback,
                bouncetime=200
            )

    def _gpio_callback(self, channel):
        if GPIO.input(channel) == GPIO.LOW:
            self.button_pressed.emit(channel)
        else:
            self.button_released.emit(channel)

    def cleanup(self):
        GPIO.cleanup()
