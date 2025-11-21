from PySide6.QtCore import QObject, Signal

class RxManager(QObject):
    tms_state = Signal(int)

    coil_temperature_reading = Signal(float)
    igbt_temperature_reading = Signal(float)
    resistor_temperature_reading = Signal(float)
    uC_SW_state_Reading = Signal(bool)

    intensity_reading = Signal(int)

    def __init__(self, uart_service):
        super().__init__()
        uart_service.telemetry_updated.connect(self._on_packet)

    def _on_packet(self, packet: bytes):
        # State : IDLE, Single, Start, Run Stimulation, Pause, Stop, Error
        uC_state = int(packet[1])

        # Intensity or MT can change by this encoder BigIndian
        intensity_Enc = (packet[2] << 8) + (packet[3] << 0)

        # Reading Temperatures e.g. 23.1
        coil_temp_i16 = (packet[4] << 8) + (packet[5] << 0)
        coil_Temperature = round(float(0.1 * coil_temp_i16), 1)

        igbt_temp_i16 = (packet[6] << 8) + (packet[7] << 0)
        igbt_Temperature = round(float(0.1 * igbt_temp_i16), 1)

        resistor_temp_i16 = (packet[8] << 8) + (packet[9] << 0)
        resistor_Temperature = round(float(0.1 * resistor_temp_i16), 1)

        uC_SW_state = bool((packet[10] >> 0) & 0x01)

        self.tms_state.emit(uC_state)
        self.intensity_reading.emit(intensity_Enc) # Event with Args

        self.coil_temperature_reading.emit(coil_Temperature)
        self.igbt_temperature_reading.emit(igbt_Temperature)
        self.resistor_temperature_reading.emit(resistor_Temperature)

        self.uC_SW_state_Reading.emit(uC_SW_state)