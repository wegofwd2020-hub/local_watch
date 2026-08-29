from local_watch.schema import Metric, Snapshot
from local_watch.rules import evaluate, Flag

def snap(disk, facts=None):
    return Snapshot("box", "linux", "t", [Metric("disk_root_pct", disk, "%")], facts or {})

def test_disk_crit_over_90():
    flags = evaluate(snap(93.0), {"disk_root_pct": [93.0]})
    assert any(f.key == "disk_full" and f.severity == "crit" for f in flags)

def test_disk_ok_under_threshold():
    assert not [f for f in evaluate(snap(40.0), {"disk_root_pct": [40.0]}) if f.key == "disk_full"]

def test_reboot_required_flag():
    flags = evaluate(snap(10.0, {"reboot_required": "true"}), {"disk_root_pct": [10.0]})
    assert any(f.key == "reboot_required" and f.severity == "warn" for f in flags)

def test_updates_pending_flag():
    flags = evaluate(snap(10.0, {"updates_pending": "12"}), {"disk_root_pct": [10.0]})
    assert any(f.key == "updates_pending" for f in flags)

def test_failed_unit_is_crit():
    flags = evaluate(snap(10.0, {"failed_units": "nginx.service"}), {"disk_root_pct": [10.0]})
    assert any(f.key == "failed_units" and f.severity == "crit" for f in flags)
