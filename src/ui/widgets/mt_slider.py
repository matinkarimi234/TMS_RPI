# mt_slider.py
from __future__ import annotations
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QLabel, QSlider, QHBoxLayout, QVBoxLayout, QSizePolicy
from PySide6.QtGui import QPalette, QColor

try:
    from core.protocol_manager import TMSProtocol  # type: ignore
except Exception:
    TMSProtocol = object  # type: ignore


class MTSlider(QWidget):
    """
    Motor Threshold slider.

    - Visuals come from QSS (uses #mtSlider selectors with theme tokens).
    - Programmatic updates are silent (no valueChanged) to avoid loops.
    - applyTheme() also sets a local palette so palette() roles are sane even
      if you choose to use palette() in your QSS later.
    """
    valueChanged = Signal(int)

    def __init__(self, parent=None, minimum: int = 1, maximum: int = 100, value: int = 50):
        super().__init__(parent)
        self._min, self._max = int(minimum), int(maximum)

        self.lbl_left  = QLabel("% MT")
        self.lbl_right = QLabel("")
        self.lbl_right.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setObjectName("mtSlider")  # important for QSS
        self.setObjectName("MTSlider")
        self.lbl_left.setObjectName("mtSliderLeft")
        self.lbl_right.setObjectName("mtSliderValue")

        self.slider.setRange(self._min, self._max)
        self.slider.setValue(max(self._min, min(self._max, int(value))))
        self.slider.valueChanged.connect(self._on_slider)
        self.slider.setToolTip(f"Range: {self._min} – {self._max}")

        # No inline stylesheet here — QSS controls visuals using tokens.

        top = QHBoxLayout()
        top.addWidget(self.lbl_left)
        top.addStretch(1)
        top.addWidget(self.lbl_right)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.slider)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self._sync_label()

    # --- Theme hook
    def applyTheme(self, theme_manager, theme_name: str):
        """Set a local palette, and re-polish so QSS re-applies."""
        try:
            sec = theme_manager.get_color(theme_name, "TEXT_COLOR_SECONDARY", None)
            if sec:
                self.lbl_left.setStyleSheet(f"color: {sec};")

            pal = QPalette(self.palette())
            bg   = theme_manager.get_color(theme_name, "BACKGROUND_COLOR", None)
            txt  = theme_manager.get_color(theme_name, "TEXT_COLOR", None)
            acc  = theme_manager.get_color(theme_name, "ACCENT_COLOR", None)
            midl = theme_manager.get_color(theme_name, "BORDER_COLOR", None)

            if bg:   pal.setColor(QPalette.Window, QColor(bg))
            if txt:  pal.setColor(QPalette.WindowText, QColor(txt))
            if txt:  pal.setColor(QPalette.Text, QColor(txt))
            if acc:  pal.setColor(QPalette.Highlight, QColor(acc))
            if midl: pal.setColor(QPalette.Midlight, QColor(midl))
            if bg:   pal.setColor(QPalette.Button, QColor(bg))
            if txt:  pal.setColor(QPalette.ButtonText, QColor(txt))

            self.setPalette(pal)
            self.slider.setPalette(pal)

            # Re-polish so QSS (with tokens) is reapplied immediately
            for w in (self, self.slider, self.lbl_left, self.lbl_right):
                try:
                    style = w.style()
                    style.unpolish(w)
                    style.polish(w)
                except Exception:
                    pass
            self.update()
        except Exception:
            pass

    # --- Protocol helpers
    def setFromProtocol(self, proto: "TMSProtocol"):
        try:
            self.blockSignals(True); self.slider.blockSignals(True)
            self.setRange(int(getattr(proto, "MIN_MT_PERCENT", 1)),
                          int(getattr(proto, "MAX_MT_PERCENT", 100)))
            self.setValue(int(round(getattr(proto, "subject_mt_percent"))))
        except Exception:
            pass
        finally:
            self.slider.blockSignals(False); self.blockSignals(False)

    def syncToProtocol(self, proto: "TMSProtocol"):
        try:
            proto.subject_mt_percent = float(self.value())
        except Exception:
            pass

    # --- API
    def value(self) -> int:
        return self.slider.value()

    def setValue(self, v: int):
        new_v = int(max(self._min, min(self._max, int(v))))
        if new_v != self.slider.value():
            self.slider.blockSignals(True)
            self.slider.setValue(new_v)
            self.slider.blockSignals(False)
        self._sync_label()

    def setRange(self, minimum: int, maximum: int):
        self._min, self._max = int(minimum), int(maximum)
        self.slider.blockSignals(True)
        self.slider.setRange(self._min, self._max)
        self.slider.blockSignals(False)
        self.slider.setToolTip(f"Range: {self._min} – {self._max}")
        self._sync_label()

    # --- internals
    def _sync_label(self):
        self.lbl_right.setText(str(int(self.slider.value())))

    def _on_slider(self, v: int):
        self._sync_label()
        if self.signalsBlocked():
            return
        self.valueChanged.emit(int(v))


# tiny tester
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
    app = QApplication(sys.argv)
    w = QWidget()
    lay = QVBoxLayout(w)
    s = MTSlider(value=60)
    lay.addWidget(s)
    w.resize(360, 120)
    w.show()
    sys.exit(app.exec())
