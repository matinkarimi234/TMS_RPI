from PySide6.QtCore import QObject, Signal

class RxManager(QObject):
    tms_status = Signal(bool)
    intensity_reading = Signal(int)

    def __init__(self, uart_service):
        super().__init__()
        uart_service.telemetry_updated.connect(self._on_packet)

    def _on_packet(self, packet: bytes):
        status = (packet[0] == 0x01)
        intensity = (packet[1] << 8) | packet[2]
        self.tms_status.emit(status) # Event with Args
        self.intensity_reading.emit(intensity) # Event with Args
