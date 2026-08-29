from __future__ import annotations
from dataclasses import dataclass
from local_watch.schema import Snapshot

@dataclass(frozen=True)
class Flag:
    machine: str
    key: str
    severity: str   # info | warn | crit
    message: str

def _metric(latest: Snapshot, name: str) -> float | None:
    for m in latest.metrics:
        if m.name == name:
            return m.value
    return None

def evaluate(latest: Snapshot, series: dict[str, list[float]]) -> list[Flag]:
    f: list[Flag] = []
    mc = latest.machine
    disk = _metric(latest, "disk_root_pct")
    if disk is not None:
        if disk >= 90:
            f.append(Flag(mc, "disk_full", "crit", f"Root filesystem {disk:.0f}% full"))
        elif disk >= 80:
            f.append(Flag(mc, "disk_full", "warn", f"Root filesystem {disk:.0f}% full"))
    mem = _metric(latest, "mem_used_pct")
    if mem is not None and mem >= 90:
        f.append(Flag(mc, "mem_pressure", "warn", f"Memory {mem:.0f}% used"))
    if latest.facts.get("reboot_required") == "true":
        f.append(Flag(mc, "reboot_required", "warn", "Reboot required"))
    up = int(latest.facts.get("updates_pending", "0") or 0)
    if up > 0:
        f.append(Flag(mc, "updates_pending", "info" if up < 20 else "warn", f"{up} package updates pending"))
    failed = latest.facts.get("failed_units", "")
    if failed:
        f.append(Flag(mc, "failed_units", "crit", f"Failed services: {failed}"))
    return f
