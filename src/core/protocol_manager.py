

from __future__ import annotations
from dataclasses   import dataclass, field, asdict
from typing       import ClassVar, Optional, List
import json


@dataclass
class TMSProtocol:
    # ——— 1) Init‐args without defaults — must come first ———
    name                     : str
    subject_mt_percent       : float
    intensity_percent_of_mt  : float
    frequency_hz             : float
    pulses_per_train         : int
    train_count              : int
    inter_train_interval_s   : float
    target_region            : str

    # ——— 2) Init‐args with defaults — now you can safely list these ———
    description              : Optional[str] = None
    _absolute_output_init: Optional[float] = None 

    # ——— 3) Device bounds — annotate as ClassVar so dataclass skips them ———
    MIN_MT_PERCENT                       : ClassVar[float] =   1.0
    MAX_MT_PERCENT                       : ClassVar[float] = 100.0

    MIN_RELATIVE_INTENSITY_PERCENT       : ClassVar[float] =  10.0
    MAX_RELATIVE_INTENSITY_PERCENT_STATIC: ClassVar[float] = 200.0

    MIN_ABSOLUTE_OUTPUT_PERCENT          : ClassVar[float] =   0.0
    MAX_ABSOLUTE_OUTPUT_PERCENT          : ClassVar[float] = 100.0

    MIN_FREQUENCY_HZ                     : ClassVar[float] =   1.0
    MAX_FREQUENCY_HZ                     : ClassVar[float] = 100.0

    MIN_PULSES_PER_TRAIN                 : ClassVar[int]   =     1
    MAX_PULSES_PER_TRAIN                 : ClassVar[int]   = 10000

    MIN_TRAIN_COUNT                      : ClassVar[int]   =     1
    MAX_TRAIN_COUNT                      : ClassVar[int]   = 10000

    MIN_INTER_TRAIN_INTERVAL_S           : ClassVar[float] =   0.0
    MAX_INTER_TRAIN_INTERVAL_S           : ClassVar[float] = 3600.0

    # ——— 4) Private backing fields (no __init__) ———
    _subject_mt_percent       : float         = field(init=False, repr=False)
    _intensity_percent_of_mt  : float         = field(init=False, repr=False)
    _frequency_hz             : float         = field(init=False, repr=False)
    _pulses_per_train         : int           = field(init=False, repr=False)
    _train_count              : int           = field(init=False, repr=False)
    _inter_train_interval_s   : float         = field(init=False, repr=False)
    _absolute_output_percent  : float         = field(init=False, repr=False)
    _description              : Optional[str] = field(init=False, repr=False)
    _target_region            : str           = field(init=False, repr=False)


    def __post_init__(self):
        # Force every constructor argument through the setter logic:
        self.subject_mt_percent      = self.subject_mt_percent
        self.description             = self.description
        self.target_region           = self.target_region

        if self._absolute_output_init is not None:
            self.absolute_output_percent = self._absolute_output_init
        else:
            self.intensity_percent_of_mt = self.intensity_percent_of_mt

        self.frequency_hz             = self.frequency_hz
        self.pulses_per_train         = self.pulses_per_train
        self.train_count              = self.train_count
        self.inter_train_interval_s   = self.inter_train_interval_s


    # ——— subject_mt_percent ———
    @property
    def subject_mt_percent(self) -> float:
        return self._subject_mt_percent

    @subject_mt_percent.setter
    def subject_mt_percent(self, value: float):
        if value < self.MIN_MT_PERCENT or value > self.MAX_MT_PERCENT:
            raise ValueError(
                f"subject_mt_percent must be in "
                f"[{self.MIN_MT_PERCENT}, {self.MAX_MT_PERCENT}]%"
            )
        self._subject_mt_percent = value
        # clamp relative intensity if it now exceeds the dynamic max
        if hasattr(self, "_intensity_percent_of_mt") \
           and self._intensity_percent_of_mt > self.max_intensity_percent_of_mt:
            self._intensity_percent_of_mt = self.max_intensity_percent_of_mt


    # ——— intensity_percent_of_mt ———
    @property
    def intensity_percent_of_mt(self) -> float:
        return self._intensity_percent_of_mt

    @intensity_percent_of_mt.setter
    def intensity_percent_of_mt(self, value: float):
        min_r = self.MIN_RELATIVE_INTENSITY_PERCENT
        max_r = self.max_intensity_percent_of_mt
        if value < min_r or value > max_r:
            raise ValueError(
                f"intensity_percent_of_mt must be in [{min_r}, {max_r}]% of MT"
            )
        self._intensity_percent_of_mt = value
        # update absolute
        self._absolute_output_percent = (self._subject_mt_percent * value) / 100.0

    @property
    def max_intensity_percent_of_mt(self) -> float:
        # dynamic upper‐bound so |absolute| ≤ 100%
        dyn = 100.0 * 100.0 / self._subject_mt_percent
        return min(self.MAX_RELATIVE_INTENSITY_PERCENT_STATIC, dyn)


    # ——— absolute_output_percent ———
    @property
    def absolute_output_percent(self) -> float:
        return self._absolute_output_percent

    @absolute_output_percent.setter
    def absolute_output_percent(self, value: float):
        if value < self.MIN_ABSOLUTE_OUTPUT_PERCENT \
           or value > self.MAX_ABSOLUTE_OUTPUT_PERCENT:
            raise ValueError(
                f"absolute_output_percent must be in "
                f"[{self.MIN_ABSOLUTE_OUTPUT_PERCENT}, "
                f"{self.MAX_ABSOLUTE_OUTPUT_PERCENT}]%"
            )
        # derive new relative intensity
        rel = (value / self._subject_mt_percent) * 100.0
        if rel > self.max_intensity_percent_of_mt:
            raise ValueError(
                "absolute_output_percent would force "
                "intensity_percent_of_mt above dynamic max"
            )
        self._absolute_output_percent     = value
        self._intensity_percent_of_mt     = rel


    # ——— frequency_hz ———
    @property
    def frequency_hz(self) -> float:
        return self._frequency_hz

    @frequency_hz.setter
    def frequency_hz(self, value: float):
        if value < self.MIN_FREQUENCY_HZ or value > self.MAX_FREQUENCY_HZ:
            raise ValueError(
                f"frequency_hz must be in "
                f"[{self.MIN_FREQUENCY_HZ}, {self.MAX_FREQUENCY_HZ}]"
            )
        self._frequency_hz = value


    # ——— pulses_per_train ———
    @property
    def pulses_per_train(self) -> int:
        return self._pulses_per_train

    @pulses_per_train.setter
    def pulses_per_train(self, value: int):
        if value < self.MIN_PULSES_PER_TRAIN \
           or value > self.MAX_PULSES_PER_TRAIN:
            raise ValueError(
                f"pulses_per_train must be in "
                f"[{self.MIN_PULSES_PER_TRAIN}, {self.MAX_PULSES_PER_TRAIN}]"
            )
        self._pulses_per_train = value


    # ——— train_count ———
    @property
    def train_count(self) -> int:
        return self._train_count

    @train_count.setter
    def train_count(self, value: int):
        if value < self.MIN_TRAIN_COUNT or value > self.MAX_TRAIN_COUNT:
            raise ValueError(
                f"train_count must be in "
                f"[{self.MIN_TRAIN_COUNT}, {self.MAX_TRAIN_COUNT}]"
            )
        self._train_count = value


    # ——— inter_train_interval_s ———
    @property
    def inter_train_interval_s(self) -> float:
        return self._inter_train_interval_s

    @inter_train_interval_s.setter
    def inter_train_interval_s(self, value: float):
        if (value < self.MIN_INTER_TRAIN_INTERVAL_S
            or value > self.MAX_INTER_TRAIN_INTERVAL_S):
            raise ValueError(
                f"inter_train_interval_s must be in "
                f"[{self.MIN_INTER_TRAIN_INTERVAL_S}, "
                f"{self.MAX_INTER_TRAIN_INTERVAL_S}]"
            )
        self._inter_train_interval_s = value


    # ——— target_region ———
    @property
    def target_region(self) -> str:
        return self._target_region

    @target_region.setter
    def target_region(self, value: str):
        if not isinstance(value, str):
            raise ValueError("target_region must be a string")
        self._target_region = value


    # ——— description ———
    @property
    def description(self) -> Optional[str]:
        return self._description

    @description.setter
    def description(self, value: Optional[str]):
        if value is not None and not isinstance(value, str):
            raise ValueError("description must be a string or None")
        self._description = value


    # ——— Summary metrics ———
    def total_pulses(self) -> int:
        return self.pulses_per_train * self.train_count

    def total_duration_s(self) -> float:
        stim = self.pulses_per_train / self.frequency_hz
        rest = self.inter_train_interval_s * (self.train_count - 1)
        return stim * self.train_count + rest



@dataclass
class ProtocolManager:
    """Holds, JSON‐loads/saves, and queries many TMSProtocol instances."""
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
        # Each dict must have exactly the keys:
        #   name, subject_mt_percent, intensity_percent_of_mt,
        #   frequency_hz, pulses_per_train, train_count,
        #   inter_train_interval_s, target_region
        # (and optionally) description, absolute_output_percent
        self.protocols = [TMSProtocol(**entry) for entry in data]
