from enum import Enum


class SessionState(Enum):
    IDLE = 0
    RUNNING = 1
    PAUSED = 2
    MT_EDIT = 3
    PROTOCOL_EDIT = 4