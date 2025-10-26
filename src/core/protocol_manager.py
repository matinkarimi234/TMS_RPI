from dataclasses import dataclass, field, asdict
from typing import List, Optional
import json

@dataclass
class TMSProtocol:
    """
    A TMS protocol with full bounds-checking and two-way linkage between:
      - subject_mt_percent             (each subject’s motor threshold in % MSO)
      - intensity_percent_of_mt        (stimulation intensity as % of that MT)
      - absolute_output_percent        (the actual stimulator output in % MSO)

    All other parameters carry hard bounds typical of TMS devices.
    """

    name: str
    
    # Internal storage of the “master” values
    _subject_mt_percent:        float
    _intensity_percent_of_mt:   float
    _frequency_hz:              float
    _pulses_per_train:          int
    _train_count:               int
    _inter_train_interval_s:    float

    target_region: str
    description:   Optional[str] = None

    #— DEVICE BOUNDS (class constants) —
    MIN_MT_PERCENT                    =  1.0
    MAX_MT_PERCENT                    =100.0

    MIN_RELATIVE_INTENSITY_PERCENT            = 10.0
    MAX_RELATIVE_INTENSITY_PERCENT_STATIC     =200.0

    MIN_ABSOLUTE_OUTPUT_PERCENT       =  0.0
    MAX_ABSOLUTE_OUTPUT_PERCENT       =100.0

    MIN_FREQUENCY_HZ                  =  1
    MAX_FREQUENCY_HZ                  =100.0

    MIN_PULSES_PER_TRAIN              =  1
    MAX_PULSES_PER_TRAIN              =10000

    MIN_TRAIN_COUNT                   =  1
    MAX_TRAIN_COUNT                   =10000

    MIN_INTER_TRAIN_INTERVAL_S        =  0.0
    MAX_INTER_TRAIN_INTERVAL_S        =3600.0  # up to 1 hour

    def __post_init__(self):
        # Run all setters once to enforce bounds
        self.subject_mt_percent         = self._subject_mt_percent
        self.intensity_percent_of_mt    = self._intensity_percent_of_mt
        self.frequency_hz               = self._frequency_hz
        self.pulses_per_train           = self._pulses_per_train
        self.train_count                = self._train_count
        self.inter_train_interval_s     = self._inter_train_interval_s

    #— MT PROPERTY —
    @property
    def subject_mt_percent(self) -> float:
        """Subject’s motor threshold in % MSO."""
        return self._subject_mt_percent

    @subject_mt_percent.setter
    def subject_mt_percent(self, new_mt: float) -> None:
        if not (self.MIN_MT_PERCENT <= new_mt <= self.MAX_MT_PERCENT):
            raise ValueError(
                f"subject_mt_percent must be in "
                f"[{self.MIN_MT_PERCENT}, {self.MAX_MT_PERCENT}]%"
            )
        self._subject_mt_percent = new_mt

        # After MT changes, ensure intensity is still within dynamic bound
        if self._intensity_percent_of_mt > self.max_intensity_percent_of_mt:
            self._intensity_percent_of_mt = self.max_intensity_percent_of_mt

    #— RELATIVE INTENSITY PROPERTY —
    @property
    def intensity_percent_of_mt(self) -> float:
        """Stimulation intensity as % of subject’s MT."""
        return self._intensity_percent_of_mt

    @intensity_percent_of_mt.setter
    def intensity_percent_of_mt(self, new_intensity_percent_of_mt: float) -> None:
        min_allowed = self.MIN_RELATIVE_INTENSITY_PERCENT
        max_allowed = self.max_intensity_percent_of_mt
        if not (min_allowed <= new_intensity_percent_of_mt <= max_allowed):
            raise ValueError(
                f"intensity_percent_of_mt must be in "
                f"[{min_allowed:.1f}, {max_allowed:.1f}]% of MT "
                f"(dynamic max so that absolute ≤100% MSO)"
            )
        self._intensity_percent_of_mt = new_intensity_percent_of_mt

    @property
    def max_intensity_percent_of_mt(self) -> float:
        """
        Dynamic upper bound on relative intensity so that
        absolute_output_percent ≤ 100% MSO:
          max_rel = 100 * 100 / subject_mt_percent
        but never above MAX_RELATIVE_INTENSITY_PERCENT_STATIC.
        """
        dynamic_bound = 100.0 * 100.0 / self._subject_mt_percent
        return min(self.MAX_RELATIVE_INTENSITY_PERCENT_STATIC, dynamic_bound)

    #— ABSOLUTE OUTPUT PROPERTY —
    @property
    def absolute_output_percent(self) -> float:
        """
        The actual stimulator output in % MSO,
        computed as subject_mt_percent × intensity_percent_of_mt ÷ 100.
        """
        return self._subject_mt_percent * self._intensity_percent_of_mt / 100.0

    @absolute_output_percent.setter
    def absolute_output_percent(self, new_absolute_output_percent: float) -> None:
        if not (
            self.MIN_ABSOLUTE_OUTPUT_PERCENT
            <= new_absolute_output_percent
            <= self.MAX_ABSOLUTE_OUTPUT_PERCENT
        ):
            raise ValueError(
                f"absolute_output_percent must be in "
                f"[{self.MIN_ABSOLUTE_OUTPUT_PERCENT}, "
                f"{self.MAX_ABSOLUTE_OUTPUT_PERCENT}]% MSO"
            )

        # Compute the new relative intensity so that:
        # new_relative_intensity_percent_of_mt =
        #    new_absolute_output_percent / subject_mt_percent × 100
        new_intensity_percent_of_mt = (
            new_absolute_output_percent
            / self._subject_mt_percent
            * 100.0
        )

        # Double-check it does not exceed the dynamic bound
        if new_intensity_percent_of_mt > self.max_intensity_percent_of_mt:
            raise ValueError(
                "Computed intensity_percent_of_mt "
                "would exceed the dynamic maximum"
            )

        # Everything is valid → store it
        self._intensity_percent_of_mt = new_intensity_percent_of_mt

    #— FREQUENCY PROPERTY —
    @property
    def frequency_hz(self) -> float:
        return self._frequency_hz

    @frequency_hz.setter
    def frequency_hz(self, new_frequency_hz: float) -> None:
        if not (
            self.MIN_FREQUENCY_HZ
            <= new_frequency_hz
            <= self.MAX_FREQUENCY_HZ
        ):
            raise ValueError(
                f"frequency_hz must be in "
                f"[{self.MIN_FREQUENCY_HZ}, {self.MAX_FREQUENCY_HZ}] Hz"
            )
        self._frequency_hz = new_frequency_hz

    #— PULSES PER TRAIN PROPERTY —
    @property
    def pulses_per_train(self) -> int:
        return self._pulses_per_train

    @pulses_per_train.setter
    def pulses_per_train(self, new_pulses_per_train: int) -> None:
        if not (
            self.MIN_PULSES_PER_TRAIN
            <= new_pulses_per_train
            <= self.MAX_PULSES_PER_TRAIN
        ):
            raise ValueError(
                f"pulses_per_train must be in "
                f"[{self.MIN_PULSES_PER_TRAIN}, {self.MAX_PULSES_PER_TRAIN}]"
            )
        self._pulses_per_train = new_pulses_per_train

    #— TRAIN COUNT PROPERTY —
    @property
    def train_count(self) -> int:
        return self._train_count

    @train_count.setter
    def train_count(self, new_train_count: int) -> None:
        if not (
            self.MIN_TRAIN_COUNT
            <= new_train_count
            <= self.MAX_TRAIN_COUNT
        ):
            raise ValueError(
                f"train_count must be in "
                f"[{self.MIN_TRAIN_COUNT}, {self.MAX_TRAIN_COUNT}]"
            )
        self._train_count = new_train_count

    #— INTER-TRAIN INTERVAL PROPERTY —
    @property
    def inter_train_interval_s(self) -> float:
        return self._inter_train_interval_s

    @inter_train_interval_s.setter
    def inter_train_interval_s(self, new_interval_s: float) -> None:
        if not (
            self.MIN_INTER_TRAIN_INTERVAL_S
            <= new_interval_s
            <= self.MAX_INTER_TRAIN_INTERVAL_S
        ):
            raise ValueError(
                f"inter_train_interval_s must be in "
                f"[{self.MIN_INTER_TRAIN_INTERVAL_S}, "
                f"{self.MAX_INTER_TRAIN_INTERVAL_S}] seconds"
            )
        self._inter_train_interval_s = new_interval_s

    #— SUMMARY CALCULATIONS —
    def total_pulses(self) -> int:
        return self._pulses_per_train * self._train_count

    def total_duration_s(self) -> float:
        stim_time = self._pulses_per_train / self._frequency_hz
        rest_time = self._inter_train_interval_s * (self._train_count - 1)
        return stim_time * self._train_count + rest_time


