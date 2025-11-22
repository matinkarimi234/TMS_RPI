# ui/helpers/gpio_guard.py

from __future__ import annotations  # optional but nice to have

from typing import Callable, Any, Optional
from PySide6.QtCore import QObject, QTimer


class GpioEventGuard(QObject):
    """
    Simple helper to debounce / temporarily block GPIO-driven events.

    Usage:
        guard = GpioEventGuard(block_ms=250, parent=self)
        gb.startPausePressed.connect(guard.wrap(self._on_session_start_requested))

        # later, after MT Apply:
        guard.block()  # ignores wrapped slots for ~block_ms ms
    """

    def __init__(self, block_ms: int = 250, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._enabled: bool = True
        self._default_block_ms: int = block_ms

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._rearm)

    def block(self, ms: Optional[int] = None) -> None:
        """Temporarily ignore wrapped GPIO events for `ms` milliseconds."""
        self._enabled = False
        duration = self._default_block_ms if ms is None else ms
        if self._timer.isActive():
            self._timer.stop()
        self._timer.start(duration)

    def _rearm(self) -> None:
        """Re-enable wrapped GPIO events."""
        self._enabled = True

    def wrap(self, slot: Callable[..., Any]) -> Callable[..., Any]:
        """
        Return a new callable that:
          - ignores calls while guard is disabled
          - otherwise forwards to `slot`.
        """

        def guarded(*args: Any, **kwargs: Any) -> Any:
            if not self._enabled:
                return None
            return slot(*args, **kwargs)

        return guarded
