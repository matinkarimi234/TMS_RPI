# demo.py
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QSizePolicy
)
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtCore import Signal, Qt

# ─── allow imports from src/ ────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.resolve()
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# ─── your existing modules under src/ ─────────────────────────
from app.theme_manager import ThemeManager
from core.protocol_manager import ProtocolManager, TMSProtocol
from ui.widgets.navigation_list_widget import NavigationListWidget
from ui.widgets.pulse_bars_widget import PulseBarsWidget
# ───────────────────────────────────────────────────────────────


class ParamsPage(QWidget):
    """
    Shows the currently selected TMSProtocol:
      - title/desc
      - schematic waveform (PulseBarsWidget)
      - editable param list (+/- navigation)
      - theme toggle
      - protocol chooser
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

        # ── PulseBarsWidget (waveform schematic + elapsed/remaining + start/stop) ─
        self.pulse_widget = PulseBarsWidget(self)
        # (palette will be applied after we build everything)

        # ── Parameter list ────────────────────────────────
        self.list_widget = NavigationListWidget()
        params = [
            ("MT Threshold (%)",
             "subject_mt_percent",
             TMSProtocol.MIN_MT_PERCENT,
             TMSProtocol.MAX_MT_PERCENT,
             "%"),
            ("Intensity (% of MT)",
             "intensity_percent_of_mt",
             TMSProtocol.MIN_RELATIVE_INTENSITY_PERCENT,
             None,  # dynamic max at runtime
             "%"),
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

        # ── + / − edit buttons ───────────────────────────
        btn_dec = QPushButton("- Decrease")
        btn_inc = QPushButton("+ Increase")
        btn_dec.clicked.connect(lambda: self._modify_value(-1))
        btn_inc.clicked.connect(lambda: self._modify_value(+1))
        edit_box = QHBoxLayout()
        edit_box.addWidget(btn_dec)
        edit_box.addWidget(btn_inc)

        # ── Bottom controls (protocol select, theme toggle) ─────────────────
        self.btn_select_protocol = QPushButton("Select Protocol")
        self.btn_select_protocol.clicked.connect(
            lambda: self.request_protocol_list.emit()
        )
        self.btn_toggle_theme = QPushButton("Toggle Theme")
        self.btn_toggle_theme.clicked.connect(self._toggle_theme)
        bottom = QHBoxLayout()
        bottom.addWidget(self.btn_select_protocol)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_toggle_theme)

        # ── assemble left/right content ───────────────────
        content = QHBoxLayout()
        content.addWidget(self.pulse_widget, stretch=1)

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

        # NOW that widgets exist, apply theme (stylesheet + palettes)
        self._apply_theme_to_app(self.current_theme)

    # ---------------------------------------------------------
    # public API from MainWindow:
    # ---------------------------------------------------------
    def set_protocol(self, proto: TMSProtocol):
        """
        Load a TMSProtocol and update:
          - header labels
          - parameter list values/bounds
          - waveform widget (pulse_widget)
        """
        self.current_protocol = proto

        # header text
        self.lbl_name.setText(f"Protocol: {proto.name}")
        desc = proto.description or "<none>"
        self.lbl_desc.setText(f"Description: {desc}")

        # helper for formatting display ranges
        def fmt(x):
            return f"{x:.1f}" if isinstance(x, float) else str(x)

        # update the parameter list widget rows
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

            # live value from protocol
            val = getattr(proto, key)
            row_widget.set_value(val)

            # dynamic max for intensity % of MT
            hi_act = proto.max_intensity_percent_of_mt if key == "intensity_percent_of_mt" else hi
            suffix = f"{unit}   ( {fmt(lo)} – {fmt(hi_act)} )"
            row_widget.set_suffix(suffix)

        # update the waveform widget:
        self.pulse_widget.set_protocol(proto)

        # refresh palette on the waveform in case theme changed earlier
        self.pulse_widget.setPalette(self.theme_manager.generate_palette(self.current_theme))

    # ---------------------------------------------------------
    # internal helpers
    # ---------------------------------------------------------
    def _modify_value(self, delta: int):
        """
        User hit + or -. We nudge current selected param
        and then re-run set_protocol() so both UI columns and waveform redraw.
        """
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

        # write back into the dataclass (will auto-clamp via property setters)
        setattr(self.current_protocol, key, cur_val + delta)

        # re-bind everything
        self.set_protocol(self.current_protocol)

    def _apply_theme_to_app(self, theme_name: str):
        app = QApplication.instance()
        if app:
            ss = self.theme_manager.generate_stylesheet(theme_name)
            if ss:
                app.setStyleSheet(ss)

        pal = self.theme_manager.generate_palette(theme_name)

        if hasattr(self, "pulse_widget") and self.pulse_widget is not None:
            # apply to the composite widget
            self.pulse_widget.setPalette(pal)

            # and to its paint-children so they pick up QPalette.Highlight etc.
            self.pulse_widget.train_view.setPalette(pal)
            self.pulse_widget.rest_circle.setPalette(pal)

    def _toggle_theme(self):
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        self._apply_theme_to_app(self.current_theme)


# ───────────────────────────────────────────────────────────────
class ProtocolListPage(QWidget):
    accepted = Signal(str)
    canceled = Signal()

    def __init__(self, pm: ProtocolManager, parent=None):
        super().__init__(parent)
        self.pm = pm

        self.list_widget = QListWidget()
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.list_widget.addItems(self.pm.list_protocols())
        self.list_widget.setCurrentRow(0)

        btn_up = QPushButton("Up")
        btn_down = QPushButton("Down")
        btn_up.clicked.connect(self._up)
        btn_down.clicked.connect(self._down)
        nav = QHBoxLayout()
        nav.addWidget(btn_up)
        nav.addWidget(btn_down)

        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancel")
        btn_ok.clicked.connect(self._on_ok)
        btn_cancel.clicked.connect(lambda: self.canceled.emit())
        ctl = QHBoxLayout()
        ctl.addWidget(btn_ok)
        ctl.addWidget(btn_cancel)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(15, 10, 15, 10)
        lay.setSpacing(5)
        lay.addWidget(self.list_widget)
        lay.addLayout(nav)
        lay.addLayout(ctl)
        lay.setStretch(0, 1)

    def _up(self):
        r = self.list_widget.currentRow()
        if r > 0:
            self.list_widget.setCurrentRow(r - 1)

    def _down(self):
        r = self.list_widget.currentRow()
        if r < self.list_widget.count() - 1:
            self.list_widget.setCurrentRow(r + 1)

    def _on_ok(self):
        item = self.list_widget.currentItem()
        if item:
            self.accepted.emit(item.text())


# ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, protocol_json: Path, theme_manager: ThemeManager, initial_theme="dark"):
        super().__init__()
        self.setWindowTitle("TMS Control Interface")
        self.resize(320, 480)

        self.pm = ProtocolManager()
        self.pm.load_from_json(protocol_json)

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCentralWidget(self.stack)

        self.params = ParamsPage(theme_manager, initial_theme)
        self.params.request_protocol_list.connect(self._show_list)

        self.plist = ProtocolListPage(self.pm)
        self.plist.accepted.connect(self._choose)
        self.plist.canceled.connect(self._show_params)

        self.stack.addWidget(self.params)
        self.stack.addWidget(self.plist)
        self._show_params()

        self.resize(400, 600)
        self.setMinimumSize(320, 480)

        # load first protocol by default
        names = self.pm.list_protocols()
        if names:
            self._load(names[0])

    def _show_params(self):
        self.stack.setCurrentWidget(self.params)

    def _show_list(self):
        self.stack.setCurrentWidget(self.plist)

    def _choose(self, name: str):
        self._load(name)
        self._show_params()

    def _load(self, name: str):
        proto = self.pm.get_protocol(name)
        if proto:
            self.params.set_protocol(proto)


# ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)

    # load your custom font
    font_id = QFontDatabase.addApplicationFont("assets/fonts/Tw-Cen-MT-Condensed.ttf")
    families = QFontDatabase.applicationFontFamilies(font_id)
    if families:
        app.setFont(QFont(families[0]))

    tpl         = PROJECT_ROOT / "assets" / "styles" / "template.qss"
    theme_dir   = SRC          / "config"
    protocols_f = SRC          / "protocols.json"

    theme_mgr = ThemeManager(template_path=tpl, themes_dir=theme_dir)

    w = MainWindow(protocol_json=protocols_f,
                   theme_manager=theme_mgr,
                   initial_theme="dark")
    w.show()
    sys.exit(app.exec())
