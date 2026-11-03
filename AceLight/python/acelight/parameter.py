
from dataclasses import dataclass


@dataclass(frozen=True)
class Parameter:
    id: int
    data_type: str
    description: str
    unit: str
    access: str 