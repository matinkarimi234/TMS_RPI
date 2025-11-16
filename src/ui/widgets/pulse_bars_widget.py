from __future__ import annotations
import time
from typing import Optional

from PySide6.QtCore import Qt, QRectF, QTimer, QSize
from PySide6.QtGui import QPainter, QPen, QFont, QPalette
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QSizePolicy
)

###############################################################################
# CountdownCircle
###############################################################################

class CountdownCircle(QWidget):
    """
    Spinner-style rest indicator shown between trains.
    _fraction goes 0.0 -> 1.0 over the REST period.
    Arc shrinks from full circle -> 0.
    Label in the middle shows remaining seconds (rounded up).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CountdownCircle")
        self._fraction = 0.0        # how much of the REST is already done (0..1)
        self._seconds_left_text = "0s"
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def sizeHint(self):
        return QSize(60, 60)

    def set_fraction_and_label(self, frac: float, seconds_left: float):
        # clamp
        if frac < 0.0:
            frac = 0.0
        if frac > 1.0:
            frac = 1.0
        self._fraction = frac

        # ceil-ish for display
        sec_left_i = max(0, int(seconds_left + 0.999))
        self._seconds_left_text = f"{sec_left_i}s"

        self.update()

    def paintEvent(self, ev):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        d = min(self.width(), self.height())
        rect = QRectF(2, 2, d - 4, d - 4)

        mid_color = self.palette().color(QPalette.Mid)
        hi_color = self.palette().color(QPalette.Highlight)
        text_color = self.palette().color(self.foregroundRole())

        # background circle
        pen_bg = QPen(mid_color, 4)
        painter.setPen(pen_bg)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rect)

        # remaining arc
        remaining = 1.0 - self._fraction
        span_deg = 360.0 * remaining
        pen_arc = QPen(hi_color, 4)
        painter.setPen(pen_arc)
        painter.drawArc(rect, 90 * 16, -int(span_deg * 16))

        # middle text
        painter.setPen(QPen(text_color))
        font_mid = QFont(painter.font())
        font_mid.setPointSizeF(font_mid.pointSizeF() * 0.9)
        font_mid.setBold(True)
        painter.setFont(font_mid)

        tw = painter.fontMetrics().horizontalAdvance(self._seconds_left_text)
        th = painter.fontMetrics().height()
        tx = rect.center().x() - tw / 2
        ty = rect.center().y() + th * 0.35
        painter.drawText(int(tx), int(ty), self._seconds_left_text)


###############################################################################
# PulseTrainView
###############################################################################

class PulseTrainView(QWidget):
    """
    Draw ONLY the current train (burst), not the whole session.

    Uses two different counts:
      - _pulses_per_train        -> total pulses per train (train length)
      - _burst_pulses_count      -> pulses inside each burst (1..5 from protocol)

    Behaviour:

    pulses_per_burst == 1  (pulse-to-pulse mode)
      - show 2 pulses at the beginning and 2 at the end
      - label interval as 1000/frequency_hz (ms)  [pulse-to-pulse]

    pulses_per_burst = 2..5  (burst mode)
      - show N pulses at the beginning and N at the end (N = 2..5)
      - label interval as protocol IPI (inter_pulse_interval_ms)

    Visual elements:
      - amplitude label on the far left (e.g. "120")
      - dashed baseline under pulses
      - pulses rendered as biphasic pairs
      - TOP bracket over full burst with visual duration in ms
      - interval brackets between:
            * first & second pulses of left group
            * last-1 & last pulses of right group
      - center label: "........xN........" where N = pulses_per_train
      - playhead line in accent color
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # train-level
        self._pulses_per_train = 1
        self._freq_hz = 1.0
        self._amplitude_label = "120"

        # burst-level
        self._burst_pulses_count = 1          # 1..5 from TMSProtocol.burst_pulses_count
        self._ipi_ms = 0.0                    # IPI from protocol

        # visual timing
        self._burst_duration_s = 1.0          # pulses_per_train / freq_hz
        self._burst_progress = 0.0            # 0..1 inside THIS burst

        # train index (not drawn now, kept for future use)
        self._train_idx = 0
        self._train_count = 1

    def sizeHint(self) -> QSize:
        return QSize(400, 160)

    def set_burst_state(
        self,
        pulses_per_train: int,
        freq_hz: float,
        amplitude_label: str,
        burst_progress: float,
        ipi_ms: float,
        burst_pulses_count: int,
    ):
        """
        Called each frame during 'burst' phase (and at setup/done).
        """
        self._pulses_per_train = max(1, pulses_per_train)
        self._freq_hz = max(0.0001, freq_hz)
        self._amplitude_label = amplitude_label
        self._ipi_ms = max(0.0, ipi_ms)
        self._burst_pulses_count = max(1, burst_pulses_count)

        # visual burst duration (train-level)
        self._burst_duration_s = self._pulses_per_train / self._freq_hz

        # clamp burst_progress
        if burst_progress < 0.0:
            burst_progress = 0.0
        if burst_progress > 1.0:
            burst_progress = 1.0
        self._burst_progress = burst_progress

        self.update()

    def set_train_position(self, idx: int, count: int):
        """Update which train we are showing (kept for future use)."""
        if count < 1:
            count = 1
        if idx < 0:
            idx = 0
        if idx >= count:
            idx = count - 1
        self._train_idx = idx
        self._train_count = count
        self.update()

    def _compute_pulse_stroke_params(self):
        """
        Decide how "thick" each pulse is based on frequency.
        Made a bit chunkier to be more visible.
        """
        base = 8.0 / self._freq_hz  # bigger base
        stroke_w = base
        if stroke_w < 2.0:
            stroke_w = 2.0
        if stroke_w > 8.0:
            stroke_w = 8.0
        pair_gap_px = stroke_w * 0.75
        return stroke_w, pair_gap_px

    def _draw_pulse_pair(
        self,
        painter: QPainter,
        x: float,
        y_top: float,
        y_bottom: float,
        stroke_w: float,
        pair_gap_px: float
    ):
        line_color = self.palette().color(self.foregroundRole())
        pen = QPen(line_color, stroke_w)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)

        painter.drawLine(int(x), int(y_top), int(x), int(y_bottom))
        painter.drawLine(int(x + pair_gap_px), int(y_top),
                         int(x + pair_gap_px), int(y_bottom))

    def _draw_bracket_with_label_above(
        self,
        painter: QPainter,
        x0: float,
        x1: float,
        y_top: float,
        y_label: float,
        text: str
    ):
        """Bracket from x0..x1 at y_top, text ABOVE the bracket."""
        pen = QPen(self.palette().color(self.foregroundRole()))
        painter.setPen(pen)

        painter.drawLine(int(x0), int(y_top), int(x0), int(y_label))
        painter.drawLine(int(x1), int(y_top), int(x1), int(y_label))
        painter.drawLine(int(x0), int(y_top), int(x1), int(y_top))

        tw = painter.fontMetrics().horizontalAdvance(text)
        tx = (x0 + x1) / 2 - tw / 2
        ty = y_label - 2
        painter.drawText(int(tx), int(ty), text)

    def _draw_bracket_with_label_below(
        self,
        painter: QPainter,
        x0: float,
        x1: float,
        y_top: float,
        y_label: float,
        text: str
    ):
        """Bracket from x0..x1 at y_top, text BELOW the bracket."""
        pen = QPen(self.palette().color(self.foregroundRole()))
        painter.setPen(pen)

        painter.drawLine(int(x0), int(y_top), int(x0), int(y_label))
        painter.drawLine(int(x1), int(y_top), int(x1), int(y_label))
        painter.drawLine(int(x0), int(y_top), int(x1), int(y_top))

        tw = painter.fontMetrics().horizontalAdvance(text)
        tx = (x0 + x1) / 2 - tw / 2
        ty = int(y_label)
        painter.drawText(int(tx), ty, text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        W = self.width()
        H = self.height()

        # layout geometry
        amp_gutter_w = 24
        usable_left = amp_gutter_w + 10
        usable_right = W - 10
        usable_w = max(usable_right - usable_left, 1)

        pulse_top_y = H * 0.2
        pulse_bottom_y = H * 0.55
        baseline_y = H * 0.6

        # dashed baseline across the full burst width
        dash_color = self.palette().color(self.foregroundRole())
        dash_pen = QPen(dash_color)
        dash_pen.setStyle(Qt.DashLine)
        painter.setPen(dash_pen)
        painter.drawLine(int(usable_left), int(baseline_y),
                         int(usable_right), int(baseline_y))

        # amplitude label on far left
        painter.setPen(QPen(self.palette().color(self.foregroundRole())))
        font_amp = QFont(painter.font())
        font_amp.setPointSizeF(font_amp.pointSizeF() * 1.1)
        painter.setFont(font_amp)
        painter.drawText(
            5,
            int((pulse_top_y + pulse_bottom_y) / 2),
            self._amplitude_label
        )

        # visual burst duration (for top bracket & playhead)
        burst_total_ms = self._burst_duration_s * 1000.0

        # stroke size
        stroke_w, pair_gap_px = self._compute_pulse_stroke_params()

        # ---- decide how many pulses per group & what interval to display ----
        if self._burst_pulses_count == 1:
            # pulse-to-pulse mode: 2 at begin, 2 at end
            group_count = 2
            ipi_display_ms = 1000.0 / self._freq_hz
        else:
            # burst mode: N at begin, N at end (2..5)
            group_count = min(self._burst_pulses_count, 5)
            if self._ipi_ms > 0.0:
                ipi_display_ms = self._ipi_ms
            else:
                ipi_display_ms = 1000.0 / self._freq_hz

        # ---- compute group regions ----
        left_group_left = usable_left + 0.05 * usable_w
        left_group_right = usable_left + 0.35 * usable_w
        left_span = max(left_group_right - left_group_left, 1.0)

        right_group_right = usable_right - 0.05 * usable_w
        right_group_left = usable_left + 0.65 * usable_w
        right_span = max(right_group_right - right_group_left, 1.0)

        begin_x_positions = []
        end_x_positions = []

        if group_count == 1:
            # just in case; not expected with our logic
            x_left = left_group_left + left_span * 0.5
            x_right = right_group_left + right_span * 0.5
            begin_x_positions = [x_left]
            end_x_positions = [x_right]
        else:
            # Distribute pulses evenly in each group
            step_left = left_span / (group_count - 1)
            step_right = right_span / (group_count - 1)

            begin_x_positions = [
                left_group_left + i * step_left for i in range(group_count)
            ]
            end_x_positions = [
                right_group_left + i * step_right for i in range(group_count)
            ]

        # ---- draw pulses ----
        for x in begin_x_positions + end_x_positions:
            self._draw_pulse_pair(
                painter,
                x,
                pulse_top_y,
                pulse_bottom_y,
                stroke_w,
                pair_gap_px
            )

        # ---- TOP bracket -> burst visual duration in ms ----
        painter.setPen(QPen(self.palette().color(self.foregroundRole())))
        font_ann = QFont(painter.font())
        font_ann.setPointSizeF(font_ann.pointSizeF() * 0.9)
        painter.setFont(font_ann)

        burst_label_ms = f"{burst_total_ms:.1f} ms"
        bracket_top_y = pulse_top_y - 15
        bracket_text_y = bracket_top_y - 3
        self._draw_bracket_with_label_above(
            painter,
            usable_left,
            usable_right,
            bracket_top_y,
            bracket_text_y,
            burst_label_ms
        )

        # ---- INTERVAL BRACKETS ----
        painter.setFont(font_ann)
        if group_count >= 2:
            ipi_text = f"{ipi_display_ms:.1f} ms"
            # push further down so it doesn't collide with center label
            ipi_top_y = baseline_y + 18
            ipi_label_y = ipi_top_y + 18

            # First interval (left group, first two pulses)
            x0 = begin_x_positions[0]
            x1 = begin_x_positions[1]
            self._draw_bracket_with_label_below(
                painter,
                x0,
                x1,
                ipi_top_y,
                ipi_label_y,
                ipi_text
            )

            # Last interval (right group, last two pulses)
            x0_last = end_x_positions[-2]
            x1_last = end_x_positions[-1]
            self._draw_bracket_with_label_below(
                painter,
                x0_last,
                x1_last,
                ipi_top_y,
                ipi_label_y,
                ipi_text
            )

        # ---- CENTER LABEL: "........xN........" (N = pulses_per_train) ----
        label_font = QFont(painter.font())
        label_font.setPointSizeF(label_font.pointSizeF() * 0.9)
        painter.setFont(label_font)

        pulses_text = f"x{self._pulses_per_train}"
        center_label_text = f"........{pulses_text}........"

        cl_tw = painter.fontMetrics().horizontalAdvance(center_label_text)
        cl_tx = usable_left + (usable_w - cl_tw) / 2
        cl_ty = int((pulse_top_y + baseline_y) / 2)
        painter.drawText(int(cl_tx), cl_ty, center_label_text)

        # ---- playhead: vertical accent bar across whole burst ----
        play_x = usable_left + (self._burst_progress * usable_w)
        hi_color = self.palette().color(QPalette.Highlight)
        play_pen = QPen(hi_color, 2)
        play_pen.setCapStyle(Qt.FlatCap)
        painter.setPen(play_pen)

        play_y0 = pulse_top_y - 4
        play_y1 = baseline_y + 20
        painter.drawLine(int(play_x), int(play_y0), int(play_x), int(play_y1))


###############################################################################
# SessionStatusBar
###############################################################################

class SessionStatusBar(QWidget):
    """
    Bottom row: Start/Stop button only (elapsed/remaining removed).
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        self.btn_start = QPushButton("Start")
        self.btn_start.setObjectName("StartStopButton")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addStretch(1)
        lay.addWidget(self.btn_start)
        lay.addStretch(1)

    # kept for compatibility; they do nothing now
    def set_elapsed_text(self, txt: str):
        pass

    def set_remaining_text(self, txt: str):
        pass

    def set_button_running(self, running: bool):
        self.btn_start.setText("Stop" if running else "Start")


###############################################################################
# PulseBarsWidget
###############################################################################

class PulseBarsWidget(QWidget):
    """
    Orchestrates the live stimulation cycle.

    ACTIVE TRAIN:
        - show PulseTrainView with pulses, top bracket,
          interval brackets and center label
        - hide CountdownCircle

    REST:
        - hide PulseTrainView
        - show CountdownCircle with shrinking arc & seconds until next train
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.train_view = PulseTrainView(self)
        self.rest_circle = CountdownCircle(self)
        self.status_bar = SessionStatusBar(self)

        # runtime state
        self._running = False
        self._start_time = 0.0

        # protocol definition
        self._train_count = 1
        self._pulses_per_train = 1
        self._freq_hz = 1.0
        self._iti_s = 0.0
        self._burst_duration_s = 1.0
        self._total_duration_s = 1.0
        self._amp_label = "120"
        self._ipi_ms = 0.0
        self._burst_pulses_count = 1    # NEW: 1..5 from protocol

        # layout
        header_box = QHBoxLayout()
        header_box.setContentsMargins(0, 0, 0, 0)
        header_box.setSpacing(0)
        header_box.addWidget(self.train_view, stretch=1)
        header_box.addWidget(self.rest_circle, stretch=0, alignment=Qt.AlignCenter)

        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(8, 8, 8, 8)
        main_lay.setSpacing(6)
        main_lay.addLayout(header_box, stretch=1)
        main_lay.addWidget(self.status_bar, stretch=0)

        # timer
        self.timer = QTimer(self)
        self.timer.setInterval(50)  # ~20 FPS
        self.timer.timeout.connect(self._tick)

        # start/stop hookup
        self.status_bar.btn_start.clicked.connect(self._on_start_stop_clicked)

        # default visuals
        self._show_train_mode()

    # ---------- public API ----------

    def set_protocol(self, proto) -> None:
        """
        Initialize widget from a TMSProtocol-like object.
        proto must expose:
            train_count
            pulses_per_train
            frequency_hz
            inter_train_interval_s
            intensity_percent_of_mt
            inter_pulse_interval_ms
            burst_pulses_count
            total_duration_s (property)
        """
        self._train_count = proto.train_count
        self._pulses_per_train = proto.pulses_per_train
        self._freq_hz = proto.frequency_hz
        self._iti_s = proto.inter_train_interval_s
        self._amp_label = f"{int(round(proto.intensity_percent_of_mt))}"
        self._ipi_ms = proto.inter_pulse_interval_ms
        self._burst_pulses_count = proto.burst_pulses_count

        # visual burst duration used for timing/playhead (train-level)
        self._burst_duration_s = (
            self._pulses_per_train / self._freq_hz if self._freq_hz else 0.0
        )

        # full session duration (stim+rests)
        self._total_duration_s = proto.total_duration_s

        # reset UI state
        self.stop()

        # set initial train index (even if not drawn)
        self.train_view.set_train_position(0, self._train_count)

        # show fresh burst (0% progress)
        self.train_view.set_burst_state(
            pulses_per_train=self._pulses_per_train,
            freq_hz=self._freq_hz,
            amplitude_label=self._amp_label,
            burst_progress=0.0,
            ipi_ms=self._ipi_ms,
            burst_pulses_count=self._burst_pulses_count,
        )

        # init spinner with rest duration
        self.rest_circle.set_fraction_and_label(
            frac=0.0,
            seconds_left=self._iti_s
        )

        self._show_train_mode()

    # ---------- session control ----------

    def _on_start_stop_clicked(self):
        if self._running:
            self.stop()
        else:
            self.start()

    def start(self):
        if self._running:
            return
        self._running = True
        self._start_time = time.monotonic()
        self.timer.start()
        self.status_bar.set_button_running(True)

    def stop(self):
        if not self._running:
            self.status_bar.set_button_running(False)
            return
        self._running = False
        self.timer.stop()
        self.status_bar.set_button_running(False)

    # ---------- internal helpers ----------

    def _get_cycle_state(self, elapsed_s: float):
        """
        Which phase are we in?
        Return {
          train_idx: int,
          phase: "burst" | "rest" | "done",
          phase_progress: float [0..1],
          phase_remaining_s: float
        }
        """
        burst_dur = self._burst_duration_s
        rest_dur = self._iti_s

        session_dur = self._total_duration_s

        if elapsed_s >= session_dur:
            return {
                "train_idx": self._train_count - 1,
                "phase": "done",
                "phase_progress": 1.0,
                "phase_remaining_s": 0.0,
            }

        t = elapsed_s
        for train_i in range(self._train_count):
            # burst window
            if t <= burst_dur:
                prog = t / burst_dur if burst_dur > 0 else 1.0
                rem = max(burst_dur - t, 0.0)
                return {
                    "train_idx": train_i,
                    "phase": "burst",
                    "phase_progress": prog,
                    "phase_remaining_s": rem,
                }
            t -= burst_dur

            # last train has no following rest
            if train_i == self._train_count - 1:
                return {
                    "train_idx": train_i,
                    "phase": "done",
                    "phase_progress": 1.0,
                    "phase_remaining_s": 0.0,
                }

            # rest window
            if t <= rest_dur:
                prog = t / rest_dur if rest_dur > 0 else 1.0
                rem = max(rest_dur - t, 0.0)
                return {
                    "train_idx": train_i,
                    "phase": "rest",
                    "phase_progress": prog,
                    "phase_remaining_s": rem,
                }
            t -= rest_dur

        # fallback
        return {
            "train_idx": self._train_count - 1,
            "phase": "done",
            "phase_progress": 1.0,
            "phase_remaining_s": 0.0,
        }

    def _show_train_mode(self):
        self.train_view.setVisible(True)
        self.rest_circle.setVisible(False)

    def _show_rest_mode(self):
        self.train_view.setVisible(False)
        self.rest_circle.setVisible(True)

    # ---------- tick ----------

    def _tick(self):
        now = time.monotonic()
        elapsed = now - self._start_time

        # clamp
        if elapsed >= self._total_duration_s:
            elapsed = self._total_duration_s
            self.stop()

        # where are we in the protocol
        st = self._get_cycle_state(elapsed)
        phase = st["phase"]
        train_idx = st["train_idx"]

        # keep train index in sync (for future use)
        self.train_view.set_train_position(train_idx, self._train_count)

        if phase == "burst":
            # show pulses + brackets + center label
            self._show_train_mode()
            self.train_view.set_burst_state(
                pulses_per_train=self._pulses_per_train,
                freq_hz=self._freq_hz,
                amplitude_label=self._amp_label,
                burst_progress=st["phase_progress"],
                ipi_ms=self._ipi_ms,
                burst_pulses_count=self._burst_pulses_count,
            )

        elif phase == "rest":
            # hide pulses, show countdown ring
            self._show_rest_mode()
            self.rest_circle.set_fraction_and_label(
                frac=st["phase_progress"],
                seconds_left=st["phase_remaining_s"]
            )

        else:
            # done: freeze burst at 100%
            self._show_train_mode()
            self.train_view.set_burst_state(
                pulses_per_train=self._pulses_per_train,
                freq_hz=self._freq_hz,
                amplitude_label=self._amp_label,
                burst_progress=1.0,
                ipi_ms=self._ipi_ms,
                burst_pulses_count=self._burst_pulses_count,
            )

    # ---------- util ----------

    @staticmethod
    def _fmt_time(t: float) -> str:
        total = int(t)
        m = total // 60
        s = total % 60
        return f"{m:02d}:{s:02d}"
