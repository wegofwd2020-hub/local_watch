from local_watch.schema import Metric, Snapshot
from local_watch.rules import Flag
from local_watch.report import render_dashboard, render_markdown

SNAPS = [Snapshot("box1", "linux", "t", [Metric("disk_root_pct", 93.0, "%")], {})]
FLAGS = [Flag("box1", "disk_full", "crit", "Root filesystem 93% full")]
RECS = {"box1": "Prune old logs."}
SERIES = {"box1": {"disk_root_pct": [80.0, 85.0, 93.0]}}

def test_dashboard_is_self_contained_html():
    html = render_dashboard(SNAPS, FLAGS, RECS, SERIES)
    assert "<html" in html.lower() and "box1" in html
    assert "93" in html and "Prune old logs." in html
    assert "http://" not in html and "https://" not in html   # no external assets
    assert "<svg" in html   # sparkline present

def test_markdown_lists_machine_and_flags():
    md = render_markdown(SNAPS, FLAGS, RECS)
    assert "box1" in md and "Root filesystem 93% full" in md and "Prune old logs." in md
