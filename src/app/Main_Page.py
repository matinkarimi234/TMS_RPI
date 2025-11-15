
from typing import Optional
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QApplication, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton)
from pathlib import Path
import sys
PROJECT_ROOT = Path(__file__).parent.resolve()
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from app.theme_manager import ThemeManager
from core._Archive.protocol_manager import TMSProtocol
from ui.widgets.navigation_list_widget import NavigationListWidget
from ui.widgets.pulse_bars_widget import PulseBarsWidget

from ui.widgets.intensity_gauge import IntensityGauge

class ParamsPage(QWidget):
    """
    Shows the currently selected TMSProtocol:
      - title/desc
      - waveform schematic (PulseBarsWidget)
      - left column: IntensityGauge + MTSlider
      - editable param list (minus MT & Intensity) with nav/edit buttons
      - theme toggle & protocol chooser
    """
    request_protocol_list = Signal()

    def __init__(self, theme_manager: ThemeManager, initial_theme="dark", parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.current_theme = initial_theme

        self.current_protocol: Optional[TMSProtocol] = None

        # ── Header ─────────────────────────────────────────
        self.lbl_name = QLabel("Protocol: <none>")
        self.lbl_desc = QLabel("Description: <none>")

        # ── Left column: Intensity gauge + MT slider ───────
        self.intensity_gauge = IntensityGauge(self)

        # live updates back into the protocol
        self.intensity_gauge.valueChanged.connect(self._on_intensity_changed)

        # ── PulseBarsWidget (waveform schematic) ───────────
        self.pulse_widget = PulseBarsWidget(self)

        # ── Parameter list (MT & Intensity REMOVED) ────────
        self.list_widget = NavigationListWidget()
        params = [
            ("Frequency (Hz)",
             "frequency_hz",
             TMSProtocol.MIN_FREQUENCY_HZ,
             TMSProtocol.MAX_FREQUENCY_HZ,
             "Hz"),
            ("Pulses per Train",
             "pulses_per_train",
             TMSProtocol.MIN_PULSES_PER_TRAIN,
             TMSProtocol.MAX_PULSES_PER_TRAIN,
             ""),
            ("Train Count",
             "train_count",
             TMSProtocol.MIN_TRAIN_COUNT,
             TMSProtocol.MAX_TRAIN_COUNT,
             ""),
            ("Inter-train Interval (s)",
             "inter_train_interval_s",
             TMSProtocol.MIN_INTER_TRAIN_INTERVAL_S,
             TMSProtocol.MAX_INTER_TRAIN_INTERVAL_S,
             "s"),
            ("Ramp Fraction",
             "ramp_fraction",
             TMSProtocol.MIN_RAMP_FRACTION,
             TMSProtocol.MAX_RAMP_FRACTION,
             ""),
            ("Ramp Steps",
             "ramp_steps",
             TMSProtocol.MIN_RAMP_STEPS,
             TMSProtocol.MAX_RAMP_STEPS,
             ""),
        ]
        for label, key, lo, hi, unit in params:
            self.list_widget.add_item(
                title=label,
                value=0,
                bounds="",
                data={"key": key, "lo": lo, "hi": hi, "unit": unit}
            )
        self.list_widget.setCurrentRow(0)

        # ── Up / Down navigation ──────────────────────────
        btn_up = QPushButton("Up")
        btn_down = QPushButton("Down")
        btn_up.clicked.connect(self.list_widget.select_previous)
        btn_down.clicked.connect(self.list_widget.select_next)
        nav_box = QHBoxLayout()
        nav_box.addWidget(btn_up)
        nav_box.addWidget(btn_down)

        # ── + / − edit buttons (affect list params only) ──
        btn_dec = QPushButton("- Decrease")
        btn_inc = QPushButton("+ Increase")
        btn_dec.clicked.connect(lambda: self._modify_value(-1))
        btn_inc.clicked.connect(lambda: self._modify_value(+1))
        edit_box = QHBoxLayout()
        edit_box.addWidget(btn_dec)
        edit_box.addWidget(btn_inc)

        # ── Bottom controls (protocol select, theme toggle) ─────────────────
        self.btn_select_protocol = QPushButton("Select Protocol")
        self.btn_select_protocol.clicked.connect(lambda: self.request_protocol_list.emit())
        self.btn_toggle_theme = QPushButton("Toggle Theme")
        self.btn_toggle_theme.clicked.connect(self._toggle_theme)
        bottom = QHBoxLayout()
        bottom.addWidget(self.btn_select_protocol)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_toggle_theme)

        # ── assemble left / center / right content ────────
        content = QHBoxLayout()

        # LEFT: Intensity (top) + MT (below)
        left_col = QVBoxLayout()
        left_col.addWidget(self.intensity_gauge)
        content.addLayout(left_col, stretch=0)

        # CENTER: waveform schematic
        content.addWidget(self.pulse_widget, stretch=1)

        # RIGHT: params list + controls
        param_col = QVBoxLayout()
        param_col.addWidget(self.list_widget, stretch=1)
        param_col.addLayout(nav_box)
        param_col.addLayout(edit_box)
        content.addLayout(param_col, stretch=1)

        # ── main layout ───────────────────────────────────
        main_lay = QVBoxLayout(self)
        main_lay.addWidget(self.lbl_name)
        main_lay.addWidget(self.lbl_desc)
        main_lay.addLayout(content, stretch=1)
        main_lay.addLayout(bottom)

        # Apply theme/palette now that widgets exist
        self._apply_theme_to_app(self.current_theme)

    # ---------------------------------------------------------
    # public API from MainWindow:
    # ---------------------------------------------------------
    def set_protocol(self, proto: TMSProtocol):
        """
        Bind TMSProtocol to the UI:
          - header labels
          - left column (gauge + MT slider)
          - waveform widget
          - parameter list values/bounds (excluding MT/Intensity)
        """
        self.current_protocol = proto

        # header text
        self.lbl_name.setText(f"Protocol: {proto.name}")
        desc = proto.description or "<none>"
        self.lbl_desc.setText(f"Description: {desc}")

        # left column widgets pull values/ranges from protocol
        self.intensity_gauge.setFromProtocol(proto)  # uses max_intensity_percent_of_mt

        # update the parameter list widget rows (list no longer includes MT/Intensity)
        def fmt(x):
            return f"{x:.1f}" if isinstance(x, float) else str(x)

        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            meta = item.data(Qt.UserRole) or {}
            key = meta.get("key")
            lo = meta.get("lo")
            hi = meta.get("hi")
            unit = meta.get("unit", "")
            row_widget = self.list_widget.itemWidget(item)
            if not key or not row_widget:
                continue

            val = getattr(proto, key)
            row_widget.set_value(val)
            suffix = f"{unit}   ( {fmt(lo)} – {fmt(hi)} )" if (lo is not None and hi is not None) else unit
            row_widget.set_suffix(suffix)

        # update the waveform widget:
        self.pulse_widget.set_protocol(proto)

        # refresh palettes on themed children
        pal = self.theme_manager.generate_palette(self.current_theme)
        self.pulse_widget.setPalette(pal)
        self.pulse_widget.train_view.setPalette(pal)
        self.pulse_widget.rest_circle.setPalette(pal)

        # also theme the new left-column widgets
        self.intensity_gauge.setPalette(pal)
        # call their theme hooks (colors like TEXT_COLOR_SECONDARY, gradients, etc.)
        try:
            self.intensity_gauge.applyTheme(self.theme_manager, self.current_theme)
        except Exception:
            pass

    # ---------------------------------------------------------
    # internal helpers
    # ---------------------------------------------------------

    def _on_intensity_changed(self, v: int):
        """When gauge value changes, write back to protocol and refresh UI."""
        if not self.current_protocol:
            return
        self.current_protocol.intensity_percent_of_mt = float(v)
        self.set_protocol(self.current_protocol)

    def _modify_value(self, delta: int):
        """Nudge the currently selected *list* param (MT/Intensity excluded)."""
        if not self.current_protocol:
            return
        item = self.list_widget.currentItem()
        if not item:
            return
        meta = item.data(Qt.UserRole) or {}
        key = meta.get("key")
        row_widget = self.list_widget.itemWidget(item)
        if not key or row_widget is None:
            return

        try:
            cur_val = float(row_widget.get_value())
        except (ValueError, TypeError):
            return

        setattr(self.current_protocol, key, cur_val + delta)
        self.set_protocol(self.current_protocol)

    def _apply_theme_to_app(self, theme_name: str):
        app = QApplication.instance()
        if app:
            ss = self.theme_manager.generate_stylesheet(theme_name)
            if ss:
                app.setStyleSheet(ss)

        pal = self.theme_manager.generate_palette(theme_name)

        # apply palette to composite widgets
        self.pulse_widget.setPalette(pal)
        self.pulse_widget.train_view.setPalette(pal)
        self.pulse_widget.rest_circle.setPalette(pal)

        self.intensity_gauge.setPalette(pal)

        # propagate token-based colors (ACCENT_GRADIENT_START/END, TEXT_COLOR_SECONDARY, etc.)
        try:
            self.intensity_gauge.applyTheme(self.theme_manager, theme_name)
        except Exception:
            print("Cant apply theme to gauge and slider")

    def _toggle_theme(self):
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        self._apply_theme_to_app(self.current_theme)
        # re-bind to make sure any dynamic bounds are refreshed under the new theme
        if self.current_protocol:
            self.set_protocol(self.current_protocol)
