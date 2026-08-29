from local_watch.schema import Metric, Snapshot

def test_snapshot_roundtrip():
    s = Snapshot(machine="mambakkam", os="linux", ts="2026-08-29T12:00:00Z",
                 metrics=[Metric("disk_root_pct", 87.5, "%"), Metric("mem_used_pct", 61.0, "%")],
                 facts={"reboot_required": "false", "updates_pending": "4"})
    back = Snapshot.from_json(s.to_json())
    assert back == s
    assert back.metrics[0].name == "disk_root_pct" and back.metrics[0].value == 87.5

def test_metric_defaults_and_types():
    m = Metric("cpu_load1", 0.4)
    assert isinstance(m.value, float)
    assert m.unit == ""
