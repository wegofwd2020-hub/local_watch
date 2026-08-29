from pathlib import Path
from local_watch.collectors import macos

FX = Path(__file__).parent.parent / "fixtures"

def fake_runner(cmd):
    key = " ".join(cmd)
    table = {
        "df -P": "macos_df.txt",
        "vm_stat": "macos_vm_stat.txt",
        "softwareupdate --list": "macos_swupdate.txt",
    }
    for k, f in table.items():
        if key.startswith(k):
            return (FX / f).read_text()
    return ""

def test_macos_collect_produces_snapshot():
    snap = macos.collect(runner=fake_runner, machine="testmac", now="2026-08-29T00:00:00Z")
    assert snap.machine == "testmac" and snap.os == "macos"
    names = {m.name for m in snap.metrics}
    assert "disk_root_pct" in names and "mem_used_pct" in names
    assert 0.0 <= next(m.value for m in snap.metrics if m.name == "disk_root_pct") <= 100.0
    assert 0.0 <= next(m.value for m in snap.metrics if m.name == "mem_used_pct") <= 100.0
    assert "updates_pending" in snap.facts
    assert "reboot_required" in snap.facts

def test_macos_collect_parses_disk_and_updates():
    snap = macos.collect(runner=fake_runner, machine="testmac", now="2026-08-29T00:00:00Z")
    disk_pct = next(m.value for m in snap.metrics if m.name == "disk_root_pct")
    assert disk_pct == 5.0
    assert snap.facts["updates_pending"] == "2"
    assert snap.facts["reboot_required"] == "false"
