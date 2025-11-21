from typing import Optional

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton
)

from app.theme_manager import ThemeManager
from core.protocol_manager_revised import TMSProtocol
from ui.widgets.navigation_list_widget import NavigationListWidget
from ui.widgets.pulse_bars_widget import PulseBarsWidget
from ui.widgets.intensity_gauge import IntensityGauge, GaugeMode
from ui.widgets.temperature_widget import CoilTemperatureWidget
from ui.widgets.session_control_widget import SessionControlWidget
from services.uart_backend import Uart_Backend
from services.gpio_backend import GPIO_Backend

from config.settings import WARNING_TEMPERATURE_THRESHOLD, DANGER_TEMPERATURE_THRESHOLD


class ParamsPage(QWidget):
    """
    Parameter editor for an active TMSProtocol.
    Uses GPIO_Backend (hardware buttons + encoder) for input.
    """

    request_protocol_list = Signal()

    # IPI value to enforce when burst_pulses_count == 1
    IPI_FOR_SINGLE_BURST_MS = 10.0

    def __init__(
        self,
        theme_manager: ThemeManager,
        gpio_backend: Optional[GPIO_Backend] = None,
        initial_theme: str = "dark",
        parent=None,
    ):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.current_theme = initial_theme
        self.current_protocol: Optional[TMSProtocol] = None
        self.backend: Optional[Uart_Backend] = None
        self.gpio_backend: Optional[GPIO_Backend] = gpio_backend

        # NEW: explicit session state tracking
        self.session_active: bool = False      # True only when running
        self.session_paused: bool = False      # True only when paused

        # --- Primary widgets ---
        self.intensity_gauge = IntensityGauge(self)
        self.intensity_gauge.valueChanged.connect(self._on_intensity_changed)

        self.pulse_widget = PulseBarsWidget(self)
        self.list_widget = NavigationListWidget()

        # when pulses/time change, update remaining gauge
        self.pulse_widget.sessionRemainingChanged.connect(
            self._update_remaining_gauge
        )

        # --- Parameter list setup ---
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
                title=label, value=0, bounds="", data={"key": key, "unit": unit}
            )
        self.list_widget.setCurrentRow(0)

        # ---------------------------------------------------------
        #   LAYOUT SETUP
        # ---------------------------------------------------------
        self.top_panel = QWidget()
        self.top_panel.setFixedHeight(80)
        self.top_panel.setStyleSheet("background-color: rgba(128,128,128,15%);")

        self.bottom_panel = QWidget()
        self.bottom_panel.setFixedHeight(50)
        self.bottom_panel.setStyleSheet("background-color: rgba(128,128,128,15%);")

        # bottom row controls
        hbox_bottom = QHBoxLayout(self.bottom_panel)
        hbox_bottom.setContentsMargins(10, 0, 10, 0)

        self.btn_select_protocol = QPushButton("Select Protocol")
        self.btn_select_protocol.clicked.connect(self._on_protocols_list_requested)

        self.btn_toggle_theme = QPushButton("Toggle Theme")
        self.btn_toggle_theme.clicked.connect(self._toggle_theme)

        # Session control widget (Pause, Start/Stop as frames)
        self.session_controls = SessionControlWidget(self)

        # LEFT: Select Protocol
        hbox_bottom.addWidget(self.btn_select_protocol, alignment=Qt.AlignLeft)

        # CENTER: Toggle theme (centered horizontally)
        hbox_bottom.addStretch(1)
        hbox_bottom.addWidget(self.btn_toggle_theme, alignment=Qt.AlignHCenter)
        hbox_bottom.addStretch(1)

        # RIGHT: Session controls
        hbox_bottom.addWidget(self.session_controls, alignment=Qt.AlignRight)

        # main content layout
        content = QHBoxLayout()
        left_col = QVBoxLayout()
        left_col.addWidget(self.intensity_gauge)
        content.addLayout(left_col, stretch=0)
        content.addWidget(self.pulse_widget, stretch=1)
        right_col = QVBoxLayout()
        right_col.addWidget(self.list_widget, stretch=1)
        content.addLayout(right_col, stretch=1)

        # top layout
        top_layout = QHBoxLayout(self.top_panel)
        top_layout.setContentsMargins(5, 5, 5, 5)
        top_layout.setAlignment(Qt.AlignRight)

        self.coil_temp_widget = CoilTemperatureWidget(
            warning_threshold=WARNING_TEMPERATURE_THRESHOLD,
            danger_threshold=DANGER_TEMPERATURE_THRESHOLD,
        )
        self.coil_temp_widget.setMaximumWidth(int(self.coil_temp_widget.height() * 1.4))
        top_layout.addWidget(self.coil_temp_widget)

        # assemble main layout
        lay = QVBoxLayout(self)
        lay.addWidget(self.top_panel)
        lay.addLayout(content, stretch=1)
        lay.addWidget(self.bottom_panel)

        # apply theme + connect GPIO
        self._apply_theme_to_app(self.current_theme)
        self._connect_gpio_backend()

    # ---------------------------------------------------------
    #   Bind UART backend
    # ---------------------------------------------------------
    def bind_backend(self, backend: Uart_Backend):
        self.backend = backend

        # UC -> UI
        backend.intensityFromUc.connect(self._apply_intensity_from_uc)
        backend.coilTempFromUc.connect(self.set_coil_temperature)

        # UI -> backend
        self.session_controls.startRequested.connect(self._on_session_start_requested)
        self.session_controls.stopRequested.connect(self._on_session_stop_requested)
        self.session_controls.pauseRequested.connect(self._on_session_start_requested)

    # ---------------------------------------------------------
    #   Protocol binding
    # ---------------------------------------------------------
    def set_protocol(self, proto: TMSProtocol):
        self.current_protocol = proto

        self.intensity_gauge.setMode(GaugeMode.INTENSITY)
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

        if self.backend is not None:
            self.backend.request_param_update(proto)

    # ---------------------------------------------------------
    #   Gauge mode helpers
    # ---------------------------------------------------------
    def _enter_remaining_mode(self):
        """
        Force gauge into REMAINING mode only if session is
        running or paused (not while in pure settings mode).
        """
        try:
            if self.session_active or self.session_paused:  # NEW
                self.intensity_gauge.setMode(GaugeMode.REMAINING)
        except Exception:
            pass

    def _exit_remaining_mode(self):
        """
        Back to INTENSITY only if we are not in a running/paused
        session anymore (i.e., in settings / idle).
        """
        try:
            if not (self.session_active or self.session_paused):  # NEW
                self.intensity_gauge.setMode(GaugeMode.INTENSITY)
                if self.current_protocol:
                    self.intensity_gauge.setFromProtocol(self.current_protocol)
        except Exception:
            pass

    def _update_remaining_gauge(
        self,
        remaining_pulses: int,
        total_pulses: int,
        remaining_seconds: float,
        total_seconds: float,
    ):
        """
        Called from PulseBarsWidget each tick while session is running.
        Only allowed to affect gauge mode when session is actually
        running or paused.
        """
        try:
            if not (self.session_active or self.session_paused):
                # In pure settings mode: ignore remaining updates
                return  # NEW

            if self.intensity_gauge.mode() != GaugeMode.REMAINING:
                self.intensity_gauge.setMode(GaugeMode.REMAINING)

            self.intensity_gauge.setRemainingState(
                remaining_pulses=remaining_pulses,
                total_pulses=total_pulses,
                remaining_seconds=remaining_seconds,
                total_seconds=total_seconds,
            )
        except Exception:
            pass

    # ---------------------------------------------------------
    #   UI Sync / ranges / modifiers
    # ---------------------------------------------------------
    def _get_param_range_for_key(self, proto: TMSProtocol, key: str):
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
            return min(proto.BURST_PULSES_ALLOWED), max(proto.BURST_PULSES_ALLOWED)
        elif key == "ramp_fraction":
            return 0.7, 1.0
        elif key == "ramp_steps":
            return 1, 10
        else:
            return 0, 1

    def _get_param_range(self, proto: TMSProtocol):
        item = self.list_widget.currentItem()
        if not item:
            return 0, 1
        meta = item.data(Qt.UserRole) or {}
        key = meta.get("key")
        if not key:
            return 0, 1
        return self._get_param_range_for_key(proto, key)

    def _sync_ui_from_protocol(self):
        if not self.current_protocol:
            return

        proto = self.current_protocol
        self.pulse_widget.set_protocol(proto)

        # enforce single-burst rule
        try:
            if int(getattr(proto, "burst_pulses_count", 0)) == 1:
                proto.inter_pulse_interval_ms = self.IPI_FOR_SINGLE_BURST_MS
        except Exception:
            pass

        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            row_widget = self.list_widget.itemWidget(item)
            meta = item.data(Qt.UserRole) or {}
            key = meta.get("key")
            unit = meta.get("unit", "")
            if not key or not row_widget:
                continue

            try:
                val = getattr(proto, key)
            except AttributeError:
                continue

            lo, hi = self._get_param_range_for_key(proto, key)

            if isinstance(val, (int, float)) and isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                clamped = max(lo, min(hi, float(val)))
                if isinstance(val, int):
                    clamped = int(round(clamped))
                if clamped != val:
                    setattr(proto, key, clamped)
                    val = clamped

                row_widget.set_value(val)
                row_widget.set_suffix(f"{unit}   ({lo:.2f}–{hi:.2f})")
            else:
                row_widget.set_value(val)
                row_widget.set_suffix(unit)

    def _modify_value(self, delta: float):
        """
        Modify the currently selected parameter by 'delta' encoder steps.
        """
        if not self.current_protocol:
            return

        item = self.list_widget.currentItem()
        if not item:
            return

        meta = item.data(Qt.UserRole) or {}
        key = meta.get("key")
        if not key:
            return

        proto = self.current_protocol

        # lock IPI if single burst
        if key == "inter_pulse_interval_ms" and int(getattr(proto, "burst_pulses_count", 0)) == 1:
            proto.inter_pulse_interval_ms = self.IPI_FOR_SINGLE_BURST_MS
            self._sync_ui_from_protocol()
            return

        lo, hi = self._get_param_range_for_key(proto, key)
        row_widget = self.list_widget.itemWidget(item)
        if row_widget is None:
            return

        try:
            cur_val = float(row_widget.get_value())
        except (ValueError, TypeError):
            cur_val = getattr(proto, key, 0.0)

        # Step size per parameter type
        if key == "frequency_hz":
            step = 0.1 if cur_val < 1.0 else 1.0
        elif key in ("inter_pulse_interval_ms", "inter_train_interval_s"):
            step = 1
        elif key == "ramp_fraction":
            step = 0.1
        elif key in ("ramp_steps", "pulses_per_train", "train_count", "burst_pulses_count"):
            step = 1
        else:
            step = 1

        if delta > 0 and cur_val + step > hi:
            return
        if delta < 0 and cur_val - step < lo:
            return

        new_val = cur_val + delta * step

        if key == "frequency_hz":
            new_val = round(new_val, 1) if new_val < 1.0 else round(new_val)

        if isinstance(new_val, (float, int)):
            new_val = max(lo, min(hi, new_val))

        setattr(proto, key, new_val)

        if key == "burst_pulses_count" and int(proto.burst_pulses_count) == 1:
            proto.inter_pulse_interval_ms = self.IPI_FOR_SINGLE_BURST_MS

        self._sync_ui_from_protocol()

        if self.backend is not None and self.current_protocol is not None:
            self.backend.request_param_update(self.current_protocol)

    # ---------------------------------------------------------
    #   GPIO backend integration
    # ---------------------------------------------------------
    def _connect_gpio_backend(self):
        if not self.gpio_backend:
            return

        self.gpio_backend.encoderStep.connect(self._on_encoder_step_hw)
        self.gpio_backend.arrowUpPressed.connect(self._on_nav_up)
        self.gpio_backend.arrowDownPressed.connect(self._on_nav_down)
        self.gpio_backend.startPausePressed.connect(self._on_session_start_requested)
        self.gpio_backend.stopPressed.connect(self._on_session_stop_requested)
        self.gpio_backend.protocolPressed.connect(self._on_protocols_list_requested)
        self.gpio_backend.reservedPressed.connect(self._toggle_theme)

    def _on_encoder_step_hw(self, step: int):
        self._modify_value(float(step))

    def _on_nav_up(self):
        self.list_widget.select_previous()

    def _on_nav_down(self):
        self.list_widget.select_next()

    # ---------------------------------------------------------
    #   Session control handlers
    # ---------------------------------------------------------
    def _on_session_start_requested(self):
        state = self.session_controls.get_state()

        if state == "Start":
            # NEW: update session state
            self.session_active = True
            self.session_paused = False

            if hasattr(self.pulse_widget, "start"):
                self.pulse_widget.start()
            self.session_controls.set_state(running=True, paused=False)
            self._enter_remaining_mode()
            if self.backend:
                self.backend.start_session()

        elif state == "Pause":
            # NEW: update session state
            self.session_active = False
            self.session_paused = True

            if hasattr(self.pulse_widget, "pause"):
                self.pulse_widget.pause()
            self.session_controls.set_state(running=False, paused=True)
            self._enter_remaining_mode()
            if self.backend:
                self.backend.pause_session()

    def _on_session_stop_requested(self):
        # NEW: clear session state
        self.session_active = False
        self.session_paused = False

        if hasattr(self.pulse_widget, "stop"):
            self.pulse_widget.stop()
        self.session_controls.set_state(running=False, paused=False)
        self._exit_remaining_mode()
        if self.backend:
            self.backend.stop_session()

    def _on_session_pause_requested(self):
        if hasattr(self.pulse_widget, "pause"):
            self.pulse_widget.pause()
        self.session_controls.set_state(running=False, paused=True)

        # NEW: keep behavior consistent
        self.session_active = False
        self.session_paused = True
        self._enter_remaining_mode()

    def _on_protocols_list_requested(self):
        self.request_protocol_list.emit()

    # ---------------------------------------------------------
    #   Theme support
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
            self.coil_temp_widget.applyTheme(self.theme_manager, theme_name)
        except Exception as e:
            print("Couldn't apply theme to gauge:", e)

    def _on_intensity_changed(self, v: int):
        # Ignore changes that come from REMAINING mode animation
        if self.intensity_gauge.mode() != GaugeMode.INTENSITY:
            return

        if self.current_protocol:
            self.current_protocol.intensity_percent_of_mt_init = int(v)
            self._sync_ui_from_protocol()

            if self.backend is not None:
                self.backend.request_param_update(self.current_protocol)

    def _toggle_theme(self):
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        self._apply_theme_to_app(self.current_theme)
        if self.current_protocol:
            self._sync_ui_from_protocol()

    # ---------------------------------------------------------
    #   Temperature + intensity from uC
    # ---------------------------------------------------------
    def set_coil_temperature(self, temperature: float):
        if hasattr(self, "coil_temp_widget"):
            self.coil_temp_widget.setTemperature(temperature)

    def _apply_intensity_from_uc(self, val: int):
        v = max(0, min(65535, int(val)))
        v = (v * 100) / 65535

        # Always keep protocol's model in sync
        if self.current_protocol:
            self.current_protocol.intensity_percent_of_mt_init = float(v)

        # NEW: Only visually update gauge + list when in INTENSITY mode
        if self.intensity_gauge.mode() != GaugeMode.INTENSITY:
            return

        try:
            self.intensity_gauge.setValue(v)
        except Exception:
            pass

        if self.current_protocol:
            self._sync_ui_from_protocol()
