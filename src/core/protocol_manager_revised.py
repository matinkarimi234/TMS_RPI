"""
This module defines the TMSProtocol class, which encapsulates all parameters
and safety constraints for a transcranial magnetic stimulation session.

Key Revision (v7 - UI Blocking Version):
- No automatic correction of IPI or burst pulses is performed.
- Only the frequency spinbox in the UI will be dynamically bounded according
  to the physical constraint: (burst_pulses_count - 1) * IPI <= 1000 / frequency.
- IPI is only limited by absolute hardware constraints (10–1000 ms).
- Burst pulse count is never dynamically restricted.
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Any, ClassVar

# ---------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------

def clamp(value: float, min_value: float, max_value: float) -> float:
    """Clamp a value into a specified interval."""
    return max(min_value, min(value, max_value))


# ---------------------------------------------------------------------
# Protocol Class Definition
# ---------------------------------------------------------------------

@dataclass
class TMSProtocol:
    # --- Protocol Identification ---
    name: str
    target_region: str
    description: str | None = None

    # --- Subject-Specific Parameters ---
    subject_mt_percent_init: int = 50  # Motor Threshold as a % of MSO

    # --- Intensity Parameters ---
    intensity_percent_of_mt_init: int = 100  # Stimulation intensity relative to MT

    # --- Core Stimulation Parameters ---
    frequency_hz_init: float = 10.0
    pulses_per_train: int = 50
    train_count: int = 10
    inter_train_interval_s: float = 20.0

    # --- Burst Mode Parameters ---
    waveform: str = "biphasic"  # "biphasic" or "biphasic_burst"
    burst_pulses_count_init: int = 3   # pulses per burst
    inter_pulse_interval_ms_init: float = 20.0  # ms

    # --- Ramp-up Parameters ---
    ramp_fraction: float = 1.0
    ramp_steps: int = 1

    # --- Internal Fields ---
    _subject_mt_percent: int = field(init=False, repr=False)
    _intensity_percent_of_mt: int = field(init=False, repr=False)
    _frequency_hz: float = field(init=False, repr=False)
    _inter_pulse_interval_ms: float = field(init=False, repr=False)
    _burst_pulses_count: int = field(init=False, repr=False)

    # --- Class Constants ---
    SUBJECT_MT_MIN: int = 0
    SUBJECT_MT_MAX: int = 100
    INTENSITY_OF_MT_MIN: int = 1
    INTENSITY_OF_MT_MAX: int = 200
    INTENSITY_ABS_MAX: int = 100  # %MSO absolute max
    FREQ_MIN: float = 0.1
    FREQ_MAX: float = 100.0
    IPI_MIN_HARD: float = 10.0   # ms
    IPI_MAX_HARD: float = 1000.0 # ms
    BURST_PULSES_ALLOWED: ClassVar[List[int]] = [1, 2, 3, 4, 5]

    # -----------------------------------------------------------------
    # Initialization
    # -----------------------------------------------------------------

    def __post_init__(self):
        """Atomic initializer that ensures consistent, valid state."""
        # Independent parameters
        self._subject_mt_percent = clamp(
            self.subject_mt_percent_init, self.SUBJECT_MT_MIN, self.SUBJECT_MT_MAX
        )
        max_intensity = self._max_intensity_for_current_mt()
        self._intensity_percent_of_mt = clamp(
            self.intensity_percent_of_mt_init,
            self.INTENSITY_OF_MT_MIN,
            max_intensity,
        )

        # Core TMS timing parameters
        self._burst_pulses_count = self._snap_to_allowed(
            self.burst_pulses_count_init, self.BURST_PULSES_ALLOWED
        )
        self._inter_pulse_interval_ms = clamp(
            self.inter_pulse_interval_ms_init, self.IPI_MIN_HARD, self.IPI_MAX_HARD
        )
        self._frequency_hz = clamp(self.frequency_hz_init, self.FREQ_MIN, self.FREQ_MAX)

        # No automatic correction; rely on UI dynamic bounds
        self._frequency_hz = clamp(
            min(self._frequency_hz, self._calculate_max_frequency_hz()),
            self.FREQ_MIN, self.FREQ_MAX
        )

    # -----------------------------------------------------------------
    # Constraint Math Helpers
    # -----------------------------------------------------------------

    def _calculate_max_frequency_hz(self) -> float:
        """Return the maximum allowed frequency based on current burst/IPI."""
        if self._burst_pulses_count <= 1:
            return self.FREQ_MAX
        burst_len_ms = self._inter_pulse_interval_ms * (self._burst_pulses_count)
        if burst_len_ms <= 0:
            return self.FREQ_MIN
        max_freq = round(1000.0 / burst_len_ms, 1)
        return clamp(max_freq, self.FREQ_MIN, self.FREQ_MAX)

    def _calculate_min_frequency_hz(self) -> float:
        """Minimum frequency; typically the global device lower bound."""
        return self.FREQ_MIN

    def _snap_to_allowed(self, value: int, allowed: List[int]) -> int:
        """Snap to nearest allowed burst pulse count."""
        return min(allowed, key=lambda x: abs(x - value))

    def _max_intensity_for_current_mt(self) -> int:
        """Maximum allowed stimulation intensity given subject MT."""
        if self._subject_mt_percent == 0:
            return self.INTENSITY_OF_MT_MIN
        return min(
            self.INTENSITY_OF_MT_MAX,
            (self.INTENSITY_ABS_MAX * 100) // self._subject_mt_percent,
        )

    def is_valid(self) -> bool:
        """Validate timing parameters against the physics constraint."""
        if self._burst_pulses_count <= 1:
            return True
        val = (self._inter_pulse_interval_ms * (self._burst_pulses_count - 1)) * self._frequency_hz / 1000.0
        return val <= 1.0 + 1e-12
    def get_absolute_intensity(self) -> float:
        return (self._subject_mt_percent * self._intensity_percent_of_mt) / 100

    # -----------------------------------------------------------------
    # Properties
    # -----------------------------------------------------------------

    @property
    def subject_mt_percent(self) -> int:
        return self._subject_mt_percent

    @subject_mt_percent.setter
    def subject_mt_percent(self, value: int):
        self._subject_mt_percent = clamp(value, self.SUBJECT_MT_MIN, self.SUBJECT_MT_MAX)
        self._intensity_percent_of_mt = clamp(
            self._intensity_percent_of_mt,
            self.INTENSITY_OF_MT_MIN,
            self._max_intensity_for_current_mt(),
        )

    @property
    def intensity_percent_of_mt(self) -> int:
        return self._intensity_percent_of_mt

    @intensity_percent_of_mt.setter
    def intensity_percent_of_mt(self, value: int):
        self._intensity_percent_of_mt = clamp(
            value,
            self.INTENSITY_OF_MT_MIN,
            self._max_intensity_for_current_mt(),
        )

    @property
    def frequency_hz(self) -> float:
        return self._frequency_hz

    @frequency_hz.setter
    def frequency_hz(self, value: float):
        """Only allow frequency within dynamic valid range."""
        freq_min = self._calculate_min_frequency_hz()
        freq_max = self._calculate_max_frequency_hz()
        self._frequency_hz = clamp(value, freq_min, freq_max)

    @property
    def inter_pulse_interval_ms(self) -> float:
        """Free user choice, only hard limited 10–1000 ms."""
        return self._inter_pulse_interval_ms

    @inter_pulse_interval_ms.setter
    def inter_pulse_interval_ms(self, value: float):
        self._inter_pulse_interval_ms = clamp(value, self.IPI_MIN_HARD, self.IPI_MAX_HARD)

    @property
    def burst_pulses_count(self) -> int:
        """Free user choice among allowed integers."""
        return self._burst_pulses_count
    
    @property
    def total_duration_s(self) -> float:
        """
        Estimated total protocol duration (in seconds).
        Includes all trains and inter-train intervals.

        Formula:
            duration = (pulses_per_train / frequency_hz) * train_count
                     + inter_train_interval_s * (train_count - 1)
        """
        if self._frequency_hz <= 0.0:
            return 0.0

        train_duration = self.pulses_per_train / self._frequency_hz
        total = (train_duration * self.train_count)

        if self.train_count > 1:
            total += self.inter_train_interval_s * (self.train_count - 1)

        return total

    @burst_pulses_count.setter
    def burst_pulses_count(self, value: int):
        self._burst_pulses_count = self._snap_to_allowed(value, self.BURST_PULSES_ALLOWED)

    # -----------------------------------------------------------------
    # Serialization Helpers
    # -----------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TMSProtocol:
        return cls(**data)


# ---------------------------------------------------------------------
# Protocol Manager for managing multiple protocol objects
# ---------------------------------------------------------------------

@dataclass
class ProtocolManager:
    protocols: Dict[str, TMSProtocol] = field(default_factory=dict)

    def add_protocol(self, protocol: TMSProtocol):
        self.protocols[protocol.name] = protocol

    def get_protocol(self, name: str) -> TMSProtocol | None:
        return self.protocols.get(name)

    def list_protocols(self) -> List[str]:
        return list(self.protocols.keys())

    # ---------------- I/O ------------------

    def save_to_json(self, filepath: Path | str):
        data = {name: p.to_dict() for name, p in self.protocols.items()}
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)

    def load_from_json(self, filepath: Path | str):
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if isinstance(data, dict):
            self.protocols = {
                name: TMSProtocol.from_dict(pdata) for name, pdata in data.items()
            }
        elif isinstance(data, list):
            # Legacy format conversion
            print("Converting legacy list-based protocol file to dictionary format.")
            self.protocols = {
                pdata["name"]: TMSProtocol.from_dict(pdata) for pdata in data
            }
        else:
            raise TypeError(
                f"Unsupported file format: expected dict or list, got {type(data).__name__}"
            )
