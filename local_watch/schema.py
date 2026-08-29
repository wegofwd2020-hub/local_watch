from __future__ import annotations
import json
from dataclasses import dataclass, asdict, field

@dataclass(frozen=True)
class Metric:
    name: str
    value: float
    unit: str = ""

@dataclass(frozen=True)
class Snapshot:
    machine: str
    os: str
    ts: str                       # ISO-8601 UTC
    metrics: list[Metric] = field(default_factory=list)
    facts: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> "Snapshot":
        d = json.loads(s)
        return cls(machine=d["machine"], os=d["os"], ts=d["ts"],
                   metrics=[Metric(**m) for m in d.get("metrics", [])],
                   facts=d.get("facts", {}))
