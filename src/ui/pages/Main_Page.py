from typing import Optional, Tuple, Any, Dict, List
import time
from pathlib import Path

from PySide6.QtCore import Signal, Qt, QSize, QTimer
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QStackedLayout,
    QListWidgetItem,
    QSizePolicy,
)

from app.theme_manager import ThemeManager
from core.protocol_manager_revised import TMSProtocol, ProtocolManager
from ui.widgets.navigation_list_widget import NavigationListWidget
from ui.widgets.pulse_bars_widget import PulseBarsWidget
from ui.widgets.intensity_gauge import IntensityGauge, GaugeMode
from ui.widgets.temperature_widget import CoilTemperatureWidget
from ui.widgets.session_control_widget import SessionControlWidget
from ui.widgets.session_log_widget import SessionLogWidget
from services.uart_backend import Uart_Backend
from services.gpio_backend import GPIO_Backend
from ui.widgets.session_info_widget import SessionInfoWidget
from config.settings import (
    COIL_WARNING_TEMPERATURE_THRESHOLD,
    COIL_DANGER_TEMPERATURE_THRESHOLD,
    IGBT_WARNING_TEMPERATURE_THRESHOLD,
    IGBT_DANGER_TEMPERATURE_THRESHOLD,
    RESISTOR_WARNING_TEMPERATURE_THRESHOLD,
    RESISTOR_DANGER_TEMPERATURE_THRESHOLD,
    HARD_MAX_INTENSITY,
    SERIAL_NUMBER,
)

# NEW helpers
from ui.helpers.session_state import SessionState
from ui.helpers.gpio_guard import GpioEventGuard

GAUGE_COLUMN_WIDTH = 260  # fixed width so gauge x-position matches between pages



