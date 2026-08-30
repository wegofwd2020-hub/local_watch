from __future__ import annotations
from local_watch.schema import Metric, Snapshot
from local_watch.collectors.base import probe

def _disk_root_pct(df_out: str) -> float | None:
    for line in df_out.splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[5] == "/":
            return float(parts[4].rstrip("%"))
    return None

def _mem_used_pct(free_out: str) -> float | None:
    for line in free_out.splitlines():
        if line.startswith("Mem:"):
            p = line.split()
            total, used = float(p[1]), float(p[2])
            return round(100.0 * used / total, 1) if total else None
    return None

def _updates_pending(apt_out: str) -> int:
    return sum(1 for ln in apt_out.splitlines() if "/" in ln and "upgradable" in ln)

def _failed_units(failed_out: str) -> str:
    units = []
    for ln in failed_out.splitlines():
        if not ln.strip():
            continue
        # systemctl --failed prefixes each line with a "●" bullet marker;
        # strip it before taking the first field (the unit name).
        parts = ln.replace("●", " ").split()
        if parts:
            units.append(parts[0])
    return ",".join(units)

def collect(runner=probe, machine: str = "", now: str = "") -> Snapshot:
    failed: list[str] = []
    metrics: list[Metric] = []
    facts: dict[str, str] = {}

    def read(name: str, cmd: list[str], timeout: int | None = None) -> str | None:
        """Run one probe; record it as failed if it could not run."""
        out = runner(cmd, timeout=timeout)
        if out is None:
            failed.append(name)
        return out

    def metric(name: str, probe_name: str, raw: str | None, parse, unit: str = "%") -> None:
        """Add a metric, or drop it and mark the probe failed. Never emits a
        placeholder zero — an absent metric plus a flag beats a false reading."""
        if raw is None:
            return                      # read() already recorded the failure
        value = parse(raw)
        if value is None:
            failed.append(probe_name)   # ran, but produced nothing parseable
        else:
            metrics.append(Metric(name, value, unit))

    df = read("df", ["df", "-P"])
    free = read("free", ["free", "-b"])
    apt = read("apt", ["apt", "list", "--upgradable"])
    systemctl = read("systemctl", ["systemctl", "--failed", "--no-legend"])

    metric("disk_root_pct", "df", df, _disk_root_pct)
    metric("mem_used_pct", "free", free, _mem_used_pct)

    # Facts are omitted entirely when their probe failed, so downstream rules
    # see "unknown" rather than a reassuring zero.
    if apt is not None:
        facts["updates_pending"] = str(_updates_pending(apt))
    if systemctl is not None:
        facts["failed_units"] = _failed_units(systemctl)
    facts["reboot_required"] = "false"   # refined in a later step / task 2b if desired
    facts["probes_failed"] = ",".join(failed)
    return Snapshot(machine=machine, os="linux", ts=now, metrics=metrics, facts=facts)
