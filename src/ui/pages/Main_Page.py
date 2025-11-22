from typing import Optional, Tuple, Any, Dict

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
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
    Main parameter/session page.

    - Edits parameters of the active TMSProtocol
    - Shows intensity gauge, timing bars, coil temp, session controls
    - Optionally uses GPIO_Backend (encoder + buttons) as hardware UI
    """

    request_protocol_list = Signal()

    # IPI value to enforce when burst_pulses_count == 1
    IPI_FOR_SINGLE_BURST_MS = 10.0

    def __init__(
        self,
        theme_manager: ThemeManager,
        gpio_backend: Optional[GPIO_Backend] = None,
        initial_theme: str = "dark",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        # --- Core references / state ---
        self.theme_manager = theme_manager
        self.current_theme = initial_theme

        self.current_protocol: Optional[TMSProtocol] = None
        self.backend: Optional[Uart_Backend] = None
        self.gpio_backend: Optional[GPIO_Backend] = gpio_backend

        # Explicit session state tracking
        self.session_active: bool = False   # True only when running
        self.session_paused: bool = False   # True only when paused

        # Global enable flag (front panel EN button)
        self.enabled: bool = False

        # Coil connection state (from uC_SW_state_Reading)
        # This affects ONLY start/stop interlock, not LEDs/panel visuals.
        self.coil_connected: bool = True

        # Param list definition: (label, proto_key, unit)
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

        # --- UI construction ---
        self._init_widgets()
        self._build_layout()
        self._populate_param_list()

        # --- Initial visual / logic state ---
        self._apply_enable_state()
        self._apply_theme_to_app(self.current_theme)
        self._connect_gpio_backend()

    # ------------------------------------------------------------------
    #   UI construction
    # ------------------------------------------------------------------
    def _init_widgets(self) -> None:
        """Create all main widgets (no layouts here)."""
        # Main widgets
        self.intensity_gauge = IntensityGauge(self)
        self.intensity_gauge.valueChanged.connect(self._on_intensity_changed)

        self.pulse_widget = PulseBarsWidget(self)
        self.list_widget = NavigationListWidget()
        self.list_widget.setCurrentRow(0)

        self.pulse_widget.sessionRemainingChanged.connect(
            self._update_remaining_gauge
        )

        # Top panel
        self.top_panel = QWidget()
        self.top_panel.setFixedHeight(80)
        self.top_panel.setStyleSheet("background-color: rgba(128,128,128,15%);")

        self.coil_temp_widget = CoilTemperatureWidget(
            warning_threshold=WARNING_TEMPERATURE_THRESHOLD,
            danger_threshold=DANGER_TEMPERATURE_THRESHOLD,
        )

        # Bottom panel
        self.bottom_panel = QWidget()
        self.bottom_panel.setObjectName("bottom_panel")
        self.bottom_panel.setFixedHeight(50)

        self.session_controls = SessionControlWidget(self)

    def _build_layout(self) -> None:
        """Wire widgets into layouts."""
        # --- Top layout ---
        top_layout = QHBoxLayout(self.top_panel)
        top_layout.setContentsMargins(5, 5, 5, 5)
        top_layout.setAlignment(Qt.AlignRight)

        # Keep temp widget roughly square-ish
        self.coil_temp_widget.setMaximumWidth(
            int(self.coil_temp_widget.height() * 1.4)
        )
        top_layout.addWidget(self.coil_temp_widget)

        # --- Bottom row: session controls ---
        bottom_layout = QHBoxLayout(self.bottom_panel)
        bottom_layout.setContentsMargins(10, 0, 10, 0)
        bottom_layout.addStretch(1)
        bottom_layout.addWidget(self.session_controls, alignment=Qt.AlignHCenter)
        bottom_layout.addStretch(1)

        # --- Main content: [Gauge] [PulseBars] [Param list] ---
        content_layout = QHBoxLayout()

        left_col = QVBoxLayout()
        left_col.addWidget(self.intensity_gauge)
        content_layout.addLayout(left_col, stretch=0)

        content_layout.addWidget(self.pulse_widget, stretch=1)

        right_col = QVBoxLayout()
        right_col.addWidget(self.list_widget, stretch=1)
        content_layout.addLayout(right_col, stretch=1)

        # --- Assemble page layout ---
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.top_panel)
        main_layout.addLayout(content_layout, stretch=1)
        main_layout.addWidget(self.bottom_panel)

    def _populate_param_list(self) -> None:
        """Fill the navigation list with parameter rows."""
        for label, key, unit in self.param_definitions:
            self.list_widget.add_item(
                title=label,
                value=0,
                bounds="",
                data={"key": key, "unit": unit},
            )

    # ------------------------------------------------------------------
    #   Backend binding
    # ------------------------------------------------------------------
    def bind_backend(self, backend: Uart_Backend) -> None:
        """Bind the UART backend and hook up all signals."""
        self.backend = backend

        # UC -> UI
        backend.intensityFromUc.connect(self._apply_intensity_from_uc)
        backend.coilTempFromUc.connect(self.set_coil_temperature)

        # Coil connection state (from uC)
        # True  = coil connected
        # False = coil not connected -> interlock start/stop, send error_state()
        if hasattr(backend, "uC_SW_state_Reading"):
            backend.uC_SW_state_Reading.connect(self._on_coil_sw_state)

        # UI -> backend (session control)
        self.session_controls.startRequested.connect(
            self._on_session_start_requested
        )
        self.session_controls.stopRequested.connect(
            self._on_session_stop_requested
        )
        self.session_controls.pauseRequested.connect(
            self._on_session_start_requested
        )

        # Extra session controls (Protocol / MT / Theme)
        if hasattr(self.session_controls, "protocolRequested"):
            self.session_controls.protocolRequested.connect(
                self._on_protocols_list_requested
            )
        if hasattr(self.session_controls, "themeToggleRequested"):
            self.session_controls.themeToggleRequested.connect(self._toggle_theme)
        if hasattr(self.session_controls, "mtRequested"):
            self.session_controls.mtRequested.connect(self._on_mt_requested)

        # After bind, enforce proper start/stop enabled state
        self._apply_enable_state()

    # ------------------------------------------------------------------
    #   Protocol binding / syncing
    # ------------------------------------------------------------------
    def set_protocol(self, proto: TMSProtocol) -> None:
        """Attach a TMSProtocol instance and sync UI from it."""
        self.current_protocol = proto

        # Gauge + pulse widget
        self.intensity_gauge.setMode(GaugeMode.INTENSITY)
        self.intensity_gauge.setFromProtocol(proto)
        self.pulse_widget.set_protocol(proto)

        # Palette / theme
        pal = self.theme_manager.generate_palette(self.current_theme)
        self.pulse_widget.setPalette(pal)
        self.intensity_gauge.setPalette(pal)
        try:
            self.intensity_gauge.applyTheme(self.theme_manager, self.current_theme)
        except Exception:
            pass

        # Initial param sync
        self._sync_ui_from_protocol()

        # Notify backend
        if self.backend is not None:
            self.backend.request_param_update(proto)

    # ---- Remaining gauge mode helpers --------------------------------
    def _enter_remaining_mode(self) -> None:
        """
        Force gauge into REMAINING mode only when session is
        running or paused (not while in pure settings mode).
        """
        if self.session_active or self.session_paused:
            try:
                self.intensity_gauge.setMode(GaugeMode.REMAINING)
            except Exception:
                pass

    def _exit_remaining_mode(self) -> None:
        """
        Back to INTENSITY mode only when we are not in a running/paused
        session anymore (i.e., settings / idle).
        """
        if self.session_active or self.session_paused:
            return

        try:
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
    ) -> None:
        """
        Called from PulseBarsWidget each tick while session is running.
        Only allowed to affect gauge when session is actually running/paused.
        """
        if not (self.session_active or self.session_paused):
            # Pure settings mode: ignore remaining updates
            return

        try:
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

    # ---- Param ranges / sync -----------------------------------------
    def _get_param_range_for_key(
        self, proto: TMSProtocol, key: str
    ) -> Tuple[float, float]:
        """Return allowed min/max for a given protocol attribute key."""
        if key == "frequency_hz":
            return proto.FREQ_MIN, proto._calculate_max_frequency_hz()
        if key == "inter_pulse_interval_ms":
            return proto.IPI_MIN_HARD, proto.IPI_MAX_HARD
        if key == "pulses_per_train":
            return 1, 10000
        if key == "train_count":
            return 1, 10000
        if key == "inter_train_interval_s":
            return 0.01, 10000.0
        if key == "burst_pulses_count":
            return min(proto.BURST_PULSES_ALLOWED), max(proto.BURST_PULSES_ALLOWED)
        if key == "ramp_fraction":
            return 0.7, 1.0
        if key == "ramp_steps":
            return 1, 10
        return 0, 1

    def _get_current_param_meta(self) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        Return (key, meta) for the currently selected param row.
        key may be None if invalid row.
        """
        item = self.list_widget.currentItem()
        if not item:
            return None, {}
        meta = item.data(Qt.UserRole) or {}
        key = meta.get("key")
        return key, meta

    def _sync_ui_from_protocol(self) -> None:
        """Update param list + gauge from current_protocol."""
        if not self.current_protocol:
            return

        proto = self.current_protocol
        self.pulse_widget.set_protocol(proto)

        # Enforce single-burst rule
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

            if isinstance(val, (int, float)):
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

    def _modify_value(self, delta: float) -> None:
        """
        Modify the currently selected parameter by 'delta' encoder steps.
        """
        if not self.current_protocol:
            return

        key, meta = self._get_current_param_meta()
        if not key:
            return

        proto = self.current_protocol

        # Lock IPI if single burst
        if key == "inter_pulse_interval_ms" and int(
            getattr(proto, "burst_pulses_count", 0)
        ) == 1:
            proto.inter_pulse_interval_ms = self.IPI_FOR_SINGLE_BURST_MS
            self._sync_ui_from_protocol()
            return

        lo, hi = self._get_param_range_for_key(proto, key)
        item = self.list_widget.currentItem()
        row_widget = self.list_widget.itemWidget(item) if item else None
        if row_widget is None:
            return

        try:
            cur_val = float(row_widget.get_value())
        except (ValueError, TypeError):
            cur_val = getattr(proto, key, 0.0)

        # Step size per parameter
        if key == "frequency_hz":
            step = 0.1 if cur_val < 1.0 else 1.0
        elif key in ("inter_pulse_interval_ms", "inter_train_interval_s"):
            step = 1
        elif key == "ramp_fraction":
            step = 0.1
        elif key in (
            "ramp_steps",
            "pulses_per_train",
            "train_count",
            "burst_pulses_count",
        ):
            step = 1
        else:
            step = 1

        # Range checks
        if delta > 0 and cur_val + step > hi:
            return
        if delta < 0 and cur_val - step < lo:
            return

        new_val = cur_val + delta * step

        if key == "frequency_hz":
            new_val = round(new_val, 1) if new_val < 1.0 else round(new_val)

        new_val = max(lo, min(hi, new_val))

        setattr(proto, key, new_val)

        # Re-enforce single-burst IPI if needed
        if key == "burst_pulses_count" and int(proto.burst_pulses_count) == 1:
            proto.inter_pulse_interval_ms = self.IPI_FOR_SINGLE_BURST_MS

        self._sync_ui_from_protocol()

        if self.backend is not None and self.current_protocol is not None:
            self.backend.request_param_update(self.current_protocol)

    # ------------------------------------------------------------------
    #   GPIO backend integration
    # ------------------------------------------------------------------
    def _connect_gpio_backend(self) -> None:
        """Wire hardware controls (if any)."""
        if not self.gpio_backend:
            return

        gb = self.gpio_backend

        gb.encoderStep.connect(self._on_encoder_step_hw)
        gb.arrowUpPressed.connect(self._on_nav_up)
        gb.arrowDownPressed.connect(self._on_nav_down)
        gb.startPausePressed.connect(self._on_session_start_requested)
        gb.stopPressed.connect(self._on_session_stop_requested)
        gb.protocolPressed.connect(self._on_protocols_list_requested)
        gb.reservedPressed.connect(self._toggle_theme)
        if hasattr(gb, "mtPressed"):
            gb.mtPressed.connect(self._on_mt_requested)

        # EN button toggles global enable/disable
        gb.enPressed.connect(self._on_en_pressed)

    def _on_encoder_step_hw(self, step: int) -> None:
        self._modify_value(float(step))

    def _on_nav_up(self) -> None:
        self.list_widget.select_previous()

    def _on_nav_down(self) -> None:
        self.list_widget.select_next()

    # ------------------------------------------------------------------
    #   Session control handlers
    # ------------------------------------------------------------------
    def _on_session_start_requested(self) -> None:
        """
        Handle Start/Pause button (UI + GPIO share this).

        Logic is driven by SessionControlWidget.get_state():
        - "Start" -> start session
        - "Pause" -> pause session

        Interlocks:
        - EN must be armed (self.enabled)
        - Coil must be connected (self.coil_connected)
        """
        # Ignore any start/pause request if interlocks not satisfied
        if not self.enabled or not self.coil_connected:
            return

        state = self.session_controls.get_state()

        if state == "Start":
            self.session_active = True
            self.session_paused = False

            if hasattr(self.pulse_widget, "start"):
                self.pulse_widget.start()
            self.session_controls.set_state(running=True, paused=False)
            self._enter_remaining_mode()
            if self.backend:
                self.backend.start_session()

        elif state == "Pause":
            self.session_active = False
            self.session_paused = True

            if hasattr(self.pulse_widget, "pause"):
                self.pulse_widget.pause()
            self.session_controls.set_state(running=False, paused=True)
            self._enter_remaining_mode()
            if self.backend:
                self.backend.pause_session()

    def _on_session_stop_requested(self) -> None:
        """
        Handle Stop button.

        Stop is allowed regardless of coil connection, and even if EN
        is not armed, to make sure we can always kill a session.
        """
        self.session_active = False
        self.session_paused = False

        if hasattr(self.pulse_widget, "stop"):
            self.pulse_widget.stop()

        self.session_controls.set_state(running=False, paused=False)
        self._exit_remaining_mode()

        if self.backend:
            self.backend.stop_session()

    def _on_protocols_list_requested(self) -> None:
        self.request_protocol_list.emit()

    def _on_mt_requested(self) -> None:
        """
        Handler for MT button (both UI and GPIO).
        Implement MT logic here when you know what you want it to do.
        """
        print("MT requested (not implemented yet)")

    # ------------------------------------------------------------------
    #   Coil connection state (from uC)
    # ------------------------------------------------------------------
    def _on_coil_sw_state(self, connected: bool) -> None:
        """
        Called when uC reports coil switch state.

        - Update coil temp widget mode
        - If disconnected:
            * send error_state() to uC
            * disable Start/Stop (via _apply_enable_state)
            * stop running session
        """
        self.coil_connected = bool(connected)

        # Update the temp widget visual mode (DISCONNECTED / normal)
        if hasattr(self, "coil_temp_widget"):
            try:
                self.coil_temp_widget.setCoilConnected(self.coil_connected)
            except Exception:
                pass

        # Notify uC if disconnected
        if not self.coil_connected and self.backend:
            try:
                self.backend.error_state()
            except Exception:
                pass

        # Update Start/Stop enabled state (only, not LEDs/panel)
        self._apply_enable_state()

        # If we just lost the coil while running/paused -> stop session
        if (not self.coil_connected) and (self.session_active or self.session_paused):
            self._on_session_stop_requested()

    # ------------------------------------------------------------------
    #   Enable state + gradient + LEDs
    # ------------------------------------------------------------------
    def _get_theme_color(self, attr_name: str, fallback: str) -> QColor:
        """
        Safely get a QColor from ThemeManager or fallback hex string.
        """
        try:
            raw = getattr(self.theme_manager, attr_name, fallback)
        except Exception:
            raw = fallback
        if isinstance(raw, QColor):
            return raw
        return QColor(str(raw))

    def _update_bottom_panel_style(self) -> None:
        """
        Set bottom_panel gradient depending on EN (self.enabled),
        using ThemeManager.NORMAL_COLOR / DANGER_COLOR.
        Coil connection does NOT affect this.
        """
        normal_color = self._get_theme_color("NORMAL_COLOR", "#00B75A")
        danger_color = self._get_theme_color("DANGER_COLOR", "#CC4444")

        base = normal_color if self.enabled else danger_color
        r, g, b, _ = base.red(), base.green(), base.blue(), base.alpha()

        css = f"""
        QWidget#bottom_panel {{
            background: qlineargradient(
                x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba({r}, {g}, {b}, 0),
                stop:1 rgba({r}, {g}, {b}, 120)
            );
        }}
        """
        self.bottom_panel.setStyleSheet(css)

    def _set_start_stop_enabled(self, enabled: bool) -> None:
        """
        Enable/disable ONLY Start/Stop inside SessionControlWidget.
        Protocol / MT / Theme stay enabled.
        """
        sc = getattr(self, "session_controls", None)
        if sc is None:
            return

        if hasattr(sc, "setStartStopEnabled"):
            try:
                sc.setStartStopEnabled(enabled)
                return
            except Exception:
                pass

        # Fallback if SessionControlWidget API changes
        for attr in ("start_pause_frame", "start_button", "btn_start", "button_start"):
            if hasattr(sc, attr):
                try:
                    getattr(sc, attr).setEnabled(enabled)
                except Exception:
                    pass
        for attr in ("stop_frame", "stop_button", "btn_stop", "button_stop"):
            if hasattr(sc, attr):
                try:
                    getattr(sc, attr).setEnabled(enabled)
                except Exception:
                    pass

    def _update_intensity_for_enable(self, enabled: bool) -> None:
        """
        When EN is disabled:
          - force intensity to 0 in both UI and model
          - lock the gauge so user can't change it
          - notify uC about error_state()

        When EN is enabled:
          - unlock the gauge
          - notify uC about idle_state()

        NOTE: coil connection does NOT affect intensity directly.
        """
        if enabled:
            if self.backend:
                try:
                    self.backend.idle_state()
                except Exception:
                    pass

            self.intensity_gauge.setDisabled(False)
            return

        # Disabled path (EN off)
        if self.backend:
            try:
                self.backend.error_state()
            except Exception:
                pass

        # Model side
        if self.current_protocol:
            self.current_protocol.intensity_percent_of_mt_init = 0

        # UI side
        try:
            self.intensity_gauge.setValue(0)
        except Exception:
            pass

        self.intensity_gauge.setDisabled(True)

    def _update_leds_for_enable(self, enabled: bool) -> None:
        """
        Green LED when EN enabled, red when EN disabled.
        Coil connection does NOT affect LEDs.
        """
        if not self.gpio_backend:
            return

        try:
            self.gpio_backend.set_green_led(enabled)
            self.gpio_backend.set_red_led(not enabled)
        except Exception:
            # Never crash UI because of LED I/O
            pass

    def _apply_enable_state(self) -> None:
        """
        Apply current EN + coil state to:
        - bottom gradient (red/green): only EN
        - Start/Stop controls: EN AND coil_connected
        - intensity gauge (0 + locked when EN disabled)
        - GPIO LEDs (EN only)
        """
        en_enabled = self.enabled
        start_stop_enabled = self.enabled and self.coil_connected

        # 1) Background gradient (EN only)
        self._update_bottom_panel_style()

        # 2) Start/Stop UI state (EN + coil)
        self._set_start_stop_enabled(start_stop_enabled)

        # 3) Intensity behavior (EN only)
        self._update_intensity_for_enable(en_enabled)

        # 4) LEDs reflect EN only
        self._update_leds_for_enable(en_enabled)

    def _on_en_pressed(self) -> None:
        """Toggle enable state when EN button is pressed."""
        self.enabled = not self.enabled
        self._apply_enable_state()

        # If we just disabled while running, force stop
        if not self.enabled and (self.session_active or self.session_paused):
            self._on_session_stop_requested()

    # ------------------------------------------------------------------
    #   Theme support
    # ------------------------------------------------------------------
    def _apply_theme_to_app(self, theme_name: str) -> None:
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
            print("Couldn't apply theme to gauge/coil widget:", e)

        # Gradient should respect theme colors
        self._update_bottom_panel_style()

    def _toggle_theme(self) -> None:
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        self._apply_theme_to_app(self.current_theme)
        if self.current_protocol:
            self._sync_ui_from_protocol()

    # ------------------------------------------------------------------
    #   Temperature + intensity from uC
    # ------------------------------------------------------------------
    def set_coil_temperature(self, temperature: float) -> None:
        # Optional: ignore temperature when coil not connected,
        # but currently we still pass it to the widget; the widget
        # decides how to display (DISCONNECTED vs °C).
        if hasattr(self, "coil_temp_widget"):
            self.coil_temp_widget.setTemperature(temperature)

    def _on_intensity_changed(self, v: int) -> None:
        """
        Intensity changed from UI.

        - Ignored in REMAINING mode.
        - Ignored (and reset to 0) when EN is disabled.
        Coil connection does NOT affect manual intensity changes.
        """
        # Ignore changes that come from REMAINING mode animation
        if self.intensity_gauge.mode() != GaugeMode.INTENSITY:
            return

        # If EN is not armed, keep intensity at 0 and ignore user changes
        if not self.enabled:
            try:
                self.intensity_gauge.setValue(0)
            except Exception:
                pass
            return

        if self.current_protocol:
            self.current_protocol.intensity_percent_of_mt_init = int(v)
            self._sync_ui_from_protocol()

            if self.backend is not None:
                self.backend.request_param_update(self.current_protocol)

    def _apply_intensity_from_uc(self, val: int) -> None:
        """
        Intensity update coming from the microcontroller.

        - When EN enabled: track the value normally.
        - When EN disabled: force model and UI to 0 and ignore 'val'.
        Coil connection does NOT affect this; it's purely EN.
        """
        # Model side
        if self.current_protocol:
            if self.enabled:
                self.current_protocol.intensity_percent_of_mt_init = int(val)
            else:
                self.current_protocol.intensity_percent_of_mt_init = 0

        # Only visually update gauge + list when in INTENSITY mode
        if self.intensity_gauge.mode() != GaugeMode.INTENSITY:
            return

        # When EN disabled, keep UI at 0
        if not self.enabled:
            try:
                self.intensity_gauge.setValue(0)
            except Exception:
                pass
            return

        # Normal path when EN enabled
        try:
            self.intensity_gauge.setValue(val)
        except Exception:
            pass

        if self.current_protocol:
            self._sync_ui_from_protocol()
