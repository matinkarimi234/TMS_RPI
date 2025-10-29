from PySide6.QtWidgets import (
    QWidget, QLabel, QLineEdit,
    QDoubleSpinBox, QSpinBox,
    QFormLayout, QApplication, QComboBox
)
import sys, os
from pathlib import Path

# ensure we can import from src/core
ROOT = Path(__file__).parent.parent
SRC  = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.protocol_manager import TMSProtocol, ProtocolManager

class ProtocolWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TMS Protocol Editor")

        # load protocols
        self.manager = ProtocolManager()
        self.manager.load_from_json(SRC / "protocols.json")

        # widgets
        self.protocol_cb = QComboBox()
        self.protocol_cb.addItems(self.manager.list_protocols())
        self.protocol_cb.currentTextChanged.connect(self.on_protocol_changed)

        self.mt_sb    = QDoubleSpinBox()
        self.mt_sb.setRange(TMSProtocol.MIN_MT_PERCENT,
                            TMSProtocol.MAX_MT_PERCENT)
        self.mt_sb.setSingleStep(1.0)
        self.mt_sb.valueChanged.connect(self.on_mt_changed)

        self.rel_sb   = QDoubleSpinBox()
        self.rel_sb.setRange(TMSProtocol.MIN_RELATIVE_INTENSITY_PERCENT,
                             TMSProtocol.MAX_RELATIVE_INTENSITY_PERCENT_STATIC)
        self.rel_sb.setSingleStep(1.0)
        self.rel_sb.valueChanged.connect(self.on_rel_changed)

        self.abs_sb   = QDoubleSpinBox()
        self.abs_sb.setRange(TMSProtocol.MIN_ABSOLUTE_OUTPUT_PERCENT,
                             TMSProtocol.MAX_ABSOLUTE_OUTPUT_PERCENT)
        self.abs_sb.setSingleStep(1.0)
        self.abs_sb.valueChanged.connect(self.on_abs_changed)

        self.freq_sb  = QDoubleSpinBox()
        self.freq_sb.setRange(TMSProtocol.MIN_FREQUENCY_HZ,
                              TMSProtocol.MAX_FREQUENCY_HZ)
        self.freq_sb.setSingleStep(0.1)
        self.freq_sb.valueChanged.connect(self.on_freq_changed)

        self.pulses_sb = QSpinBox()
        self.pulses_sb.setRange(TMSProtocol.MIN_PULSES_PER_TRAIN,
                                TMSProtocol.MAX_PULSES_PER_TRAIN)
        self.pulses_sb.valueChanged.connect(self.on_pulses_changed)

        self.count_sb  = QSpinBox()
        self.count_sb.setRange(TMSProtocol.MIN_TRAIN_COUNT,
                               TMSProtocol.MAX_TRAIN_COUNT)
        self.count_sb.valueChanged.connect(self.on_count_changed)

        self.interval_sb = QDoubleSpinBox()
        self.interval_sb.setRange(TMSProtocol.MIN_INTER_TRAIN_INTERVAL_S,
                                  TMSProtocol.MAX_INTER_TRAIN_INTERVAL_S)
        self.interval_sb.setSingleStep(0.1)
        self.interval_sb.valueChanged.connect(self.on_interval_changed)

        self.target_le = QLineEdit()
        self.target_le.textChanged.connect(self.on_target_changed)

        self.desc_le   = QLineEdit()
        self.desc_le.textChanged.connect(self.on_description_changed)

        self.ramp_frac_sb = QDoubleSpinBox()
        self.ramp_frac_sb.setRange(TMSProtocol.MIN_RAMP_FRACTION,
                                   TMSProtocol.MAX_RAMP_FRACTION)
        self.ramp_frac_sb.setSingleStep(0.01)
        self.ramp_frac_sb.valueChanged.connect(self.on_ramp_fraction_changed)

        self.ramp_steps_sb = QSpinBox()
        self.ramp_steps_sb.setRange(TMSProtocol.MIN_RAMP_STEPS,
                                   TMSProtocol.MAX_RAMP_STEPS)
        self.ramp_steps_sb.valueChanged.connect(self.on_ramp_steps_changed)

        self.total_pulses_lbl   = QLabel("0")
        self.total_duration_lbl = QLabel("0.00")

        # layout
        form = QFormLayout()
        form.addRow("Protocol",               self.protocol_cb)
        form.addRow("MT % (MSO)",             self.mt_sb)
        form.addRow("Intensity % of MT",      self.rel_sb)
        form.addRow("Absolute % MSO",         self.abs_sb)
        form.addRow("Freq (Hz)",              self.freq_sb)
        form.addRow("Pulses/Train",           self.pulses_sb)
        form.addRow("Train Count",            self.count_sb)
        form.addRow("Interval (s)",           self.interval_sb)
        form.addRow("Target Region",          self.target_le)
        form.addRow("Description",            self.desc_le)
        form.addRow("Ramp Fraction",          self.ramp_frac_sb)
        form.addRow("Ramp Steps",             self.ramp_steps_sb)
        form.addRow("Total Pulses",           self.total_pulses_lbl)
        form.addRow("Total Duration (s)",     self.total_duration_lbl)
        self.setLayout(form)

        # initialize
        self.on_protocol_changed(self.protocol_cb.currentText())

    def on_protocol_changed(self, name: str):
        self.current = self.manager.get_protocol(name)
        # block signals
        widgets = [
            self.mt_sb, self.rel_sb, self.abs_sb,
            self.freq_sb, self.pulses_sb, self.count_sb,
            self.interval_sb, self.target_le, self.desc_le,
            self.ramp_frac_sb, self.ramp_steps_sb
        ]
        for w in widgets:
            w.blockSignals(True)

        self.mt_sb.setValue(self.current.subject_mt_percent)
        self.rel_sb.setValue(self.current.intensity_percent_of_mt)
        self.abs_sb.setValue(self.current.absolute_output_percent)
        self.freq_sb.setValue(self.current.frequency_hz)
        self.pulses_sb.setValue(self.current.pulses_per_train)
        self.count_sb.setValue(self.current.train_count)
        self.interval_sb.setValue(self.current.inter_train_interval_s)
        self.target_le.setText(self.current.target_region)
        self.desc_le.setText(self.current.description or "")
        self.ramp_frac_sb.setValue(self.current.ramp_fraction)
        self.ramp_steps_sb.setValue(self.current.ramp_steps)

        for w in widgets:
            w.blockSignals(False)

        self._update_dependent_bounds()
        self._update_summary()

    def _update_dependent_bounds(self):
        max_rel = min(
            TMSProtocol.MAX_RELATIVE_INTENSITY_PERCENT_STATIC,
            10000.0 / self.current.subject_mt_percent
        )
        self.rel_sb.setMaximum(max_rel)

    def _update_summary(self):
        self.total_pulses_lbl.setText(str(self.current.total_pulses()))
        self.total_duration_lbl.setText(f"{self.current.total_duration_s():.2f}")

    # handlers
    def on_mt_changed(self, v):           self.current.subject_mt_percent      = v; self._update_dependent_bounds(); self.rel_sb.setValue(self.current.intensity_percent_of_mt); self.abs_sb.setValue(self.current.absolute_output_percent); self._update_summary()
    def on_rel_changed(self, v):          self.current.intensity_percent_of_mt = v; self.abs_sb.setValue(self.current.absolute_output_percent); self._update_summary()
    def on_abs_changed(self, v):          self.current.absolute_output_percent = v; self.rel_sb.setValue(self.current.intensity_percent_of_mt); self._update_summary()
    def on_freq_changed(self, v):         self.current.frequency_hz             = v; self._update_summary()
    def on_pulses_changed(self, v):       self.current.pulses_per_train        = v; self._update_summary()
    def on_count_changed(self, v):        self.current.train_count              = v; self._update_summary()
    def on_interval_changed(self, v):     self.current.inter_train_interval_s   = v; self._update_summary()
    def on_target_changed(self, v):       self.current.target_region            = v
    def on_description_changed(self, v):  self.current.description              = v
    def on_ramp_fraction_changed(self, v):self.current.ramp_fraction           = v; self._update_summary()
    def on_ramp_steps_changed(self, v):   self.current.ramp_steps               = v; self._update_summary()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w   = ProtocolWidget()
    w.show()
    sys.exit(app.exec())
