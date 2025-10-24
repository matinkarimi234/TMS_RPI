from PySide6.QtCore import Qt, QTimer, QRectF, QElapsedTimer, QSize
from PySide6.QtGui import QPainter, QPen, QFontMetrics, QConicalGradient
from PySide6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QVBoxLayout, QFormLayout,
    QPushButton, QLabel, QFrame
)
from PySide6.QtGui import QPalette, QColor
import sys, math
from typing import Optional


def fmt_time(sec: float) -> str:
    m = int(sec // 60)
    s = int(round(sec - 60*m))
    return f"{m}:{s:02d}"


class PulseBarsGraph(QWidget):
    """
    iTBS-like graph with hollow line pulses, green cursor, labeled brackets,
    and a BETWEEN-LOOPS countdown circle.
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        # --- protocol
        self.repeats = 5
        self.train_duration_s = 1.93
        self.inter_train_interval_s = 6.0
        self.bursts_per_train = 3

        # --- pulse look
        self.pulse_line_count = 2
        self.pulse_inner_gap_px = 3
        self.stroke_width = 2

        # --- overlay labels
        self.top_label = "50.0"
        self.mid_label = "120"
        self.bottom_train_label = "19.3"
        self.bottom_gap_label = "60"

        # --- total time label
        self.show_total_time = True

        # --- animation & looping
        self.loop = True
        self.loop_pause_s = None           # None -> use inter_train_interval_s
        self._timer = QTimer(self); self._timer.setInterval(30)
        self._timer.timeout.connect(self.update)
        self._elapsed = QElapsedTimer()
        self._running = False
        # hide the green cursor while we're in the final (between-loops) pause
        self.hide_cursor_between_loops = True   # set True to hide, False to show


        # --- countdown circle options
        self.countdown_enabled = True
        self.countdown_radius_px = 15
        self.countdown_ring_width = 3
        self.countdown_margin_px = 10
        self.countdown_pos = "top_right"   # or: top_left, bottom_right, bottom_left

    # ---------- public API
    def set_protocol(self, *, repeats=None, train_duration_s=None,
                     inter_train_interval_s=None, bursts_per_train=None):
        if repeats is not None: self.repeats = max(1, int(repeats))
        if train_duration_s is not None:
            self.train_duration_s = max(0.1, float(train_duration_s))
            t10 = int(round(self.train_duration_s * 10))
            self.bottom_train_label = f"{t10/10:g}"
        if inter_train_interval_s is not None:
            self.inter_train_interval_s = max(0.0, float(inter_train_interval_s))
            if self.loop_pause_s is None:   # keep in sync if using default pause
                self.bottom_gap_label = f"{int(round(self.inter_train_interval_s*10))/10:g}"
        if bursts_per_train is not None: self.bursts_per_train = max(1, int(bursts_per_train))
        self.update()

    def set_annotations(self, *, top=None, mid=None, train=None, gap=None):
        if top is not None: self.top_label = str(top)
        if mid is not None: self.mid_label = str(mid)
        if train is not None: self.bottom_train_label = str(train)
        if gap is not None: self.bottom_gap_label = str(gap)
        self.update()

    def set_loop_pause(self, seconds: Optional[float] = None, margin: Optional[float] = None):
        """Set extra pause after the last train before the next loop.
        Use None to tie it to inter_train_interval_s."""
        self.loop_pause_s = None if seconds is None else max(0.0, float(seconds))
        self.countdown_margin_px = 10 if margin is None else max(0.0, float(margin))
        self.update()

    def start(self):
        if not self._running:
            self._running = True
            self._elapsed.start()
            self._timer.start()
            self.update()

    def stop(self):
        self._running = False
        self._timer.stop()
        self.update()

    def total_duration(self):
        """Duration to traverse from left to right (no final gap)."""
        if self.repeats <= 0: return 0.0
        return (self.train_duration_s + self.inter_train_interval_s) * self.repeats - self.inter_train_interval_s

    def loop_period(self):
        """Full loop period INCLUDING the final between-loops pause."""
        last_gap = self.loop_pause_s if self.loop_pause_s is not None else self.inter_train_interval_s
        return self.total_duration() + (last_gap if self.loop else 0.0)

    # ---------- Qt sizing
    def sizeHint(self): return QSize(820, 240)
    def minimumSizeHint(self): return QSize(420, 180)

    # ---------- drawing
    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), self.palette().base())

        # graph rect
        left, right, top, bottom = 30, 20, 12, 40
        R = QRectF(left, top, self.width()-left-right, self.height()-top-bottom)

        # pens
        axis = QPen(self.palette().mid().color(), 1, Qt.DashLine)
        trainPen = QPen(self.palette().text().color(), self.stroke_width, Qt.SolidLine)
        faint = QPen(self.palette().mid().color(), 1, Qt.DotLine)
        labelPen = QPen(self.palette().text().color(), 1)

        # mid dashed line + label "120"
        p.setPen(axis)
        mid_y = R.top() + R.height()*0.62
        p.drawLine(R.left(), mid_y, R.right(), mid_y)
        p.setPen(labelPen); p.drawText(R.left()-24, mid_y+4, self.mid_label)

        # geometry per train
        span_per_train = R.width() / self.repeats
        total_path = max(self.total_duration(), 0.0001)
        ratio = self.train_duration_s / (self.train_duration_s + self.inter_train_interval_s if (self.train_duration_s + self.inter_train_interval_s) else 1)
        cluster_w = span_per_train * ratio
        gap_w = span_per_train - cluster_w
        step = cluster_w / max(1, self.bursts_per_train)

        # draw pulses as hollow double-lines
        p.setPen(trainPen)
        for i in range(self.repeats):
            x0 = R.left() + i * span_per_train
            for b in range(self.bursts_per_train):
                base_x = x0 + b * step + step*0.25
                for k in range(self.pulse_line_count):
                    x = base_x + k * self.pulse_inner_gap_px
                    p.drawLine(x, R.top()+4, x, R.bottom())
            # faint end-of-block separator
            p.setPen(faint)
            p.drawLine(x0 + cluster_w + gap_w, R.top(), x0 + cluster_w + gap_w, R.bottom())
            p.setPen(trainPen)


        # timing state
        show_cursor = self._running or self._elapsed.isValid()
        t_now = self._elapsed.elapsed()/1000.0 if self._running else 0.0
        period = self.loop_period()
        t_mod = (t_now % period) if (self.loop and period > 0) else min(t_now, total_path)
        in_final_pause = self.loop and (t_mod > total_path - 1e-9)

        # green cursor (optionally hide during final pause)
        draw_cursor_now = show_cursor and not (in_final_pause and self.hide_cursor_between_loops)
        if draw_cursor_now:
            x = R.right() if in_final_pause else (R.left() + (t_mod/total_path)*R.width())
            p.setPen(QPen(self.palette().accent().color(), 3))
            p.drawLine(x, R.top(), x, R.bottom())

        # top bracket, bottom brackets, total time text
        p.setPen(labelPen)
        fm = QFontMetrics(p.font())

        def dim_bracket(x1, x2, y, text, above=True):
            tick = 7
            p.drawLine(x1, y, x2, y)
            p.drawLine(x1, y, x1, y - tick if above else y + tick)
            p.drawLine(x2, y, x2, y - tick if above else y + tick)
            w = fm.horizontalAdvance(text)
            p.drawText((x1+x2-w)/2, y - 2 if above else y + fm.ascent() + 2, text)

        dim_bracket(R.left(), R.left()+R.width()*0.18, R.top()+2, self.top_label, above=True)
        yb = R.bottom()+16
        dim_bracket(R.left(), R.left()+cluster_w, yb, self.bottom_train_label, above=False)
        dim_bracket(R.left()+cluster_w, R.left()+cluster_w+gap_w, yb, self.bottom_gap_label, above=False)
        if self.show_total_time:
            p.drawText(R.left()+R.width()/2 - 40, self.height()-10, fmt_time(total_path))

        # -------- countdown circle (between loops)
        if self.countdown_enabled and in_final_pause and period > total_path:
            pause_len = period - total_path
            remain = pause_len - (t_mod - total_path)
            remain = max(0.0, min(pause_len, remain))
            # circle position
            r = self.countdown_radius_px
            margin = self.countdown_margin_px
            if self.countdown_pos == "top_left":
                cx, cy = R.left()+margin+r, R.top()+margin+r
            elif self.countdown_pos == "bottom_right":
                cx, cy = R.right()-margin-r, R.bottom()-margin-r
            elif self.countdown_pos == "bottom_left":
                cx, cy = R.left()+margin+r, R.bottom()-margin-r
            else:  # top_right
                cx, cy = R.right()-margin-r, R.top()+margin+r

            # ring
            rect = QRectF(cx-r, cy-r, 2*r, 2*r)
            p.setPen(QPen(self.palette().mid().color(), self.countdown_ring_width))
            p.drawEllipse(rect)
            # progress arc (sweep)
            sweep = int(360 * (remain / pause_len)) if pause_len > 0 else 0
            p.setPen(QPen(self.palette().accent().color(), self.countdown_ring_width))
            # draw arc from top, clockwise negative angle
            p.drawArc(rect, 90*16, -sweep*16)

            # number
            p.setPen(self.palette().text().color())
            txt = f"{int(math.ceil(remain))}"
            tw = fm.horizontalAdvance(txt)
            th = fm.ascent()
            p.drawText(cx - tw/2, cy + th/2 - 2, txt)

        p.end()


class PulseBarsWidget(QWidget):
    """
    Left: TMSGraph. Right: live label panel + start/stop.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.graph = PulseBarsGraph(self)

        self.form = QFormLayout()
        root = QHBoxLayout(self)
        root.addWidget(self.graph, 1)

    # helpers

    def set_protocol(self, **kwargs):
        self.graph.set_protocol(**kwargs)

    def set_annotations(self, **kwargs):
        self.graph.set_annotations(**kwargs)

    def set_loop_pause(self, seconds: Optional[float] = None, margin: Optional[float] = None):
        self.graph.set_loop_pause(seconds, margin)

    def _start(self):
        self.graph.start()

    def _stop(self):
        self.graph.stop()


# ---- demo
if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = PulseBarsWidget()
    pal = app.palette()
    pal.setColor(QPalette.Base, QColor("#3c3c3c"))
    pal.setColor(QPalette.Text, QColor("#c8c8c8"))
    pal.setColor(QPalette.Mid,  QColor("#c8c8c8"))   # grid / faint lines
    pal.setColor(QPalette.Accent, QColor("#32CD32"))
    app.setPalette(pal)
    w.setWindowTitle("TMS Graph + Countdown — PySide6")
    # photo-like defaults
    w.set_protocol(repeats=3, train_duration_s=0.5, inter_train_interval_s=0.5, bursts_per_train=3)
    w.set_annotations(top="50.0", mid="120", train="19.3", gap="60")
    w.graph.hide_cursor_between_loops = True
    # pause between loops (uses inter_train_interval_s if None)
    w.set_loop_pause(seconds= 4, margin = 8)
    # optional: place the circle
    w.graph.countdown_pos = "bottom_right"      # "top_left" | "bottom_right" | "bottom_left"
    w.resize(400, 320)
    
    w.show()
    w._start()
    sys.exit(app.exec())
