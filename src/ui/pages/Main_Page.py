from typing import Optional, Tuple, Any, Dict

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QStackedLayout,
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
from ui.widgets.session_info_widget import SessionInfoWidget

from config.settings import WARNING_TEMPERATURE_THRESHOLD, DANGER_TEMPERATURE_THRESHOLD


class ParamsPage(QWidget):
    """
    Main parameter/session page.

    Normal mode:
      - Left: INTENSITY gauge
      - Center: PulseBarsWidget
      - Right: parameter list
      - Bottom: SessionControlWidget (Protocol, MT, Theme, Stop, Start/Pause)

    MT mode:
      - Center stack switched to MT page:
          [ MT gauge | image placeholder | text ]
      - Bottom SessionControlWidget visually becomes:
          [Cancel ................. Apply]
        using FrameButtons (no QPushButtons).
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

        # Coil connection state (from sw_state_from_uC)
        self.coil_connected: bool = True

        # Track last backend "global" state to avoid spamming uC
        # possible values: None, "idle", "error"
        self._backend_state: Optional[str] = None

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

        # --- MT mode state ---
        self.mt_mode: bool = False
        self._session_btn_labels_backup: Dict[str, str] = {}
        self._mt_signals_hooked: bool = False

        # Backup for intensity percentage when entering MT
        self._prev_intensity_percent: Optional[float] = None

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
        # Main widgets for NORMAL page
        self.intensity_gauge = IntensityGauge(self)
        self.intensity_gauge.valueChanged.connect(self._on_intensity_changed)
        # Temporary default, will be updated based on MT
        try:
            self.intensity_gauge.setRange(0, 100)
        except Exception:
            pass

        self.pulse_widget = PulseBarsWidget(self)
        self.list_widget = NavigationListWidget()
        self.list_widget.setCurrentRow(0)

        self.pulse_widget.sessionRemainingChanged.connect(
            self._update_remaining_gauge
        )

        # Gauge for MT page
        self.mt_gauge = IntensityGauge(self)
        self.mt_gauge.setMode(GaugeMode.MT_PERCENT)
        self.mt_gauge.setTitles("MT", "PERCENT")
        self.mt_gauge.setRange(0, 100)  # MT always absolute 0–100%

        # Top-left session info widget
        self.session_info = SessionInfoWidget(self)

        # Top panel
        self.top_panel = QWidget()
        self.top_panel.setFixedHeight(80)
        self.top_panel.setStyleSheet("background-color: rgba(128,128,128,15%);")

        self.coil_temp_widget = CoilTemperatureWidget(
            warning_threshold=WARNING_TEMPERATURE_THRESHOLD,
            danger_threshold=DANGER_TEMPERATURE_THRESHOLD,
        )
        self.coil_temp_widget.setCoilConnected(False)

        # Bottom panel + session controls
        self.bottom_panel = QWidget()
        self.bottom_panel.setObjectName("bottom_panel")
        self.bottom_panel.setFixedHeight(50)

        self.session_controls = SessionControlWidget(self)

    def _build_layout(self) -> None:
        """Wire widgets into layouts."""
        # --- Top layout ---
        top_layout = QHBoxLayout(self.top_panel)
        top_layout.setContentsMargins(8, 5, 8, 5)
        top_layout.setSpacing(8)

        # Left: new session info
        top_layout.addWidget(self.session_info, alignment=Qt.AlignLeft | Qt.AlignVCenter)

        # Middle: stretch
        top_layout.addStretch(1)

        # Right: coil temperature widget
        self.coil_temp_widget.setMaximumWidth(
            int(self.coil_temp_widget.height() * 1.4)
        )
        top_layout.addWidget(self.coil_temp_widget, alignment=Qt.AlignRight | Qt.AlignVCenter)

        # --- Bottom row: session controls ---
        bottom_layout = QHBoxLayout(self.bottom_panel)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addStretch(1)
        bottom_layout.addWidget(self.session_controls, alignment=Qt.AlignHCenter)
        bottom_layout.addStretch(1)

        # --- NORMAL PAGE content: [Gauge] [PulseBars] [Param list] ---
        normal_page = QWidget()
        normal_content_layout = QHBoxLayout(normal_page)
        normal_content_layout.setContentsMargins(0, 0, 0, 0)

        left_col = QVBoxLayout()
        left_col.addWidget(self.intensity_gauge)
        normal_content_layout.addLayout(left_col, stretch=0)

        normal_content_layout.addWidget(self.pulse_widget, stretch=1)

        right_col = QVBoxLayout()
        right_col.addWidget(self.list_widget, stretch=1)
        normal_content_layout.addLayout(right_col, stretch=1)

        # --- MT PAGE content: (gauge(MT), Picture, Text) ---
        mt_page = self._create_mt_page()

        # --- Central stack: NORMAL (0) / MT (1) ---
        self.main_stack = QStackedLayout()
        self.main_stack.addWidget(normal_page)   # index 0
        self.main_stack.addWidget(mt_page)       # index 1

        # --- Assemble page layout ---
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.top_panel)
        main_layout.addLayout(self.main_stack, stretch=1)
        main_layout.addWidget(self.bottom_panel)

    def _create_mt_page(self) -> QWidget:
        """
        MT page content:

            [ mt_gauge | (spacer) | (image + text) ]
        """
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)

        # Left: MT gauge
        left_col = QVBoxLayout()
        left_col.addWidget(self.mt_gauge)
        left_col.addStretch(1)
        layout.addLayout(left_col, stretch=0)

        # Middle: stretch (empty)
        layout.addStretch(1)

        # Right: picture + text
        right_col = QVBoxLayout()

        picture = QLabel("Image placeholder", page)
        picture.setAlignment(Qt.AlignCenter)
        picture.setFixedSize(220, 220)
        picture.setStyleSheet(
            "border: 1px dashed rgba(255, 255, 255, 80); "
            "color: rgba(255, 255, 255, 160);"
        )

        text = QLabel(
            "MT instructions / description\n"
            "You can replace this with real content later.",
            page,
        )
        text.setWordWrap(True)

        right_col.addWidget(picture)
        right_col.addSpacing(8)
        right_col.addWidget(text)
        right_col.addStretch(1)

        layout.addLayout(right_col, stretch=0)

        return page

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
        if hasattr(backend, "sw_state_from_uC"):
            backend.sw_state_from_uC.connect(self._on_coil_sw_state)

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

        # NEW: update header protocol name
        proto_name = getattr(proto, "name", None) or getattr(proto, "protocol_name", None) or "–"
        self.session_info.setProtocolName(str(proto_name))

        # NEW: update MT in header if it exists
        mt_val = 0
        for attr in ("subject_mt_percent", "subject_mt", "mt_percent", "mt_value", "subject_mt_percent_init"):
            if hasattr(proto, attr):
                try:
                    mt_val = int(getattr(proto, attr))
                except Exception:
                    mt_val = 0
                break
        self.session_info.setMtValue(mt_val)

        # Palette / theme (existing)
        pal = self.theme_manager.generate_palette(self.current_theme)
        self.pulse_widget.setPalette(pal)
        self.intensity_gauge.setPalette(pal)
        self.mt_gauge.setPalette(pal)
        try:
            self.intensity_gauge.applyTheme(self.theme_manager, self.current_theme)
            self.mt_gauge.applyTheme(self.theme_manager, self.current_theme)
            self.coil_temp_widget.applyTheme(self.theme_manager, self.current_theme)
        except Exception:
            pass

        # Adjust intensity range based on MT
        self._update_intensity_gauge_range()

        self._sync_ui_from_protocol()

        if self.backend is not None:
            self.backend.request_param_update(proto)

    # ---- Remaining gauge mode helpers --------------------------------
    def _enter_remaining_mode(self) -> None:
        if self.mt_mode:
            return
        if self.session_active or self.session_paused:
            try:
                self.intensity_gauge.setMode(GaugeMode.REMAINING)
            except Exception:
                pass

    def _exit_remaining_mode(self) -> None:
        if self.mt_mode:
            return
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
        if self.mt_mode:
            return

        if not (self.session_active or self.session_paused):
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
        item = self.list_widget.currentItem()
        if not item:
            return None, {}
        meta = item.data(Qt.UserRole) or {}
        key = meta.get("key")
        return key, meta

    def _sync_ui_from_protocol(self) -> None:
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

    # ------------------------------------------------------------------
    #   MT / intensity helpers
    # ------------------------------------------------------------------
    def _get_subject_mt_percent(self) -> float:
        """Read MT % from the current protocol, in a tolerant way."""
        if not self.current_protocol:
            return 0.0

        proto = self.current_protocol
        for attr in (
            "subject_mt_percent",
            "subject_mt",
            "mt_percent",
            "mt_value",
            "subject_mt_percent_init",
        ):
            if hasattr(proto, attr):
                try:
                    return float(getattr(proto, attr))
                except Exception:
                    pass
        return 0.0

    def _clamp_intensity_by_mt(self, v: float) -> float:
        """
        Clamp intensity_percent_of_mt such that:
            MT * intensity / 100 <= 100
        i.e. intensity_max = 10000 / MT.
        """
        if v < 0:
            return 0.0

        mt = self._get_subject_mt_percent()
        if mt <= 0:
            # No MT known → safest is 0
            return 0.0

        max_intensity = 10000.0 / mt  # so mt * intensity / 100 <= 100
        if v > max_intensity:
            return max_intensity
        return v

    def _update_intensity_gauge_range(self) -> None:
        """
        Update intensity gauge range based on current MT:
            max_intensity = 10000 / MT
        """
        mt = self._get_subject_mt_percent()
        if mt <= 0:
            max_intensity = 0.0
        else:
            max_intensity = 10000.0 / mt

        try:
            self.intensity_gauge.setRange(0, max_intensity)
        except Exception:
            pass

        # Clamp current protocol intensity to this range
        if self.current_protocol is not None:
            try:
                cur = float(
                    getattr(self.current_protocol, "intensity_percent_of_mt_init", 0.0)
                )
            except Exception:
                cur = 0.0

            clamped = self._clamp_intensity_by_mt(cur)
            if clamped != cur:
                try:
                    setattr(self.current_protocol, "intensity_percent_of_mt_init", clamped)
                except Exception:
                    pass

            try:
                self.intensity_gauge.setValue(int(clamped))
            except Exception:
                pass

    # ------------------------------------------------------------------
    #   Value modification (encoder)
    # ------------------------------------------------------------------
    def _modify_value(self, delta: float) -> None:
        if self.mt_mode:
            # Encoder adjusts MT gauge value directly (0–100)
            cur = int(self.mt_gauge.value())
            new_val = cur + int(delta)
            new_val = max(0, min(100, new_val))
            self.mt_gauge.setValue(new_val)
            return

        if not self.current_protocol:
            return

        key, meta = self._get_current_param_meta()
        if not key:
            return

        proto = self.current_protocol

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

        if delta > 0 and cur_val + step > hi:
            return
        if delta < 0 and cur_val - step < lo:
            return

        new_val = cur_val + delta * step

        if key == "frequency_hz":
            new_val = round(new_val, 1) if new_val < 1.0 else round(new_val)

        new_val = max(lo, min(hi, new_val))
        setattr(proto, key, new_val)

        if key == "burst_pulses_count" and int(proto.burst_pulses_count) == 1:
            proto.inter_pulse_interval_ms = self.IPI_FOR_SINGLE_BURST_MS

        self._sync_ui_from_protocol()

        if self.backend is not None and self.current_protocol is not None:
            self.backend.request_param_update(self.current_protocol)

    # ------------------------------------------------------------------
    #   GPIO backend integration
    # ------------------------------------------------------------------
    def _connect_gpio_backend(self) -> None:
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
        gb.singlePulsePressed.connect(self._single_pulse_requested)
        if hasattr(gb, "mtPressed"):
            gb.mtPressed.connect(self._on_mt_requested)

        gb.enPressed.connect(self._on_en_pressed)

    def _on_encoder_step_hw(self, step: int) -> None:
        self._modify_value(float(step))

    def _on_nav_up(self) -> None:
        if self.mt_mode:
            # No param list navigation in MT page
            return
        self.list_widget.select_previous()

    def _on_nav_down(self) -> None:
        if self.mt_mode:
            # No param list navigation in MT page
            return
        self.list_widget.select_next()

    def _single_pulse_requested(self) -> None:
        """
        Hardware 'Single' button.

        In MT mode: send current MT gauge value (not yet committed) to uC:
            backend.single_pulse_request(current_MT)
        In normal mode: no action (same as previous behaviour).
        """
        if self.mt_mode and self.backend is not None:
            try:
                current_mt = float(self.mt_gauge.value())
                self.backend.single_pulse_request(current_mt)
            except Exception:
                pass

    # ------------------------------------------------------------------
    #   Session control handlers
    # ------------------------------------------------------------------
    def _on_session_start_requested(self) -> None:
        # In MT mode: Start / Pause (both GUI and GPIO) act as "Apply"
        if self.mt_mode:
            self._on_mt_apply()
            return

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
        # You can optionally map Stop to Cancel in MT mode. For now, ignore.
        if self.mt_mode:
            return

        self.session_active = False
        self.session_paused = False

        if hasattr(self.pulse_widget, "stop"):
            self.pulse_widget.stop()

        self.session_controls.set_state(running=False, paused=False)
        self._exit_remaining_mode()

        if self.backend:
            self.backend.stop_session()

    def _on_protocols_list_requested(self) -> None:
        # In MT mode: Protocol (both GUI + GPIO) acts as "Cancel"
        if self.mt_mode:
            self._on_mt_cancel()
            return
        self.request_protocol_list.emit()

    # ------------------------------------------------------------------
    #   MT mode: enter/exit/apply/cancel
    # ------------------------------------------------------------------
    def _enter_mt_mode(self) -> None:
        if self.mt_mode:
            return

        self.mt_mode = True
        self.main_stack.setCurrentIndex(1)  # show MT page

        # --- Backup and force intensity to 100% while in MT (raw MT) ---
        if self.current_protocol is not None:
            try:
                self._prev_intensity_percent = float(
                    getattr(self.current_protocol, "intensity_percent_of_mt_init", 0.0)
                )
            except Exception:
                self._prev_intensity_percent = None

            try:
                setattr(self.current_protocol, "intensity_percent_of_mt_init", 100.0)
            except Exception:
                pass

            # Also show 100% on intensity gauge (even if visually hidden)
            try:
                self.intensity_gauge.setValue(100)
            except Exception:
                pass

            if self.backend is not None:
                try:
                    self.backend.request_param_update(self.current_protocol)
                except Exception:
                    pass

        # Configure MT gauge from protocol (if available)
        self.mt_gauge.setRange(0, 100)

        if self.current_protocol is not None:
            mt_val = 0
            for attr in ("subject_mt_percent", "subject_mt", "mt_percent", "mt_value", "subject_mt_percent_init"):
                if hasattr(self.current_protocol, attr):
                    try:
                        mt_val = int(getattr(self.current_protocol, attr))
                    except Exception:
                        mt_val = 0
                    break
            mt_val = max(0, min(100, mt_val))
            self.mt_gauge.setValue(mt_val)
        else:
            self.mt_gauge.setValue(0)

        # Inform backend that we are in MT state with current protocol MT value
        if self.backend is not None:
            try:
                mt_for_uc = self._get_subject_mt_percent()
                self.backend.mt_state(mt_for_uc)
            except Exception:
                pass

        # Back up labels and hide extra buttons
        sc = self.session_controls
        self._session_btn_labels_backup = {
            "protocol": sc.protocol_frame.text(),
            "mt": sc.mt_frame.text(),
            "theme": sc.theme_frame.text(),
            "stop": sc.stop_frame.text(),
            "start": sc.start_pause_frame.text(),
        }

        sc.protocol_frame.setText("Cancel")
        sc.start_pause_frame.setText("Apply")

        sc.mt_frame.hide()
        sc.theme_frame.hide()
        sc.stop_frame.hide()

        # Hook MT actions using existing FrameButtons/signals (GUI clicks)
        if not self._mt_signals_hooked:
            sc.protocolRequested.connect(self._on_mt_cancel)
            sc.start_pause_frame.clicked.connect(self._on_mt_apply)
            self._mt_signals_hooked = True

        # Disable normal start/stop semantics while in MT
        self._apply_enable_state()

    def _exit_mt_mode(self) -> None:
        if not self.mt_mode:
            return

        self.mt_mode = False
        self.main_stack.setCurrentIndex(0)  # back to normal page

        # Restore labels and buttons
        sc = self.session_controls
        if self._session_btn_labels_backup:
            sc.protocol_frame.setText(self._session_btn_labels_backup.get("protocol", "Protocol"))
            sc.mt_frame.setText(self._session_btn_labels_backup.get("mt", "MT"))
            sc.theme_frame.setText(self._session_btn_labels_backup.get("theme", "Toggle Theme"))
            sc.stop_frame.setText(self._session_btn_labels_backup.get("stop", "Stop"))
            sc.start_pause_frame.setText(self._session_btn_labels_backup.get("start", "Start"))

        sc.mt_frame.show()
        sc.theme_frame.show()
        sc.stop_frame.show()

        # Unhook MT actions (GUI)
        if self._mt_signals_hooked:
            try:
                sc.protocolRequested.disconnect(self._on_mt_cancel)
            except Exception:
                pass
            try:
                sc.start_pause_frame.clicked.disconnect(self._on_mt_apply)
            except Exception:
                pass
            self._mt_signals_hooked = False

        # Restore previous intensity percent after MT, with dynamic clamp
        if self.current_protocol is not None and self._prev_intensity_percent is not None:
            try:
                restored = self._clamp_intensity_by_mt(float(self._prev_intensity_percent))
                setattr(self.current_protocol, "intensity_percent_of_mt_init", restored)
                try:
                    self.intensity_gauge.setValue(int(restored))
                except Exception:
                    pass
                if self.backend is not None:
                    try:
                        self.backend.request_param_update(self.current_protocol)
                    except Exception:
                        pass
            except Exception:
                pass

        # Re-apply enable state for normal session behavior
        self._apply_enable_state()

        # Inform backend that MT mode is finished, back to idle state
        self._set_backend_state("idle")

    def _on_mt_cancel(self) -> None:
        self._exit_mt_mode()

    def _on_mt_apply(self) -> None:
        """
        Take current MT gauge value, store in protocol, and go back.
        """
        value = int(self.mt_gauge.value())
        value = max(0, min(100, value))  # MT itself is 0–100 % MSO

        if self.current_protocol is not None:
            stored = False
            for attr in ("subject_mt_percent", "subject_mt", "mt_percent", "mt_value", "subject_mt_percent_init"):
                if hasattr(self.current_protocol, attr):
                    try:
                        setattr(self.current_protocol, attr, value)
                        stored = True
                        break
                    except Exception:
                        pass

            if stored and self.backend is not None:
                try:
                    self.backend.request_param_update(self.current_protocol)
                except Exception:
                    pass

            # AFTER MT changes, recompute allowed intensity range
            self._update_intensity_gauge_range()

        # Reflect MT in the header widget
        self.session_info.setMtValue(value)

        self._exit_mt_mode()

    def _on_mt_requested(self) -> None:
        """Handler for MT button in SessionControlWidget or GPIO."""
        # Only allow MT when EN and coil (Sw) are both true
        if not (self.enabled and self.coil_connected):
            return
        self._enter_mt_mode()

    # ------------------------------------------------------------------
    #   Coil connection state (from uC)
    # ------------------------------------------------------------------
    def _on_coil_sw_state(self, connected: bool) -> None:
        self.coil_connected = bool(connected)

        if hasattr(self, "coil_temp_widget"):
            try:
                self.coil_temp_widget.setCoilConnected(self.coil_connected)
            except Exception:
                pass

        if not self.coil_connected:
            self._set_backend_state("error")

        self._apply_enable_state()

        if (not self.coil_connected) and (self.session_active or self.session_paused):
            self._on_session_stop_requested()

    # ------------------------------------------------------------------
    #   Backend state helper
    # ------------------------------------------------------------------
    def _set_backend_state(self, state: str) -> None:
        if not self.backend:
            return

        if state == self._backend_state:
            return

        try:
            if state == "idle":
                self.backend.idle_state()
            elif state == "error":
                self.backend.error_state()
        except Exception:
            pass

        self._backend_state = state

    # ------------------------------------------------------------------
    #   Enable state + gradient
    # ------------------------------------------------------------------
    def _get_theme_color(self, attr_name: str, fallback: str) -> QColor:
        try:
            raw = getattr(self.theme_manager, attr_name, fallback)
        except Exception:
            raw = fallback
        if isinstance(raw, QColor):
            return raw
        return QColor(str(raw))

    def _update_bottom_panel_style(self) -> None:
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
        sc = getattr(self, "session_controls", None)
        if sc is None:
            return

        # In MT mode, Start/Stop is repurposed as "Apply"; keep it enabled,
        # but don't allow normal start/stop semantics.
        if self.mt_mode:
            sc.stop_frame.setEnabled(False)
            sc.start_pause_frame.setEnabled(True)
            return

        if hasattr(sc, "setStartStopEnabled"):
            try:
                sc.setStartStopEnabled(enabled)
                return
            except Exception:
                pass

        for attr in ("start_pause_frame",):
            if hasattr(sc, attr):
                try:
                    getattr(sc, attr).setEnabled(enabled)
                except Exception:
                    pass
        for attr in ("stop_frame",):
            if hasattr(sc, attr):
                try:
                    getattr(sc, attr).setEnabled(enabled)
                except Exception:
                    pass

    def _update_intensity_for_enable(self, enabled: bool) -> None:
        if self.mt_mode:
            # In MT mode we just track backend state; MT gauge is visual-only
            if enabled:
                self._set_backend_state("idle")
            else:
                self._set_backend_state("error")
            return

        if enabled:
            self._set_backend_state("idle")
            self.intensity_gauge.setDisabled(False)
            return

        self._set_backend_state("error")

        if self.current_protocol:
            self.current_protocol.intensity_percent_of_mt_init = 0.0

        try:
            self.intensity_gauge.setValue(0)
        except Exception:
            pass

        self.intensity_gauge.setDisabled(True)

    def _apply_enable_state(self) -> None:
        en_enabled = self.enabled
        start_stop_enabled = self.enabled and self.coil_connected

        self._update_bottom_panel_style()
        self._set_start_stop_enabled(start_stop_enabled)
        self._update_intensity_for_enable((en_enabled and self.coil_connected))
        self._update_leds_for_enable(en_enabled)

        # MT button enabled only when EN and coil switch (Sw) are both true
        sc = getattr(self, "session_controls", None)
        if sc is not None:
            mt_enabled = self.enabled and self.coil_connected and (not self.mt_mode)
            sc.mt_frame.setEnabled(mt_enabled)

    def _on_en_pressed(self) -> None:
        if self.mt_mode:
            # In MT mode we still reflect enable on LEDs / backend state
            self.enabled = not self.enabled
            self._apply_enable_state()
            return

        self.enabled = not self.enabled
        self._apply_enable_state()

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
        self.mt_gauge.setPalette(pal)

        try:
            self.intensity_gauge.applyTheme(self.theme_manager, theme_name)
            self.mt_gauge.applyTheme(self.theme_manager, theme_name)
            self.coil_temp_widget.applyTheme(self.theme_manager, theme_name)
        except Exception as e:
            print("Couldn't apply theme to gauge/coil widget:", e)

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
        if hasattr(self, "coil_temp_widget"):
            self.coil_temp_widget.setTemperature(temperature)

    def _on_intensity_changed(self, v: int) -> None:
        # User changing INTENSITY gauge (normal mode only)
        if self.mt_mode:
            # MT gauge is edited by encoder; intensity_gauge is inactive in MT
            return

        if self.intensity_gauge.mode() != GaugeMode.INTENSITY:
            return

        if not self.enabled:
            try:
                self.intensity_gauge.setValue(0)
            except Exception:
                pass
            return

        # Clamp based on MT so that MT * intensity / 100 <= 100
        v_f = float(v)
        v_clamped = self._clamp_intensity_by_mt(v_f)

        try:
            self.intensity_gauge.setValue(int(v_clamped))
        except Exception:
            pass

        if self.current_protocol:
            self.current_protocol.intensity_percent_of_mt_init = v_clamped
            self._sync_ui_from_protocol()

            if self.backend is not None:
                self.backend.request_param_update(self.current_protocol)

    def _apply_intensity_from_uc(self, val: int) -> None:
        """
        uC -> UI intensity updates.

        - Normal mode:
            drive intensity_gauge and protocol.intensity_percent_of_mt_init,
            with dynamic clamp so: MT * intensity / 100 <= 100.
        - MT mode:
            show the SAME value (0–100) on mt_gauge (absolute % MSO),
            but DO NOT write MT into the protocol here (that happens only on Apply).
        """
        # --- MT MODE: treat value as absolute % MSO (0–100) ---
        if self.mt_mode:
            v = int(val)
            if v < 0:
                v = 0
            if v > 100:
                v = 100

            if not self.enabled:
                try:
                    self.mt_gauge.setValue(0)
                except Exception:
                    pass
                return

            try:
                self.mt_gauge.setValue(v)
            except Exception:
                pass

            # No protocol MT update here; _on_mt_apply commits MT
            return

        # --- NORMAL MODE: intensity is % of MT; clamp based on MT ---
        v_f = float(val)
        v_clamped = self._clamp_intensity_by_mt(v_f)

        if self.current_protocol:
            if self.enabled:
                self.current_protocol.intensity_percent_of_mt_init = v_clamped
            else:
                self.current_protocol.intensity_percent_of_mt_init = 0.0

        if self.intensity_gauge.mode() != GaugeMode.INTENSITY:
            return

        if not self.enabled:
            try:
                self.intensity_gauge.setValue(0)
            except Exception:
                pass
            return

        try:
            self.intensity_gauge.setValue(int(v_clamped))
        except Exception:
            pass

        if self.current_protocol:
            self._sync_ui_from_protocol()

    def _update_leds_for_enable(self, enabled: bool) -> None:
        if not self.gpio_backend:
            return

        try:
            self.gpio_backend.set_green_led(enabled)
            self.gpio_backend.set_red_led(not enabled)
        except Exception:
            pass
