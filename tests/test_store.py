from local_watch.schema import Metric, Snapshot
from local_watch.store import Store

def _snap(ts, disk):
    return Snapshot("box", "linux", ts, [Metric("disk_root_pct", disk, "%")], {})

def test_append_latest_series(tmp_path):
    st = Store(str(tmp_path / "m.sqlite"))
    st.append(_snap("2026-08-29T00:00:00Z", 80.0))
    st.append(_snap("2026-08-29T01:00:00Z", 82.0))
    assert st.machines() == ["box"]
    assert st.latest("box").metrics[0].value == 82.0
    # (ts, value) pairs, oldest first: a trend projection is meaningless
    # without knowing how far apart the readings are.
    assert st.series("box", "disk_root_pct", 5) == [
        ("2026-08-29T00:00:00Z", 80.0), ("2026-08-29T01:00:00Z", 82.0)]


def test_series_is_capped_and_keeps_the_most_recent_points(tmp_path):
    st = Store(str(tmp_path / "m.sqlite"))
    for h in range(5):
        st.append(_snap(f"2026-08-29T0{h}:00:00Z", 70.0 + h))
    assert st.series("box", "disk_root_pct", 2) == [
        ("2026-08-29T03:00:00Z", 73.0), ("2026-08-29T04:00:00Z", 74.0)]


def test_series_is_empty_for_a_metric_that_was_never_collected(tmp_path):
    st = Store(str(tmp_path / "m.sqlite"))
    st.append(_snap("2026-08-29T00:00:00Z", 80.0))
    assert st.series("box", "mem_used_pct", 5) == []
