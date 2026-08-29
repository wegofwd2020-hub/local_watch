from pathlib import Path
from local_watch.collectors import linux

FX = Path(__file__).parent.parent / "fixtures"

def fake_runner(cmd):
    key = " ".join(cmd)
    table = {
        "df -P": "linux_df.txt", "free -b": "linux_free.txt", "uptime": "linux_uptime.txt",
        "apt list --upgradable": "linux_aptlist.txt", "systemctl --failed --no-legend": "linux_failed.txt",
    }
    for k, f in table.items():
        if key.startswith(k):
            return (FX / f).read_text()
    return ""

def test_linux_collect_produces_snapshot():
    snap = linux.collect(runner=fake_runner, machine="testbox", now="2026-08-29T00:00:00Z")
    assert snap.machine == "testbox" and snap.os == "linux"
    names = {m.name for m in snap.metrics}
    assert "disk_root_pct" in names and "mem_used_pct" in names
    assert "updates_pending" in snap.facts   # a count string
    assert 0.0 <= next(m.value for m in snap.metrics if m.name == "disk_root_pct") <= 100.0
