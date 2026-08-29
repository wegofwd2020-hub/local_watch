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
    assert st.series("box", "disk_root_pct", 5) == [80.0, 82.0]
