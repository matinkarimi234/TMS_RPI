from PySide6.QtCore import QObject, Signal


class UARTService(QObject):
    telemetry_updated = Signal(bytes)
    error = Signal(str)
    connection_status_changed = Signal(bool)

    def __init__(self, uart_manager):
        super().__init__()
        self.uart = uart_manager
        # re-emit correctly
        self.uart.data_received.connect(self.telemetry_updated.emit)
        self.uart.error.connect(self.error.emit)
        self.uart.connection_status_changed.connect(self.connection_status_changed.emit)

    def open(self):
        self.uart.open()

    def close(self):
        self.uart.close()

    def send(self, packet: bytes):
        self.uart.send(packet)