class ParamsPage(QWidget):
    """
    Main parameter/session page.

    Normal mode:
      - Left: INTENSITY gauge
      - Center: PulseBarsWidget
      - Right: parameter list
      - Bottom: SessionControlWidget (Protocol, MT, Settings, Stop, Start/Pause)

    MT mode:
      - Center stack switched to MT page:
          [ MT gauge | image placeholder | text + single timeout ]
      - Bottom SessionControlWidget visually becomes:
          [Cancel ................. Apply]

    Protocol mode:
      - Center stack switched to Protocol page
      - Bottom becomes:
          [Cancel] [User Defined] [Psychiatry] [Neurology] [Apply]
        * User Defined / Psychiatry / Neurology are SUBJECT FILTERS
        * Default filter is User Defined

    Settings mode:
      - Center stack switched to Settings page:
          [ About / info | settings NavigationListWidget ]
      - Bottom SessionControlWidget visually becomes:
          [Cancel ................. Apply]
    """

    request_protocol_list = Signal()

    # IPI value to enforce when burst_pulses_count == 1
    IPI_FOR_SINGLE_BURST_MS = 10.0

    def __init__(
        self,
        theme_manager: ThemeManager,
        protocol_manager: Optional[ProtocolManager] = None,
        gpio_backend: Optional[GPIO_Backend] = None,
        initial_theme: str = "dark",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        # --- Core references / state ---
        self.theme_manager = theme_manager
        self.protocol_manager = protocol_manager
        self.current_theme = initial_theme

        self.current_protocol: Optional[TMSProtocol] = None
        self.backend: Optional[Uart_Backend] = None
        self.gpio_backend: Optional[GPIO_Backend] = gpio_backend

        # Explicit session state machine
        self.session_state: SessionState = SessionState.IDLE

        # Backwards-compatible flags
        self.session_active: bool = False   # True only when running
        self.session_paused: bool = False   # True only when paused

        # --- Log / error state ---
        self._log_error_latched: bool = False

        # Global enable flag (front panel EN button)
        self.enabled: bool = False

        # Coil connection state (from sw_state_from_uC)
        self.coil_connected: bool = True

        self.coil_normal_Temperature: bool = True
        self.igbt_normal_Temperature: bool = True
        self.resistor_normal_Temperature: bool = True

        self._stimulation_start_time = 0.0

        self.system_enabled: bool = False

        # --- Auto disable / auto discharge ---
        # minutes: 0 = OFF
        self.auto_disable_minutes: int = 0
        self._pending_auto_disable_minutes: int = self.auto_disable_minutes
        self._last_idle_enabled_ts: float = 0.0

        # Periodic check for auto-disable
        self._auto_disable_timer = QTimer(self)
        self._auto_disable_timer.setInterval(1000)  # check every 1 s
        self._auto_disable_timer.timeout.connect(self._check_auto_disable)
        self._auto_disable_timer.start()

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

        self._uC_State: int = 0

        # Backup for intensity percentage when entering MT
        self._prev_intensity_percent: Optional[float] = None

        # Last time a single pulse was sent in MT mode (for timeout)
        self._last_single_pulse_time: float = 0.0

        # --- Protocol mode state ---
        self._selected_protocol_name: Optional[str] = None

        # NEW: protocol list subject filter (default)
        self._protocol_subject_filter: str = "User Defined"

        # --- Settings mode state ---
        self.buzzer_enabled: bool = True
        self._pending_theme: str = self.current_theme
        self._pending_buzzer: bool = self.buzzer_enabled

        # --- GPIO event guard (debounce after MT apply) ---
        self._gpio_guard = GpioEventGuard(block_ms=250, parent=self)

        # --- UI construction ---
        self._init_widgets()
        self._build_layout()
        self._populate_param_list()
        self._init_settings_list()

        # Initial MT shown in header = 0
        self.session_info.setMtValue(0)

        # --- Initial visual / logic state ---
        self._apply_enable_state()
        self._apply_theme_to_app(self.current_theme)
        self._connect_gpio_backend()

    # ------------------------------------------------------------------
    #   Locking rules
    # ------------------------------------------------------------------
    def _is_user_defined_protocol(self, proto: Optional[TMSProtocol]) -> bool:
        """
        User Defined means:
          - disease_subject is None/"" OR equals "User Defined" (case-insensitive)
        """
        if proto is None:
            return False
        ds = (getattr(proto, "disease_subject", None) or "").strip()
        return (ds == "") or (ds.casefold() == "user defined".casefold())

    def _is_stimulation_locked(self) -> bool:
        """True while RUNNING or PAUSED."""
        return self.session_state in (SessionState.RUNNING, SessionState.PAUSED)

    def _is_param_edit_locked(self) -> bool:
        """
        Params editable only when:
          - IDLE
          - current protocol is User Defined
          - not RUNNING/PAUSED
        """
        if self._is_stimulation_locked():
            return True
        if self.session_state != SessionState.IDLE:
            return True
        if not self._is_user_defined_protocol(self.current_protocol):
            return True
        return False

    def _apply_lock_ui_state(self) -> None:
        """
        UI-level lock:
          - While RUNNING/PAUSED: cannot open Protocol/MT/Settings; params locked; intensity locked
          - Preset protocols: params still appear, but edits are blocked by handler guards
        """
        sc = getattr(self, "session_controls", None)
        locked_stim = self._is_stimulation_locked()

        # While in Protocol edit page, bottom buttons are filters; don't override them here
        if self.session_state == SessionState.PROTOCOL_EDIT:
            return

        # While in MT/Settings edit, your existing logic hides buttons; don't override
        if self.session_state in (SessionState.MT_EDIT, SessionState.SETTINGS_EDIT):
            return

        # Disable opening Protocol/MT/Settings while running/paused
        if sc is not None:
            try:
                sc.protocol_frame.setEnabled(not locked_stim)
                sc.settings_frame.setEnabled(not locked_stim)
                sc.mt_frame.setEnabled((not locked_stim) and self.system_enabled)
            except Exception:
                pass

        # Lock parameter list widget entirely during stimulation (prevents mouse edits too)
        try:
            self.list_widget.setEnabled(not locked_stim)
        except Exception:
            pass

        # Lock intensity during stimulation
        try:
            if locked_stim:
                self.intensity_gauge.setDisabled(True)
            else:
                self.intensity_gauge.setDisabled(not self.system_enabled)
        except Exception:
            pass

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
        self.pulse_widget.sessionRemainingChanged.connect(self._on_session_remaining_changed)

        self.list_widget = NavigationListWidget()
        self.list_widget.setCurrentRow(0)

        # Protocol selection widgets
        self.protocol_list_widget = NavigationListWidget(self)
        self.protocol_list_widget.itemSelectionChanged.connect(self._on_protocol_selected)
        self.protocol_list_widget.setObjectName("protocol_list_widget")

        self.protocol_image = QLabel(self)
        self.protocol_image.setAlignment(Qt.AlignCenter)

        self.protocol_param_list = NavigationListWidget()

        # Gauge for MT page (0–100 % MSO)
        self.mt_gauge = IntensityGauge(self)
        self.mt_gauge.setMode(GaugeMode.MT_PERCENT)
        self.mt_gauge.setTitles("MT", "PERCENT")
        self.mt_gauge.setRange(0, 100)

        # Align MT gauge visually with intensity gauge
        gauge_size = QSize(220, 220)
        self.intensity_gauge.setFixedSize(gauge_size)
        self.mt_gauge.setFixedSize(gauge_size)

        self.mt_image = QLabel()

        # Single timeout row widget for MT page (right column)
        self.mt_timeout_widget = NavigationListWidget(self)
        self._init_mt_timeout_row()

        # Settings widgets
        self.settings_list_widget = NavigationListWidget(self)

        # --- About Us block (Settings left column) ---
        self.about_title = QLabel("MAGSTREAM", self)
        self.about_title.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.about_title.setObjectName("about_title")

        self.about_model = QLabel("Model: RT100", self)
        self.about_model.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.about_model.setObjectName("about_model")

        serial_str = self._format_serial_number()
        self.about_sn = QLabel(f"S/N: {serial_str}", self)
        self.about_sn.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.about_sn.setObjectName("about_sn")

        self.about_mfg = QLabel("Manifacturer: ARTIN Co.", self)
        self.about_mfg.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.about_mfg.setObjectName("about_mfg")

        self.about_contact = QLabel("Contact Us: www.ArtinMT.com", self)
        self.about_contact.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.about_contact.setObjectName("about_contact")

        # Top-left session info widget
        self.session_info = SessionInfoWidget(self)
        # Top-center log
        self.session_log_widget = SessionLogWidget(self)

        # Top panel
        self.top_panel = QWidget()
        self.top_panel.setFixedHeight(80)

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

    def _create_gauge_column_widget(self, gauge: QWidget) -> QWidget:
        """
        Wraps a gauge in a fixed-width column widget so that the
        gauge x-position is identical on NORMAL and MT pages.
        """
        container = QWidget(self)
        container.setFixedWidth(GAUGE_COLUMN_WIDTH)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch(1)
        layout.addWidget(gauge, alignment=Qt.AlignCenter)
        layout.addStretch(1)

        return container

    def _build_layout(self) -> None:
        """Wire widgets into layouts."""
        # --- Top layout ---
        top_layout = QHBoxLayout(self.top_panel)
        top_layout.setContentsMargins(8, 5, 8, 5)
        top_layout.setSpacing(8)

        top_layout.addWidget(self.session_info, alignment=Qt.AlignLeft | Qt.AlignVCenter)
        top_layout.addStretch(1)

        # log widget in the middle
        top_layout.addWidget(self.session_log_widget, alignment=Qt.AlignCenter)

        top_layout.addStretch(1)
        self.coil_temp_widget.setMaximumWidth(int(self.coil_temp_widget.height() * 1.4))
        top_layout.addWidget(self.coil_temp_widget, alignment=Qt.AlignRight | Qt.AlignVCenter)

        # --- Bottom row: session controls ---
        bottom_layout = QHBoxLayout(self.bottom_panel)
        bottom_layout.setContentsMargins(8, 0, 8, 0)
        bottom_layout.setSpacing(0)
        bottom_layout.addWidget(self.session_controls)

        # --- NORMAL PAGE content: [Gauge] [PulseBars] [Param list] ---
        normal_page = QWidget()
        normal_content_layout = QHBoxLayout(normal_page)
        normal_content_layout.setContentsMargins(8, 5, 8, 5)

        # Left: gauge in fixed-width container
        left_container = self._create_gauge_column_widget(self.intensity_gauge)
        normal_content_layout.addWidget(left_container, stretch=0)

        # Center: pulse widget
        normal_content_layout.addWidget(self.pulse_widget, stretch=1)

        # Right: param list
        right_col = QVBoxLayout()
        right_col.addWidget(self.list_widget, stretch=0)
        normal_content_layout.addLayout(right_col, stretch=1)

        # MT / PROTOCOL / SETTINGS pages
        mt_page = self._create_mt_page()
        protocol_page = self._create_protocols_page()
        settings_page = self._create_settings_page()

        self.main_stack = QStackedLayout()
        self.main_stack.addWidget(normal_page)    # index 0
        self.main_stack.addWidget(mt_page)        # index 1
        self.main_stack.addWidget(protocol_page)  # index 2
        self.main_stack.addWidget(settings_page)  # index 3

        # --- Assemble page layout ---
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(self.top_panel)
        main_layout.addLayout(self.main_stack, stretch=1)
        main_layout.addWidget(self.bottom_panel)

    # ------------------------------------------------------------------
    #   MT timeout row helpers
    # ------------------------------------------------------------------
    def _init_mt_timeout_row(self) -> None:
        """Create a single row that behaves like other param rows."""
        self.mt_timeout_widget.clear()

        title = "Single Delay"
        value = 0.0
        lo, hi = 0.0, 2.0
        step = 0.1
        unit = "Seconds"

        self.mt_timeout_widget.add_item(
            title=title,
            value=value,
            bounds="",
            data={
                "timeout_s": value,
                "lo": lo,
                "hi": hi,
                "step": step,
                "unit": unit,
            },
        )

        if self.mt_timeout_widget.count() > 0:
            item = self.mt_timeout_widget.item(0)
            row_widget = self.mt_timeout_widget.itemWidget(item)
            if row_widget is not None:
                row_widget.set_value(value)
                suffix = f"{unit}   ({lo:.1f}–{hi:.1f})"
                row_widget.set_suffix(suffix)

            row_h = self.mt_timeout_widget.sizeHintForRow(0)
            self.mt_timeout_widget.setFixedHeight(row_h + 6)
            self.mt_timeout_widget.setCurrentRow(0)

    def _get_selected_single_timeout_s(self) -> float:
        """Read timeout_s from the single-row timeout widget (in seconds)."""
        if self.mt_timeout_widget.count() == 0:
            return 0.0

        item = self.mt_timeout_widget.item(0)
        if not item:
            return 0.0

        meta = item.data(Qt.UserRole) or {}
        if "timeout_s" in meta:
            try:
                return float(meta["timeout_s"])
            except (TypeError, ValueError):
                pass

        row_widget = self.mt_timeout_widget.itemWidget(item)
        if row_widget is None:
            return 0.0

        try:
            return float(row_widget.get_value())
        except Exception:
            return 0.0

    # ------------------------------------------------------------------
    #   MT / PROTOCOL / SETTINGS pages
    # ------------------------------------------------------------------
    def _create_mt_page(self) -> QWidget:
        """
        MT page content:
            [ mt_gauge ] [ image + text ] [ timeout row ]
        """
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(8, 5, 8, 5)

        # Left: MT gauge in the same fixed-width container
        left_container = self._create_gauge_column_widget(self.mt_gauge)
        layout.addWidget(left_container, stretch=0)

        # Center: image + text
        center_col = QVBoxLayout()

        self.mt_image = QLabel("Image placeholder", page)
        self.mt_image.setAlignment(Qt.AlignCenter)
        self.mt_image.setFixedSize(220, 220)

        text = QLabel(
            "MT Instruction\n"
            "Gradually increase intensity while observing for a clear motor response in the target muscle.",
            page,
        )
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignCenter)

        center_col.addStretch(1)
        center_col.addWidget(self.mt_image, alignment=Qt.AlignCenter)
        center_col.addSpacing(8)
        center_col.addWidget(text, alignment=Qt.AlignCenter)
        center_col.addStretch(1)

        layout.addLayout(center_col, stretch=1)

        # Right: single timeout row (centered vertically)
        right_col = QVBoxLayout()

        timeout_label = QLabel("Single Pulse Delay", page)
        timeout_label.setAlignment(Qt.AlignCenter)

        right_col.addStretch(1)
        right_col.addWidget(timeout_label, alignment=Qt.AlignCenter)
        right_col.addSpacing(4)
        right_col.addWidget(self.mt_timeout_widget, alignment=Qt.AlignCenter)
        right_col.addStretch(2)

        layout.addLayout(right_col, stretch=1)

        return page

    def _create_protocols_page(self) -> QWidget:
        """
        Protocol selection page content:
            [ protocol list ............... | image ]
        """
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(8, 5, 8, 5)

        self.protocol_list_widget.setMinimumSize(200, 55)
        self.protocol_list_widget.setMaximumSize(800, 1000)
        self.protocol_list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Left: list fills remaining space
        layout.addWidget(self.protocol_list_widget, stretch=1)

        # Right: image fixed size
        self.protocol_image.setFixedSize(270, 270)
        self.protocol_image.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        layout.addWidget(self.protocol_image, stretch=0, alignment=Qt.AlignRight | Qt.AlignCenter)

        return page

    def _create_settings_page(self) -> QWidget:
        """
        Settings page content:
            [ About block | settings NavigationListWidget ]
        """
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(8, 50, 8, 5)
        layout.setSpacing(16)

        left_col = QVBoxLayout()
        left_col.setSpacing(20)

        left_col.addWidget(self.about_title, stretch=0, alignment=Qt.AlignLeft | Qt.AlignTop)
        left_col.addSpacing(30)
        left_col.addWidget(self.about_model, stretch=0, alignment=Qt.AlignLeft | Qt.AlignTop)
        left_col.addSpacing(4)
        left_col.addWidget(self.about_sn, stretch=0, alignment=Qt.AlignLeft | Qt.AlignTop)
        left_col.addSpacing(8)
        left_col.addWidget(self.about_mfg, stretch=0, alignment=Qt.AlignLeft | Qt.AlignTop)
        left_col.addSpacing(8)
        left_col.addWidget(self.about_contact, stretch=0, alignment=Qt.AlignLeft | Qt.AlignTop)

        layout.addLayout(left_col, stretch=1)

        right_col = QVBoxLayout()
        right_col.addWidget(self.settings_list_widget, stretch=1)
        layout.addLayout(right_col, stretch=1)

        return page

    def _populate_param_list(self) -> None:
        """Fill the navigation list with parameter rows."""
        self._populate_param_widget(self.list_widget)
        self._populate_param_widget(self.protocol_param_list)

    def _populate_param_widget(self, widget: NavigationListWidget) -> None:
        widget.clear()
        for label, key, unit in self.param_definitions:
            widget.add_item(
                title=label,
                value=0,
                bounds="",
                data={"key": key, "unit": unit},
            )
        if widget.count() > 0:
            widget.setCurrentRow(0)

    # ------------------------------------------------------------------
    #   Settings list helpers
    # ------------------------------------------------------------------
    def _init_settings_list(self) -> None:
        """Initialise Settings page NavigationListWidget."""
        self.settings_list_widget.clear()

        theme_text = "Dark" if self.current_theme.lower() == "dark" else "Light"
        self._pending_theme = self.current_theme

        buzzer_text = "On" if self.buzzer_enabled else "Off"
        self._pending_buzzer = self.buzzer_enabled

        def _auto_disable_label(minutes: int) -> str:
            return "Off" if minutes <= 0 else f"{minutes} min"

        auto_disable_text = _auto_disable_label(self.auto_disable_minutes)
        self._pending_auto_disable_minutes = self.auto_disable_minutes

        self.settings_list_widget.add_item(
            title="Theme",
            value=theme_text,
            bounds="",
            data={"key": "theme", "value": theme_text},
        )

        self.settings_list_widget.add_item(
            title="On-Prior-Beep",
            value=buzzer_text,
            bounds="",
            data={"key": "On-Prior-Beep", "value": buzzer_text},
        )

        self.settings_list_widget.add_item(
            title="Auto Disable",
            value=auto_disable_text,
            bounds="",
            data={"key": "auto_disable", "minutes": self.auto_disable_minutes},
        )

        if self.settings_list_widget.count() > 0:
            self.settings_list_widget.setCurrentRow(0)

    # ------------------------------------------------------------------
    #   Backend binding
    # ------------------------------------------------------------------
    def bind_backend(self, backend: Uart_Backend) -> None:
        """Bind the UART backend and hook up all signals."""
        self.backend = backend

        backend.stateFromUc.connect(self._manage_state_from_uc)
        backend.intensityFromUc.connect(self._apply_intensity_from_uc)
        backend.coilTempFromUc.connect(self.set_coil_temperature)

        backend.igbtTempFromUc.connect(self._on_igbt_Temperature)
        backend.resistorTempFromUc.connect(self._on_resistor_Temperature)

        if hasattr(backend, "sw_state_from_uC"):
            backend.sw_state_from_uC.connect(self._on_coil_sw_state)

        self.session_controls.startRequested.connect(self._on_session_start_requested)
        self.session_controls.stopRequested.connect(self._on_session_stop_requested)
        self.session_controls.pauseRequested.connect(self._on_session_start_requested)

        if hasattr(self.session_controls, "protocolRequested"):
            self.session_controls.protocolRequested.connect(self._on_protocols_list_requested)
        if hasattr(self.session_controls, "settingsRequested"):
            self.session_controls.settingsRequested.connect(self._on_settings_requested)
        if hasattr(self.session_controls, "mtRequested"):
            self.session_controls.mtRequested.connect(self._on_mt_requested)

        self._apply_enable_state()

    # ------------------------------------------------------------------
    #   Protocol binding / syncing
    # ------------------------------------------------------------------
    def set_protocol(self, proto: TMSProtocol) -> None:
        """Attach a TMSProtocol instance and sync UI from it."""
        self.current_protocol = proto

        self.intensity_gauge.setMode(GaugeMode.INTENSITY)
        self.intensity_gauge.setFromProtocol(proto)
        self.pulse_widget.set_protocol(proto)

        proto_name = getattr(proto, "name", None) or getattr(proto, "protocol_name", None) or "–"
        self.session_info.setProtocolName(str(proto_name))
        self._selected_protocol_name = str(proto_name)

        mt_val = int(self._get_subject_mt_percent())
        self.session_info.setMtValue(mt_val)

        pal = self.theme_manager.generate_palette(self.current_theme)
        self.pulse_widget.setPalette(pal)
        self.intensity_gauge.setPalette(pal)
        self.mt_gauge.setPalette(pal)
        try:
            self.intensity_gauge.applyTheme(self.theme_manager, self.current_theme)
            self.mt_gauge.applyTheme(self.theme_manager, self.current_theme)
            self.session_log_widget.applyTheme(self.theme_manager, self.current_theme)
            self.coil_temp_widget.applyTheme(self.theme_manager, self.current_theme)
        except Exception:
            pass

        self._update_intensity_gauge_range()

        self._sync_ui_from_protocol()
        self._update_log_widget_for_current_state()
        self._sync_param_widget_from_protocol(proto, self.protocol_param_list, False)

        if self.backend is not None:
            self.backend.request_param_update(proto, self.buzzer_enabled)

        # NEW: refresh UI lock state
        self._apply_lock_ui_state()

    # ------------------------------------------------------------------
    #   Param ranges / sync
    # ------------------------------------------------------------------
    def _get_param_range_for_key(self, proto: TMSProtocol, key: str) -> Tuple[float, float]:
        if key == "frequency_hz":
            return proto.FREQ_MIN, proto._calculate_max_frequency_hz()
        if key == "inter_pulse_interval_ms":
            return proto.IPI_MIN_HARD, proto.IPI_MAX_HARD
        if key == "pulses_per_train":
            return 1, 2000
        if key == "train_count":
            return 1, 500
        if key == "inter_train_interval_s":
            return proto.ITI_MIN, proto.ITI_MAX
        if key == "burst_pulses_count":
            return min(proto.BURST_PULSES_ALLOWED), max(proto.BURST_PULSES_ALLOWED)
        if key == "ramp_fraction":
            return 0.7, 1.0
        if key == "ramp_steps":
            return 1, 10
        return 0, 1

    def _compute_protocol_session_stats(self, proto: TMSProtocol) -> tuple[int, float]:
        """MCU-equivalent session stats for a protocol."""
        try:
            E = int(getattr(proto, "pulses_per_train", 1))
            B = int(getattr(proto, "burst_pulses_count", 1))
            N = int(getattr(proto, "train_count", 1))
            freq = float(getattr(proto, "frequency_hz", 1.0))
            ipi_ms = float(getattr(proto, "inter_pulse_interval_ms", 0.0))
            iti_s = float(getattr(proto, "inter_train_interval_s", 0.0))
        except Exception:
            return 0, 0.0

        E = max(1, E)
        B = max(1, B)
        N = max(1, N)

        freq = max(0.1, freq)
        T_rep = 1.0 / freq
        T_ipi = max(0.0, ipi_ms / 1000.0)

        train_dur = E * (T_rep + (B - 1) * T_ipi)
        total_dur = N * train_dur + max(0, N - 1) * iti_s

        total_pulses = N * E * B
        return total_pulses, total_dur

    def _update_log_widget_for_current_state(self) -> None:
        if not hasattr(self, "session_log_widget"):
            return

        if getattr(self, "_log_error_latched", False):
            return

        if self.session_state in (SessionState.RUNNING, SessionState.PAUSED):
            return

        if self.session_state == SessionState.PROTOCOL_EDIT:
            if self.protocol_manager and self._selected_protocol_name:
                proto = self.protocol_manager.get_protocol(self._selected_protocol_name)
                if proto:
                    pulses, dur = self._compute_protocol_session_stats(proto)
                    self.session_log_widget.show_preview(pulses, dur, source="Protocol")
                    return
            self.session_log_widget.show_blank()
            return

        if self.session_state in (SessionState.MT_EDIT, SessionState.SETTINGS_EDIT):
            self.session_log_widget.show_blank()
            return

        if self.session_state == SessionState.IDLE:
            if self.current_protocol is not None:
                pulses = self.pulse_widget.totalPulses
                dur = self.pulse_widget.totalSeconds
                self.session_log_widget.show_preview(pulses, dur, source="Current")
            else:
                self.session_log_widget.show_blank()
            return

    def _get_current_param_meta(self) -> Tuple[Optional[str], Dict[str, Any]]:
        item = self.list_widget.currentItem()
        if not item:
            return None, {}
        meta = item.data(Qt.UserRole) or {}
        key = meta.get("key")
        return key, meta

    def _sync_param_widget_from_protocol(self, proto: TMSProtocol, widget: NavigationListWidget, mutate_proto: bool) -> None:
        for i in range(widget.count()):
            item = widget.item(i)
            row_widget = widget.itemWidget(item)
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

            display_val = val
            if isinstance(val, (int, float)):
                clamped = max(lo, min(hi, float(val)))
                if isinstance(val, int):
                    clamped = int(round(clamped))
                if mutate_proto and clamped != val:
                    try:
                        setattr(proto, key, clamped)
                        val = clamped
                    except Exception:
                        val = clamped
                display_val = clamped

            row_widget.set_value(display_val)
            suffix = unit
            if isinstance(display_val, (int, float)):
                suffix = f"{unit}   ({lo:.2f}–{hi:.2f})" if unit else f"({lo:.2f}–{hi:.2f})"
            row_widget.set_suffix(suffix)

    def _sync_ui_from_protocol(self) -> None:
        if not self.current_protocol:
            return

        proto = self.current_protocol

        if self.session_state == SessionState.IDLE:
            self.pulse_widget.set_protocol(proto)

        # Enforce single-burst rule
        try:
            if int(getattr(proto, "burst_pulses_count", 0)) == 1:
                proto.inter_pulse_interval_ms = self.IPI_FOR_SINGLE_BURST_MS
        except Exception:
            pass

        self._sync_param_widget_from_protocol(proto, self.list_widget, True)

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
        """Clamp intensity so MT * intensity / 100 <= 100."""
        if v < 0:
            return 0.0

        mt = self._get_subject_mt_percent()
        if mt <= 0:
            return 0.0

        max_intensity = 10000.0 / mt
        if max_intensity > HARD_MAX_INTENSITY:
            max_intensity = HARD_MAX_INTENSITY

        return min(v, max_intensity)

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
                cur = float(getattr(self.current_protocol, "intensity_percent_of_mt", 0.0))
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
        if self.session_state == SessionState.PROTOCOL_EDIT:
            return

        if not self.current_protocol:
            return

        key, meta = self._get_current_param_meta()
        if not key:
            return

        #NEW: lock logic + exception for ramp params
        if not self._can_edit_param_key(key):
            return

        proto = self.current_protocol

        if key == "inter_pulse_interval_ms" and int(getattr(proto, "burst_pulses_count", 0)) == 1:
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
            step = 0.5 if key == "inter_train_interval_s" else 1
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

        if key == "inter_train_interval_s":
            new_val = round(new_val * 2.0) / 2.0

        if key == "ramp_fraction":
            new_val = round(new_val * 10.0) / 10.0

        new_val = max(lo, min(hi, new_val))
        setattr(proto, key, new_val)

        if key == "burst_pulses_count" and int(proto.burst_pulses_count) == 1:
            proto.inter_pulse_interval_ms = self.IPI_FOR_SINGLE_BURST_MS

        self._sync_ui_from_protocol()

        if self.backend is not None and self.current_protocol is not None:
            self.backend.request_param_update(self.current_protocol, self.buzzer_enabled)

    def _modify_mt_timeout(self, delta: int) -> None:
        if delta == 0:
            return
        if self.mt_timeout_widget.count() == 0:
            return

        item = self.mt_timeout_widget.item(0)
        row_widget = self.mt_timeout_widget.itemWidget(item)
        if row_widget is None:
            return

        meta = item.data(Qt.UserRole) or {}
        lo = float(meta.get("lo", 0.0))
        hi = float(meta.get("hi", 2.0))
        step = float(meta.get("step", 0.1))
        unit = meta.get("unit", "Seconds")

        try:
            cur_val = float(row_widget.get_value())
        except Exception:
            cur_val = float(meta.get("timeout_s", 0.0))

        new_val = cur_val + delta * step
        new_val = max(lo, min(hi, new_val))
        new_val = round(new_val * 10.0) / 10.0

        row_widget.set_value(new_val)
        suffix = f"{unit}   ({lo:.1f}–{hi:.1f})"
        row_widget.set_suffix(suffix)

        meta["timeout_s"] = new_val
        item.setData(Qt.UserRole, meta)

    def _modify_settings_value(self, delta: int) -> None:
        if delta == 0:
            return
        if self.settings_list_widget.count() == 0:
            return

        item = self.settings_list_widget.currentItem()
        if not item:
            return

        row_widget = self.settings_list_widget.itemWidget(item)
        meta = item.data(Qt.UserRole) or {}
        key = meta.get("key", "")

        if row_widget is None or not key:
            return

        AUTO_DISABLE_OPTIONS = [0, 5, 10, 15, 20, 30]

        if key == "theme":
            try:
                cur_val = str(row_widget.get_value())
            except Exception:
                cur_val = str(meta.get("value", ""))

            cur_lower = cur_val.strip().lower()
            if cur_lower.startswith("dark"):
                new_val = "Light"
                self._pending_theme = "light"
            else:
                new_val = "Dark"
                self._pending_theme = "dark"

            row_widget.set_value(new_val)
            meta["value"] = new_val

        elif key == "On-Prior-Beep":
            try:
                cur_val = str(row_widget.get_value())
            except Exception:
                cur_val = str(meta.get("value", ""))

            cur_lower = cur_val.strip().lower()
            if cur_lower.startswith("on"):
                new_val = "Off"
                self._pending_buzzer = False
            else:
                new_val = "On"
                self._pending_buzzer = True

            row_widget.set_value(new_val)
            meta["value"] = new_val

        elif key == "auto_disable":
            cur_minutes = int(meta.get("minutes", 0))
            if cur_minutes not in AUTO_DISABLE_OPTIONS:
                cur_minutes = 0

            idx = AUTO_DISABLE_OPTIONS.index(cur_minutes)
            step = 1 if delta > 0 else -1
            idx = (idx + step) % len(AUTO_DISABLE_OPTIONS)

            new_minutes = AUTO_DISABLE_OPTIONS[idx]
            self._pending_auto_disable_minutes = new_minutes

            new_label = "Off" if new_minutes == 0 else f"{new_minutes} min"
            row_widget.set_value(new_label)
            meta["minutes"] = new_minutes

        else:
            return

        item.setData(Qt.UserRole, meta)

    # ------------------------------------------------------------------
    #   GPIO backend integration
    # ------------------------------------------------------------------
    def _connect_gpio_backend(self) -> None:
        if not self.gpio_backend:
            return

        gb = self.gpio_backend

        gb.encoderStep.connect(self._gpio_guard.wrap(self._on_encoder_step_hw))
        gb.arrowUpPressed.connect(self._gpio_guard.wrap(self._on_nav_up))
        gb.arrowDownPressed.connect(self._gpio_guard.wrap(self._on_nav_down))
        gb.startPausePressed.connect(self._gpio_guard.wrap(self._on_session_start_requested))
        gb.stopPressed.connect(self._gpio_guard.wrap(self._on_session_stop_requested))
        gb.protocolPressed.connect(self._gpio_guard.wrap(self._on_protocols_list_requested))
        gb.reservedPressed.connect(self._gpio_guard.wrap(self._on_settings_requested))
        gb.singlePulsePressed.connect(self._gpio_guard.wrap(self._single_pulse_requested))
        if hasattr(gb, "mtPressed"):
            gb.mtPressed.connect(self._gpio_guard.wrap(self._on_mt_requested))

        gb.enPressed.connect(self._gpio_guard.wrap(self._on_en_pressed))

    # ---------- Original handlers (GUI + GPIO) ------------------------
    def _on_encoder_step_hw(self, step: int) -> None:
        if self.session_state == SessionState.MT_EDIT:
            self._modify_mt_timeout(step)
            return

        if self.session_state == SessionState.SETTINGS_EDIT:
            self._modify_settings_value(step)
            return

        self._modify_value(float(step))

    def _on_nav_up(self) -> None:
        if self.session_state == SessionState.MT_EDIT:
            return

        if self.session_state == SessionState.PROTOCOL_EDIT:
            self.protocol_list_widget.select_previous()
            if self.protocol_manager:
                try:
                    name = self.protocol_list_widget.current_title()
                    tr = self.protocol_manager.get_target_region(name)
                    if tr:
                        self._set_protocol_image(self.current_theme, tr)
                except Exception:
                    pass
            return

        if self.session_state == SessionState.SETTINGS_EDIT:
            self.settings_list_widget.select_previous()
            return

        self.list_widget.select_previous()

    def _on_nav_down(self) -> None:
        if self.session_state == SessionState.MT_EDIT:
            return

        if self.session_state == SessionState.PROTOCOL_EDIT:
            self.protocol_list_widget.select_next()
            if self.protocol_manager:
                try:
                    name = self.protocol_list_widget.current_title()
                    tr = self.protocol_manager.get_target_region(name)
                    if tr:
                        self._set_protocol_image(self.current_theme, tr)
                except Exception:
                    pass
            return

        if self.session_state == SessionState.SETTINGS_EDIT:
            self.settings_list_widget.select_next()
            return

        self.list_widget.select_next()

    def _single_pulse_requested(self) -> None:
        if self.session_state == SessionState.MT_EDIT and self.backend is not None:
            now = time.time()
            timeout_s = self._get_selected_single_timeout_s()

            if timeout_s > 0.0 and (now - self._last_single_pulse_time) < timeout_s:
                return

            try:
                current_mt = int(self.mt_gauge.value())
                self.backend.single_pulse_request(current_mt)
                self._last_single_pulse_time = now
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

        if new_state == SessionState.IDLE and self.enabled:
            self._last_idle_enabled_ts = time.time()
        elif new_state in (SessionState.RUNNING, SessionState.PAUSED):
            self._last_idle_enabled_ts = 0.0

        if new_state not in (SessionState.RUNNING, SessionState.PAUSED):
            self._update_log_widget_for_current_state()

        # NEW: apply lock UX
        self._apply_lock_ui_state()

    def _start_session(self, is_resume: bool = False) -> None:
        if not self.enabled or not self.coil_connected:
            return
        if self.session_state in (SessionState.MT_EDIT, SessionState.PROTOCOL_EDIT, SessionState.SETTINGS_EDIT):
            return

        self._set_session_state(SessionState.RUNNING)

        self.pulse_widget.start()
        self.session_controls.set_state(running=True, paused=False)

        self._stimulation_start_time = time.time()

        if self.backend:
            self.backend.start_session()

    def _pause_session(self) -> None:
        if self.session_state != SessionState.RUNNING:
            return

        self._set_session_state(SessionState.PAUSED)

        self.pulse_widget.pause()
        self.session_controls.set_state(running=False, paused=True)

        if self.backend:
            self.backend.pause_session()

    def _stop_session(self) -> None:
        if self.session_state in (SessionState.MT_EDIT, SessionState.PROTOCOL_EDIT, SessionState.SETTINGS_EDIT):
            return

        self._set_session_state(SessionState.IDLE)

        self.pulse_widget.stop()
        self.session_controls.set_state(running=False, paused=False)

        self._stimulation_start_time = 0.0

        if self.backend:
            self.backend.stop_session()

    # ------------------------------------------------------------------
    #   Session control handlers
    # ------------------------------------------------------------------
    def _on_session_start_requested(self) -> None:
        if self.session_state == SessionState.MT_EDIT:
            self._on_mt_apply()
            self._set_backend_state("idle", force=True)
            return

        if self.session_state == SessionState.PROTOCOL_EDIT:
            self._on_protocol_apply()
            self._set_backend_state("idle", force=True)
            return

        if self.session_state == SessionState.SETTINGS_EDIT:
            self._on_settings_apply()
            self._set_backend_state("idle", force=True)
            return

        if not self.enabled or not self.coil_connected:
            return

        if self.session_state == SessionState.IDLE:
            self._start_session(is_resume=False)
        elif self.session_state == SessionState.PAUSED:
            self._start_session(is_resume=True)
        elif self.session_state == SessionState.RUNNING:
            self._pause_session()

    def _on_session_stop_requested(self) -> None:
        # In Protocol mode: Stop button becomes "Neurology" filter
        if self.session_state == SessionState.PROTOCOL_EDIT:
            self._set_protocol_subject_filter("Neurology")
            return

        if self.session_state in (SessionState.MT_EDIT, SessionState.PROTOCOL_EDIT, SessionState.SETTINGS_EDIT):
            return

        self._stop_session()

    def _on_protocols_list_requested(self) -> None:
        # NEW: cannot open protocol list while RUNNING/PAUSED
        if self._is_stimulating():
            return

        if self.session_state == SessionState.MT_EDIT:
            self._on_mt_cancel()
            return
        if self.session_state == SessionState.PROTOCOL_EDIT:
            self._on_protocol_cancel()
            return
        if self.session_state == SessionState.SETTINGS_EDIT:
            self._on_settings_cancel()
            return

        if self.protocol_manager is None:
            self.request_protocol_list.emit()
            return

        self._enter_protocol_mode()

    def _on_session_remaining_changed(self, rem_pulses, total_pulses, rem_s, total_s):
        if self._log_error_latched:
            return
        if self.session_state in (SessionState.RUNNING, SessionState.PAUSED):
            self.session_log_widget.show_live(rem_pulses, total_pulses, rem_s, total_s)

    # ------------------------------------------------------------------
    #   MT mode: enter/exit/apply/cancel
    # ------------------------------------------------------------------
    def _backup_session_controls(self) -> None:
        sc = self.session_controls
        self._session_btn_labels_backup = {
            "protocol": sc.protocol_frame.text(),
            "mt": sc.mt_frame.text(),
            "settings": sc.settings_frame.text(),
            "stop": sc.stop_frame.text(),
            "start": sc.start_pause_frame.text(),
        }

    def _apply_edit_controls(self, apply_label: str) -> None:
        sc = self.session_controls
        sc.protocol_frame.setText("Cancel")
        sc.start_pause_frame.setText(apply_label)

        sc.mt_frame.hide()
        sc.settings_frame.hide()
        sc.stop_frame.hide()

    def _restore_session_controls(self) -> None:
        sc = self.session_controls
        if self._session_btn_labels_backup:
            sc.protocol_frame.setText(self._session_btn_labels_backup.get("protocol", "Protocol"))
            sc.mt_frame.setText(self._session_btn_labels_backup.get("mt", "MT"))
            sc.settings_frame.setText(self._session_btn_labels_backup.get("settings", "Settings"))
            sc.stop_frame.setText(self._session_btn_labels_backup.get("stop", "Stop"))
            sc.start_pause_frame.setText(self._session_btn_labels_backup.get("start", "Start"))

        sc.mt_frame.show()
        sc.settings_frame.show()
        sc.stop_frame.show()

    def _enter_mt_mode(self) -> None:
        if self._is_stimulation_locked():
            return

        if self.session_state in (SessionState.MT_EDIT, SessionState.PROTOCOL_EDIT, SessionState.SETTINGS_EDIT):
            return

        if self.session_state in (SessionState.RUNNING, SessionState.PAUSED):
            self._stop_session()

        self._set_session_state(SessionState.MT_EDIT)
        self.main_stack.setCurrentIndex(1)

        if self.current_protocol is not None:
            try:
                self._prev_intensity_percent = float(getattr(self.current_protocol, "intensity_percent_of_mt", 0.0))
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

            self.mt_gauge.setRange(0, 100)
            mt_val = int(self.current_protocol.subject_mt_percent)
            mt_val = max(0, min(100, mt_val))

            if self.backend is not None:
                try:
                    self.backend.mt_state(mt_val)
                    self.backend.request_param_update(self.current_protocol, self.buzzer_enabled)
                except Exception:
                    pass
        else:
            mt_val = 0

        self.mt_gauge.setValue(mt_val)

        self._backup_session_controls()
        self._apply_edit_controls("Apply")
        self._apply_enable_state()

    def _exit_mt_mode(self) -> None:
        if self.session_state != SessionState.MT_EDIT:
            return

        self._set_session_state(SessionState.IDLE)
        self.intensity_gauge.setValue(0)
        self.main_stack.setCurrentIndex(0)

        self._restore_session_controls()

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
                        self.backend.request_param_update(self.current_protocol, self.buzzer_enabled)
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
            for attr in (
                "subject_mt_percent",
                "subject_mt",
                "mt_percent",
                "mt_value",
                "subject_mt_percent_init",
            ):
                if hasattr(self.current_protocol, attr):
                    try:
                        setattr(self.current_protocol, attr, value)
                        stored = True
                        break
                    except Exception:
                        pass

            if stored and self.backend is not None:
                try:
                    self.backend.request_param_update(self.current_protocol, self.buzzer_enabled)
                except Exception:
                    pass

        self._update_intensity_gauge_range()
        self.session_info.setMtValue(value)

        self._exit_mt_mode()
        self._gpio_guard.block()

    # ------------------------------------------------------------------
    #   Protocol mode: subject filters + population
    # ------------------------------------------------------------------
    def _apply_protocol_filter_controls(self) -> None:
        """
        In PROTOCOL_EDIT:
          Protocol = Cancel
          Start/Pause = Apply
          MT/Settings/Stop become subject filters.
        """
        sc = self.session_controls

        sc.protocol_frame.setText("Cancel")
        sc.start_pause_frame.setText("Apply")

        sc.mt_frame.show()
        sc.settings_frame.show()
        sc.stop_frame.show()

        sc.mt_frame.setText("User Defined")
        sc.settings_frame.setText("Psychiatry")
        sc.stop_frame.setText("Neurology")
        self._mark_protocol_filter_buttons_small(True)

        sc.mt_frame.setEnabled(True)
        sc.settings_frame.setEnabled(True)
        sc.stop_frame.setEnabled(True)
        sc.protocol_frame.setEnabled(True)
        sc.start_pause_frame.setEnabled(True)

    def _get_protocol_names_for_filter(self) -> List[str]:
        if not self.protocol_manager:
            return []

        subj = (self._protocol_subject_filter or "").strip()
        subj_norm = subj.casefold()

        if subj_norm == "user defined".casefold():
            names: List[str] = []
            for p in self.protocol_manager.protocols.values():
                ds = (getattr(p, "disease_subject", None) or "").strip()
                if (ds == "") or (ds.casefold() == "user defined".casefold()):
                    names.append(p.name)
            return names

        return self.protocol_manager.list_protocols_on_disease_subject(subj)

    def _set_protocol_subject_filter(self, subject: str) -> None:
        self._protocol_subject_filter = (subject or "").strip() or "User Defined"
        if self.session_state == SessionState.PROTOCOL_EDIT:
            self._populate_protocol_list()

    def _mark_protocol_filter_buttons_small(self, enable: bool) -> None:
        sc = self.session_controls
        frames = (sc.mt_frame, sc.settings_frame, sc.stop_frame)

        for fr in frames:
            fr.setProperty("protoFilter", enable)

            # Force style refresh (important!)
            fr.style().unpolish(fr)
            fr.style().polish(fr)
            fr.update()

            # Also repolish labels inside (some styles only apply to the QLabel)
            for lb in fr.findChildren(QLabel):
                lb.style().unpolish(lb)
                lb.style().polish(lb)
                lb.update()

    def _populate_protocol_list(self) -> None:
        if not self.protocol_manager:
            self.protocol_list_widget.clear()
            self.protocol_image.setPixmap(QPixmap())
            return

        current_name = self._selected_protocol_name
        if self.current_protocol and not current_name:
            current_name = getattr(self.current_protocol, "name", None)

        names = self._get_protocol_names_for_filter()

        self.protocol_list_widget.clear()
        for name in names:
            item = QListWidgetItem(name)
            self.protocol_list_widget.addItem(item)
            if name == current_name:
                self.protocol_list_widget.setCurrentItem(item)

        if self.protocol_list_widget.currentItem() is None:
            if self.protocol_list_widget.count() > 0:
                self.protocol_list_widget.setCurrentRow(0)
            else:
                self.protocol_image.setPixmap(QPixmap())
                return

        self._on_protocol_selected()

    # Params that are allowed to change even on non-User-Defined protocols (IDLE only)
    EDITABLE_ON_PRESET_PROTOCOL_KEYS = {"ramp_fraction", "ramp_steps"}
    def _is_stimulating(self) -> bool:
        return self.session_state in (SessionState.RUNNING, SessionState.PAUSED)

    def _current_protocol_is_user_defined(self) -> bool:
        # Use YOUR existing filter state if you have it (recommended).
        # Example:
        # return getattr(self, "_selected_disease_subject", "User Defined") == "User Defined"

        # Fallback if you store it on protocol:
        p = self.current_protocol
        if not p:
            return True
        if hasattr(p, "disease_subject"):
            return str(getattr(p, "disease_subject")).strip().lower() == "user defined"
        return False

    def _can_edit_param_key(self, key: str) -> bool:
        # During stimulation: lock ALL list parameters
        if self._is_stimulating():
            return False

        # In edit pages you already block modification
        if self.session_state in (SessionState.MT_EDIT, SessionState.PROTOCOL_EDIT, SessionState.SETTINGS_EDIT):
            return False

        # IDLE rules:
        if self._current_protocol_is_user_defined():
            return True

        # Preset protocol: allow only ramp params
        return key in self.EDITABLE_ON_PRESET_PROTOCOL_KEYS


    def _on_protocol_selected(self) -> None:
        item = self.protocol_list_widget.currentItem()
        if not item or not self.protocol_manager:
            return

        name = item.text()
        self._selected_protocol_name = name
        proto = self.protocol_manager.get_protocol(name)

        if proto:
            self._sync_param_widget_from_protocol(proto, self.protocol_param_list, False)
            self._update_log_widget_for_current_state()

            target_region = getattr(proto, "target_region", "") or ""
            if target_region:
                self._set_protocol_image(self.current_theme, target_region)
            else:
                self.protocol_image.setPixmap(QPixmap())

    def _on_mt_requested(self) -> None:
        # In Protocol mode: MT button becomes "User Defined" filter
        if self.session_state == SessionState.PROTOCOL_EDIT:
            self._set_protocol_subject_filter("User Defined")
            return

        if self._is_stimulation_locked():
            return
        if not (self.enabled and self.coil_connected):
            return
        if self.session_state != SessionState.IDLE:
            return
        self._enter_mt_mode()

    def _enter_protocol_mode(self) -> None:
        if self.session_state == SessionState.PROTOCOL_EDIT:
            return

        if self.session_state in (SessionState.RUNNING, SessionState.PAUSED):
            # lock: cannot enter protocol mode while stimulating
            return

        self._set_session_state(SessionState.PROTOCOL_EDIT)
        self.main_stack.setCurrentIndex(2)

        # default filter each entry
        self._protocol_subject_filter = "User Defined"

        self._backup_session_controls()
        self._apply_protocol_filter_controls()

        self._populate_protocol_list()
        self._apply_enable_state()

    def _exit_protocol_mode(self) -> None:
        if self.session_state != SessionState.PROTOCOL_EDIT:
            return
        
        self._mark_protocol_filter_buttons_small(False)
        self._set_session_state(SessionState.IDLE)
        self.main_stack.setCurrentIndex(0)
        self._restore_session_controls()
        self._apply_enable_state()

    def _on_protocol_cancel(self) -> None:
        self._exit_protocol_mode()

    def _on_protocol_apply(self) -> None:
        if not (self.protocol_manager and self._selected_protocol_name):
            self._exit_protocol_mode()
            return

        proto = self.protocol_manager.get_protocol(self._selected_protocol_name)
        if proto and self.current_protocol is not None:
            proto.subject_mt_percent = self.current_protocol.subject_mt_percent
            self.set_protocol(proto)

        self._exit_protocol_mode()

    # ------------------------------------------------------------------
    #   Settings mode: enter/exit/apply/cancel
    # ------------------------------------------------------------------
    def _on_settings_requested(self) -> None:
        # In Protocol mode: Settings becomes "Psychiatry" filter
        if self.session_state == SessionState.PROTOCOL_EDIT:
            self._set_protocol_subject_filter("Psychiatry")
            return

        # NEW: cannot open settings while stimulating/paused
        if self._is_stimulation_locked():
            return

        if self.session_state == SessionState.MT_EDIT:
            self._on_mt_cancel()
            return
        if self.session_state == SessionState.SETTINGS_EDIT:
            self._on_settings_cancel()
            return

        self._enter_settings_mode()

    def _enter_settings_mode(self) -> None:
        if self.session_state in (SessionState.MT_EDIT, SessionState.PROTOCOL_EDIT, SessionState.SETTINGS_EDIT):
            return

        if self.session_state in (SessionState.RUNNING, SessionState.PAUSED):
            self._stop_session()

        self._pending_theme = self.current_theme
        self._pending_buzzer = self.buzzer_enabled
        self._init_settings_list()

        self._set_session_state(SessionState.SETTINGS_EDIT)
        self.main_stack.setCurrentIndex(3)

        self._backup_session_controls()
        self._apply_edit_controls("Apply")

        self._apply_enable_state()

    def _exit_settings_mode(self) -> None:
        if self.session_state != SessionState.SETTINGS_EDIT:
            return

        self._set_session_state(SessionState.IDLE)
        self.main_stack.setCurrentIndex(0)
        self._restore_session_controls()
        self._apply_enable_state()

    def _apply_settings(self) -> None:
        theme = (self._pending_theme or self.current_theme).lower()
        if theme not in ("dark", "light"):
            theme = "dark"

        if theme != self.current_theme:
            self.current_theme = theme
            self._apply_theme_to_app(self.current_theme)
            if self.current_protocol:
                self._sync_ui_from_protocol()

        self.buzzer_enabled = bool(self._pending_buzzer)
        self.auto_disable_minutes = int(self._pending_auto_disable_minutes)

        if self.auto_disable_minutes > 0 and self.enabled and self.session_state == SessionState.IDLE:
            self._last_idle_enabled_ts = time.time()
        else:
            self._last_idle_enabled_ts = 0.0

        if self.backend is not None:
            self.backend.request_param_update(self.current_protocol, self.buzzer_enabled)

    def _on_settings_cancel(self) -> None:
        self._exit_settings_mode()

    def _on_settings_apply(self) -> None:
        self._apply_settings()
        self._exit_settings_mode()
        self._gpio_guard.block()

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
            self._log_error_latched = True
            self.session_log_widget.show_error("Coil Disconnected")

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
                stop:1 rgba({r}, {g}, {b}, 220)
            );
        }}
        """
        self.bottom_panel.setStyleSheet(css)

    def _set_start_stop_enabled(self, enabled: bool) -> None:
        sc = getattr(self, "session_controls", None)
        if sc is None:
            return

        # In protocol edit, Stop/MT/Settings are FILTER buttons → keep enabled
        if self.session_state == SessionState.PROTOCOL_EDIT:
            try:
                sc.stop_frame.setEnabled(True)
                sc.mt_frame.setEnabled(True)
                sc.settings_frame.setEnabled(True)
                sc.start_pause_frame.setEnabled(True)
            except Exception:
                pass
            return

        # In MT/Settings edit, only Apply should be enabled
        if self.session_state in (SessionState.MT_EDIT, SessionState.SETTINGS_EDIT):
            sc.stop_frame.setEnabled(False)
            sc.start_pause_frame.setEnabled(True)
            return

        if hasattr(sc, "setStartStopEnabled"):
            try:
                sc.setStartStopEnabled(enabled)
                return
            except Exception:
                pass

        if hasattr(sc, "start_pause_frame"):
            try:
                sc.start_pause_frame.setEnabled(enabled)
            except Exception:
                pass
        if hasattr(sc, "stop_frame"):
            try:
                sc.stop_frame.setEnabled(enabled)
            except Exception:
                pass

    def _update_intensity_for_enable(self, enabled: bool) -> None:
        if self.session_state in (SessionState.MT_EDIT, SessionState.PROTOCOL_EDIT, SessionState.SETTINGS_EDIT):
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

    def _check_auto_disable(self) -> None:
        if self.auto_disable_minutes <= 0:
            return

        if not self.enabled:
            self._last_idle_enabled_ts = 0.0
            return

        if self.session_state != SessionState.IDLE:
            self._last_idle_enabled_ts = 0.0
            return

        if self._last_idle_enabled_ts <= 0.0:
            self._last_idle_enabled_ts = time.time()
            return

        elapsed = time.time() - self._last_idle_enabled_ts
        if elapsed >= self.auto_disable_minutes * 60:
            self.enabled = False
            self._last_idle_enabled_ts = 0.0
            self._apply_enable_state()
            try:
                self.session_log_widget.show_error("Auto Discharge Activated")
            except Exception:
                pass

    def _apply_enable_state(self) -> None:
        normal_temp = (
            self.coil_normal_Temperature
            and self.igbt_normal_Temperature
            and self.resistor_normal_Temperature
        )

        if not normal_temp:
            self.enabled = False

        if not self.coil_connected:
            self.enabled = False

        self.system_enabled = self.enabled and self.coil_connected and normal_temp

        if self.session_state == SessionState.MT_EDIT and not self.system_enabled:
            self._exit_mt_mode()
            return

        if self.session_state in (SessionState.RUNNING, SessionState.PAUSED) and not self.system_enabled:
            self._stop_session()

        self._update_bottom_panel_style()
        self._set_start_stop_enabled(self.system_enabled)
        self._update_intensity_for_enable(self.system_enabled)
        self._update_leds_for_enable(self.system_enabled)
        self._force_mt_at_disable(self.system_enabled)

        sc = getattr(self, "session_controls", None)
        if sc is not None:
            if self.session_state == SessionState.PROTOCOL_EDIT:
                # Filter buttons should always be usable here
                try:
                    sc.mt_frame.setEnabled(True)
                    sc.settings_frame.setEnabled(True)
                    sc.stop_frame.setEnabled(True)
                except Exception:
                    pass
            else:
                mt_enabled = self.system_enabled and (
                    self.session_state not in (SessionState.MT_EDIT, SessionState.PROTOCOL_EDIT, SessionState.SETTINGS_EDIT)
                )
                try:
                    sc.mt_frame.setEnabled(mt_enabled)
                except Exception:
                    pass

        if self.coil_connected and normal_temp:
            if self._log_error_latched:
                self._log_error_latched = False

        self._update_log_widget_for_current_state()

        # NEW: refresh lock UX
        self._apply_lock_ui_state()

    def _force_mt_at_disable(self, en: bool):
        if not en and self.current_protocol:
            self.current_protocol.subject_mt_percent = 0
            proto = self.current_protocol
            try:
                self.intensity_gauge.setFromProtocol(proto)
                self.set_protocol(proto)
                self._sync_ui_from_protocol()
            except Exception:
                pass

    def _on_en_pressed(self) -> None:
        self.enabled = not self.enabled

        if self.enabled and self.session_state == SessionState.IDLE:
            self._last_idle_enabled_ts = time.time()
        else:
            self._last_idle_enabled_ts = 0.0

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
            self.session_log_widget.applyTheme(self.theme_manager, theme_name)
            self.coil_temp_widget.applyTheme(self.theme_manager, theme_name)
        except Exception as e:
            print("Couldn't apply theme to gauge/coil widget:", e)

        self._toggle_icons_on_theme(self.current_theme)
        self._toggle_mt_image_on_theme(self.current_theme)
        self._toggle_protocol_image_on_theme(self.current_theme)

        self._update_bottom_panel_style()

    def _toggle_theme(self) -> None:
        """Kept only for GPIO reserved button compatibility. Now just opens/closes Settings mode."""
        self._on_settings_requested()

    def _toggle_icons_on_theme(self, theme: str) -> None:
        icon_path = Path(f"assets/icons/User_{theme}.png")
        user_icon = QPixmap(str(icon_path))
        self.session_info.setUserIcon(user_icon)

    def _toggle_mt_image_on_theme(self, theme: str) -> QPixmap:
        image_path = Path(f"assets/Images/MT_{theme}.png")
        image = QPixmap(str(image_path))
        self._set_Mt_image(image)
        return image

    def _toggle_protocol_image_on_theme(self, theme: str) -> None:
        if self.current_protocol and self.protocol_manager:
            target_region = self.protocol_manager.get_target_region(self.current_protocol.name)
            if target_region:
                self._set_protocol_image(theme, target_region)

    def _set_Mt_image(self, pix: QPixmap) -> None:
        if not pix.isNull():
            size = self.mt_image.size()
            if size.width() <= 0 or size.height() <= 0:
                size = QSize(200, 200)
            scaled = pix.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.mt_image.setPixmap(scaled)

    def _set_protocol_image(self, theme: str, target_region_name: str) -> None:
        image_path = Path(f"assets/Images/Protocols/{target_region_name}_{theme}.png")
        image = QPixmap(str(image_path))
        if not image.isNull():
            size = self.protocol_image.size()
            if size.width() <= 0 or size.height() <= 0:
                size = QSize(200, 200)
            scaled = image.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.protocol_image.setPixmap(scaled)
        else:
            self.protocol_image.setPixmap(QPixmap())

    # ------------------------------------------------------------------
    #   Temperature + intensity from uC
    # ------------------------------------------------------------------
    def set_coil_temperature(self, temperature: float) -> None:
        if hasattr(self, "coil_temp_widget"):
            self.coil_temp_widget.setTemperature(temperature)

        if temperature < COIL_WARNING_TEMPERATURE_THRESHOLD:
            self.coil_normal_Temperature = True
            self._apply_enable_state()
        elif temperature < COIL_DANGER_TEMPERATURE_THRESHOLD:
            self.coil_normal_Temperature = True
            self._apply_enable_state()
        else:
            if self.coil_normal_Temperature:
                self._set_backend_state("error")
                self.coil_normal_Temperature = False
                self._log_error_latched = True
                self.session_log_widget.show_error("High Coil Temperature")
                self._apply_enable_state()

    def _on_intensity_changed(self, v: int) -> None:
        # NEW: lock intensity changes during stimulation
        # if self._is_stimulation_locked():
        #     return

        if self.session_state in (SessionState.MT_EDIT, SessionState.PROTOCOL_EDIT, SessionState.SETTINGS_EDIT):
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
                self.backend.request_param_update(proto, self.buzzer_enabled)

    def _manage_state_from_uc(self, val: int):
        self._uC_State = val
        if val == 1:  # Idle
            if self.session_state in (SessionState.RUNNING, SessionState.PAUSED):
                elapsed_time = time.time() - self._stimulation_start_time
                if elapsed_time > 0.5:
                    self._set_session_state(SessionState.IDLE)
                    self._stimulation_start_time = 0.0
                    if hasattr(self.pulse_widget, "stop"):
                        self.pulse_widget.stop()
                    self.session_controls.set_state(running=False, paused=False)

    def _apply_intensity_from_uc(self, val: int) -> None:
        # # NEW: ignore UI intensity updates while running/paused (keep locked UI stable)
        # if self._is_stimulation_locked():
        #     return

        if self.session_state == SessionState.MT_EDIT and self._uC_State == 7:
            v = int(val)
            v = max(0, min(100, v))

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

            if self.backend is not None:
                try:
                    self.backend.mt_state(v)
                except Exception:
                    pass

            return

        if self.session_state in (SessionState.PROTOCOL_EDIT, SessionState.SETTINGS_EDIT):
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

        if self.intensity_gauge.mode() != GaugeMode.INTENSITY or self._uC_State == 7:
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
    def _on_resistor_Temperature(self, temperature: float):
        if temperature < RESISTOR_WARNING_TEMPERATURE_THRESHOLD:
            self.resistor_normal_Temperature = True
            self._apply_enable_state()
        elif temperature < RESISTOR_DANGER_TEMPERATURE_THRESHOLD:
            self.resistor_normal_Temperature = True
            self._apply_enable_state()
        else:
            if self.resistor_normal_Temperature:
                self._set_backend_state("error")
                self.resistor_normal_Temperature = False
                self._log_error_latched = True
                self.session_log_widget.show_error("High Resistor Temperature")
                self._apply_enable_state()

    def _on_igbt_Temperature(self, temperature: float):
        if temperature < IGBT_WARNING_TEMPERATURE_THRESHOLD:
            self.igbt_normal_Temperature = True
            self._apply_enable_state()
        elif temperature < IGBT_DANGER_TEMPERATURE_THRESHOLD:
            self.igbt_normal_Temperature = True
            self._apply_enable_state()
        else:
            if self.igbt_normal_Temperature:
                self._set_backend_state("error")
                self.igbt_normal_Temperature = False
                self._log_error_latched = True
                self.session_log_widget.show_error("High IGBT Temperature")
                self._apply_enable_state()

    def _format_serial_number(self) -> str:
        if not isinstance(SERIAL_NUMBER, dict):
            return str(SERIAL_NUMBER) if SERIAL_NUMBER is not None else "—"

        parts = [
            str(SERIAL_NUMBER.get("MODEL", "")).strip(),
            str(SERIAL_NUMBER.get("YEAR", "")).strip(),
            str(SERIAL_NUMBER.get("MONTH", "")).strip(),
            str(SERIAL_NUMBER.get("UNIT", "")).strip(),
        ]

        parts = [p for p in parts if p]
        return "".join(parts) if parts else ""
