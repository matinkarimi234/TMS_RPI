from dataclasses import dataclass, field, asdict
from typing import List, Optional
import json


@dataclass
class TMSProtocol:
    """
    A dataclass representing a single TMS (Transcranial Magnetic Stimulation)
    protocol with all the necessary stimulation parameters.
    """
    name: str
    intensity_percent: float            # Stimulation intensity as % of maximum stimulator output
    frequency_hz: float                # Stimulation frequency in Hz
    pulses_per_train: int              # Number of pulses in each train
    train_count: int                   # How many trains to deliver
    inter_train_interval_s: float      # Interval between trains in seconds
    target_region: str                 # Anatomical or coordinate-based target description
    description: Optional[str] = None  # Optional free‐text description of the protocol

    def total_pulses(self) -> int:
        """
        Compute total number of pulses delivered by this protocol.
        """
        return self.pulses_per_train * self.train_count

    def total_duration_s(self) -> float:
        """
        Estimate total stimulation time (not counting ramp‐up/down).
        """
        stimulation_time = self.pulses_per_train / self.frequency_hz
        rest_time = self.inter_train_interval_s * (self.train_count - 1)
        return stimulation_time * self.train_count + rest_time


@dataclass
class ProtocolManager:
    """
    A manager for storing, retrieving, and persisting multiple TMSProtocol instances.
    """
    protocols: List[TMSProtocol] = field(default_factory=list)

    def add_protocol(self, protocol: TMSProtocol) -> None:
        """
        Add a new protocol. If a protocol with the same name exists, it will be replaced.
        """
        # Remove existing protocol with same name if present
        self.protocols = [p for p in self.protocols if p.name != protocol.name]
        self.protocols.append(protocol)

    def remove_protocol(self, protocol_name: str) -> bool:
        """
        Remove a protocol by name.
        Returns True if removed, False if not found.
        """
        initial_count = len(self.protocols)
        self.protocols = [p for p in self.protocols if p.name != protocol_name]
        return len(self.protocols) < initial_count

    def get_protocol(self, protocol_name: str) -> Optional[TMSProtocol]:
        """
        Retrieve a protocol by name. Returns None if not found.
        """
        for p in self.protocols:
            if p.name == protocol_name:
                return p
        return None

    def list_protocols(self) -> List[str]:
        """
        Return a list of all protocol names currently stored.
        """
        return [p.name for p in self.protocols]

    def save_to_json(self, filepath: str) -> None:
        """
        Serialize all stored protocols to a JSON file.
        """
        with open(filepath, 'w', encoding='utf-8') as f:
            # Convert each protocol to dict
            data = [asdict(p) for p in self.protocols]
            json.dump(data, f, indent=4)

    def load_from_json(self, filepath: str) -> None:
        """
        Load protocols from a JSON file, replacing any currently stored.
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.protocols = [TMSProtocol(**entry) for entry in data]



# Usage
# from pathlib import Path

# def main():
#     PROJECT_ROOT = Path(__file__).parent.resolve()
#     manager = ProtocolManager()
#     manager.load_from_json(PROJECT_ROOT / "protocols.json")

#     print("Loaded protocols:", manager.list_protocols())
    
#     proto = manager.get_protocol("HighFreq_rTMS_Depression")
#     if proto:
#         print(f"{proto.name} -> total pulses: {proto.total_pulses()}, "
#               f"total duration: {proto.total_duration_s():.1f} s")

    
#     manager.save_to_json("protocols_updated.json")

# if __name__ == "__main__":
#     main()