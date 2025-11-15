# ---------------------------------------------------------------
# TMS Protocol Editor Widget (Revised for New TMSProtocol Logic)
# ---------------------------------------------------------------
#
# Key Revisions:
# 1. Centralized UI Update via `sync_ui_from_protocol`:
#    The entire interface is refreshed from the model in one place.
#
# 2. Simplified Handlers:
#    Each slot directly updates the `TMSProtocol` object and calls `sync_ui_from_protocol`
#    to update everything else (range limits and dependent fields).
#
# 3. Dynamic Range Updates:
#    Frequency maximum is dynamically computed using
#    TMSProtocol._calculate_max_frequency_hz().
#    IPI and Burst remain with fixed hard ranges.
#
# 4. Removed Old Logic:
#    No local recalculation helpers or scattered updates remain.
#
# ---------------------------------------------------------------

from PySide6.QtWidgets import (
    QWidget, QLabel, QLineEdit,
    QDoubleSpinBox, QSpinBox,
    QFormLayout, QApplication, QComboBox
)
import sys
from pathlib import Path

# Locate your core module dynamically
ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Import the revised protocol classes
from core.protocol_manager_revised import TMSProtocol, ProtocolManager


class ProtocolWidget(QWidget):
    """User interface for editing a TMSProtocol object."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TMS Protocol Editor (Revised)")
        self.current: TMSProtocol | None = None

        # --- Protocol Manager and Data Loading ---
        self.manager = ProtocolManager()
        try:
            json_path = Path(__file__).parent / "protocols.json"
            if not json_path.exists():
                json_path = SRC / "protocols.json"
            self.manager.load_from_json(json_path)
        except (FileNotFoundError, IOError) as e:
            print(f"⚠️ Warning: Could not load protocols.json: {e}")
            default_p = TMSProtocol(
                name="Default",
                target_region="DLPFC",
                description="Default test protocol",
                subject_mt_percent_init=50,
                intensity_percent_of_mt_init=100,
                frequency_hz_init=10,
                pulses_per_train=50,
                train_count=10,
                inter_train_interval_s=20,
            )
            self.manager.add_protocol(default_p)

        # --- Widget Creation ---
        self.protocol_cb = QComboBox()
        self.mt_sb = QSpinBox()
        self.rel_sb = QSpinBox()
        self.freq_sb = QDoubleSpinBox()
        self.ipi_sb = QDoubleSpinBox()
        self.burst_pulses_sb = QSpinBox()
        self.waveform_cb = QComboBox()
        self.pulses_sb = QSpinBox()
        self.count_sb = QSpinBox()
        self.interval_sb = QDoubleSpinBox()
        self.target_le = QLineEdit()
        self.desc_le = QLineEdit()
        self.ramp_frac_sb = QDoubleSpinBox()
        self.ramp_steps_sb = QSpinBox()

        # --- Configuration & Connections ---
        self._configure_widgets()

        # --- Layout ---
        form = QFormLayout()
        form.addRow("Protocol", self.protocol_cb)
        form.addRow("MT % (MSO)", self.mt_sb)
        form.addRow("Intensity % of MT", self.rel_sb)
        form.addRow("Frequency (Hz)", self.freq_sb)
        form.addRow("IPI (ms)", self.ipi_sb)
        form.addRow("Pulses per Burst", self.burst_pulses_sb)
        form.addRow("Waveform", self.waveform_cb)
        form.addRow("Pulses/Train", self.pulses_sb)
        form.addRow("Train Count", self.count_sb)
        form.addRow("Inter-Train Interval (s)", self.interval_sb)
        form.addRow("Target Region", self.target_le)
        form.addRow("Description", self.desc_le)
        form.addRow("Ramp Fraction", self.ramp_frac_sb)
        form.addRow("Ramp Steps", self.ramp_steps_sb)
        self.setLayout(form)

        # --- Initial Population ---
        if self.manager.protocols:
            self.protocol_cb.addItems(self.manager.list_protocols())
            self.on_protocol_changed(self.protocol_cb.currentText())

    # ------------------------------------------------------------
    # Widget Configuration
    # ------------------------------------------------------------

    def _configure_widgets(self):
        """Defines basic ranges, step sizes, and connects signals."""
        # Protocol selection
        self.protocol_cb.currentTextChanged.connect(self.on_protocol_changed)

        # MT & Intensity
        self.mt_sb.setRange(TMSProtocol.SUBJECT_MT_MIN, TMSProtocol.SUBJECT_MT_MAX)
        self.mt_sb.valueChanged.connect(self.on_mt_changed)
        self.rel_sb.setRange(TMSProtocol.INTENSITY_OF_MT_MIN, TMSProtocol.INTENSITY_OF_MT_MAX)
        self.rel_sb.valueChanged.connect(self.on_rel_changed)

        # Frequency/IPI/Burst Config
        self.freq_sb.setRange(TMSProtocol.FREQ_MIN, TMSProtocol.FREQ_MAX)
        self.freq_sb.setSingleStep(0.1)
        self.freq_sb.setDecimals(1)
        self.freq_sb.valueChanged.connect(self.on_freq_changed)

        self.ipi_sb.setRange(TMSProtocol.IPI_MIN_HARD, TMSProtocol.IPI_MAX_HARD)
        self.ipi_sb.setSingleStep(0.1)
        self.ipi_sb.setDecimals(1)
        self.ipi_sb.valueChanged.connect(self.on_ipi_changed)

        self.burst_pulses_sb.setRange(
            min(TMSProtocol.BURST_PULSES_ALLOWED),
            max(TMSProtocol.BURST_PULSES_ALLOWED)
        )
        self.burst_pulses_sb.valueChanged.connect(self.on_burst_pulses_changed)

        # Remaining parameters
        self.waveform_cb.addItems(["biphasic", "biphasic_burst"])
        self.waveform_cb.currentTextChanged.connect(self.on_waveform_changed)
        self.pulses_sb.setRange(1, 10000)
        self.pulses_sb.valueChanged.connect(self.on_pulses_changed)
        self.count_sb.setRange(1, 10000)
        self.count_sb.valueChanged.connect(self.on_count_changed)
        self.interval_sb.setRange(0.01, 10000.0)
        self.interval_sb.setSingleStep(0.1)
        self.interval_sb.valueChanged.connect(self.on_interval_changed)

        self.target_le.textChanged.connect(self.on_target_changed)
        self.desc_le.textChanged.connect(self.on_description_changed)

        self.ramp_frac_sb.setRange(0.7, 1.0)
        self.ramp_frac_sb.setSingleStep(0.01)
        self.ramp_frac_sb.valueChanged.connect(self.on_ramp_fraction_changed)
        self.ramp_steps_sb.setRange(1, 10)
        self.ramp_steps_sb.valueChanged.connect(self.on_ramp_steps_changed)

    # ------------------------------------------------------------
    # Core Update Logic
    # ------------------------------------------------------------

    def on_protocol_changed(self, name: str):
        """Load a new protocol by name."""
        self.current = self.manager.get_protocol(name)
        self.sync_ui_from_protocol()

    def sync_ui_from_protocol(self):
        """Centralized synchronization from the current protocol to all UI widgets."""
        if not self.current:
            return

        widgets_to_block = [
            self.mt_sb, self.rel_sb, self.freq_sb, self.ipi_sb,
            self.burst_pulses_sb, self.waveform_cb, self.pulses_sb,
            self.count_sb, self.interval_sb, self.target_le,
            self.desc_le, self.ramp_frac_sb, self.ramp_steps_sb
        ]
        for w in widgets_to_block:
            w.blockSignals(True)

        # --- Dynamic bounds ---
        freq_min = self.current._calculate_min_frequency_hz()
        freq_max = self.current._calculate_max_frequency_hz()
        self.freq_sb.setRange(freq_min, freq_max)
        self.ipi_sb.setRange(TMSProtocol.IPI_MIN_HARD, TMSProtocol.IPI_MAX_HARD)
        self.burst_pulses_sb.setRange(
            min(TMSProtocol.BURST_PULSES_ALLOWED),
            max(TMSProtocol.BURST_PULSES_ALLOWED)
        )
        self.rel_sb.setMaximum(self.current._max_intensity_for_current_mt())

        # --- Set widget values ---
        self.mt_sb.setValue(self.current.subject_mt_percent)
        self.rel_sb.setValue(self.current.intensity_percent_of_mt)
        self.freq_sb.setValue(self.current.frequency_hz)
        self.ipi_sb.setValue(self.current.inter_pulse_interval_ms)
        self.burst_pulses_sb.setValue(self.current.burst_pulses_count)
        self.waveform_cb.setCurrentText(self.current.waveform)
        self.pulses_sb.setValue(self.current.pulses_per_train)
        self.count_sb.setValue(self.current.train_count)
        self.interval_sb.setValue(self.current.inter_train_interval_s)
        self.target_le.setText(self.current.target_region)
        self.desc_le.setText(self.current.description or "")
        self.ramp_frac_sb.setValue(self.current.ramp_fraction)
        self.ramp_steps_sb.setValue(self.current.ramp_steps)

        for w in widgets_to_block:
            w.blockSignals(False)

    # ------------------------------------------------------------
    # Slot Handlers
    # ------------------------------------------------------------
    # Each handler updates the model then refreshes the entire UI.

    def on_mt_changed(self, value):
        if self.current:
            self.current.subject_mt_percent = value
            self.sync_ui_from_protocol()

    def on_rel_changed(self, value):
        if self.current:
            self.current.intensity_percent_of_mt = value
            self.sync_ui_from_protocol()

    def on_freq_changed(self, value):
        if self.current:
            self.current.frequency_hz = value
            self.sync_ui_from_protocol()

    def on_ipi_changed(self, value):
        if self.current:
            self.current.inter_pulse_interval_ms = value
            self.sync_ui_from_protocol()

    def on_burst_pulses_changed(self, value):
        if self.current:
            self.current.burst_pulses_count = value
            self.sync_ui_from_protocol()

    def on_waveform_changed(self, text):
        if self.current:
            self.current.waveform = text
            self.sync_ui_from_protocol()

    def on_pulses_changed(self, value):
        if self.current:
            self.current.pulses_per_train = value
            self.sync_ui_from_protocol()

    def on_count_changed(self, value):
        if self.current:
            self.current.train_count = value
            self.sync_ui_from_protocol()

    def on_interval_changed(self, value):
        if self.current:
            self.current.inter_train_interval_s = value
            self.sync_ui_from_protocol()

    def on_target_changed(self, text):
        if self.current:
            self.current.target_region = text
            self.sync_ui_from_protocol()

    def on_description_changed(self, text):
        if self.current:
            self.current.description = text
            self.sync_ui_from_protocol()

    def on_ramp_fraction_changed(self, value):
        if self.current:
            self.current.ramp_fraction = value
            self.sync_ui_from_protocol()

    def on_ramp_steps_changed(self, value):
        if self.current:
            self.current.ramp_steps = value
            self.sync_ui_from_protocol()


# ------------------------------------------------------------
# Entry Point
# ------------------------------------------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = ProtocolWidget()
    w.resize(420, 520)
    w.show()
    sys.exit(app.exec())
