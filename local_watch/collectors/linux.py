from __future__ import annotations
from local_watch.schema import Metric, Snapshot
from local_watch.collectors.base import probe

def _disk_root_pct(df_out: str) -> float:
    for line in df_out.splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[5] == "/":
            return float(parts[4].rstrip("%"))
    return 0.0

def _mem_used_pct(free_out: str) -> float:
    for line in free_out.splitlines():
        if line.startswith("Mem:"):
            p = line.split()
            total, used = float(p[1]), float(p[2])
            return round(100.0 * used / total, 1) if total else 0.0
    return 0.0

def _updates_pending(apt_out: str) -> int:
    return sum(1 for ln in apt_out.splitlines() if "/" in ln and "upgradable" in ln)

def collect(runner=probe, machine: str = "", now: str = "") -> Snapshot:
    df = runner(["df", "-P"]); free = runner(["free", "-b"])
    apt = runner(["apt", "list", "--upgradable"]); failed = runner(["systemctl", "--failed", "--no-legend"])
    metrics = [Metric("disk_root_pct", _disk_root_pct(df), "%"),
               Metric("mem_used_pct", _mem_used_pct(free), "%")]
    failed_units = ",".join(ln.split()[0] for ln in failed.splitlines() if ln.strip())
    facts = {"updates_pending": str(_updates_pending(apt)),
             "failed_units": failed_units,
             "reboot_required": "false"}   # refined in a later step / task 2b if desired
    return Snapshot(machine=machine, os="linux", ts=now, metrics=metrics, facts=facts)
