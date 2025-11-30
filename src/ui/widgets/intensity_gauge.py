from __future__ import annotations
from typing import Optional
from enum import Enum

from PySide6.QtCore import Qt, QRectF, QSize, Signal, QPointF, Property, QEvent
from PySide6.QtGui import QPainter, QPen, QFont, QConicalGradient, QColor, QBrush
from PySide6.QtWidgets import QWidget

try:
    from core._Archive.protocol_manager import TMSProtocol  # type: ignore
except Exception:
    TMSProtocol = object  # type: ignore


def _luminance(c: QColor) -> float:
    return 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()


class GaugeMode(Enum):
    INTENSITY = 0       # Intensity (% of MT) behavior
    MT_PERCENT = 1      # Another MT-related % mode
    REMAINING = 2       # Remaining pulses/time display


class IntensityGauge(QWidget):
    """
    Donut gauge that can be in 3 modes:
    - INTENSITY: 'Intensity (% of MT)' style.
    - MT_PERCENT: another MT-related % mode (you provide the value).
    - REMAINING: Remaining pulses/time:
        * Top text: "remaining_pulses / total_pulses"
        * Bottom text: "remaining_time / total_time"
        * Donut fill = remaining fraction (0–100%).
    """
    valueChanged = Signal(int)

    def __init__(self, parent=None, minimum: int = 0, maximum: int = 200, step: int = 1):
        super().__init__(parent)
        self.setObjectName("IntensityGauge")

        # range/interaction
        self._min = int(minimum)
        self._max = int(maximum)
        self._val = int(minimum)
        self._step = max(1, int(step))
        self._drag_anchor_y: Optional[float] = None
        self._drag_start_val: Optional[int] = None

        # geometry
        self._start_angle_deg = 220
        self._span_total_deg = 280
        self._ring_thickness_ratio = 0.16

        # colors (theme-overridable)
        self._grad_start = QColor("#48dbfb")
        self._grad_end   = QColor("#fadb5a")
        self._text_secondary = QColor("#9aa0a6")
        self._track_override: Optional[QColor] = None

        # mode & labels
        self._mode: GaugeMode = GaugeMode.INTENSITY
        self._title_line = "INTENSITY"
        self._subtitle   = "MT%"   # default subtitle

        # REMAINING mode state
        self._rem_pulses = 0
        self._total_pulses = 0
        self._rem_time_sec = 0.0
        self._total_time_sec = 0.0

        # QSS typography knobs (smaller defaults)
        self._value_point = 0.0
        self._title_point = 0.0
        self._subtitle_point = 0.0
        self._value_scale = 0.90
        self._title_scale = 0.85
        self._subtitle_scale = 0.85
        self._value_family = ""
        self._title_family = ""
        self._subtitle_family = ""

        self.setMinimumSize(150, 150)
        self.setFocusPolicy(Qt.StrongFocus)

    # -------- Q_PROPERTIES (QSS) --------
    def getValuePointSize(self) -> float: return self._value_point
    def setValuePointSize(self, v: float) -> None: self._value_point = float(v); self.update()
    valuePointSize = Property(float, getValuePointSize, setValuePointSize)

    def getTitlePointSize(self) -> float: return self._title_point
    def setTitlePointSize(self, v: float) -> None: self._title_point = float(v); self.update()
    titlePointSize = Property(float, getTitlePointSize, setTitlePointSize)

    def getSubtitlePointSize(self) -> float: return self._subtitle_point
    def setSubtitlePointSize(self, v: float) -> None: self._subtitle_point = float(v); self.update()
    subtitlePointSize = Property(float, getSubtitlePointSize, setSubtitlePointSize)

    def getValueScale(self) -> float: return self._value_scale
    def setValueScale(self, v: float) -> None: self._value_scale = float(v); self.update()
    valueScale = Property(float, getValueScale, setValueScale)

    def getTitleScale(self) -> float: return self._title_scale
    def setTitleScale(self, v: float) -> None: self._title_scale = float(v); self.update()
    titleScale = Property(float, getTitleScale, setTitleScale)

    def getSubtitleScale(self) -> float: return self._subtitle_scale
    def setSubtitleScale(self, v: float) -> None: self._subtitle_scale = float(v); self.update()
    subtitleScale = Property(float, getSubtitleScale, setSubtitleScale)

    def getValueFamily(self) -> str: return self._value_family
    def setValueFamily(self, s: str) -> None: self._value_family = str(s); self.update()
    valueFamily = Property(str, getValueFamily, setValueFamily)

    def getTitleFamily(self) -> str: return self._title_family
    def setTitleFamily(self, s: str) -> None: self._title_family = str(s); self.update()
    titleFamily = Property(str, getTitleFamily, setTitleFamily)

    def getSubtitleFamily(self) -> str: return self._subtitle_family
    def setSubtitleFamily(self, s: str) -> None: self._subtitle_family = str(s); self.update()
    subtitleFamily = Property(str, getSubtitleFamily, setSubtitleFamily)

    def getRingThicknessRatio(self) -> float: return self._ring_thickness_ratio
    def setRingThicknessRatio(self, r: float) -> None:
        self._ring_thickness_ratio = max(0.06, min(0.35, float(r))); self.update()
    ringThicknessRatio = Property(float, getRingThicknessRatio, setRingThicknessRatio)

    # mode accessors
    def mode(self) -> GaugeMode:
        return self._mode

    def setMode(self, mode: GaugeMode) -> None:
        if isinstance(mode, GaugeMode):
            self._mode = mode
        else:
            self._mode = GaugeMode(int(mode))
        self.update()

    # -------- Theme hook --------
    def applyTheme(self, theme_manager, theme_name: str):
        """
        Pull colors from tokens. If gradient tokens are missing, derive a nice
        gradient from ACCENT_COLOR so the gauge always follows the theme.
        """
        try:
            c1 = theme_manager.get_color(theme_name, "ACCENT_GRADIENT_START", None)
            c2 = theme_manager.get_color(theme_name, "ACCENT_GRADIENT_END", None)
            acc = theme_manager.get_color(theme_name, "ACCENT_COLOR", None)
            cs = theme_manager.get_color(theme_name, "TEXT_COLOR_SECONDARY", None)
            tr = (theme_manager.get_color(theme_name, "BORDER_COLOR", None)
                  or theme_manager.get_color(theme_name, "Gray", None))

            if c1 and c2:
                self._grad_start = QColor(c1)
                self._grad_end   = QColor(c2)
            else:
                # derive from ACCENT_COLOR if provided
                if acc:
                    base = QColor(acc)
                    self._grad_start = base.lighter(130)  # brighter
                    self._grad_end   = base.lighter(170)  # even brighter

            if cs:
                self._text_secondary = QColor(cs)
            self._track_override = QColor(tr) if tr else None

            # Re-polish to ensure QSS + fonts + palette changes apply
            try:
                style = self.style()
                style.unpolish(self)
                style.polish(self)
            except Exception:
                pass

            self.update()
        except Exception:
            pass

    # -------- public config --------
    def setTitles(self, title: str, subtitle: str) -> None:
        """
        Only really used in INTENSITY / MT_PERCENT modes.
        REMAINING mode uses its own top/bottom texts.
        """
        self._title_line = str(title)
        self._subtitle = str(subtitle)
        self.update()

    # -------- Protocol helpers --------
    def setFromProtocol(self, proto: "TMSProtocol"):
        """
        Helper for INTENSITY mode: uses proto.max_intensity_percent_of_mt
        and proto.intensity_percent_of_mt.
        """
        if self._mode != GaugeMode.INTENSITY:
            return
        try:
            self.blockSignals(True)
            dyn_max = int(round(getattr(proto, "max_intensity_percent_of_mt")))
            self.setRange(0, max(1, dyn_max))
            self.setValue(int(round(getattr(proto, "intensity_percent_of_mt"))))
        except Exception:
            pass
        finally:
            self.blockSignals(False)

    def syncToProtocol(self, proto: "TMSProtocol"):
        """
        Push the current value back into the protocol in INTENSITY mode.
        MT_PERCENT/REMAINING are typically display only.
        """
        if self._mode != GaugeMode.INTENSITY:
            return
        try:
            proto.intensity_percent_of_mt = float(self._val)
        except Exception:
            pass

    # -------- REMAINING mode API --------
    def setRemainingState(
        self,
        remaining_pulses: int,
        total_pulses: int,
        remaining_seconds: float,
        total_seconds: float,
    ) -> None:
        self._rem_pulses = max(0, int(remaining_pulses))
        self._total_pulses = max(0, int(total_pulses))
        self._rem_time_sec = max(0.0, float(remaining_seconds))
        self._total_time_sec = max(0.0, float(total_seconds))

        fracs = []
        if self._total_pulses > 0:
            fracs.append(self._rem_pulses / self._total_pulses)
        if self._total_time_sec > 0:
            fracs.append(self._rem_time_sec / self._total_time_sec)

        if fracs:
            frac = max(0.0, min(1.0, min(fracs)))
        else:
            frac = 0.0

        #Don't emit valueChanged here – this is just visual animation
        old_block = self.signalsBlocked()
        self.blockSignals(True)
        self.setRange(0, 100)
        self.setValue(int(round(frac * 100)))
        self.blockSignals(old_block)

    # -------- API --------
    def value(self) -> int:
        return self._val

    def setValue(self, v: int):
        v = int(max(self._min, min(self._max, int(v))))
        if v != self._val:
            self._val = v
            if not self.signalsBlocked():
                self.valueChanged.emit(self._val)
            self.update()

    def setRange(self, minimum: int, maximum: int):
        if minimum > maximum:
            minimum, maximum = maximum, minimum
        self._min, self._max = int(minimum), int(maximum)
        clamped = int(max(self._min, min(self._max, self._val)))
        if clamped != self._val:
            old = self.signalsBlocked()
            self.blockSignals(True)
            self._val = clamped
            self.blockSignals(old)
        self.update()

    def setStep(self, step: int):
        self._step = max(1, int(step))

    # -------- Events --------
    def sizeHint(self) -> QSize:
        return QSize(220, 220)

    def minimumSizeHint(self) -> QSize:
        return QSize(150, 150)

    def changeEvent(self, ev):
        if ev.type() in (QEvent.PaletteChange, QEvent.FontChange, QEvent.StyleChange):
            self.update()
        super().changeEvent(ev)

    def _isInteractiveMode(self) -> bool:
        """Only INTENSITY and MT_PERCENT should be user-draggable."""
        return self._mode in (GaugeMode.INTENSITY, GaugeMode.MT_PERCENT)

    def wheelEvent(self, ev):
        if not self._isInteractiveMode():
            ev.ignore()
            return
        steps = ev.angleDelta().y() // 120
        if steps:
            self.setValue(self._val + steps * self._step)
        ev.accept()

    def keyPressEvent(self, ev):
        if not self._isInteractiveMode():
            ev.ignore()
            return

        k = ev.key()
        if k in (Qt.Key_Left, Qt.Key_Down):
            self.setValue(self._val - self._step); ev.accept(); return
        if k in (Qt.Key_Right, Qt.Key_Up):
            self.setValue(self._val + self._step); ev.accept(); return
        if k == Qt.Key_PageDown:
            self.setValue(self._val - 10 * self._step); ev.accept(); return
        if k == Qt.Key_PageUp:
            self.setValue(self._val + 10 * self._step); ev.accept(); return
        if k == Qt.Key_Home:
            self.setValue(self._min); ev.accept(); return
        if k == Qt.Key_End:
            self.setValue(self._max); ev.accept(); return
        super().keyPressEvent(ev)

    def mousePressEvent(self, ev):
        if not self._isInteractiveMode():
            ev.ignore()
            return
        self._drag_anchor_y = float(ev.position().y())
        self._drag_start_val = self._val
        ev.accept()

    def mouseMoveEvent(self, ev):
        if not self._isInteractiveMode():
            ev.ignore()
            return
        if self._drag_anchor_y is None or self._drag_start_val is None:
            return
        dy = self._drag_anchor_y - float(ev.position().y())
        self.setValue(self._drag_start_val + int(dy / 3) * self._step)
        ev.accept()

    def mouseReleaseEvent(self, ev):
        if not self._isInteractiveMode():
            ev.ignore()
            return
        self._drag_anchor_y = None
        self._drag_start_val = None
        ev.accept()

    # -------- helpers --------
    def _fraction(self) -> float:
        if self._max == self._min:
            return 0.0
        return max(0.0, min(1.0, (self._val - self._min) / (self._max - self._min)))

    def _trackColor(self) -> QColor:
        if self._track_override:
            c = QColor(self._track_override)
        else:
            c = self.palette().windowText().color()
            
        col = QColor(c)
        return col

    @staticmethod
    def _format_time(seconds: float) -> str:
        total = max(0, int(round(seconds)))
        h = total // 3600
        m = (total % 3600) // 60
        s = total % 60
        if h > 0:
            return f"{h:d}:{m:02d}:{s:02d}"
        else:
            return f"{m:d}:{s:02d}"

    # -------- Paint --------
    def paintEvent(self, _):
        pal = self.palette()
        bg = pal.window().color()
        text = pal.windowText().color()

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), bg)

        s = min(self.width(), self.height())
        cx, cy = self.width() / 2.0, self.height() / 2.0
        radius = s * 0.42
        ring_w = max(8.0, s * self._ring_thickness_ratio)
        rect = QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius)

        # track
        pen_bg = QPen(self._trackColor())
        pen_bg.setWidthF(ring_w)
        pen_bg.setCapStyle(Qt.FlatCap)
        p.setPen(pen_bg)
        p.drawArc(rect, int((90 - self._start_angle_deg) * 16), int(-self._span_total_deg * 16))

        # value arc with gradient
        frac = self._fraction()
        if frac > 0.0:
            grad = QConicalGradient(QPointF(cx, cy), -self._start_angle_deg)
            grad.setColorAt(0.00, self._grad_start)
            grad.setColorAt(0.60, self._grad_start)
            grad.setColorAt(1.00, self._grad_end)
            pen_val = QPen(QBrush(grad), ring_w)
            pen_val.setCapStyle(Qt.FlatCap)
            p.setPen(pen_val)
            span = self._span_total_deg * frac
            p.drawArc(rect, int((90 - self._start_angle_deg) * 16), int(-span * 16))

        # inner donut
        inner_r = radius - ring_w * 0.9
        inner = QRectF(cx - inner_r, cy - inner_r, 2 * inner_r, 2 * inner_r)
        p.setPen(Qt.NoPen)
        inner_col = bg.darker(108) if _luminance(bg) > 0.5 else bg.lighter(115)
        p.setBrush(inner_col)
        p.drawEllipse(inner)

        # center value text (percentage) – NOT in REMAINING mode
        if self._mode != GaugeMode.REMAINING:
            p.setPen(text)
            f_big = QFont(self.font())
            if self._value_family:
                f_big.setFamily(self._value_family)
            auto_val_pt = max(10.0, s * 0.13 * self._value_scale)
            val_pt = self._value_point if self._value_point > 0.0 else auto_val_pt
            f_big.setBold(True)
            f_big.setPointSizeF(val_pt)
            p.setFont(f_big)
            p.drawText(self.rect(), Qt.AlignCenter, f"{self._val}%")

        # text around center
        if self._mode == GaugeMode.REMAINING:
            # Use darker / primary text color
            p.setPen(text)

            # Top: pulses (ratio only, moved up & bigger)
            f_mid = QFont(self.font())
            if self._title_family:
                f_mid.setFamily(self._title_family)
            # bigger scaling for remaining mode
            auto_title_pt = max(10.0, s * 0.05)  # was ~0.045
            title_pt = self._title_point if self._title_point > 0.0 else auto_title_pt
            f_mid.setBold(True)
            f_mid.setPointSizeF(title_pt)
            p.setFont(f_mid)

            if self._total_pulses > 0:
                pulses_str = f"{self._rem_pulses} / {self._total_pulses}"
            else:
                pulses_str = f"{self._rem_pulses}"

            p.drawText(0, int(cy - s * 0.14), self.width(), 30, Qt.AlignHCenter, pulses_str)

            # Bottom: time (ratio only, moved up & bigger)
            f_sub = QFont(self.font())
            if self._subtitle_family:
                f_sub.setFamily(self._subtitle_family)
            auto_sub_pt = max(9.0, s * 0.05)  # was ~0.036
            sub_pt = self._subtitle_point if self._subtitle_point > 0.0 else auto_sub_pt
            f_sub.setPointSizeF(sub_pt)
            p.setFont(f_sub)

            if self._total_time_sec > 0:
                rem_t = self._format_time(self._rem_time_sec)
                tot_t = self._format_time(self._total_time_sec)
                time_str = f"{rem_t} / {tot_t}"
            else:
                time_str = self._format_time(self._rem_time_sec)

            p.drawText(0, int(cy + s * 0.02), self.width(), 26, Qt.AlignHCenter, time_str)

        else:
            # INTENSITY / MT_PERCENT: original title/subtitle style using secondary text color
            p.setPen(self._text_secondary)

            f_mid = QFont(self.font())
            if self._title_family:
                f_mid.setFamily(self._title_family)
            auto_title_pt = max(8.0, s * 0.045 * self._title_scale)
            title_pt = self._title_point if self._title_point > 0.0 else auto_title_pt
            f_mid.setBold(True)
            f_mid.setPointSizeF(title_pt)
            p.setFont(f_mid)
            p.drawText(0, int(cy + s * 0.10), self.width(), 22, Qt.AlignHCenter, self._title_line)

            f_sub = QFont(self.font())
            if self._subtitle_family:
                f_sub.setFamily(self._subtitle_family)
            auto_sub_pt = max(7.0, s * 0.036 * self._subtitle_scale)
            sub_pt = self._subtitle_point if self._subtitle_point > 0.0 else auto_sub_pt
            f_sub.setPointSizeF(sub_pt)
            p.setFont(f_sub)
            #p.drawText(0, int(cy + s * 0.17), self.width(), 20, Qt.AlignHCenter, self._subtitle)

        p.end()


