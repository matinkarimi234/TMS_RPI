from typing import Optional
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton
)
from pathlib import Path
from app.theme_manager import ThemeManager
from core.protocol_manager_revised import TMSProtocol
from ui.widgets.navigation_list_widget import NavigationListWidget
from ui.widgets.pulse_bars_widget import PulseBarsWidget
from ui.widgets.intensity_gauge import IntensityGauge


class ParamsPage(QWidget):
    """
    Parameters editor for an active TMSProtocol.
    Simplified UI compared to ProtocolWidget, using TMSProtocol in full logic form.
    """

    request_protocol_list = Signal()

    def __init__(self, theme_manager: ThemeManager, initial_theme="dark", parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.current_theme = initial_theme
        self.current_protocol: Optional[TMSProtocol] = None

        # --- Header ---
        self.lbl_name = QLabel("Protocol: <none>")
        self.lbl_desc = QLabel("Description: <none>")

        # --- Auxiliary widgets ---
        self.intensity_gauge = IntensityGauge(self)
        self.intensity_gauge.valueChanged.connect(self._on_intensity_changed)

        self.pulse_widget = PulseBarsWidget(self)

        # --- Editable parameter list ---
        self.list_widget = NavigationListWidget()

        # Initialize the list with placeholders (filled when protocol is set)
        self.param_definitions = [
            ("Burst Pulses / Burst", "burst_pulses_count", "pulses"),
            ("Inter-pulse Interval (ms)", "inter_pulse_interval_ms", "ms"),
            ("Frequency (Hz)", "frequency_hz", "Hz"),
            ("Pulses per Train", "pulses_per_train", ""),
            ("Train Count", "train_count", ""),
            ("Inter-train Interval (s)", "inter_train_interval_s", "s"),
            ("Ramp Fraction", "ramp_fraction", ""),
            ("Ramp Steps", "ramp_steps", ""),
        ]

        for label, key, unit in self.param_definitions:
            self.list_widget.add_item(
                title=label,
                value=0,
                bounds="",
                data={"key": key, "unit": unit}
            )
        self.list_widget.setCurrentRow(0)

        # --- Navigation ---
        btn_up = QPushButton("Up")
        btn_down = QPushButton("Down")
        btn_up.clicked.connect(self.list_widget.select_previous)
        btn_down.clicked.connect(self.list_widget.select_next)

        nav_box = QHBoxLayout()
        nav_box.addWidget(btn_up)
        nav_box.addWidget(btn_down)

        # --- Increment/Decrement ---
        btn_dec = QPushButton("− Decrease")
        btn_inc = QPushButton("+ Increase")
        btn_dec.clicked.connect(lambda: self._modify_value(-1))
        btn_inc.clicked.connect(lambda: self._modify_value(+1))
        edit_box = QHBoxLayout()
        edit_box.addWidget(btn_dec)
        edit_box.addWidget(btn_inc)

        # --- Bottom Controls ---
        self.btn_select_protocol = QPushButton("Select Protocol")
        self.btn_select_protocol.clicked.connect(self.request_protocol_list.emit)

        self.btn_toggle_theme = QPushButton("Toggle Theme")
        self.btn_toggle_theme.clicked.connect(self._toggle_theme)
        bottom = QHBoxLayout()
        bottom.addWidget(self.btn_select_protocol)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_toggle_theme)

        # --- Layout ---
        content = QHBoxLayout()
        left_col = QVBoxLayout()
        left_col.addWidget(self.intensity_gauge)
        content.addLayout(left_col, stretch=0)

        content.addWidget(self.pulse_widget, stretch=1)

        right_col = QVBoxLayout()
        right_col.addWidget(self.list_widget, stretch=1)
        right_col.addLayout(nav_box)
        right_col.addLayout(edit_box)
        content.addLayout(right_col, stretch=1)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.lbl_name)
        main_layout.addWidget(self.lbl_desc)
        main_layout.addLayout(content, stretch=1)
        main_layout.addLayout(bottom)

        self._apply_theme_to_app(self.current_theme)

    # ---------------------------------------------------------
    #   Public binding to apply a protocol instance
    # ---------------------------------------------------------
    def set_protocol(self, proto: TMSProtocol):
        self.current_protocol = proto
        self.lbl_name.setText(f"Protocol: {proto.name}")
        self.lbl_desc.setText(f"Description: {getattr(proto, 'description', '<none>')}")

        self.intensity_gauge.setFromProtocol(proto)
        self.pulse_widget.set_protocol(proto)
        self._sync_ui_from_protocol()

        pal = self.theme_manager.generate_palette(self.current_theme)
        self.pulse_widget.setPalette(pal)
        self.intensity_gauge.setPalette(pal)
        try:
            self.intensity_gauge.applyTheme(self.theme_manager, self.current_theme)
        except Exception:
            pass

    # ---------------------------------------------------------
    #   Synchronize all displayed values from protocol
    # ---------------------------------------------------------
    def _sync_ui_from_protocol(self):
        """Refreshes all list widget entries from current protocol data and logic."""
        if not self.current_protocol:
            return

        proto = self.current_protocol

        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            row_widget = self.list_widget.itemWidget(item)
            meta = item.data(Qt.UserRole) or {}
            key = meta.get("key")
            unit = meta.get("unit", "")

            # Retrieve live value from protocol
            try:
                val = getattr(proto, key)
            except AttributeError:
                continue

            # Compute proper bounds dynamically
            lo, hi = self._get_param_range(proto)

            # Format and update
            if row_widget:
                row_widget.set_value(val)
                bounds_txt = f"{unit}   ({lo:.2f}–{hi:.2f})" if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) else unit
                row_widget.set_suffix(bounds_txt)

            

    # ---------------------------------------------------------
    #   Retrieve live parameter ranges based on protocol logic
    # ---------------------------------------------------------
    def _get_param_range(self, proto):
        """Return (lo, hi) for the given protocol field based on its logic."""
        key = None
        item = self.list_widget.currentItem()
        if item:
            meta = item.data(Qt.UserRole)
            if meta:
                key = meta.get("key")

        if not key:
            return 0, 1

        if key == "frequency_hz":
            return proto.FREQ_MIN, proto._calculate_max_frequency_hz()
        elif key == "inter_pulse_interval_ms":
            return proto.IPI_MIN_HARD, proto.IPI_MAX_HARD
        elif key == "pulses_per_train":
            return 1, 10000
        elif key == "train_count":
            return 1, 10000
        elif key == "inter_train_interval_s":
            return 0.01, 10000.0
        elif key == "burst_pulses_count":
            return (
                min(proto.BURST_PULSES_ALLOWED),
                max(proto.BURST_PULSES_ALLOWED)
            )
        elif key == "ramp_fraction":
            return 0.7, 1.0
        elif key == "ramp_steps":
            return 1, 10
        else:
            return 0, 1

    # ---------------------------------------------------------
    #   Interactive Handlers
    # ---------------------------------------------------------
    def _on_intensity_changed(self, v: int):
        """Handles intensity gauge change (kept for compatibility)."""
        if not self.current_protocol:
            return
        self.current_protocol.intensity_percent_of_mt_init = float(v)
        self._sync_ui_from_protocol()

    def _modify_value(self, delta: float):
        """Increment or decrement currently selected parameter with adaptive step size and hard pre-limit freeze."""
        if not self.current_protocol:
            return

        item = self.list_widget.currentItem()
        if not item:
            return
        meta = item.data(Qt.UserRole) or {}
        key = meta.get("key")
        if not key:
            return

        lo, hi = self._get_param_range(self.current_protocol)
        row_widget = self.list_widget.itemWidget(item)
        if row_widget is None:
            return

        try:
            cur_val = float(row_widget.get_value())
        except (ValueError, TypeError):
            cur_val = getattr(self.current_protocol, key, 0.0)

        # --- Adaptive, continuous step-size logic ---
        if key == "frequency_hz":
            if delta > 0 and cur_val < 1.0:
                step = 0.1
            elif delta < 0 and cur_val <= 1.0:
                step = 0.1
            else:
                step = 1.0
        elif key in ("inter_pulse_interval_ms", "inter_train_interval_s"):
            step = 0.1
        elif key == "ramp_fraction":
            step = 0.01
        elif key in ("ramp_steps", "pulses_per_train", "train_count", "burst_pulses_count"):
            step = 1
        else:
            step = 1

        # --- Freeze if next step would exceed limits ---
        if delta > 0 and cur_val + step > hi:
            # stepping upward would pass the max; freeze
            return
        if delta < 0 and cur_val - step < lo:
            # stepping downward would go below min; freeze
            return

        # normal increment
        new_val = cur_val + delta * step

        # rounding for nice display
        if key == "frequency_hz":
            if new_val < 1.0:
                new_val = round(new_val, 1)
            else:
                new_val = round(new_val)

        try:
            setattr(self.current_protocol, key, new_val)
        except Exception as e:
            print(f"Failed to set {key}: {e}")

        self._sync_ui_from_protocol()





    # ---------------------------------------------------------
    #   Theme Application
    # ---------------------------------------------------------
    def _apply_theme_to_app(self, theme_name: str):
        app = QApplication.instance()
        if app:
            ss = self.theme_manager.generate_stylesheet(theme_name)
            if ss:
                app.setStyleSheet(ss)

        pal = self.theme_manager.generate_palette(theme_name)
        self.pulse_widget.setPalette(pal)
        self.intensity_gauge.setPalette(pal)
        try:
            self.intensity_gauge.applyTheme(self.theme_manager, theme_name)
        except Exception as e:
            print("Couldn't apply theme to gauge:", e)

    def _toggle_theme(self):
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        self._apply_theme_to_app(self.current_theme)
        if self.current_protocol:
            self._sync_ui_from_protocol()


__all__ = ["ParamsPage"]
