from PySide6.QtCore import QObject, Signal

class CommandManager(QObject):
    packet_ready = Signal(bytes)

    def __init__(self):
        super().__init__()

    def build_start_tms(self, intensity: int, duration_ms: int):
        cmd = bytearray(15)
        cmd[0] = 0x10
        cmd[1] = intensity & 0xFF
        cmd[2] = (duration_ms >> 8) & 0xFF
        cmd[3] = duration_ms & 0xFF
        self.packet_ready.emit(bytes(cmd))

    def build_stop_tms(self):
        cmd = bytearray(15)
        cmd[0] = 0x11
        self.packet_ready.emit(bytes(cmd))
