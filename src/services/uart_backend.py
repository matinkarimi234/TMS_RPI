from __future__ import annotations
from typing import Optional
from enum import Enum

from PySide6.QtCore import QObject, Signal, Slot, QTimer

from hardware.uart_manager import UARTManager
from services.uart_service import UARTService
from services.command_manager import CommandManager
from services.rx_manager import RxManager  # your existing RX parser


class uC_State(Enum):
    IDLE = 0
    SET_PARAMETERS = 1
    START = 2
    STOP = 3
    PAUSE = 4
    STIMULATE = 5
    ERROR = 6
    MT = 7

class Uart_Backend(QObject):
    """
    Single façade for the TMS protocol.

    PC/RPi is the **master** now:

    - Every 125 ms we send ONE frame on UART.
      * If a command is pending → we send that frame.
      * Else, if MT streaming is enabled → we send mt_state(mt_value).
      * Else, we send the latest 'set params' frame.
    """

    # ---- signals to UI (from uC via RxManager) ----
    stateFromUc = Signal(int)
    intensityFromUc = Signal(int)
    coilTempFromUc = Signal(float)
    igbtTempFromUc = Signal(float)
    resistorTempFromUc = Signal(float)
    sw_state_from_uC = Signal(bool)

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

        # state tracking
        self._state: SessionState = SessionState.IDLE
        self._current_proto = None
        self._last_params_frame: Optional[bytes] = None
        self._next_command_frame: Optional[bytes] = None

        # MT streaming state
        self._mt_streaming: bool = False
        self._mt_current_value: Optional[int] = 0  # default 0 at startup

        # ---- wiring: RX side ----
        self.uart_s.connection_status_changed.connect(self.connectionChanged)
        self.uart_s.error.connect(self.errorOccurred)

        self.rx_m.tms_state.connect(self._on_state_from_uc)
        self.rx_m.intensity_reading.connect(self._on_intensity_from_uc)
        self.rx_m.coil_temperature_reading.connect(self._on_coil_temp_from_uc)
        self.rx_m.igbt_temperature_reading.connect(self._on_igbt_temp_from_uc)
        self.rx_m.resistor_temperature_reading.connect(self._on_resistor_temp_from_uc)
        self.rx_m.uC_SW_state_Reading.connect(self._on_sw_state_from_uc)

        # Debug hook for CommandManager
        self.cmd_m.packet_ready.connect(self._on_cmd_packet_ready_debug)

        # ---- TX scheduler: 125 ms master tick ----
        self._tx_timer = QTimer(self)
        self._tx_timer.setInterval(125)  # ms
        self._tx_timer.timeout.connect(self._on_tx_tick)

    # ------------------------------------------------------------------
    #   public API for UI (slots)
    # ------------------------------------------------------------------
    @Slot()
    def open(self):
        self.uart_s.open()
        self._tx_timer.start()

    @Slot()
    def close(self):
        self._tx_timer.stop()
        self.uart_s.close()

    # ------------------------------------------------------------------
    #   Parameters from UI
    # ------------------------------------------------------------------
    @Slot(object)
    def request_param_update(self, proto):
        """
        UI asks: 'please update uC params to match this protocol'.

        - We store the protocol.
        - We build a fresh 'set params' frame.
        - That frame is then sent every 125 ms (unless a command or MT overrides).
        """
        self._current_proto = proto
        if proto is None:
            self._last_params_frame = None
            return

        self._last_params_frame = self.cmd_m.build_set_params(proto)
        # (Optional) could send once immediately here if you want.

    # ------------------------------------------------------------------
    #   Commands from UI
    # ------------------------------------------------------------------
    @Slot()
    def start_session(self):
        frame = self.cmd_m.start_stimulation_command()
        self._next_command_frame = frame

    @Slot()
    def stop_session(self):
        frame = self.cmd_m.stop_stimulation_command()
        self._next_command_frame = frame

    @Slot()
    def pause_session(self):
        frame = self.cmd_m.pause_stimulation_command()
        self._next_command_frame = frame

    @Slot()
    def error_state(self):
        frame = self.cmd_m.send_error_command()
        self._next_command_frame = frame

    @Slot(int)
    def single_pulse_request(self, current_MT: int):
        """
        One-shot single-pulse command with current MT value.
        Higher priority than MT streaming (next tick).
        """
        frame = self.cmd_m.send_single_pulse_command(current_MT)
        self._next_command_frame = frame

    @Slot()
    def idle_state(self):
        """
        One-shot idle command. Does NOT affect MT streaming flag.
        Used by UI as a “go back to idle” command.
        """
        frame = self.cmd_m.send_IDLE_command()
        self._next_command_frame = frame

    # ---- MT streaming control ----------------------------------------
    @Slot(int)
    def mt_state(self, mt_value: int):
        """
        MT streaming entry/update.

        - Stores mt_value.
        - Enables MT streaming mode.
        Then, every 125 ms, _on_tx_tick will send mt_state(mt_value)
        instead of the regular params frame, until MT streaming is disabled.
        """
        self._mt_current_value = int(mt_value)
        self._mt_streaming = True

    @Slot(bool)
    def set_mt_streaming(self, enable: bool):
        """
        Enable/disable continuous MT streaming.

        - When True: _on_tx_tick sends mt_state(mt_value) each tick.
        - When False: _on_tx_tick goes back to sending params frames.
        """
        self._mt_streaming = bool(enable)

    @Slot(object)
    def apply_protocol(self, proto):
        """
        Optional: alias for request_param_update.
        """
        self.request_param_update(proto)

    # ------------------------------------------------------------------
    #   TX scheduler
    # ------------------------------------------------------------------
    def _on_tx_tick(self):
        """
        Called every 125 ms.
        Priority:
        1) If there is a queued command frame -> send it, clear, return.
        2) Else, if MT streaming is enabled -> send mt_state(current_MT).
        3) Else, if we have a params frame -> send that.
        """
        # 1) send command if pending
        if self._next_command_frame is not None:
            self._send_packet(self._next_command_frame)
            self._next_command_frame = None
            return

        # 2) MT streaming mode
        if self._mt_streaming and (self._mt_current_value is not None):
            frame = self.cmd_m.mt_state(int(self._mt_current_value))
            self._send_packet(frame)
            return

        # 3) otherwise send latest params frame
        if self._last_params_frame is not None:
            self._send_packet(self._last_params_frame)

    def _send_packet(self, frame: bytes):
        if not frame:
            return
        self.uart_s.send(frame)

    # ------------------------------------------------------------------
    #   RX handlers
    # ------------------------------------------------------------------
    def _on_state_from_uc(self, val: int):
        # map uC state code to enum if you like
        if val == 0:
            self._state = SessionState.IDLE
        elif val == 1:
            self._state = SessionState.SET_PARAMETERS
        self.stateFromUc.emit(val)

    def _on_intensity_from_uc(self, val: int):
        self.intensityFromUc.emit(val)

    def _on_coil_temp_from_uc(self, temp: float):
        self.coilTempFromUc.emit(temp)

    def _on_igbt_temp_from_uc(self, temp: float):
        self.igbtTempFromUc.emit(temp)

    def _on_resistor_temp_from_uc(self, temp: float):
        self.resistorTempFromUc.emit(temp)

    def _on_sw_state_from_uc(self, state: bool):
        self.sw_state_from_uC.emit(state)

    # ------------------------------------------------------------------
    #   Debug helpers
    # ------------------------------------------------------------------
    def _on_cmd_packet_ready_debug(self, frame: bytes):
        print("[CMD FRAME]", frame.hex(" "))
        pass
