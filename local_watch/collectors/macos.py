from __future__ import annotations
from local_watch.schema import Metric, Snapshot
from local_watch.collectors.base import probe

def _disk_root_pct(df_out: str) -> float | None:
    # macOS `df -P` uses the same POSIX columns as Linux (Filesystem, blocks,
    # Used, Available, Capacity, Mounted on), but on APFS macOS the "/" mount
    # is the sealed read-only system snapshot (near-empty by design); real
    # user data lives on "/System/Volumes/Data". Prefer that mount's
    # capacity %, falling back to "/" if the Data volume row is absent.
    root_pct = None
    for line in df_out.splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        if parts[5] == "/System/Volumes/Data":
            return float(parts[4].rstrip("%"))
        if parts[5] == "/":
            root_pct = float(parts[4].rstrip("%"))
    return root_pct

def _vm_stat_pages(vm_stat_out: str) -> dict[str, int]:
    pages: dict[str, int] = {}
    for line in vm_stat_out.splitlines():
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        label = label.strip().strip('"').lower()
        value = value.strip().rstrip(".")
        if not value.isdigit():
            continue
        pages[label] = int(value)
    return pages

def _mem_used_pct(vm_stat_out: str) -> float | None:
    pages = _vm_stat_pages(vm_stat_out)
    free = pages.get("pages free", 0)
    active = pages.get("pages active", 0)
    inactive = pages.get("pages inactive", 0)
    wired = pages.get("pages wired down", 0)
    compressed = pages.get("pages occupied by compressor", 0)
    total = free + active + inactive + wired + compressed
    used = active + wired + compressed
    return round(100.0 * used / total, 1) if total else None

def _updates_pending(swupdate_out: str) -> int:
    return sum(1 for ln in swupdate_out.splitlines() if ln.strip().startswith("* Label:"))

def collect(runner=probe, machine: str = "", now: str = "") -> Snapshot:
    failed: list[str] = []
    metrics: list[Metric] = []
    facts: dict[str, str] = {}

    def read(name: str, cmd: list[str]) -> str | None:
        """Run one probe; record it as failed if it could not run."""
        out = runner(cmd)
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
    vm_stat = read("vm_stat", ["vm_stat"])
    swupdate = read("softwareupdate", ["softwareupdate", "--list"])

    metric("disk_root_pct", "df", df, _disk_root_pct)
    metric("mem_used_pct", "vm_stat", vm_stat, _mem_used_pct)

    # Facts are omitted entirely when their probe failed, so downstream rules
    # see "unknown" rather than a reassuring zero.
    if swupdate is not None:
        facts["updates_pending"] = str(_updates_pending(swupdate))
    facts["reboot_required"] = "false"   # refined in a later step / task 2b if desired
    facts["probes_failed"] = ",".join(failed)
    return Snapshot(machine=machine, os="macos", ts=now, metrics=metrics, facts=facts)
