from PySide6.QtCore import QObject, Signal
import serial, threading, time

class UARTManager(QObject):
    data_received = Signal(bytes)
    error = Signal(str)
    connection_status_changed = Signal(bool)

    def __init__(self, port="/dev/serial0", baudrate=9600, timeout=0.1):
        super().__init__()
        self.port     = port
        self.baudrate = baudrate
        self.timeout  = timeout
        self._ser     = None
        self._stop    = threading.Event()
        self._thread  = None

    def open(self):
        if self._ser and self._ser.is_open:
            return
        try:
            self._ser = serial.Serial(
                self.port, baudrate=self.baudrate,
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
        if self._ser and self._ser.is_open:
            self._ser.close()
        self.connection_status_changed.emit(False)

    def send(self, packet: bytes):
        if self._ser and self._ser.is_open:
            self._ser.write(packet)
        else:
            self.error.emit("UART not open – cannot send")

    def _loop(self):
        bad = 0
        while not self._stop.is_set():
            try:
                if self._ser.in_waiting >= 16:
                    pkt = self._ser.read(16)
                    if self._checksum(pkt):
                        self.data_received.emit(pkt)
                        bad = 0
                    else:
                        bad += 1
                        self.error.emit("Checksum error")
                else:
                    time.sleep(0.01)

                if bad >= 5:
                    self.error.emit("5 bad packets – resetting")
                    self._reset()
                    bad = 0

            except Exception as e:
                self.error.emit(f"UART thread exception: {e}")
                time.sleep(1)

    def _checksum(self, pkt: bytes) -> bool:
        return len(pkt)==16 and (sum(pkt[:15])&0xFF)==pkt[15]

    def _reset(self):
        if self._ser:
            self._ser.close()
            time.sleep(0.5)
            self._ser.open()
