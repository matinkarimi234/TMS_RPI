from PySide6.QtCore import QObject, Signal
from config.settings import HEADER_A, HEADER_B, UART_TX_SIZE

def Clear_All_Buffers(buf : bytearray , length : int) -> bytearray:
    for i in range(0, length):
        buf[i] = 0x00
    return buf

def Calculate_Checksum(buf: bytearray , length:int) -> int:
    sum = 0
    for i in range(0,length - 1):
        sum += buf[i]
    
    return sum

class CommandManager(QObject):
    packet_ready = Signal(bytes)

    def __init__(self):
        super().__init__()

    def build_start_tms(self, intensity: int, duration_ms: int):
        cmd = bytearray(UART_TX_SIZE)
        cmd[0] = 0x10
        cmd[1] = intensity & 0xFF
        cmd[2] = (duration_ms >> 8) & 0xFF
        cmd[3] = duration_ms & 0xFF
        self.packet_ready.emit(bytes(cmd)) # Event with Args

    def build_stop_tms(self):
        cmd = bytearray(TX_SIZE)
        cmd[0] = 0x11
        self.packet_ready.emit(bytes(cmd)) # Event with Args


    def build_set_params(self, proto):
        buffer = bytearray(TX_SIZE)
        Clear_All_Buffers(buffer, TX_SIZE)
        buffer[0] = HEADER_A
        buffer[1] = HEADER_B

        buffer[2] = 0x01 #Set Params

        buffer[3] = proto.burst_pulses_count_init

        intensity = int(proto.get_absolute_intensity() * 10)
        buffer[4] = (intensity & 0xFF00) >> 8
        buffer[5] = (intensity & 0x00FF) >> 0

        freq = int(proto.frequency_hz_init * 10)
        buffer[6] = (freq & 0xFF00) >> 8
        buffer[7] = (freq & 0x00FF) >> 0

        iti = int(proto.inter_train_interval_s)
        buffer[8] = (iti & 0xFF00) >> 8
        buffer[9] = (iti & 0x00FF) >> 0

        ipi = int(proto.inter_pulse_interval_ms_init)
        buffer[10] = (ipi & 0xFF00) >> 8
        buffer[11] = (ipi & 0x00FF) >> 0

        ramp_frac = int(proto.ramp_fraction * 10)
        buffer[12] = ramp_frac

        buffer[13] = proto.ramp_steps

        buffer[14] = (proto.train_count & 0xFF00) >> 8
        buffer[15] = (proto.train_count & 0x00FF) >> 0
        
        buffer[16] = (proto.pulses_per_train & 0xFF00) >> 8
        buffer[17] = (proto.pulses_per_train & 0x00FF) >> 0

        
        cs = Calculate_Checksum(buffer, TX_SIZE)
        buffer[TX_SIZE - 1] = cs

        self.packet_ready.emit(bytes(buffer))


