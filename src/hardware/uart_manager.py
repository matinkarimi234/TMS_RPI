from PySide6.QtCore import QObject, Signal
import serial, threading, time
from config.settings import HEADER_A, HEADER_B


class UARTManager(QObject):
    data_received = Signal(bytes)
    error = Signal(str)
    connection_status_changed = Signal(bool)

    def __init__(self, port="/dev/serial0", baudrate=9600, timeout=0.1, rx_trigger_bytes: int = 16):
        super().__init__()
        self.port     = port
        self.baudrate = baudrate
        self.timeout  = timeout

        self._ser     = None
        self._stop    = threading.Event()
        self._thread  = None

        # how many bytes must be waiting before we attempt a read
        self._rx_trigger_bytes = max(1, int(rx_trigger_bytes))

        # fixed frame length (your protocol’s RX length)
        self._frame_len = 16

    # -------- live-tunable property ------------------------------------------
    @property
    def rx_trigger_bytes(self) -> int:
        return self._rx_trigger_bytes

    @rx_trigger_bytes.setter
    def rx_trigger_bytes(self, n: int) -> None:
        try:
            n = int(n)
        except Exception:
            self.error.emit(f"rx_trigger_bytes must be an integer (got {n!r})")
            return
        if n < 1:
            n = 1
        self._rx_trigger_bytes = n

    # -------- lifecycle -------------------------------------------------------
    def open(self):
        if self._ser and self._ser.is_open:
            return
        try:
            self._ser = serial.Serial(
                self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
            )
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            self.connection_status_changed.emit(True)
        except Exception as e:
            self.error.emit(f"UART open failed: {e}")

    def close(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join()
        if self._ser and getattr(self._ser, "is_open", False):
            try:
                self._ser.close()
            except Exception:
                pass
        self.connection_status_changed.emit(False)

    def send(self, packet: bytes):
        if self._ser and getattr(self._ser, "is_open", False):
            try:
                self._ser.write(packet)
            except Exception as e:
                self.error.emit(f"UART write failed: {e}")
        else:
            self.error.emit("UART not open – cannot send")

    # -------- internal RX loop -----------------------------------------------
    def _loop(self):
        bad = 0
        while not self._stop.is_set():
            try:
                if self._ser.in_waiting >= self._rx_trigger_bytes:
                    pkt = self._ser.read(self._frame_len)
                    if self._checksum_header(pkt):
                        self.data_received.emit(pkt)
                        bad = 0
                    else:
                        bad += 1
                        self.error.emit("Checksum/Header error")
                else:
                    time.sleep(0.01)

                if bad >= 5:
                    self.error.emit("5 bad packets – resetting")
                    self._reset()
                    bad = 0

            except Exception as e:
                self.error.emit(f"UART thread exception: {e}")
                time.sleep(1)

    def _checksum_header(self, pkt: bytes) -> bool:
        if len(pkt) != self._frame_len:
            return False
        if pkt[0] != HEADER_A:
            self.error.emit(f"Header1: {pkt[0]}")
            return False
        if pkt[1] != HEADER_B:
            self.error.emit(f"Header2: {pkt[1]}")
            return False
        return (sum(pkt[: self._frame_len - 1]) & 0xFF) == pkt[self._frame_len - 1]

    def _reset(self):
        if self._ser:
            try:
                self._ser.close()
                time.sleep(0.5)
                self._ser.open()
            except Exception as e:
                self.error.emit(f"UART reset failed: {e}")
