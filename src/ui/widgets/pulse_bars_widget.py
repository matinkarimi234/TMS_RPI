from __future__ import annotations
import time
from typing import Optional

from PySide6.QtCore import Qt, QRectF, QTimer, QSize, Signal, Property
from PySide6.QtGui import QPainter, QPen, QFont, QPalette
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy, QProgressBar
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
        return QSize(120, 120)

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
        rect = QRectF(4, 4, d - 8, d - 8)

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
        pen_arc = QPen(hi_color, 6)
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
      - _pulses_per_train        -> events_per_train (bursts per train)
      - _burst_pulses_count      -> pulses inside each burst (1..5)

    Behaviour:

    burst_pulses_count == 1  (single-pulse mode)
      - show 2 pulses at the beginning and 2 at the end
      - label interval as 1000/frequency_hz (ms)  [pulse-to-pulse]

    burst_pulses_count = 2..5  (burst mode)
      - show N pulses at the beginning and N at the end (N = 2..5)
      - label interval as protocol IPI (inter_pulse_interval_ms)

    Visual elements:
      - amplitude label on the far left (e.g. "120")
      - dashed baseline under pulses
      - pulses rendered as biphasic pairs
      - TOP bracket over full train with visual duration in seconds
      - interval brackets between:
            * first & second pulses of left group
            * last-1 & last pulses of right group
      - center label: "........xN........" where N = actual pulses per train
      - playhead line in accent color
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # train-level
        self._pulses_per_train = 1           # actually events_per_train
        self._freq_hz = 1.0
        self._amplitude_label = "120"

        # burst-level
        self._burst_pulses_count = 1         # 1..5 from protocol
        self._ipi_ms = 0.0                   # IPI from protocol

        # visual timing
        self._burst_duration_s = 1.0         # visual train duration
        self._burst_progress = 0.0           # 0..1 inside THIS train

        # train index (not drawn now, kept for future use)
        self._train_idx = 0
        self._train_count = 1

        # Calculated
        self._train_duration_s = 0.0         # T_train
        self._total_session_s = 0.0          # T_session

        # Remaining info (for parent / bindings)
        self._rem_pulses = 0
        self._total_pulses = 0
        self._rem_seconds = 0.0
        self._total_seconds = 0.0

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
        train_duration_s: Optional[float] = None
    ):
        """
        Called each frame during 'burst' phase (and at setup/done).
        """
        self._pulses_per_train = max(1, pulses_per_train)
        self._freq_hz = max(0.0001, freq_hz)
        self._amplitude_label = amplitude_label
        self._ipi_ms = max(0.0, ipi_ms)
        self._burst_pulses_count = max(1, burst_pulses_count)

        # visual train duration
        self._burst_duration_s = train_duration_s if train_duration_s is not None else 0.0

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
        """
        Bracket from x0..x1 at y_top, text BELOW the bracket.

        IMPORTANT:
        - bracket tails end at a fixed length below y_top
        - y_label is the text baseline (NOT the tail end)
        """
        pen = QPen(self.palette().color(self.foregroundRole()))
        painter.setPen(pen)

        # --- bracket geometry ---
        tail_len = 10  # px, length of vertical tails
        y_tail = y_top + tail_len

        # vertical tails
        painter.drawLine(int(x0), int(y_top), int(x0), int(y_tail))
        painter.drawLine(int(x1), int(y_top), int(x1), int(y_tail))

        # top horizontal line
        painter.drawLine(int(x0), int(y_top), int(x1), int(y_top))

        # --- text BELOW the tails ---
        tw = painter.fontMetrics().horizontalAdvance(text)
        tx = (x0 + x1) / 2 - tw / 2

        # y_label is already where we want the text baseline
        painter.drawText(int(tx), int(y_label), text)

    def get_usable_left(self) -> float:
        amp_gutter_w = 24
        usable_left = amp_gutter_w + 10
        return usable_left
    
    def get_usable_width(self) -> float:
        W = self.width()
        amp_gutter_w = 24
        usable_left = amp_gutter_w + 10
        usable_right = W - 10
        usable_w = max(usable_right - usable_left, 1)
        return usable_w
    
    def get_baseline_y(self) -> float:
        H = self.height()
        baseline_y = H * 0.6
        return baseline_y
    
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

        # dashed baseline across the full train width
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

        # visual train duration (for top bracket & playhead)
        burst_total_ms = self._burst_duration_s * 1000.0

        # stroke size
        stroke_w, pair_gap_px = self._compute_pulse_stroke_params()

        # ---- decide how many pulses per group & what interval to display ----
        if self._burst_pulses_count == 1:
            # single-pulse mode: 2 at begin, 2 at end
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

        # ---- TOP bracket -> train visual duration in seconds ----
        painter.setPen(QPen(self.palette().color(self.foregroundRole())))
        font_ann = QFont(painter.font())
        font_ann.setPointSizeF(font_ann.pointSizeF() * 0.9)
        painter.setFont(font_ann)

        burst_label_ms = f"{burst_total_ms / 1000.0:.1f} seconds"
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

            # bracket a bit below the baseline
            ipi_top_y = baseline_y + 18

            # text clearly below the tails
            ipi_label_y = ipi_top_y + 30

            # First interval
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

            # Last interval
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

        # ---- CENTER LABEL: "........xN........" (N = actual pulses/train) ----
        label_font = QFont(painter.font())
        label_font.setPointSizeF(label_font.pointSizeF() * 0.9)
        painter.setFont(label_font)

        total_pulses_per_train = self._pulses_per_train * self._burst_pulses_count
        pulses_text = f"x{total_pulses_per_train}"
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
        painter.drawLine(int(play_x), int(play_y0), int(play_x), int(play_y1)


        )


