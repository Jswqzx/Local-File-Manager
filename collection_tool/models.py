from dataclasses import dataclass
from pathlib import Path


@dataclass
class EntryRecord:
    path: Path
    kind: str
    type_label: str
    relative_path: str
    size_bytes: int