# tiny tester
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QHBoxLayout
    app = QApplication(sys.argv)
    w = QWidget()
    lay = QVBoxLayout(w)
    g = IntensityGauge(maximum=180)

    # quick mode toggles for testing
    btn_row = QHBoxLayout()
    b1 = QPushButton("INTENSITY")
    b2 = QPushButton("MT%")
    b3 = QPushButton("REMAINING")

    def to_intensity():
        g.setMode(GaugeMode.INTENSITY)
        g.setTitles("INTENSITY", "MT%")
        g.setRange(0, 180)
        g.setValue(90)

    def to_mt():
        g.setMode(GaugeMode.MT_PERCENT)
        g.setTitles("MT%", "PERCENT")
        g.setRange(0, 150)
        g.setValue(80)

    def to_remaining():
        g.setMode(GaugeMode.REMAINING)
        g.setRemainingState(
            remaining_pulses=600,
            total_pulses=1000,
            remaining_seconds=300,
            total_seconds=600,
        )

    b1.clicked.connect(to_intensity)
    b2.clicked.connect(to_mt)
    b3.clicked.connect(to_remaining)
    for b in (b1, b2, b3):
        btn_row.addWidget(b)

    lay.addLayout(btn_row)
    lay.addWidget(g)
    w.resize(360, 420)
    w.show()
    sys.exit(app.exec())
