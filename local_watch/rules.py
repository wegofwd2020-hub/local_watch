from __future__ import annotations
import datetime
from dataclasses import dataclass
from local_watch.schema import Snapshot

# A collector fires every ~20 minutes (see deploy/). Three missed runs means
# the machine is off, asleep, unreachable, or its timer is broken — in every
# case its last snapshot is history, not status.
STALE_AFTER_MIN = 60

# The disk levels the meter in report.py marks. Named here so the picture and
# the rule that colours it cannot drift apart.
DISK_WARN_PCT = 80
DISK_CRIT_PCT = 90

_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"

# Trend projection guards. A rate is only worth extrapolating if it is backed
# by enough readings over enough wall-clock time — 13 samples inside one hour
# say nothing about next Tuesday.
_MIN_TREND_POINTS = 6
_MIN_TREND_SPAN_HOURS = 6.0
_MIN_SLOPE_PCT_PER_DAY = 0.5    # below this, it is sampling noise, not a trend
_PROJECT_CRIT_DAYS = 2.0
_PROJECT_WARN_DAYS = 7.0
_DISK_FULL_PCT = 100.0

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

def age_label(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}m"
    if minutes < 60 * 24:
        return f"{minutes // 60}h"
    return f"{minutes // (60 * 24)}d"

def _slope_pct_per_day(points: list[tuple[str, float]]) -> float | None:
    """Least-squares rate of change, in percentage points per day.

    Fitted against real elapsed time rather than sample index: collection
    gaps (a sleeping laptop, a missed timer) would otherwise compress days of
    history into what looks like a steep climb. Points with unreadable
    timestamps are dropped rather than guessed at.
    """
    xs: list[float] = []
    ys: list[float] = []
    origin = None
    for ts, value in points:
        t = _parse_ts(ts)
        if t is None:
            continue
        if origin is None:
            origin = t
        xs.append((t - origin).total_seconds() / 3600.0)
        ys.append(value)
    if len(xs) < _MIN_TREND_POINTS or (max(xs) - min(xs)) < _MIN_TREND_SPAN_HOURS:
        return None
    n = len(xs)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return None
    slope_per_hour = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
    return slope_per_hour * 24.0

def _eta_label(days: float) -> str:
    """Floor rather than round: understating the headroom errs toward warning
    early, which is the safe direction for a capacity heads-up."""
    if days < 1:
        return f"{int(days * 24)}h"
    return f"{int(days)}d"

def _disk_trend(latest: Snapshot, points: list[tuple[str, float]]) -> Flag | None:
    """Flag a root filesystem on course to fill.

    The level check says where the disk is now; this says how long that lasts.
    A disk at 55% climbing 20%/day is the more urgent of the two.
    """
    current = _metric(latest, "disk_root_pct")
    if current is None:
        return None                     # probe failed; nothing to project from
    slope = _slope_pct_per_day(points)
    if slope is None or slope < _MIN_SLOPE_PCT_PER_DAY:
        return None
    days = max(0.0, (_DISK_FULL_PCT - current) / slope)
    if days > _PROJECT_WARN_DAYS:
        return None                     # true, but not news
    severity = "crit" if days <= _PROJECT_CRIT_DAYS else "warn"
    return Flag(latest.machine, "disk_filling", severity,
                f"Root filesystem filling at +{slope:.1f}%/day "
                f"- full in ~{_eta_label(days)} at this rate")

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
                f"No snapshot for {age_label(minutes)} — readings below are stale")

def evaluate(latest: Snapshot, series: dict[str, list[tuple[str, float]]],
             now: str | None = None) -> list[Flag]:
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
        if disk >= DISK_CRIT_PCT:
            f.append(Flag(mc, "disk_full", "crit", f"Root filesystem {disk:.0f}% full"))
        elif disk >= DISK_WARN_PCT:
            f.append(Flag(mc, "disk_full", "warn", f"Root filesystem {disk:.0f}% full"))
    # Memory is deliberately left out of trend projection: it sawtooths by
    # design (caches grow until something needs the pages), so a rising fit
    # over any short window is noise dressed up as a warning.
    trend = _disk_trend(latest, series.get("disk_root_pct", []))
    if trend is not None:
        f.append(trend)
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
