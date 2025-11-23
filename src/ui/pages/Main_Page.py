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
from services.uart_backend import Uart_Backend, uC_State
from services.gpio_backend import GPIO_Backend
from ui.widgets.session_info_widget import SessionInfoWidget

from config.settings import COIL_WARNING_TEMPERATURE_THRESHOLD, COIL_DANGER_TEMPERATURE_THRESHOLD
from config.settings import IGBT_WARNING_TEMPERATURE_THRESHOLD, IGBT_DANGER_TEMPERATURE_THRESHOLD
from config.settings import RESISTOR_WARNING_TEMPERATURE_THRESHOLD, RESISTOR_DANGER_TEMPERATURE_THRESHOLD
from config.settings import HARD_MAX_INTENSITY

# NEW helpers
from ui.helpers.session_state import SessionState
from ui.helpers.gpio_guard import GpioEventGuard


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

        # Explicit session state machine
        self.session_state: SessionState = SessionState.IDLE

        # Backwards-compatible flags (kept for other code that might read them)
        self.session_active: bool = False   # True only when running
        self.session_paused: bool = False   # True only when paused

        # Global enable flag (front panel EN button)
        self.enabled: bool = False

        # Coil connection state (from sw_state_from_uC)
        self.coil_connected: bool = True

        self.coil_normal_Temperature: bool = True
        self.igbt_normal_Temperature: bool = True
        self.resistor_normal_Temperature: bool = True


        self.system_enabled: bool = False

        # Track last backend "global" state to avoid spamming uC
        # possible values: None, "idle", "error"
        self._backend_state: Optional[str] = None

        # Param list definition: (label, proto_key, unit)
        self.param_definitions = [
            ("Burst Pulses / Burst", "burst_pulses_count", "pulses"),
            ("Inter Pulse Interval", "inter_pulse_interval_ms", "ms"),
            ("Rep Rate", "frequency_hz", "PPS"),
            ("Pulses in Train", "pulses_per_train", ""),
            ("Number of Trains", "train_count", ""),
            ("Inter Train Interval", "inter_train_interval_s", "s"),
            ("Ramp up", "ramp_fraction", ""),
            ("Ramp up Trains", "ramp_steps", ""),
        ]

        # --- MT mode state ---
        self.mt_mode: bool = False  # mirrors SessionState.MT_EDIT
        self._session_btn_labels_backup: Dict[str, str] = {}

        # Backup for intensity percentage when entering MT
        self._prev_intensity_percent: Optional[float] = None

        # --- GPIO event guard (debounce after MT apply) ---
        self._gpio_guard = GpioEventGuard(block_ms=250, parent=self)

        # --- UI construction ---
        self._init_widgets()
        self._build_layout()
        self._populate_param_list()

        # Initial MT shown in header = 0
        self.session_info.setMtValue(0)

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
        try:
            self.intensity_gauge.setRange(0, 100)
        except Exception:
            pass

        self.pulse_widget = PulseBarsWidget(self)
        self.list_widget = NavigationListWidget()
        self.list_widget.setCurrentRow(0)

        # Remaining gauge mode disabled, but we keep connection
        self.pulse_widget.sessionRemainingChanged.connect(
            self._update_remaining_gauge
        )

        # Gauge for MT page (0–100 % MSO)
        self.mt_gauge = IntensityGauge(self)
        self.mt_gauge.setMode(GaugeMode.MT_PERCENT)
        self.mt_gauge.setTitles("MT", "PERCENT")
        self.mt_gauge.setRange(0, 100)

        # Align MT gauge visually with intensity gauge
        self.mt_gauge.setMinimumSize(self.intensity_gauge.minimumSize())
        self.mt_gauge.setSizePolicy(self.intensity_gauge.sizePolicy())

        # Top-left session info widget
        self.session_info = SessionInfoWidget(self)

        # Top panel
        self.top_panel = QWidget()
        self.top_panel.setFixedHeight(80)
        self.top_panel.setStyleSheet("background-color: rgba(128,128,128,15%);")

        self.coil_temp_widget = CoilTemperatureWidget(
            warning_threshold=COIL_WARNING_TEMPERATURE_THRESHOLD,
            danger_threshold=COIL_DANGER_TEMPERATURE_THRESHOLD,
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
        left_col.addStretch(1)
        left_col.addWidget(self.intensity_gauge, alignment=Qt.AlignCenter)
        left_col.addStretch(1)
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
        layout.setContentsMargins(0, 0, 0, 0)

        # Left: MT gauge
        left_col = QVBoxLayout()
        left_col.addStretch(1)
        left_col.addWidget(self.mt_gauge, alignment=Qt.AlignCenter)
        left_col.addStretch(1)
        layout.addLayout(left_col, stretch=0)

        # Middle: stretch (empty) – keeps gauge in same horizontal band
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
        backend.stateFromUc.connect(self._manage_state_from_uc)
        backend.intensityFromUc.connect(self._apply_intensity_from_uc)
        backend.coilTempFromUc.connect(self.set_coil_temperature)

        backend.igbtTempFromUc.connect(self._on_igbt_Temperature)
        backend.resistorTempFromUc.connect(self._on_resistor_Temperature)

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

        # Update header protocol name
        proto_name = getattr(proto, "name", None) or getattr(proto, "protocol_name", None) or "–"
        self.session_info.setProtocolName(str(proto_name))

        # Update MT in header
        mt_val = int(self._get_subject_mt_percent())
        self.session_info.setMtValue(mt_val)

        # Palette / theme
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

    # ------------------------------------------------------------------
    #   Remaining gauge mode helpers (disabled)
    # ------------------------------------------------------------------
    def _enter_remaining_mode(self) -> None:
        return

    def _exit_remaining_mode(self) -> None:
        return

    def _update_remaining_gauge(
        self,
        remaining_pulses: int,
        total_pulses: int,
        remaining_seconds: float,
        total_seconds: float,
    ) -> None:
        return

    # ------------------------------------------------------------------
    #   Param ranges / sync
    # ------------------------------------------------------------------
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
            return 0.0

        max_intensity = 10000.0 / mt
        if max_intensity > HARD_MAX_INTENSITY:
            max_intensity = HARD_MAX_INTENSITY

        if v > max_intensity:
            return max_intensity
        return v

    def _update_intensity_gauge_range(self) -> None:
        mt = self._get_subject_mt_percent()
        if mt <= 0:
            max_intensity = 0.0
        else:
            max_intensity = 10000.0 / mt

        if max_intensity > HARD_MAX_INTENSITY:
            max_intensity = HARD_MAX_INTENSITY

        try:
            self.intensity_gauge.setRange(0, max_intensity)
        except Exception:
            pass

        if self.current_protocol is not None:
            try:
                cur = float(
                    getattr(self.current_protocol, "intensity_percent_of_mt", 0.0)
                )
            except Exception:
                cur = 0.0

            clamped = self._clamp_intensity_by_mt(cur)
            if clamped != cur:
                try:
                    self.current_protocol.intensity_percent_of_mt = clamped
                    self.current_protocol.intensity_percent_of_mt_init = clamped
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
        # MT edit state: encoder adjusts MT gauge directly
        if self.session_state == SessionState.MT_EDIT:
            cur = int(self.mt_gauge.value())
            new_val = cur + int(delta)
            new_val = max(0, min(100, new_val))
            self.mt_gauge.setValue(new_val)

            if self.backend is not None:
                try:
                    self.backend.mt_state(new_val)
                except Exception:
                    pass
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

        # Wrap GPIO slots with guard to allow blocking after MT Apply
        gb.encoderStep.connect(self._gpio_guard.wrap(self._on_encoder_step_hw))
        gb.arrowUpPressed.connect(self._gpio_guard.wrap(self._on_nav_up))
        gb.arrowDownPressed.connect(self._gpio_guard.wrap(self._on_nav_down))
        gb.startPausePressed.connect(self._gpio_guard.wrap(self._on_session_start_requested))
        gb.stopPressed.connect(self._gpio_guard.wrap(self._on_session_stop_requested))
        gb.protocolPressed.connect(self._gpio_guard.wrap(self._on_protocols_list_requested))
        gb.reservedPressed.connect(self._gpio_guard.wrap(self._toggle_theme))
        gb.singlePulsePressed.connect(self._gpio_guard.wrap(self._single_pulse_requested))
        if hasattr(gb, "mtPressed"):
            gb.mtPressed.connect(self._gpio_guard.wrap(self._on_mt_requested))

        gb.enPressed.connect(self._gpio_guard.wrap(self._on_en_pressed))

    # ---------- Original handlers (GUI + GPIO) ------------------------
    def _on_encoder_step_hw(self, step: int) -> None:
        self._modify_value(float(step))

    def _on_nav_up(self) -> None:
        if self.session_state == SessionState.MT_EDIT:
            return
        self.list_widget.select_previous()

    def _on_nav_down(self) -> None:
        if self.session_state == SessionState.MT_EDIT:
            return
        self.list_widget.select_next()

    def _single_pulse_requested(self) -> None:
        if self.session_state == SessionState.MT_EDIT and self.backend is not None:
            try:
                current_mt = int(self.mt_gauge.value())
                self.backend.single_pulse_request(current_mt)
            except Exception:
                pass

    # ------------------------------------------------------------------
    #   Session state helpers (state machine core)
    # ------------------------------------------------------------------
    def _set_session_state(self, new_state: SessionState) -> None:
        self.session_state = new_state
        self.mt_mode = (new_state == SessionState.MT_EDIT)
        self.session_active = (new_state == SessionState.RUNNING)
        self.session_paused = (new_state == SessionState.PAUSED)

    def _start_session(self) -> None:
        if not self.enabled or not self.coil_connected:
            return
        if self.session_state == SessionState.MT_EDIT:
            return

        self._set_session_state(SessionState.RUNNING)

        if hasattr(self.pulse_widget, "start"):
            self.pulse_widget.start()

        self.session_controls.set_state(running=True, paused=False)
        self._enter_remaining_mode()

        if self.backend:
            self.backend.start_session()

    def _pause_session(self) -> None:
        if self.session_state != SessionState.RUNNING:
            return

        self._set_session_state(SessionState.PAUSED)

        if hasattr(self.pulse_widget, "pause"):
            self.pulse_widget.pause()

        self.session_controls.set_state(running=False, paused=True)
        self._enter_remaining_mode()

        if self.backend:
            self.backend.pause_session()

    def _stop_session(self) -> None:
        if self.session_state == SessionState.MT_EDIT:
            return

        self._set_session_state(SessionState.IDLE)

        if hasattr(self.pulse_widget, "stop"):
            self.pulse_widget.stop()

        self.session_controls.set_state(running=False, paused=False)
        self._exit_remaining_mode()

        if self.backend:
            self.backend.stop_session()

    # ------------------------------------------------------------------
    #   Session control handlers
    # ------------------------------------------------------------------
    def _on_session_start_requested(self) -> None:
        # MT mode: Start/Pause act as "Apply MT" + idle ONLY
        if self.session_state == SessionState.MT_EDIT:
            self._on_mt_apply()
            self._set_backend_state("idle", force=True)
            return

        if not self.enabled or not self.coil_connected:
            return

        if self.session_state in (SessionState.IDLE, SessionState.PAUSED):
            self._start_session()
        elif self.session_state == SessionState.RUNNING:
            self._pause_session()

    def _on_session_stop_requested(self) -> None:
        if self.session_state == SessionState.MT_EDIT:
            return
        self._stop_session()

    def _on_protocols_list_requested(self) -> None:
        # In MT mode: Protocol acts as Cancel
        if self.session_state == SessionState.MT_EDIT:
            self._on_mt_cancel()
            return
        self.request_protocol_list.emit()

    # ------------------------------------------------------------------
    #   MT mode: enter/exit/apply/cancel
    # ------------------------------------------------------------------
    def _enter_mt_mode(self) -> None:
        if self.session_state == SessionState.MT_EDIT:
            return

        if self.session_state in (SessionState.RUNNING, SessionState.PAUSED):
            self._stop_session()

        self._set_session_state(SessionState.MT_EDIT)
        self.main_stack.setCurrentIndex(1)  # show MT page

        if self.current_protocol is not None:
            try:
                self._prev_intensity_percent = float(
                    getattr(self.current_protocol, "intensity_percent_of_mt", 0.0)
                )
            except Exception:
                self._prev_intensity_percent = None

            try:
                self.current_protocol.intensity_percent_of_mt = 0.0
                self.current_protocol.intensity_percent_of_mt_init = 0.0
            except Exception:
                pass

            try:
                self.intensity_gauge.setValue(0)
            except Exception:
                pass

            if self.backend is not None:
                try:
                    self.backend.request_param_update(self.current_protocol)
                except Exception:
                    pass

        self.mt_gauge.setRange(0, 100)
        mt_val = int(self._get_subject_mt_percent())
        mt_val = max(0, min(100, mt_val))
        self.mt_gauge.setValue(mt_val)

        if self.backend is not None:
            try:
                self.backend.mt_state(mt_val)
            except Exception:
                pass

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

        self._apply_enable_state()

    def _exit_mt_mode(self) -> None:
        if self.session_state != SessionState.MT_EDIT:
            return

        self._set_session_state(SessionState.IDLE)
        self.intensity_gauge.setValue(0)
        self.main_stack.setCurrentIndex(0)  # back to normal page

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

        if self.current_protocol is not None and self._prev_intensity_percent is not None:
            try:
                restored = self._clamp_intensity_by_mt(float(self._prev_intensity_percent))
                self.current_protocol.intensity_percent_of_mt = restored
                self.current_protocol.intensity_percent_of_mt_init = restored
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

        self._apply_enable_state()

        if self.backend is not None:
            try:
                self.backend.set_mt_streaming(False)
            except Exception:
                pass

        self._set_backend_state("idle", force=True)

    def _on_mt_cancel(self) -> None:
        self._exit_mt_mode()

    def _on_mt_apply(self) -> None:
        value = int(self.mt_gauge.value())
        value = max(0, min(100, value))

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

            self._update_intensity_gauge_range()

        self.session_info.setMtValue(value)

        self._exit_mt_mode()

        # Debounce GPIO events after MT apply
        self._gpio_guard.block()

    def _on_mt_requested(self) -> None:
        if not (self.enabled and self.coil_connected):
            return
        if self.session_state != SessionState.IDLE:
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
            self.enabled = False

        self._apply_enable_state()
        

        if (not self.coil_connected) and (self.session_state in (SessionState.RUNNING, SessionState.PAUSED)):
            self._stop_session()

    # ------------------------------------------------------------------
    #   Backend state helper
    # ------------------------------------------------------------------
    def _set_backend_state(self, state: str, force: bool = False) -> None:
        if not self.backend:
            return

        if (state == self._backend_state) and (not force):
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

        base = normal_color if self.system_enabled else danger_color
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

        if self.session_state == SessionState.MT_EDIT:
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
        if self.session_state == SessionState.MT_EDIT:
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
            proto = self.current_protocol
            proto.intensity_percent_of_mt = 0.0
            proto.intensity_percent_of_mt_init = 0.0

        try:
            self.intensity_gauge.setValue(0)
        except Exception:
            pass

        self.intensity_gauge.setDisabled(True)

    def _apply_enable_state(self) -> None:
        normal_temp = self.coil_normal_Temperature and self.igbt_normal_Temperature and self.resistor_normal_Temperature

        # Disable Completely
        if not normal_temp:
            self.enabled = False

        if not self.coil_connected:
            self.enabled = False

        self.system_enabled = self.enabled and self.coil_connected and normal_temp

        self._update_bottom_panel_style()
        self._set_start_stop_enabled(self.system_enabled)
        self._update_intensity_for_enable(self.system_enabled)
        self._update_leds_for_enable(self.system_enabled)
        self._force_mt_at_disable(self.system_enabled)

        

        sc = getattr(self, "session_controls", None)
        if sc is not None:
            mt_enabled = self.system_enabled and (self.session_state != SessionState.MT_EDIT)
            sc.mt_frame.setEnabled(mt_enabled)


    def _force_mt_at_disable(self, en : bool):
        if not en and self.current_protocol:
            self.current_protocol.subject_mt_percent = 0
            self.set_protocol(self.current_protocol)

    def _on_en_pressed(self) -> None:
        self.enabled = not self.enabled
        self._apply_enable_state()

        if (not self.enabled) and (self.session_state in (SessionState.RUNNING, SessionState.PAUSED)):
            self._stop_session()

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

        
        # Normal
        if temperature < COIL_WARNING_TEMPERATURE_THRESHOLD:
            self.coil_normal_Temperature = True

        elif temperature < COIL_DANGER_TEMPERATURE_THRESHOLD:
            self.coil_normal_Temperature = True

        else:
            if self.coil_normal_Temperature:
                self._set_backend_state("error")
                self.coil_normal_Temperature = False
                self._apply_enable_state()

    def _on_intensity_changed(self, v: int) -> None:
        if self.session_state == SessionState.MT_EDIT:
            return

        if self.intensity_gauge.mode() != GaugeMode.INTENSITY:
            return

        if not self.enabled:
            try:
                self.intensity_gauge.setValue(0)
            except Exception:
                pass
            return

        v_f = float(v)
        v_clamped = self._clamp_intensity_by_mt(v_f)

        try:
            self.intensity_gauge.setValue(int(v_clamped))
        except Exception:
            pass

        if self.current_protocol:
            proto = self.current_protocol
            try:
                proto.intensity_percent_of_mt = v_clamped
                proto.intensity_percent_of_mt_init = v_clamped
            except Exception:
                pass

            self._sync_ui_from_protocol()

            if self.backend is not None:
                self.backend.request_param_update(proto)

    def _manage_state_from_uc(self, val: int):
        pass
        # if self.session_state == SessionState.RUNNING or self.session_state == SessionState.PAUSED:
        #     if val == 1: # Set Parameters
        #         self._set_session_state(SessionState.IDLE)

        #         if hasattr(self.pulse_widget, "stop"):
        #             self.pulse_widget.stop()

        #         self.session_controls.set_state(running=False, paused=False)
        #         self._exit_remaining_mode()



    def _apply_intensity_from_uc(self, val: int) -> None:
        if self.session_state == SessionState.MT_EDIT:
            v = int(val)
            v = max(0, min(100, v))

            if not self.enabled:
                try:
                    self.mt_gauge.setValue(0)
                except Exception:
                    pass
                return
            if self.mt_mode:
                try:
                    self.mt_gauge.setValue(v)
                except Exception:
                    pass

            if self.backend is not None:
                try:
                    self.backend.mt_state(v)
                except Exception:
                    pass

            return

        v_f = float(val)
        v_clamped = self._clamp_intensity_by_mt(v_f)

        if self.current_protocol:
            proto = self.current_protocol
            if self.enabled:
                proto.intensity_percent_of_mt = v_clamped
                proto.intensity_percent_of_mt_init = v_clamped
            else:
                proto.intensity_percent_of_mt = 0.0
                proto.intensity_percent_of_mt_init = 0.0

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

    # ------------------ Temperatures Handlers ------------------- #
    def _on_resistor_Temperature(self, temperature : float):
        # Normal
        if temperature < RESISTOR_WARNING_TEMPERATURE_THRESHOLD:
            self.resistor_normal_Temperature = True

        elif temperature < RESISTOR_DANGER_TEMPERATURE_THRESHOLD:
            self.resistor_normal_Temperature = True
            
        else:
            if self.resistor_normal_Temperature:
                self._set_backend_state("error")
                self.resistor_normal_Temperature = False
                self._apply_enable_state()


    def _on_igbt_Temperature(self, temperature : float):
        # Normal
        if temperature < IGBT_WARNING_TEMPERATURE_THRESHOLD:
            self.igbt_normal_Temperature = True

        elif temperature < IGBT_DANGER_TEMPERATURE_THRESHOLD:
            self.igbt_normal_Temperature = True
            
        else:
            if self.igbt_normal_Temperature:
                self._set_backend_state("error")
                self.igbt_normal_Temperature = False
                self._apply_enable_state()