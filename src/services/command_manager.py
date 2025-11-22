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
        buff[2] = int(mt_value)

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
        buff[2] = int(current_MT)

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
    def build_set_params(self, proto) -> bytes:
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

        # Frequency * 10 (e.g. 10.0 Hz -> 100)
        freq10 = int(float(getattr(proto, "frequency_hz", 0.0)) * 10.0)
        buffer[4] = (freq10 & 0xFF00) >> 8
        buffer[5] = (freq10 & 0x00FF) >> 0

        # Inter-train interval (integer seconds)
        iti10 = int(getattr(proto, "inter_train_interval_s", 0.0) * 10)
        buffer[6] = (iti10 & 0xFF00) >> 8
        buffer[7] = (iti10 & 0x00FF) >> 0

        # Inter-pulse interval in ms
        ipi = int(float(getattr(proto, "inter_pulse_interval_ms", 0.0)))
        buffer[8] = (ipi & 0xFF00) >> 8
        buffer[9] = (ipi & 0x00FF) >> 0

        # Ramp fraction * 10 (0.7–1.0 -> 7–10)
        ramp_frac10 = int(float(getattr(proto, "ramp_fraction", 1.0)) * 10.0)
        buffer[10] = ramp_frac10 & 0xFF

        # Ramp steps (1–10)
        buffer[11] = int(getattr(proto, "ramp_steps", 1)) & 0xFF

        # Train count
        buffer[12] = int(getattr(proto, "train_count", 0)) & 0xFF

        # Pulses per train
        ppt = int(getattr(proto, "pulses_per_train", 0))
        buffer[13] = (ppt & 0xFF00) >> 8
        buffer[14] = (ppt & 0x00FF) >> 0

        # checksum
        cs = Calculate_Checksum(buffer, UART_TX_SIZE)
        buffer[UART_TX_SIZE - 1] = cs

        frame = bytes(buffer)
        self.packet_ready.emit(frame)
        return frame
