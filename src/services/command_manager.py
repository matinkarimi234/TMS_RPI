from PySide6.QtCore import QObject, Signal
from config.settings import (
    HEADER_A,
    HEADER_B,
    UART_TX_SIZE,
    START_STIMULATION,
    STOP_STIMULATION,
    PAUSE_STIMULATION,
)


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
        buff[1] = HEADER_B
        buff[2] = START_STIMULATION

        cs = Calculate_Checksum(buff, UART_TX_SIZE)
        buff[UART_TX_SIZE - 1] = cs

        frame = bytes(buff)
        self.packet_ready.emit(frame)
        return frame

    def stop_stimulation_command(self) -> bytes:
        buff = bytearray(UART_TX_SIZE)
        Clear_All_Buffers(buff, UART_TX_SIZE)

        buff[0] = HEADER_A
        buff[1] = HEADER_B
        buff[2] = STOP_STIMULATION

        cs = Calculate_Checksum(buff, UART_TX_SIZE)
        buff[UART_TX_SIZE - 1] = cs

        frame = bytes(buff)
        self.packet_ready.emit(frame)
        return frame

    def pause_stimulation_command(self) -> bytes:
        buff = bytearray(UART_TX_SIZE)
        Clear_All_Buffers(buff, UART_TX_SIZE)

        buff[0] = HEADER_A
        buff[1] = HEADER_B
        buff[2] = PAUSE_STIMULATION

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
        buffer[1] = HEADER_B
        buffer[2] = 0x01  # Set Params command code

        # Burst pulses
        buffer[3] = int(getattr(proto, "burst_pulses_count", 0)) & 0xFF

        # Intensity in your chosen encoding
        # here we keep your original logic: absolute intensity * 10
        abs_intensity = int(proto.get_absolute_intensity() * 10)  # e.g. 75.0% -> 750
        buffer[4] = (abs_intensity & 0xFF00) >> 8
        buffer[5] = (abs_intensity & 0x00FF) >> 0

        # Frequency * 10 (e.g. 10.0 Hz -> 100)
        freq10 = int(float(getattr(proto, "frequency_hz", 0.0)) * 10.0)
        buffer[6] = (freq10 & 0xFF00) >> 8
        buffer[7] = (freq10 & 0x00FF) >> 0

        # Inter-train interval (integer seconds)
        iti = int(getattr(proto, "inter_train_interval_s", 0.0))
        buffer[8] = (iti & 0xFF00) >> 8
        buffer[9] = (iti & 0x00FF) >> 0

        # Inter-pulse interval in ms
        ipi = int(float(getattr(proto, "inter_pulse_interval_ms", 0.0)))
        buffer[10] = (ipi & 0xFF00) >> 8
        buffer[11] = (ipi & 0x00FF) >> 0

        # Ramp fraction * 10 (0.7–1.0 -> 7–10)
        ramp_frac10 = int(float(getattr(proto, "ramp_fraction", 1.0)) * 10.0)
        buffer[12] = ramp_frac10 & 0xFF

        # Ramp steps (1–10)
        buffer[13] = int(getattr(proto, "ramp_steps", 1)) & 0xFF

        # Train count
        train_count = int(getattr(proto, "train_count", 0))
        buffer[14] = (train_count & 0xFF00) >> 8
        buffer[15] = (train_count & 0x00FF) >> 0

        # Pulses per train
        ppt = int(getattr(proto, "pulses_per_train", 0))
        buffer[16] = (ppt & 0xFF00) >> 8
        buffer[17] = (ppt & 0x00FF) >> 0

        # checksum
        cs = Calculate_Checksum(buffer, UART_TX_SIZE)
        buffer[UART_TX_SIZE - 1] = cs

        frame = bytes(buffer)
        self.packet_ready.emit(frame)
        return frame