###############################################################################
# SessionStatusBar
###############################################################################

class SessionStatusBar(QWidget):
    """
    Bottom row only for spacing, no logic.
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addStretch(1)
        lay.addStretch(1)

    # kept for compatibility; they do nothing now
    def set_elapsed_text(self, txt: str):
        pass

    def set_remaining_text(self, txt: str):
        pass


###############################################################################
# PulseBarsWidget
###############################################################################

class PulseBarsWidget(QWidget):
    """
    Orchestrates the live stimulation cycle with proper timing:

      - Each train has 'events_per_train' events (here pulses_per_train)
      - Each event is a burst of 1..5 pulses
            time(start(pulse i) -> start(pulse i+1)) = IPI (ms)
      - Events repeat in a train at 'frequency_hz':
            time(start(event n) -> start(event n+1)) = 1/frequency_hz
      - Between trains: inter_train_interval_s (ITI), no pulses.

    MCU-equivalent timing:

       T_rep = 1 / frequency_hz
       T_ipi = inter_pulse_interval_ms / 1000
       E     = pulses_per_train        (events per train)
       B     = burst_pulses_count      (pulses per event)

       Train duration:
         T_train = E * ( T_rep + (B - 1)*T_ipi )

       Session duration:
         T_session = N * T_train + (N - 1) * ITI

    Signals:
        sessionRemainingChanged(int remaining_pulses,
                                int total_pulses,
                                float remaining_seconds,
                                float total_seconds)
    """

    sessionRemainingChanged = Signal(int, int, float, float)
    pulsesRemainingChanged = Signal(int, int)   # (remaining, total)
    timeRemainingChanged = Signal(float, float) # (remaining_s, total_s)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.train_view = PulseTrainView(self)
        self.rest_circle = CountdownCircle(self)
        self.progressbar = QProgressBar(self)
        self.progressbar.setValue(100)

        # Layout
        layout = QVBoxLayout(self)
        # Container for the view switch
        self.view_container = QWidget()
        self.view_layout = QHBoxLayout(self.view_container)
        self.view_layout.setContentsMargins(0, 0, 0, 0)
        self.view_layout.addWidget(self.train_view)
        self.view_layout.addWidget(self.rest_circle)

        layout.setContentsMargins(0, 0, 0, 25)
        layout.addWidget(self.view_container)

        prog_row = QHBoxLayout()
        prog_row.addSpacing(34)  # Align left with usable_left
        prog_row.addWidget(self.progressbar)
        prog_row.addSpacing(10)  # Align right with usable_right
        layout.addLayout(prog_row)

        # Timer
        self.timer = QTimer(self)
        self.timer.setInterval(50)  # 20Hz update rate
        self.timer.timeout.connect(self._tick)

        # State
        self._running = False
        self._paused = False
        self._start_time = 0.0
        self._elapsed_offset_s = 0.0

        # Protocol Data
        self._train_count = 1               # N
        self._pulses_per_train = 1          # events_per_train (bursts per train)
        self._burst_pulses_count = 1        # pulses per burst
        self._freq_hz = 1.0                 # rep_rate_hz
        self._ipi_ms = 0.0                  # IPI
        self._iti_s = 0.0                   # ITI
        self._amp = "0%"

        # Calculated
        self._train_duration_s = 0.0        # T_train
        self._total_session_s = 0.0         # T_session

        # Init
        self._show_train_mode()
        self.sessionRemainingChanged.connect(self._update_progress)

    # ---------- timing helpers ----------

    def _compute_train_duration_s(self) -> float:
        """
        MCU-equivalent train duration:

        events_per_train = self._pulses_per_train
        Pulses_per_burst = self._burst_pulses_count

        rep_rate_hz -> separation between events (pulses-or-bursts)
        IPI_ms      -> separation between pulses inside a burst

        On the MCU:

          - For each event:
              * wait T_rep, then first pulse
              * inside event: (B-1) IPI gaps between pulses
          - No extra delay after the last event before ITI.

        So from train start to last pulse:

            T_train = E * ( T_rep + (B - 1) * T_ipi )
        """
        E = max(1, int(self._pulses_per_train))       # events_per_train
        B = max(1, int(self._burst_pulses_count))     # Pulses_per_burst

        freq = max(0.1, float(self._freq_hz))
        T_rep = 1.0 / freq

        T_ipi = max(0.0, self._ipi_ms / 1000.0)

        return E * (T_rep + (B - 1) * T_ipi)

    def _compute_total_duration_s(self) -> float:
        """
        Total session duration:

            Total = N * T_train + (N-1) * ITI
        """
        N = max(1, int(self._train_count))
        return (N * self._train_duration_s) + (max(0, N - 1) * self._iti_s)

    # ---------- public API ----------

    def set_protocol(self, proto) -> None:
        """
        Reads protocol and calculates precise timing to match MCU behavior.
        """
        self._train_count = int(getattr(proto, "train_count", 1))
        self._pulses_per_train = int(getattr(proto, "pulses_per_train", 1))
        self._freq_hz = float(getattr(proto, "frequency_hz", 1.0))
        self._iti_s = float(getattr(proto, "inter_train_interval_s", 0.0))
        self._ipi_ms = float(getattr(proto, "inter_pulse_interval_ms", 0.0))
        self._burst_pulses_count = int(getattr(proto, "burst_pulses_count", 1))

        self._amp = f"{int(getattr(proto, 'absolute_intensity', 0))}%"

        # --- KEY CALCULATION (MCU-equivalent) ---
        self._train_duration_s = self._compute_train_duration_s()
        self._total_session_s = self._compute_total_duration_s()

        # Init View at t=0
        self.train_view.set_burst_state(
            pulses_per_train=self._pulses_per_train,
            freq_hz=self._freq_hz,
            amplitude_label=self._amp,
            burst_progress=0.0,
            ipi_ms=self._ipi_ms,
            burst_pulses_count=self._burst_pulses_count,
            train_duration_s=self._train_duration_s
        )
        self._emit_remaining(0.0)

    # ---------- session control ----------

    def start(self):
        """
        Start or resume the session.

        - If previously paused -> resume from stored _elapsed_offset_s
        - If fresh (not paused) -> start from t = 0
        """
        if self._running:
            return

        if not self._paused:
            # fresh start: reset elapsed offset
            self._elapsed_offset_s = 0.0

        self._running = True
        self._paused = False
        self._start_time = time.monotonic()
        self.timer.start()

    def pause(self):
        """
        Pause the session (freeze playhead where it is).
        """
        if not self._running:
            return

        now = time.monotonic()
        # accumulate elapsed time into offset
        self._elapsed_offset_s += now - self._start_time

        self._running = False
        self._paused = True
        self.timer.stop()

    def stop(self):
        """
        Fully stop and reset the session (back to t=0).
        """
        had_activity = self._running or self._paused

        self._running = False
        self._paused = False
        self._elapsed_offset_s = 0.0
        self.timer.stop()

        # reset visuals to t=0
        self.train_view.set_train_position(0, self._train_count)
        self.train_view.set_burst_state(
            pulses_per_train=self._pulses_per_train,
            freq_hz=self._freq_hz,
            amplitude_label=self._amp,
            burst_progress=0.0,
            ipi_ms=self._ipi_ms,
            burst_pulses_count=self._burst_pulses_count,
            train_duration_s=self._train_duration_s
        )
        self._show_train_mode()

        if had_activity:
            # when fully stopped, emit "back to all remaining"
            self._emit_remaining(elapsed=0.0)

    # ---------- cycle state ----------

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
        burst_dur = self._train_duration_s
        rest_dur = self._iti_s
        session_dur = self._total_session_s

        if session_dur > 0.0 and elapsed_s >= session_dur:
            return {
                "train_idx": max(0, self._train_count - 1),
                "phase": "done",
                "phase_progress": 1.0,
                "phase_remaining_s": 0.0,
            }

        t = elapsed_s
        for train_i in range(self._train_count):
            # burst (train) window
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
            "train_idx": max(0, self._train_count - 1),
            "phase": "done",
            "phase_progress": 1.0,
            "phase_remaining_s": 0.0,
        }

    def _tick(self):
        now = time.monotonic()
        elapsed = self._elapsed_offset_s + (now - self._start_time)

        # Clamp at end of session and stop (MCU equivalent: session done)
        if self._total_session_s > 0.0 and elapsed >= self._total_session_s:
            elapsed = self._total_session_s
            self._emit_remaining(elapsed)
            self.stop()  # Session done -> reset
            return

        # Update remaining pulses/time
        self._emit_remaining(elapsed)

        # Determine phase using canonical MCU-like state splitter
        state = self._get_cycle_state(elapsed)
        phase = state["phase"]
        train_i = state["train_idx"]
        prog = state["phase_progress"]
        rem_s = state["phase_remaining_s"]

        if phase == "burst":
            # show the train view
            self._show_train_mode()
            self.train_view.set_burst_state(
                pulses_per_train=self._pulses_per_train,
                freq_hz=self._freq_hz,
                amplitude_label=self._amp,
                burst_progress=prog,
                ipi_ms=self._ipi_ms,
                burst_pulses_count=self._burst_pulses_count,
                train_duration_s=self._train_duration_s,
            )
            # train index is 1-based in the UI
            self.train_view.set_train_position(train_i + 1, self._train_count)

        elif phase == "rest":
            # show ITI spinner
            self._show_rest_mode()
            self.rest_circle.set_fraction_and_label(prog, rem_s)

        elif phase == "done":
            # Should normally be hit only if elapsed == total_session_s,
            # but we already handle that above via stop().
            self._running = False
            self._paused = False
            self.timer.stop()

    def _emit_remaining(self, elapsed):
        # total MCU pulses: trains * events_per_train * pulses_per_burst
        total_p = (
            max(1, self._train_count)
            * max(1, self._pulses_per_train)
            * max(1, self._burst_pulses_count)
        )

        rem_time = max(0.0, self._total_session_s - elapsed)

        if self._total_session_s > 0:
            frac = elapsed / self._total_session_s
        else:
            frac = 0.0

        done_p = int(total_p * frac)
        rem_p = max(0, total_p - done_p)

        # store for properties
        self._rem_pulses = rem_p
        self._total_pulses = total_p
        self._rem_seconds = rem_time
        self._total_seconds = self._total_session_s

        # old combined signal (already used by progress bar)
        self.sessionRemainingChanged.emit(
            rem_p, total_p, rem_time, self._total_session_s
        )

        # new, more specific signals
        self.pulsesRemainingChanged.emit(rem_p, total_p)
        self.timeRemainingChanged.emit(rem_time, self._total_session_s)

    def _show_train_mode(self):
        self.train_view.setVisible(True)
        self.rest_circle.setVisible(False)

    def _show_rest_mode(self):
        self.train_view.setVisible(False)
        self.rest_circle.setVisible(True)

    def sizeHint(self) -> QSize:
        tv_hint = self.train_view.sizeHint()
        prog_h = self.progressbar.sizeHint().height()
        return QSize(tv_hint.width(), tv_hint.height() + prog_h)
    
    # ---------- Qt Properties for parent access ----------

    def _get_remaining_pulses(self) -> int:
        return self._rem_pulses

    def _get_total_pulses(self) -> int:
        return self._total_pulses

    def _get_remaining_seconds(self) -> float:
        return self._rem_seconds

    def _get_total_seconds(self) -> float:
        return self._total_seconds

    remainingPulses = Property(int, _get_remaining_pulses,
                               notify=pulsesRemainingChanged)
    totalPulses = Property(int, _get_total_pulses,
                           notify=pulsesRemainingChanged)

    remainingSeconds = Property(float, _get_remaining_seconds,
                                notify=timeRemainingChanged)
    totalSeconds = Property(float, _get_total_seconds,
                            notify=timeRemainingChanged)

    # ---------- util ----------

    @staticmethod
    def _fmt_time(t: float) -> str:
        total = int(t)
        m = total // 60
        s = total % 60
        return f"{m:02d}:{s:02d}"
    
    def _update_progress(self, rem_pulses: int, total_pulses: int, rem_s: float, total_s: float):
        if total_pulses > 0:
            progress = int(100 * (1 - (rem_pulses / total_pulses)))
            self.progressbar.setValue(progress)
