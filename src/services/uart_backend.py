from __future__ import annotations
from typing import Optional
from enum import Enum

from PySide6.QtCore import QObject, Signal, Slot

from hardware.uart_manager import UARTManager
from services.uart_service import UARTService
from services.command_manager import CommandManager
from services.rx_manager import RxManager

class SessionState(Enum):
    IDLE = 0
    RUNNING = 1
    FAULT = 2   # optional, for future

def add_checksum(frame15: bytes) -> bytes:
    chk = sum(frame15) & 0xFF
    return frame15 + bytes([chk])


class Uart_Backend(QObject):
    """
    Single façade for the TMS protocol.

    - Owns UART, RX, and command managers.
    - Exposes clean signals/slots for UI.
    - uC is master: we treat RX as the source of truth and only mirror / request.
    """

    # ---- signals to UI (from uC via RxManager) ----
    stateFromUc = Signal(int)
    intensityFromUc = Signal(int)
    coilTempFromUc = Signal(float)   # if you add this to RxManager later
    igbtTempFromUc = Signal(float)
    resistorTempFromUc= Signal(float)

    connectionChanged = Signal(bool)
    errorOccurred = Signal(str)

    def __init__(
        self,
        port: str = "/dev/ttyAMA0",
        baudrate: int = 9600,
        timeout: float = 0.1,
        rx_trigger_bytes: int = 16,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)

        # ---- low-level ----
        self.uart_m = UARTManager(
            port=port,
            baudrate=baudrate,
            timeout=timeout,
            rx_trigger_bytes=rx_trigger_bytes,
        )
        self.uart_s = UARTService(self.uart_m)

        # ---- protocol-level ----
        self.cmd_m = CommandManager()
        self.rx_m = RxManager(self.uart_s)

        # ---- wiring: RX side ----
        self.uart_s.connection_status_changed.connect(self.connectionChanged)
        self.uart_s.error.connect(self.errorOccurred)


        # Events From RX Manager

        # raw RX is already consumed by RxManager inside its constructor,
        # but you can still monitor it for debug if you want:
        # self.uart_s.telemetry_updated.connect(self._on_raw_frame)
        self.rx_m.tms_state.connect(self._on_state_from_uc)
        self.rx_m.intensity_reading.connect(self._on_intensity_from_uc)

        self.rx_m.coil_temperature_reading.connect(self._on_coil_temp_from_uc)
        self.rx_m.igbt_temperature_reading.connect(self._on_igbt_temp_from_uc)
        self.rx_m.resistor_temperature_reading.connect(self._on_resistor_temp_from_uc)

        # ---- wiring: TX side ----
        self.cmd_m.packet_ready.connect(self._send_with_checksum)

    # ------------------------------------------------------------------
    #   public API for UI (slots)
    # ------------------------------------------------------------------
    @Slot()
    def open(self):
        self.uart_s.open()

    @Slot()
    def close(self):
        self.uart_s.close()

    # ------------------------------------------------------------------
    #   public API for UI
    # ------------------------------------------------------------------
    @Slot(object)
    def request_param_update(self, proto):
        """
        UI asks: 'please update uC params to match this protocol'.

        - If uC is idle -> send now.
        - If uC is running -> remember it, and send automatically
          when we next see IDLE from uC.
        """
        self._pending_proto = proto
        if self._state == SessionState.IDLE:
            self._send_params(proto)

    def _send_params(self, proto):
        """
        Translate TMSProtocol -> frames via CommandManager.
        All low-level details stay here.
        """
        if proto is None:
            return

        # You implement this in CommandManager to match your protocol:
        # - build one or several packets that configure burst, IPI, trains, etc.
        # - each call emits packet_ready(frame15) which we then checksum+send.
        self.cmd_m.build_set_params(proto)   # you add this method

        # once sent, we can clear pending
        self._pending_proto = None

    @Slot(int)
    def start_session(self, intensity: int):
        """
        UI requests session start. We don't build frames here;
        we just delegate to CommandManager.
        """
        # Example: same as your test app
        self.cmd_m.build_start_tms(intensity, 200)

    @Slot()
    def stop_session(self):
        self.cmd_m.build_stop_tms()

    @Slot(object)
    def apply_protocol(self, proto):
        """
        Optional: UI passes a TMSProtocol object here.
        CommandManager converts it into frames (param download).
        """
        # e.g. self.cmd_m.build_set_params(proto)
        pass

    # ------------------------------------------------------------------
    #   internal helpers
    # ------------------------------------------------------------------
    def _send_with_checksum(self, frame15: bytes):
        frame16 = add_checksum(frame15)
        self.uart_s.send(frame16)

    # def _on_raw_frame(self, pkt: bytes):
    #     print("[UART RX RAW]", pkt.hex(" "))

    # Fire the Rx Events for UI
    def _on_state_from_uc(self, val: int):
        self.stateFromUc.emit(val)

    def _on_intensity_from_uc(self, val: int):
        self.intensityFromUc.emit(val)

    def _on_coil_temp_from_uc(self, temp: float):
        self.coilTempFromUc.emit(temp)

    def _on_igbt_temp_from_uc(self, temp: float):
        self.igbtTempFromUc.emit(temp)

    def _on_resistor_temp_from_uc(self, temp: float):
        self.resistorTempFromUc.emit(temp)

