"""A machine must not read as healthy just because we stopped hearing from it,
or because its collector broke. Both are worse than a threshold breach: they
mean we have no idea what the box is doing."""
from local_watch.schema import Metric, Snapshot
from local_watch.rules import evaluate

FRESH = "2026-08-30T12:00:00Z"


def snap(ts=FRESH, facts=None, metrics=None):
    return Snapshot("box", "linux", ts,
                    metrics if metrics is not None else [Metric("disk_root_pct", 10.0, "%")],
                    facts if facts is not None else {"probes_failed": ""})


def keys(flags):
    return {f.key for f in flags}


# --- degraded collector -----------------------------------------------------

def test_failed_probe_raises_a_crit_flag():
    flags = evaluate(snap(facts={"probes_failed": "df,free"}), {}, now=FRESH)
    degraded = [f for f in flags if f.key == "collector_degraded"]
    assert len(degraded) == 1
    assert degraded[0].severity == "crit"


def test_degraded_flag_names_the_probes_that_failed():
    flags = evaluate(snap(facts={"probes_failed": "df,free"}), {}, now=FRESH)
    msg = next(f.message for f in flags if f.key == "collector_degraded")
    assert "df" in msg and "free" in msg


def test_healthy_collector_raises_no_degraded_flag():
    assert "collector_degraded" not in keys(evaluate(snap(), {}, now=FRESH))


def test_missing_metrics_do_not_read_as_zero_percent_used():
    # A snapshot whose disk probe failed has no disk metric at all. The old
    # code reported 0.0% and stayed silent; now the absence must be loud.
    flags = evaluate(snap(facts={"probes_failed": "df"}, metrics=[]), {}, now=FRESH)
    assert "disk_full" not in keys(flags)
    assert "collector_degraded" in keys(flags)


# --- stale snapshot ---------------------------------------------------------

def test_snapshot_older_than_the_stale_window_is_crit():
    flags = evaluate(snap(ts="2026-08-30T09:00:00Z"), {}, now=FRESH)   # 3h old
    stale = [f for f in flags if f.key == "stale"]
    assert len(stale) == 1 and stale[0].severity == "crit"


def test_stale_message_reports_the_age():
    flags = evaluate(snap(ts="2026-08-30T09:00:00Z"), {}, now=FRESH)
    assert "3h" in next(f.message for f in flags if f.key == "stale")


def test_recent_snapshot_is_not_stale():
    flags = evaluate(snap(ts="2026-08-30T11:45:00Z"), {}, now=FRESH)   # 15m old
    assert "stale" not in keys(flags)


def test_unparseable_timestamp_is_treated_as_stale():
    assert "stale" in keys(evaluate(snap(ts="not-a-timestamp"), {}, now=FRESH))


def test_staleness_is_skipped_when_no_now_is_supplied():
    # evaluate() stays usable without a clock (unit tests, replaying history).
    assert "stale" not in keys(evaluate(snap(ts="2020-01-01T00:00:00Z"), {}))
