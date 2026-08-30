"""Trend rules: the `series` argument was plumbed all the way into evaluate()
and then ignored, so README's promise of catching "a disk creeping toward
full" did not exist. A level check tells you where the disk is; only a rate
tells you how long you have."""
import datetime

from local_watch.schema import Metric, Snapshot
from local_watch.rules import evaluate

FMT = "%Y-%m-%dT%H:%M:%SZ"
BASE = datetime.datetime(2026, 8, 30, 0, 0, 0)


def rising(start, per_day, n=13, step_minutes=60):
    """n points spaced step_minutes apart, climbing at `per_day` %/day."""
    pts = []
    for i in range(n):
        mins = i * step_minutes
        ts = (BASE + datetime.timedelta(minutes=mins)).strftime(FMT)
        pts.append((ts, start + per_day * (mins / 1440.0)))
    return pts


def snap_at(points, metric="disk_root_pct"):
    """Snapshot whose current reading is the last point of the series."""
    ts = points[-1][0] if points else BASE.strftime(FMT)
    metrics = [Metric(metric, points[-1][1], "%")] if points else []
    return Snapshot("box", "linux", ts, metrics, {"probes_failed": ""})


def trend_flags(points, snap=None, key="disk_root_pct"):
    s = snap if snap is not None else snap_at(points)
    return [f for f in evaluate(s, {key: points}) if f.key == "disk_filling"]


# --- fires when the disk is actually filling --------------------------------

def test_fast_fill_projected_within_two_days_is_crit():
    # 24%/day from 70% over 12h -> at 82%, ~18h of headroom left.
    flags = trend_flags(rising(70.0, 24.0))
    assert len(flags) == 1 and flags[0].severity == "crit"


def test_fast_fill_message_reports_rate_and_eta():
    msg = trend_flags(rising(70.0, 24.0))[0].message
    assert "24" in msg and "/day" in msg and "18h" in msg


def test_moderate_fill_projected_within_a_week_is_warn():
    # 5%/day from 70% -> at 72.5%, ~5.5 days of headroom.
    flags = trend_flags(rising(70.0, 5.0))
    assert len(flags) == 1 and flags[0].severity == "warn"
    assert "5d" in flags[0].message


# --- stays quiet when there is nothing to say -------------------------------

def test_fill_projected_beyond_a_week_is_not_flagged():
    # 1%/day from 70% is ~29 days out. True, but not news.
    assert trend_flags(rising(70.0, 1.0)) == []


def test_drift_below_the_noise_floor_is_not_flagged():
    assert trend_flags(rising(70.0, 0.2)) == []


def test_flat_disk_is_not_flagged():
    assert trend_flags(rising(70.0, 0.0)) == []


def test_shrinking_disk_is_not_flagged():
    assert trend_flags(rising(80.0, -10.0)) == []


def test_too_few_points_to_fit_a_line_is_not_flagged():
    # 3 readings spanning 12h: enough time, not enough evidence.
    assert trend_flags(rising(70.0, 24.0, n=3, step_minutes=360)) == []


def test_too_short_a_span_is_not_flagged():
    # 13 readings inside one hour: extrapolating that to days is fantasy.
    assert trend_flags(rising(70.0, 24.0, n=13, step_minutes=5)) == []


def test_no_series_at_all_is_not_flagged():
    assert trend_flags([], snap=snap_at(rising(70.0, 24.0))) == []


def test_missing_current_reading_is_not_flagged():
    # Disk probe failed, so there is no level to project from.
    degraded = Snapshot("box", "linux", BASE.strftime(FMT), [], {"probes_failed": "df"})
    assert trend_flags(rising(70.0, 24.0), snap=degraded) == []


def test_memory_growth_does_not_raise_a_disk_trend_flag():
    # Memory sawtooths by design; only disk gets a projection.
    pts = rising(70.0, 24.0)
    snap = Snapshot("box", "linux", pts[-1][0], [Metric("mem_used_pct", pts[-1][1], "%")],
                    {"probes_failed": ""})
    flags = evaluate(snap, {"mem_used_pct": pts})
    assert not [f for f in flags if f.key == "disk_filling"]


def test_unreadable_timestamps_in_the_series_are_skipped():
    pts = rising(70.0, 24.0)
    pts[3] = ("not-a-timestamp", pts[3][1])
    assert len(trend_flags(pts)) == 1


def test_trend_flag_coexists_with_the_level_flag():
    # Already critically full AND filling fast: both facts are worth saying.
    pts = rising(88.0, 24.0)
    keys = {f.key for f in evaluate(snap_at(pts), {"disk_root_pct": pts})}
    assert {"disk_full", "disk_filling"} <= keys
