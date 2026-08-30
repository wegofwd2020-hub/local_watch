from local_watch.schema import Metric, Snapshot
from local_watch.rules import evaluate, Flag

def snap(disk, facts=None, mem=None):
    metrics = [Metric("disk_root_pct", disk, "%")]
    if mem is not None:
        metrics.append(Metric("mem_used_pct", mem, "%"))
    return Snapshot("box", "linux", "t", metrics, facts or {})

def test_disk_crit_over_90():
    flags = evaluate(snap(93.0), {})
    assert any(f.key == "disk_full" and f.severity == "crit" for f in flags)

def test_disk_ok_under_threshold():
    assert not [f for f in evaluate(snap(40.0), {}) if f.key == "disk_full"]

def test_reboot_required_flag():
    flags = evaluate(snap(10.0, {"reboot_required": "true"}), {})
    assert any(f.key == "reboot_required" and f.severity == "warn" for f in flags)

def test_updates_pending_flag():
    flags = evaluate(snap(10.0, {"updates_pending": "12"}), {})
    assert any(f.key == "updates_pending" for f in flags)

def test_failed_unit_is_crit():
    flags = evaluate(snap(10.0, {"failed_units": "nginx.service"}), {})
    assert any(f.key == "failed_units" and f.severity == "crit" for f in flags)

# Fix round 1: coverage gap tests

# 1. updates_pending severity boundary
def test_updates_pending_count_12_is_info():
    """Count 12 updates → severity == 'info' (threshold <20)"""
    flags = evaluate(snap(10.0, {"updates_pending": "12"}), {})
    upd_flag = next((f for f in flags if f.key == "updates_pending"), None)
    assert upd_flag is not None
    assert upd_flag.severity == "info"

def test_updates_pending_count_20_is_warn():
    """Count 20 updates → severity == 'warn' (boundary: >=20)"""
    flags = evaluate(snap(10.0, {"updates_pending": "20"}), {})
    upd_flag = next((f for f in flags if f.key == "updates_pending"), None)
    assert upd_flag is not None
    assert upd_flag.severity == "warn"

# 2. Negative tests (no flag when under threshold)
def test_mem_50_no_pressure():
    """Memory at 50% → no mem_pressure flag"""
    flags = evaluate(snap(10.0, mem=50.0), {})
    assert not any(f.key == "mem_pressure" for f in flags)

def test_no_reboot_required_fact():
    """No reboot_required fact → no reboot_required flag"""
    flags = evaluate(snap(10.0), {})
    assert not any(f.key == "reboot_required" for f in flags)

def test_empty_failed_units():
    """Empty failed_units → no failed_units flag"""
    flags = evaluate(snap(10.0, {"failed_units": ""}), {})
    assert not any(f.key == "failed_units" for f in flags)

# 3. Disk boundary tests
def test_disk_80_is_warn():
    """Disk at exactly 80% → disk_full flag with severity == 'warn'"""
    flags = evaluate(snap(80.0), {})
    disk_flag = next((f for f in flags if f.key == "disk_full"), None)
    assert disk_flag is not None
    assert disk_flag.severity == "warn"

def test_disk_90_is_crit():
    """Disk at exactly 90% → disk_full flag with severity == 'crit'"""
    flags = evaluate(snap(90.0), {})
    disk_flag = next((f for f in flags if f.key == "disk_full"), None)
    assert disk_flag is not None
    assert disk_flag.severity == "crit"

def test_updates_pending_non_numeric_does_not_crash():
    """Non-numeric updates_pending fact must not raise and must not flag."""
    flags = evaluate(snap(10.0, {"updates_pending": "unknown"}), {})
    assert not any(f.key == "updates_pending" for f in flags)
