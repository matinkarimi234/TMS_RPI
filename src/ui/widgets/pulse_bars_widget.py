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

    Burst always spans the widget width (minus margins).
    Pulses are laid across that width, and a vertical playhead sweeps
    left→right based on burst_progress.

    Visual elements:
      - amplitude label on the far left (e.g. "120")
      - dashed baseline under pulses
      - pulses rendered as biphasic pairs
      - TOP bracket over pulses with burst duration in ms
      - BOTTOM bracket with the inter-train interval (rest) in seconds
      - duration text of the burst under the pulses
      - playhead line in accent color

    Dynamic stroke width:
      low freq → thicker pulses & bigger biphasic gap
      high freq → thinner pulses & tighter gap
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._pulses_per_train = 1
        self._freq_hz = 1.0
        self._amplitude_label = "120"
        self._iti_s = 0.0  # <-- NEW: we store ITI so we can draw bottom bracket/label

        self._burst_duration_s = 1.0      # pulses_per_train / freq_hz
        self._burst_progress = 0.0        # 0..1 inside THIS burst

    def sizeHint(self) -> QSize:
        return QSize(400, 160)

    def set_burst_state(
        self,
        pulses_per_train: int,
        freq_hz: float,
        amplitude_label: str,
        burst_progress: float,
        iti_s: float
    ):
        """
        We call this every frame while in 'burst' phase (and also at setup / done).
        We now receive iti_s so we can draw the bottom bracket.
        """
        self._pulses_per_train = max(1, pulses_per_train)
        self._freq_hz = max(0.0001, freq_hz)
        self._amplitude_label = amplitude_label
        self._iti_s = max(0.0, iti_s)

        self._burst_duration_s = self._pulses_per_train / self._freq_hz

        # clamp burst_progress
        if burst_progress < 0.0:
            burst_progress = 0.0
        if burst_progress > 1.0:
            burst_progress = 1.0
        self._burst_progress = burst_progress

        self.update()

    def _compute_pulse_stroke_params(self):
        """
        Decide how "thick" each pulse is based on frequency.

        base = 4.0 / freq
        stroke_w = clamp(base, 1.0, 4.0)
        pair_gap_px = stroke_w + 1.0

        - ~1 Hz  => ~4px wide strokes, chunky
        - ~20 Hz => ~1px wide strokes, tight
        """
        base = 4.0 / self._freq_hz
        stroke_w = base
        if stroke_w < 1.0:
            stroke_w = 1.0
        if stroke_w > 4.0:
            stroke_w = 4.0
        pair_gap_px = stroke_w + 1.0
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

    def _draw_bracket_with_label(
        self,
        painter: QPainter,
        x0: float,
        x1: float,
        y_top: float,
        y_label: float,
        text: str
    ):
        pen = QPen(self.palette().color(self.foregroundRole()))
        painter.setPen(pen)

        painter.drawLine(int(x0), int(y_top), int(x0), int(y_label))
        painter.drawLine(int(x1), int(y_top), int(x1), int(y_label))
        painter.drawLine(int(x0), int(y_top), int(x1), int(y_top))

        tw = painter.fontMetrics().horizontalAdvance(text)
        tx = (x0 + x1) / 2 - tw / 2
        ty = y_label - 2
        painter.drawText(int(tx), int(ty), text)

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

        # burst timing
        burst_total_ms = self._burst_duration_s * 1000.0
        isi_ms = (1.0 / self._freq_hz) * 1000.0

        # map local burst time (0..burst_total_ms) -> x across full usable width
        def t_to_x(local_ms: float) -> float:
            if burst_total_ms <= 0.0:
                frac = 0.0
            else:
                frac = local_ms / burst_total_ms
            return usable_left + frac * usable_w

        # dynamic pulse width/spacing based on freq
        stroke_w, pair_gap_px = self._compute_pulse_stroke_params()

        # draw pulses across full width
        for n in range(self._pulses_per_train):
            t_ms = n * isi_ms
            if t_ms > burst_total_ms:
                break
            x = t_to_x(t_ms)
            self._draw_pulse_pair(
                painter,
                x,
                pulse_top_y,
                pulse_bottom_y,
                stroke_w,
                pair_gap_px
            )

        # TOP bracket -> burst duration ms
        painter.setPen(QPen(self.palette().color(self.foregroundRole())))
        font_ann = QFont(painter.font())
        font_ann.setPointSizeF(font_ann.pointSizeF() * 0.9)
        painter.setFont(font_ann)

        burst_label_ms = f"{burst_total_ms:.1f}"
        bracket_top_y = pulse_top_y - 15
        bracket_text_y = bracket_top_y - 3
        self._draw_bracket_with_label(
            painter,
            usable_left,
            usable_right,
            bracket_top_y,
            bracket_text_y,
            burst_label_ms
        )

        # BOTTOM bracket -> ITI seconds (rest duration),
        #   This mimics the "60" under the pulses in the TMS UI screenshot.
        #   We only draw it if iti_s > 0 (if no rest, it's not meaningful).
        if self._iti_s > 0.0:
            gap_label = f"{int(self._iti_s)}"
            # we draw it BELOW the baseline in a mirrored bracket
            gap_top_y = baseline_y + 15      # top line of bracket
            gap_text_y = gap_top_y + 15      # where label will sit just under the bracket
            self._draw_bracket_with_label(
                painter,
                usable_left,
                usable_right,
                gap_top_y,
                gap_text_y,
                gap_label
            )

        # duration label below burst ("1.2s" or "0:05")
        if self._burst_duration_s < 60.0:
            dur_label = f"{self._burst_duration_s:.1f}s"
        else:
            total_s_int = int(self._burst_duration_s)
            mm = total_s_int // 60
            ss = total_s_int % 60
            dur_label = f"{mm}:{ss:02d}"

        dur_tw = painter.fontMetrics().horizontalAdvance(dur_label)
        dur_tx = usable_left + (usable_w - dur_tw) / 2
        dur_ty = H - 5
        painter.drawText(int(dur_tx), int(dur_ty), dur_label)

        # playhead: vertical accent bar sweeping left→right
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
    Bottom row: elapsed | remaining | Start/Stop button
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        self.lbl_elapsed = QLabel("00:00")
        self.lbl_remaining = QLabel("00:00")

        self.btn_start = QPushButton("Start")
        self.btn_start.setObjectName("StartStopButton")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        lay.addWidget(self.lbl_elapsed)
        lay.addStretch(1)
        lay.addWidget(self.lbl_remaining)
        lay.addStretch(1)
        lay.addWidget(self.btn_start)

    def set_elapsed_text(self, txt: str):
        self.lbl_elapsed.setText(txt)

    def set_remaining_text(self, txt: str):
        self.lbl_remaining.setText(txt)

    def set_button_running(self, running: bool):
        self.btn_start.setText("Stop" if running else "Start")


