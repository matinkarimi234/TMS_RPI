from PySide6.QtCore import QObject, Signal
from config.settings import (
    HEADER_A,
    UART_TX_SIZE,
    IDLE,
    START_STIMULATION,
    STOP_STIMULATION,
    PAUSE_STIMULATION,
    ERROR,
    SINGLE_PULSE,
    MT,
)

from math import floor


def Clear_All_Buffers(buf: bytearray, length: int) -> bytearray:
    for i in range(length):
        buf[i] = 0x00
    return buf


def Calculate_Checksum(buf: bytearray, length: int) -> int:
    s = 0
    for i in range(length - 1):
        s += buf[i]
    return int(s % 256)


class CommandManager(QObject):
    """
    Builds all UART frames for the protocol:

    - start/stop/pause stimulation commands
    - set-params frame from a TMSProtocol
    """

    packet_ready = Signal(bytes)

    def __init__(self):
        super().__init__()

    # ------------------------------------------------------------------
    #   Commands
    # ------------------------------------------------------------------
    def start_stimulation_command(self) -> bytes:
        buff = bytearray(UART_TX_SIZE)
        Clear_All_Buffers(buff, UART_TX_SIZE)

        buff[0] = HEADER_A
        buff[1] = START_STIMULATION

        cs = Calculate_Checksum(buff, UART_TX_SIZE)
        buff[UART_TX_SIZE - 1] = cs

        frame = bytes(buff)
        self.packet_ready.emit(frame)
        return frame

    def stop_stimulation_command(self) -> bytes:
        buff = bytearray(UART_TX_SIZE)
        Clear_All_Buffers(buff, UART_TX_SIZE)

        buff[0] = HEADER_A
        buff[1] = STOP_STIMULATION

        cs = Calculate_Checksum(buff, UART_TX_SIZE)
        buff[UART_TX_SIZE - 1] = cs

        frame = bytes(buff)
        self.packet_ready.emit(frame)
        return frame
    
    def send_error_command(self) -> bytes:
        buff = bytearray(UART_TX_SIZE)
        Clear_All_Buffers(buff, UART_TX_SIZE)

        buff[0] = HEADER_A
        buff[1] = ERROR

        cs = Calculate_Checksum(buff, UART_TX_SIZE)
        buff[UART_TX_SIZE - 1] = cs

        frame = bytes(buff)
        self.packet_ready.emit(frame)
        return frame
    
    def mt_state(self , mt_value) -> bytes:
        buff = bytearray(UART_TX_SIZE)
        Clear_All_Buffers(buff, UART_TX_SIZE)

        buff[0] = HEADER_A
        buff[1] = MT
        buff[4] = int(mt_value)

        cs = Calculate_Checksum(buff, UART_TX_SIZE)
        buff[UART_TX_SIZE - 1] = cs

        frame = bytes(buff)
        self.packet_ready.emit(frame)
        return frame
    
    def send_single_pulse_command(self, current_MT) -> bytes:
        buff = bytearray(UART_TX_SIZE)
        Clear_All_Buffers(buff, UART_TX_SIZE)

        buff[0] = HEADER_A
        buff[1] = SINGLE_PULSE
        buff[4] = int(current_MT)

        cs = Calculate_Checksum(buff, UART_TX_SIZE)
        buff[UART_TX_SIZE - 1] = cs

        frame = bytes(buff)
        self.packet_ready.emit(frame)
        return frame
        
    
    def send_IDLE_command(self) -> bytes:
        buff = bytearray(UART_TX_SIZE)
        Clear_All_Buffers(buff, UART_TX_SIZE)

        buff[0] = HEADER_A
        buff[1] = IDLE

        cs = Calculate_Checksum(buff, UART_TX_SIZE)
        buff[UART_TX_SIZE - 1] = cs

        frame = bytes(buff)
        self.packet_ready.emit(frame)
        return frame

    def pause_stimulation_command(self) -> bytes:
        buff = bytearray(UART_TX_SIZE)
        Clear_All_Buffers(buff, UART_TX_SIZE)

        buff[0] = HEADER_A
        buff[1] = PAUSE_STIMULATION

        cs = Calculate_Checksum(buff, UART_TX_SIZE)
        buff[UART_TX_SIZE - 1] = cs

        frame = bytes(buff)
        self.packet_ready.emit(frame)
        return frame

    # ------------------------------------------------------------------
    #   Set-params frame
    # ------------------------------------------------------------------
    def build_set_params(self, proto, buzzer_enabled: bool) -> bytes:
        """
        Build a 'Set Params' frame from the current TMSProtocol object.

        NOTE: uses current properties (not *_init)
        """
        buffer = bytearray(UART_TX_SIZE)
        Clear_All_Buffers(buffer, UART_TX_SIZE)

        buffer[0] = HEADER_A
        buffer[1] = 0x01  # Set Params command code

        # Burst pulses
        buffer[2] = int(getattr(proto, "burst_pulses_count", 0)) & 0xFF

        # Intensity in your chosen encoding
        buffer[3] = proto.absolute_intensity & 0xFF
        buffer[4] = proto.subject_mt_percent & 0xFF

        freq = float(getattr(proto, "frequency_hz", 0.0))
        coded_freq = self._encode_freq(freq)
        buffer[5] = coded_freq  # single byte

        # Inter-train interval (integer seconds)
        buffer[6] = int(getattr(proto, "inter_train_interval_s", 0.0) * 2) & 0xFF

        # Inter-pulse interval in ms
        ipi = int(float(getattr(proto, "inter_pulse_interval_ms", 0.0)))
        buffer[7] = (ipi & 0xFF00) >> 8
        buffer[8] = (ipi & 0x00FF) >> 0

        # Ramp fraction * 10 (0.7–1.0 -> 7–10)
        ramp_frac10 = int(float(getattr(proto, "ramp_fraction", 1.0)) * 10.0)
        buffer[9] = ramp_frac10 & 0xFF

        # Ramp steps (1–10)
        buffer[10] = int(getattr(proto, "ramp_steps", 1)) & 0xFF

        # Train count
        buffer[11] = int(getattr(proto, "train_count", 0)) & 0xFF

        # Pulses per train
        ppt = int(getattr(proto, "pulses_per_train", 0))
        buffer[12] = (ppt & 0xFF00) >> 8
        buffer[13] = (ppt & 0x00FF) >> 0

        bit0 = 1 if buzzer_enabled else 0
        bit1= 0  # reserved for future
        bit2= 0  # reserved for future
        bit3= 0  # reserved for future
        bit4= 0  # reserved for future
        bit5= 0  # reserved for future
        bit6= 0  # reserved for future
        
        buffer[14] = (bit0 << 0) | (bit1 << 1) | (bit2 << 2) | (bit3 << 3) | (bit4 << 4) | (bit5 << 5) | (bit6 << 6)

        # checksum
        cs = Calculate_Checksum(buffer, UART_TX_SIZE)
        buffer[UART_TX_SIZE - 1] = cs

        frame = bytes(buffer)
        self.packet_ready.emit(frame)
        return frame
    
    def _encode_freq(freq_hz: float) -> int:
        # 0 → special case (no freq)
        if freq_hz == 0:
            return 0

        # 0.1 to 0.9
        if 0.0 < freq_hz < 1.0:
            code = round(freq_hz * 10)
            # 0.1 -> 1, ..., 0.9 -> 9
            return max(1, min(9, code))

        # 1 to 100
        if 1.0 <= freq_hz <= 100.0:
            # 1 Hz -> 10, 2 Hz -> 11, ..., 100 Hz -> 109
            return int(round(freq_hz)) + 9

        raise ValueError("Frequency out of range")

