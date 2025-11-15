from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import ClassVar, Optional, List, Tuple
import json

@dataclass
class TMSProtocol:
    # ——— 1) Init‐args without defaults — must come first ———
    name: str
    subject_mt_percent: float
    intensity_percent_of_mt: float
    frequency_hz: float
    pulses_per_train: int
    train_count: int
    inter_train_interval_s: float
    target_region: str

    # ——— 2) Init‐args with defaults — now you can safely list these ———
    description: Optional[str]            = None
    _absolute_output_init: Optional[float] = None

    # NEW: ramp parameters
    ramp_fraction: float                  = 1.0   # 0.7 … 1.0
    ramp_steps: int                       = 1     # 1 … 10

    mode: str                              = "rTMS"      # "rTMS" or "cTBS"

    # Waveform is also meta: biphasic vs biphasic burst
    waveform: str                          = "biphasic"  # "biphasic" or "biphasic burst"

    # Burst definition:
    # if burst_pulses == 1 -> standard rTMS (no burst structure)
    burst_pulses: int                      = 1           # pulses within a burst
    intra_burst_frequency_hz: float        = 50.0        # Hz of pulses inside a burst
    burst_interval_s: float                = 0.2         # onset-to-onset interval between bursts (~5 Hz)

    # ——— 3) Device bounds — annotate as ClassVar so dataclass skips them ———
    MIN_MT_PERCENT: ClassVar[float]                      = 1.0
    MAX_MT_PERCENT: ClassVar[float]                      = 100.0

    MIN_RELATIVE_INTENSITY_PERCENT: ClassVar[float]      = 10.0
    MAX_RELATIVE_INTENSITY_PERCENT_STATIC: ClassVar[float] = 200.0

    MIN_ABSOLUTE_OUTPUT_PERCENT: ClassVar[float]          = 0.0
    MAX_ABSOLUTE_OUTPUT_PERCENT: ClassVar[float]          = 100.0

    MIN_FREQUENCY_HZ: ClassVar[float]                    = 1.0
    MAX_FREQUENCY_HZ: ClassVar[float]                    = 100.0

    MIN_PULSES_PER_TRAIN: ClassVar[int]                  = 1
    MAX_PULSES_PER_TRAIN: ClassVar[int]                  = 10000

    MIN_TRAIN_COUNT: ClassVar[int]                       = 1
    MAX_TRAIN_COUNT: ClassVar[int]                       = 10000

    MIN_INTER_TRAIN_INTERVAL_S: ClassVar[float]          = 0.0
    MAX_INTER_TRAIN_INTERVAL_S: ClassVar[float]          = 3600.0

    MIN_RAMP_FRACTION: ClassVar[float]                   = 0.7
    MAX_RAMP_FRACTION: ClassVar[float]                   = 1.0

    MIN_RAMP_STEPS: ClassVar[int]                        = 1
    MAX_RAMP_STEPS: ClassVar[int]                        = 10

    MIN_BURST_PULSES: ClassVar[int]               = 1
    MAX_BURST_PULSES: ClassVar[int]               = 5

    MIN_INTRA_BURST_FREQUENCY_HZ: ClassVar[float] = 1.0
    MAX_INTRA_BURST_FREQUENCY_HZ: ClassVar[float] = 200.0

    MIN_BURST_INTERVAL_S: ClassVar[float]         = 0.0
    MAX_BURST_INTERVAL_S: ClassVar[float]         = 10.0

    # ——— 4) Private backing fields ———
    _subject_mt_percent: float          = field(init=False, repr=False)
    _intensity_percent_of_mt: float     = field(init=False, repr=False)
    _frequency_hz: float                = field(init=False, repr=False)
    _pulses_per_train: int              = field(init=False, repr=False)
    _train_count: int                   = field(init=False, repr=False)
    _inter_train_interval_s: float      = field(init=False, repr=False)
    _absolute_output_percent: float     = field(init=False, repr=False)
    _target_region: str                 = field(init=False, repr=False)
    _description: Optional[str]         = field(init=False, repr=False)
    _ramp_fraction: float               = field(init=False, repr=False)
    _ramp_steps: int                    = field(init=False, repr=False)
    _mode: str                          = field(init=False, repr=False)
    _waveform: str                      = field(init=False, repr=False)
    _burst_pulses: int                  = field(init=False, repr=False)
    _intra_burst_frequency_hz: float    = field(init=False, repr=False)
    _burst_interval_s: float            = field(init=False, repr=False)

    def __post_init__(self):
        # funnel constructor args through setters
        self.subject_mt_percent      = self.subject_mt_percent
        self.description             = self.description
        self.target_region           = self.target_region

        # absolute vs. relative linkage
        if self._absolute_output_init is not None:
            self.absolute_output_percent = self._absolute_output_init
        else:
            self.intensity_percent_of_mt = self.intensity_percent_of_mt

        self.frequency_hz             = self.frequency_hz
        self.pulses_per_train         = self.pulses_per_train
        self.train_count              = self.train_count
        self.inter_train_interval_s   = self.inter_train_interval_s

        # new ramp args
        self.ramp_fraction            = self.ramp_fraction
        self.ramp_steps               = self.ramp_steps

    # ——— Helper: simple clamp ———
    def _clamp(self, val: float | int, lo: float | int, hi: float | int) -> float | int:
        """Return val clamped to [lo, hi]."""
        return lo if val < lo else hi if val > hi else val

    # ——— subject_mt_percent ———
    @property
    def subject_mt_percent(self) -> float:
        return self._subject_mt_percent

    @subject_mt_percent.setter
    def subject_mt_percent(self, val: float):
        v = self._clamp(val, self.MIN_MT_PERCENT, self.MAX_MT_PERCENT)
        self._subject_mt_percent = v
        # if intensity is already set, clamp it into its new dynamic range
        if hasattr(self, "_intensity_percent_of_mt"):
            self._intensity_percent_of_mt = self._clamp(
                self._intensity_percent_of_mt,
                self.MIN_RELATIVE_INTENSITY_PERCENT,
                self.max_intensity_percent_of_mt
            )
            # update absolute too
            self._absolute_output_percent = (v * self._intensity_percent_of_mt) / 100.0

    # ——— intensity_percent_of_mt ———
    @property
    def intensity_percent_of_mt(self) -> float:
        return self._intensity_percent_of_mt

    @intensity_percent_of_mt.setter
    def intensity_percent_of_mt(self, val: float):
        min_r = self.MIN_RELATIVE_INTENSITY_PERCENT
        max_r = self.max_intensity_percent_of_mt
        v = self._clamp(val, min_r, max_r)
        self._intensity_percent_of_mt = v
        # update absolute
        self._absolute_output_percent = (self._subject_mt_percent * v) / 100.0

    @property
    def max_intensity_percent_of_mt(self) -> float:
        dyn = 100.0 * 100.0 / self._subject_mt_percent
        return min(self.MAX_RELATIVE_INTENSITY_PERCENT_STATIC, dyn)

    # ——— absolute_output_percent ———
    @property
    def absolute_output_percent(self) -> float:
        return self._absolute_output_percent

    @absolute_output_percent.setter
    def absolute_output_percent(self, val: float):
        # clamp to hardware range first
        v_abs = self._clamp(val, self.MIN_ABSOLUTE_OUTPUT_PERCENT, self.MAX_ABSOLUTE_OUTPUT_PERCENT)
        # then ensure it doesn't force relative above its max
        max_allowed_abs = (self._subject_mt_percent * self.max_intensity_percent_of_mt) / 100.0
        v_abs = self._clamp(v_abs, self.MIN_ABSOLUTE_OUTPUT_PERCENT, max_allowed_abs)
        self._absolute_output_percent = v_abs
        # mirror back into intensity
        self._intensity_percent_of_mt = (v_abs / self._subject_mt_percent) * 100.0

    # ——— frequency_hz ———
    @property
    def frequency_hz(self) -> float:
        return self._frequency_hz

    @frequency_hz.setter
    def frequency_hz(self, val: float):
        v = self._clamp(val, self.MIN_FREQUENCY_HZ, self.MAX_FREQUENCY_HZ)
        self._frequency_hz = v

    # ——— pulses_per_train ———
    @property
    def pulses_per_train(self) -> int:
        return self._pulses_per_train

    @pulses_per_train.setter
    def pulses_per_train(self, val: int):
        v = int(self._clamp(val, self.MIN_PULSES_PER_TRAIN, self.MAX_PULSES_PER_TRAIN))
        self._pulses_per_train = v

    # ——— train_count ———
    @property
    def train_count(self) -> int:
        return self._train_count

    @train_count.setter
    def train_count(self, val: int):
        v = int(self._clamp(val, self.MIN_TRAIN_COUNT, self.MAX_TRAIN_COUNT))
        self._train_count = v

    # ——— inter_train_interval_s ———
    @property
    def inter_train_interval_s(self) -> float:
        return self._inter_train_interval_s

    @inter_train_interval_s.setter
    def inter_train_interval_s(self, val: float):
        v = self._clamp(val, self.MIN_INTER_TRAIN_INTERVAL_S, self.MAX_INTER_TRAIN_INTERVAL_S)
        self._inter_train_interval_s = v

    # ——— target_region ———
    @property
    def target_region(self) -> str:
        return self._target_region

    @target_region.setter
    def target_region(self, val: str):
        self._target_region = str(val)

    # ——— description ———
    @property
    def description(self) -> Optional[str]:
        return self._description

    @description.setter
    def description(self, val: Optional[str]):
        self._description = None if val is None else str(val)

    # ——— Summary metrics ———
    def total_pulses(self) -> int:
        return self.pulses_per_train * self.train_count

    def total_duration_s(self) -> float:
        """
        Total duration in seconds.

        - For plain rTMS (burst_pulses == 1) this is:
            pulses_per_train / frequency_hz  per train
        - For burst modes (e.g. cTBS) we use:
            pulses are grouped into bursts of 'burst_pulses',
            repeated every 'burst_interval_s' seconds, with internal
            spacing 1 / intra_burst_frequency_hz.
        """
        if self.burst_pulses <= 1:
            # classic rTMS: evenly spaced pulses
            stim_per_train = self.pulses_per_train / self.frequency_hz
        else:
            # burst mode: total pulses per train is fixed
            bursts_per_train = max(self.pulses_per_train // self.burst_pulses, 1)

            # duration of a single burst (from first to last pulse)
            burst_duration = 0.0
            if self.intra_burst_frequency_hz > 0.0 and self.burst_pulses > 1:
                burst_duration = (self.burst_pulses - 1) / self.intra_burst_frequency_hz

            if bursts_per_train == 1:
                stim_per_train = burst_duration
            else:
                # start of first burst at t=0, last pulse of final burst at:
                # (bursts_per_train - 1) * burst_interval_s + burst_duration
                stim_per_train = (bursts_per_train - 1) * self.burst_interval_s + burst_duration

        total_stim = stim_per_train * self.train_count
        total_rest = self.inter_train_interval_s * max(self.train_count - 1, 0)
        return total_stim + total_rest

    # ——— NEW: ramp properties & helper ———
    @property
    def ramp_fraction(self) -> float:
        return self._ramp_fraction

    @ramp_fraction.setter
    def ramp_fraction(self, val: float):
        v = self._clamp(val, self.MIN_RAMP_FRACTION, self.MAX_RAMP_FRACTION)
        self._ramp_fraction = v

    @property
    def ramp_steps(self) -> int:
        return self._ramp_steps
    
    # ——— mode / waveform ———
    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, val: str):
        allowed = ("rTMS", "cTBS")
        self._mode = val if val in allowed else "rTMS"

    @property
    def waveform(self) -> str:
        return self._waveform

    @waveform.setter
    def waveform(self, val: str):
        # small normalisation for spelling variants
        if val == "biphasic_burst":
            val = "biphasic burst"
        allowed = ("biphasic", "biphasic burst")
        self._waveform = val if val in allowed else "biphasic"

    # ——— burst parameters ———
    @property
    def burst_pulses(self) -> int:
        return self._burst_pulses

    @burst_pulses.setter
    def burst_pulses(self, val: int):
        v = int(self._clamp(val, self.MIN_BURST_PULSES, self.MAX_BURST_PULSES))
        self._burst_pulses = v

    @property
    def intra_burst_frequency_hz(self) -> float:
        return self._intra_burst_frequency_hz

    @intra_burst_frequency_hz.setter
    def intra_burst_frequency_hz(self, val: float):
        v = self._clamp(
            val,
            self.MIN_INTRA_BURST_FREQUENCY_HZ,
            self.MAX_INTRA_BURST_FREQUENCY_HZ
        )
        self._intra_burst_frequency_hz = v

    @property
    def burst_interval_s(self) -> float:
        return self._burst_interval_s

    @burst_interval_s.setter
    def burst_interval_s(self, val: float):
        v = self._clamp(
            val,
            self.MIN_BURST_INTERVAL_S,
            self.MAX_BURST_INTERVAL_S
        )
        self._burst_interval_s = v

    @ramp_steps.setter
    def ramp_steps(self, val: int):
        v = int(self._clamp(val, self.MIN_RAMP_STEPS, self.MAX_RAMP_STEPS))
        self._ramp_steps = v

    def compute_ramp_curve_bytes(self) -> Tuple[int, int]:
        """
        Returns the two data-bytes for the 171-118 packet:

        hi = floor(((factor - 1) * 10000) / 100)
        lo = ((factor - 1) * 10000) % 100

        where factor = (1 / ramp_fraction) ** (1 / ramp_steps).
        """
        factor = pow(1.0 / self._ramp_fraction, 1.0 / self._ramp_steps)
        flat   = int((factor - 1.0) * 10000)
        return (flat // 100, flat % 100)



@dataclass
class ProtocolManager:
    """Holds, JSON-loads/saves, and queries many TMSProtocol instances."""
    protocols: List[TMSProtocol] = field(default_factory=list)

    def add_protocol(self, p: TMSProtocol) -> None:
        # replace same‐name if present
        self.protocols = [x for x in self.protocols if x.name != p.name]
        self.protocols.append(p)

    def remove_protocol(self, name: str) -> bool:
        old = len(self.protocols)
        self.protocols = [x for x in self.protocols if x.name != name]
        return len(self.protocols) < old

    def get_protocol(self, name: str) -> Optional[TMSProtocol]:
        for x in self.protocols:
            if x.name == name:
                return x
        return None

    def list_protocols(self) -> List[str]:
        return [x.name for x in self.protocols]

    def save_to_json(self, filepath: str) -> None:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump([asdict(p) for p in self.protocols], f, indent=4)

    def load_from_json(self, filepath: str) -> None:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.protocols = [TMSProtocol(**entry) for entry in data]