@dataclass
class ProtocolManager:
    """Stores, retrieves and JSON-persists multiple TMSProtocol instances."""
    protocols: List[TMSProtocol] = field(default_factory=list)

    def add_protocol(self, proto: TMSProtocol) -> None:
        self.protocols = [
            existing for existing in self.protocols
            if existing.name != proto.name
        ]
        self.protocols.append(proto)

    def remove_protocol(self, name: str) -> bool:
        before = len(self.protocols)
        self.protocols = [
            existing for existing in self.protocols
            if existing.name != name
        ]
        return len(self.protocols) < before

    def get_protocol(self, name: str) -> Optional[TMSProtocol]:
        for existing in self.protocols:
            if existing.name == name:
                return existing
        return None

    def list_protocols(self) -> List[str]:
        return [p.name for p in self.protocols]

    def save_to_json(self, filepath: str) -> None:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump([asdict(p) for p in self.protocols], f, indent=4)

    def load_from_json(self, filepath: str) -> None:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.protocols = [TMSProtocol(**entry) for entry in data]



# Test
if "__main__":
    import json
    from pathlib import Path
    PROJECT_ROOT = Path(__file__).parent.resolve()
    # 1. Read the JSON file
    with open(PROJECT_ROOT / "protocols.json", 'r', encoding='utf-8') as f:
        raw = json.load(f)

    # 2. Instantiate TMSProtocol objects from raw entries
    manager = ProtocolManager()
    for entry in raw:
        proto = TMSProtocol(
            name=entry["name"],
            _subject_mt_percent=entry["subject_mt_percent"],
            _intensity_percent_of_mt=entry["intensity_percent_of_mt"],
            _frequency_hz=entry["frequency_hz"],
            _pulses_per_train=entry["pulses_per_train"],
            _train_count=entry["train_count"],
            _inter_train_interval_s=entry["inter_train_interval_s"],
            target_region=entry["target_region"],
            description=entry.get("description")
        )
        manager.add_protocol(proto)

    # 3. List available protocols
    print("Loaded protocols:", manager.list_protocols())
    # → ['iTBS_Standard', 'cTBS_Standard', 'rTMS_10Hz_depression', ...]

    # 4. Inspect one protocol
    p = manager.get_protocol("iTBS_Standard")
    print(f"Name: {p.name}")
    print(f"  Subject MT (MSO%):          {p.subject_mt_percent}")
    print(f"  Rel. Intensity (% of MT):  {p.intensity_percent_of_mt}")
    print(f"  Absolute Output (% MSO):   {p.absolute_output_percent:.1f}")
    print(f"  Total Pulses:              {p.total_pulses()}")
    print(f"  Total Duration (s):        {p.total_duration_s():.1f}")