###############################################################################
# PulseBarsWidget
###############################################################################

class PulseBarsWidget(QWidget):
    """
    Orchestrates the live stimulation cycle.

    ACTIVE TRAIN:
        - show PulseTrainView with pulses, top+bottom brackets
        - hide CountdownCircle

    REST:
        - hide PulseTrainView
        - show CountdownCircle with shrinking arc & seconds until next train

    We:
      - keep total elapsed / remaining in a footer
      - animate playhead in burst view
      - show rest spinner between bursts
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
            total_duration_s()
        """
        self._train_count = proto.train_count
        self._pulses_per_train = proto.pulses_per_train
        self._freq_hz = proto.frequency_hz
        self._iti_s = proto.inter_train_interval_s
        self._amp_label = f"{int(round(proto.intensity_percent_of_mt))}"

        # burst duration is pulses/freq
        self._burst_duration_s = (
            self._pulses_per_train / self._freq_hz if self._freq_hz else 0.0
        )

        # full session duration (stim+rests)
        self._total_duration_s = proto.total_duration_s

        # reset UI state
        self.stop()
        self.status_bar.set_elapsed_text("00:00")
        self.status_bar.set_remaining_text(self._fmt_time(self._total_duration_s))

        # show fresh burst (0% progress)
        self.train_view.set_burst_state(
            pulses_per_train=self._pulses_per_train,
            freq_hz=self._freq_hz,
            amplitude_label=self._amp_label,
            burst_progress=0.0,
            iti_s=self._iti_s
        )

        # init spinner with rest duration
        self.rest_circle.set_fraction_and_label(
            frac=0.0,
            seconds_left=self._iti_s
        )

        self._show_train_mode()

        # palette note:
        # after theme update in ParamsPage:
        #   pal = theme_manager.generate_palette(theme_name)
        #   pulse_widget.setPalette(pal)
        #   pulse_widget.train_view.setPalette(pal)
        #   pulse_widget.rest_circle.setPalette(pal)
        # so Highlight == ACCENT_COLOR, not default purple.

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

        # session duration = trains * burst_dur + (trains-1) * rest_dur
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

        remaining = max(self._total_duration_s - elapsed, 0.0)

        # footer labels
        self.status_bar.set_elapsed_text(self._fmt_time(elapsed))
        self.status_bar.set_remaining_text(self._fmt_time(remaining))

        # where are we in the protocol
        st = self._get_cycle_state(elapsed)
        phase = st["phase"]

        if phase == "burst":
            # show pulses + both brackets
            self._show_train_mode()
            self.train_view.set_burst_state(
                pulses_per_train=self._pulses_per_train,
                freq_hz=self._freq_hz,
                amplitude_label=self._amp_label,
                burst_progress=st["phase_progress"],
                iti_s=self._iti_s
            )

        elif phase == "rest":
            # hide pulses, show countdown ring
            self._show_rest_mode()
            self.rest_circle.set_fraction_and_label(
                frac=st["phase_progress"],            # how much rest elapsed
                seconds_left=st["phase_remaining_s"]  # seconds left in this rest
            )

        else:
            # done: freeze burst at 100%
            self._show_train_mode()
            self.train_view.set_burst_state(
                pulses_per_train=self._pulses_per_train,
                freq_hz=self._freq_hz,
                amplitude_label=self._amp_label,
                burst_progress=1.0,
                iti_s=self._iti_s
            )

    # ---------- util ----------

    @staticmethod
    def _fmt_time(t: float) -> str:
        total = int(t)
        m = total // 60
        s = total % 60
        return f"{m:02d}:{s:02d}"
