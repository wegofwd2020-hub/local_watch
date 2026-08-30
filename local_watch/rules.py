from __future__ import annotations
import datetime
from dataclasses import dataclass
from local_watch.schema import Snapshot

# A collector fires every ~20 minutes (see deploy/). Three missed runs means
# the machine is off, asleep, unreachable, or its timer is broken — in every
# case its last snapshot is history, not status.
STALE_AFTER_MIN = 60

_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"

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

def _parse_ts(ts: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.strptime(ts, _TS_FMT)
    except (ValueError, TypeError):
        return None

def _age_label(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}m"
    if minutes < 60 * 24:
        return f"{minutes // 60}h"
    return f"{minutes // (60 * 24)}d"

def _staleness(latest: Snapshot, now: str) -> Flag | None:
    """Flag a snapshot we can no longer treat as current.

    Without this, `store.latest()` happily serves the final reading from a
    machine that died weeks ago and the dashboard paints it green.
    """
    seen, current = _parse_ts(latest.ts), _parse_ts(now)
    if current is None:
        return None
    if seen is None:
        return Flag(latest.machine, "stale", "crit",
                    f"Snapshot timestamp unreadable ({latest.ts!r}) — age unknown")
    minutes = int((current - seen).total_seconds() // 60)
    if minutes < STALE_AFTER_MIN:
        return None
    return Flag(latest.machine, "stale", "crit",
                f"No snapshot for {_age_label(minutes)} — readings below are stale")

def evaluate(latest: Snapshot, series: dict[str, list[float]], now: str | None = None) -> list[Flag]:
    f: list[Flag] = []
    mc = latest.machine

    # Trust checks first: if the data is stale or partial, say so before
    # drawing any conclusion from the numbers themselves.
    if now is not None:
        stale = _staleness(latest, now)
        if stale is not None:
            f.append(stale)
    probes_failed = latest.facts.get("probes_failed", "")
    if probes_failed:
        f.append(Flag(mc, "collector_degraded", "crit",
                      f"Collector probes failed: {probes_failed} — those readings are missing, not zero"))

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
    _updates_raw = latest.facts.get("updates_pending", "0") or "0"
    up = int(_updates_raw) if str(_updates_raw).isdigit() else 0
    if up > 0:
        f.append(Flag(mc, "updates_pending", "info" if up < 20 else "warn", f"{up} package updates pending"))
    failed = latest.facts.get("failed_units", "")
    if failed:
        f.append(Flag(mc, "failed_units", "crit", f"Failed services: {failed}"))
    return f
