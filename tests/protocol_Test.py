from PySide6.QtWidgets import (
    QWidget, QLabel, QComboBox, QLineEdit, QFormLayout, QApplication
)
from PySide6.QtGui import QDoubleValidator
from PySide6.QtCore import Qt

import os, sys
from pathlib import Path

# calculate absolute path to the "src" folder
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SRC_ROOT     = os.path.join(PROJECT_ROOT, "src")

# insert src/ at front of sys.path so that "import core.*" works
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)


from core.protocol_manager import TMSProtocol, ProtocolManager


class ProtocolWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TMS Protocol Editor")

        # load manager & protocols
        self.manager = ProtocolManager()
        # assume you have protocols.json in cwd
        self.manager.load_from_json(Path(PROJECT_ROOT) / "src" / "protocols.json")

        # UI elements
        self.combo = QComboBox()
        self.combo.addItems(self.manager.list_protocols())
        self.combo.currentTextChanged.connect(self.on_protocol_changed)

        self.mt_input = QLineEdit()
        self.mt_input.setValidator(QDoubleValidator(
            TMSProtocol.MIN_MT_PERCENT,
            TMSProtocol.MAX_MT_PERCENT,
            1,
            notation=QDoubleValidator.StandardNotation
        ))
        self.mt_input.editingFinished.connect(self.on_mt_changed)

        self.rel_input = QLineEdit()
        self.rel_validator = QDoubleValidator(
            TMSProtocol.MIN_RELATIVE_INTENSITY_PERCENT,
            TMSProtocol.MAX_RELATIVE_INTENSITY_PERCENT_STATIC,
            1,
            notation=QDoubleValidator.StandardNotation
        )
        self.rel_input.setValidator(self.rel_validator)
        self.rel_input.editingFinished.connect(self.on_rel_changed)

        self.abs_input = QLineEdit()
        self.abs_validator = QDoubleValidator(
            TMSProtocol.MIN_ABSOLUTE_OUTPUT_PERCENT,
            TMSProtocol.MAX_ABSOLUTE_OUTPUT_PERCENT,
            1,
            notation=QDoubleValidator.StandardNotation
        )
        self.abs_input.setValidator(self.abs_validator)
        self.abs_input.editingFinished.connect(self.on_abs_changed)

        # layout
        form = QFormLayout()
        form.addRow("Protocol", self.combo)
        form.addRow("Motor Threshold (% MSO)", self.mt_input)
        form.addRow("Intensity (% of MT)", self.rel_input)
        form.addRow("Absolute Output (% MSO)", self.abs_input)
        self.setLayout(form)

        # initialize with first protocol
        self.on_protocol_changed(self.combo.currentText())

    def on_protocol_changed(self, name: str):
        self.current: TMSProtocol = self.manager.get_protocol(name)
        self.update_fields()

    def update_fields(self):
        # sync UI from current protocol object
        self.mt_input.setText(f"{self.current.subject_mt_percent:.1f}")
        self.rel_input.setText(f"{self.current.intensity_percent_of_mt:.1f}")
        self.abs_input.setText(f"{self.current.absolute_output_percent:.1f}")
        self.update_rel_bounds()

    def update_rel_bounds(self):
        # dynamic upper bound so that absolute_output never exceeds 100% MSO
        max_rel = min(
            TMSProtocol.MAX_RELATIVE_INTENSITY_PERCENT_STATIC,
            100.0 * 100.0 / self.current.subject_mt_percent
        )
        self.rel_validator.setTop(max_rel)

    def on_mt_changed(self):
        txt = self.mt_input.text()
        if not txt:
            return
        self.current.subject_mt_percent = float(txt)
        # mt change cascades into rel & abs
        self.update_rel_bounds()
        self.rel_input.setText(f"{self.current.intensity_percent_of_mt:.1f}")
        self.abs_input.setText(f"{self.current.absolute_output_percent:.1f}")

    def on_rel_changed(self):
        txt = self.rel_input.text()
        if not txt:
            return
        self.current.intensity_percent_of_mt = float(txt)
        # rel change cascades into abs
        self.abs_input.setText(f"{self.current.absolute_output_percent:.1f}")

    def on_abs_changed(self):
        txt = self.abs_input.text()
        if not txt:
            return
        self.current.absolute_output_percent = float(txt)
        # abs change cascades into rel
        self.rel_input.setText(f"{self.current.intensity_percent_of_mt:.1f}")


if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    w = ProtocolWidget()
    w.show()
    sys.exit(app.exec())
