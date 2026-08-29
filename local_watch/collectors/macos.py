from __future__ import annotations
from local_watch.schema import Metric, Snapshot
from local_watch.collectors.base import probe

def _disk_root_pct(df_out: str) -> float:
    # macOS `df -P` uses the same POSIX columns as Linux (Filesystem, blocks,
    # Used, Available, Capacity, Mounted on) with the root mount at "/", so
    # this mirrors linux.py's `_disk_root_pct` parser exactly.
    for line in df_out.splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[5] == "/":
            return float(parts[4].rstrip("%"))
    return 0.0

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

def _mem_used_pct(vm_stat_out: str) -> float:
    pages = _vm_stat_pages(vm_stat_out)
    free = pages.get("pages free", 0)
    active = pages.get("pages active", 0)
    inactive = pages.get("pages inactive", 0)
    wired = pages.get("pages wired down", 0)
    compressed = pages.get("pages occupied by compressor", 0)
    total = free + active + inactive + wired + compressed
    used = active + wired + compressed
    return round(100.0 * used / total, 1) if total else 0.0

def _updates_pending(swupdate_out: str) -> int:
    return sum(1 for ln in swupdate_out.splitlines() if ln.strip().startswith("* Label:"))

def collect(runner=probe, machine: str = "", now: str = "") -> Snapshot:
    df = runner(["df", "-P"])
    vm_stat = runner(["vm_stat"])
    swupdate = runner(["softwareupdate", "--list"])
    metrics = [Metric("disk_root_pct", _disk_root_pct(df), "%"),
               Metric("mem_used_pct", _mem_used_pct(vm_stat), "%")]
    facts = {"updates_pending": str(_updates_pending(swupdate)),
             "reboot_required": "false"}   # refined in a later step / task 2b if desired
    return Snapshot(machine=machine, os="macos", ts=now, metrics=metrics, facts=facts)
