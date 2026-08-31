"""The dashboard rendered every metric the same way — "name: value" plus an
identical sparkline — and gave the facts (updates_pending, failed_units,
reboot_required, probes_failed) no visual at all; they surfaced only as flag
text. Each kind of data now gets the form that fits it.
"""
from local_watch.schema import Metric, Snapshot
from local_watch.rules import Flag
from local_watch.report import render_dashboard

NOW = "2026-08-31T12:00:00Z"


def dash(machine="box1", ts=NOW, metrics=None, facts=None, flags=None,
         recs=None, series=None, now=NOW):
    snap = Snapshot(machine, "linux", ts,
                    metrics if metrics is not None else [Metric("disk_root_pct", 42.0, "%")],
                    facts if facts is not None else {"probes_failed": ""})
    return render_dashboard([snap], flags or [], recs or {}, series or {}, now=now)


# --- fleet strip ------------------------------------------------------------

def test_fleet_strip_has_a_row_for_every_machine():
    snaps = [Snapshot("box1", "linux", NOW, [Metric("disk_root_pct", 10.0, "%")], {}),
             Snapshot("box2", "linux", NOW, [Metric("disk_root_pct", 20.0, "%")], {})]
    html = render_dashboard(snaps, [], {}, {}, now=NOW)
    assert html.count("class='fleet-row") == 2


def test_fleet_strip_reports_the_worst_severity_per_machine():
    flags = [Flag("box1", "disk_full", "crit", "Root filesystem 93% full"),
             Flag("box1", "updates_pending", "info", "3 package updates pending")]
    assert "sev-crit" in dash(flags=flags)


# --- disk: a ratio against a limit -> meter ---------------------------------

def test_disk_renders_as_a_meter_not_a_bare_number():
    assert "meter" in dash(metrics=[Metric("disk_root_pct", 42.0, "%")])


def test_disk_meter_marks_the_rule_thresholds():
    # The rules warn at 80 and crit at 90; a meter without them makes the
    # reader guess whether 78% is fine.
    html = dash(metrics=[Metric("disk_root_pct", 42.0, "%")])
    assert "threshold" in html and "80" in html and "90" in html


def test_disk_meter_is_tinted_by_the_band_it_is_in():
    assert "meter meter-crit" in dash(metrics=[Metric("disk_root_pct", 93.0, "%")])
    assert "meter meter-warn" in dash(metrics=[Metric("disk_root_pct", 84.0, "%")])
    assert "meter meter-good" in dash(metrics=[Metric("disk_root_pct", 30.0, "%")])


def test_disk_meter_always_shows_the_number_so_colour_is_never_alone():
    assert "93" in dash(metrics=[Metric("disk_root_pct", 93.0, "%")])


# --- memory: sawtoothing series -> sparkline-led -----------------------------

def test_memory_renders_a_sparkline_when_history_exists():
    pts = [(f"2026-08-31T1{i}:00:00Z", 40.0 + i) for i in range(5)]
    html = dash(metrics=[Metric("mem_used_pct", 44.0, "%")],
                series={"box1": {"mem_used_pct": pts}})
    assert "<polyline" in html


def test_sparkline_carries_a_title_so_it_has_a_hover_value_without_javascript():
    pts = [(f"2026-08-31T1{i}:00:00Z", 40.0 + i) for i in range(5)]
    html = dash(metrics=[Metric("mem_used_pct", 44.0, "%")],
                series={"box1": {"mem_used_pct": pts}})
    assert "<title>" in html


# --- facts: each gets a form that fits --------------------------------------

def test_pending_updates_render_as_a_stat_tile_with_the_count():
    html = dash(facts={"updates_pending": "48", "probes_failed": ""})
    assert "stat" in html and "48" in html


def test_each_failed_unit_gets_its_own_chip():
    html = dash(facts={"failed_units": "nginx.service,redis.service", "probes_failed": ""})
    assert html.count("chip chip-crit") == 2
    assert "nginx.service" in html and "redis.service" in html


def test_no_failed_units_reads_as_an_explicit_ok_not_an_empty_space():
    html = dash(facts={"failed_units": "", "probes_failed": ""})
    assert "chip chip-good" in html


def test_reboot_required_shows_a_pill_only_when_it_is_true():
    assert "reboot" in dash(facts={"reboot_required": "true", "probes_failed": ""}).lower()
    assert "reboot" not in dash(facts={"reboot_required": "false", "probes_failed": ""}).lower()


def test_failed_probes_are_shown_as_missing_data_not_as_a_zero():
    html = dash(facts={"probes_failed": "df,free"})
    assert "chip chip-warn" in html
    assert "df" in html and "free" in html


# --- freshness --------------------------------------------------------------

def test_card_header_shows_how_old_the_reading_is():
    assert "18m ago" in dash(ts="2026-08-31T11:42:00Z", now=NOW)


def test_missing_metric_is_absent_rather_than_drawn_as_zero():
    # A failed df probe drops the metric entirely; the card must not imply 0%.
    html = dash(metrics=[], facts={"probes_failed": "df"})
    assert "meter meter-good" not in html


def test_two_readings_do_not_get_drawn_as_a_trend_line():
    """A line through two points is a straight segment at whatever angle the
    pair happens to make — it implies a direction the data has not earned. A
    freshly-installed machine has exactly this, and it rendered as the loudest
    mark on the card."""
    pts = [("2026-08-31T11:00:00Z", 89.0), ("2026-08-31T11:20:00Z", 28.6)]
    html = dash(metrics=[Metric("mem_used_pct", 28.6, "%")], series={"box1": {"mem_used_pct": pts}})
    assert "<polyline" not in html


def test_two_readings_say_so_rather_than_leaving_a_blank():
    pts = [("2026-08-31T11:00:00Z", 89.0), ("2026-08-31T11:20:00Z", 28.6)]
    html = dash(metrics=[Metric("mem_used_pct", 28.6, "%")], series={"box1": {"mem_used_pct": pts}})
    assert ">2 readings<" in html


def test_three_readings_are_enough_to_draw_a_shape():
    pts = [(f"2026-08-31T1{i}:00:00Z", 40.0 + i) for i in range(3)]
    html = dash(metrics=[Metric("mem_used_pct", 42.0, "%")], series={"box1": {"mem_used_pct": pts}})
    assert "<polyline" in html


def test_narrow_viewports_get_a_stacked_layout():
    """The fleet strip is a five-column grid; below ~720px those columns
    crush into unreadable slivers. Verified by rule, not by eye — the narrow
    rendering has not been looked at in a browser."""
    html = dash()
    assert "@media (max-width:720px)" in html
