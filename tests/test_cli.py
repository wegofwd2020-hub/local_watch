import json, sys
from pathlib import Path
from local_watch.schema import Metric, Snapshot
from local_watch import cli
import local_watch.agent as agent

def test_ingest_then_render(tmp_path, monkeypatch):
    snapf = tmp_path / "s.json"
    snapf.write_text(Snapshot("box", "linux", cli._now(),
                              [Metric("disk_root_pct", 93.0, "%")], {}).to_json())
    db = tmp_path / "m.sqlite"; html = tmp_path / "d.html"; md = tmp_path / "r.md"
    # Force the offline path deterministically: don't rely on wegofwd_llm being
    # absent or no key being configured on the host (a real key can exist at
    # ~/.config/wegofwd/anthropic_api_key) — that would make this a live call.
    monkeypatch.setattr(agent, "_default_provider", lambda: None)
    cli.main(["ingest", "--store", str(db), str(snapf)])
    cli.main(["render", "--store", str(db), "--html", str(html), "--md", str(md)])
    assert "box" in html.read_text() and "93" in html.read_text()
    assert "Root filesystem 93% full" in md.read_text()


def _write_snap(path, ts):
    path.write_text(Snapshot("box", "linux", ts, [Metric("disk_root_pct", 10.0, "%")],
                             {"probes_failed": ""}).to_json())
    return path


def _render(tmp_path, monkeypatch, ts):
    """Ingest one snapshot stamped `ts`, render, return the markdown report."""
    monkeypatch.setattr(agent, "_default_provider", lambda: None)
    snapf = _write_snap(tmp_path / "s.json", ts)
    db = tmp_path / "m.sqlite"
    html = tmp_path / "d.html"
    md = tmp_path / "r.md"
    cli.main(["ingest", "--store", str(db), str(snapf)])
    cli.main(["render", "--store", str(db), "--html", str(html), "--md", str(md)])
    return md.read_text()


def test_render_flags_a_machine_that_stopped_reporting(tmp_path, monkeypatch):
    # The CLI must hand rules.evaluate the current time, or staleness can
    # never fire in the only place it matters.
    assert "stale" in _render(tmp_path, monkeypatch, "2020-01-01T00:00:00Z").lower()


def test_render_does_not_flag_a_fresh_machine_as_stale(tmp_path, monkeypatch):
    assert "stale" not in _render(tmp_path, monkeypatch, cli._now()).lower()


def test_render_draws_a_sparkline_from_multiple_snapshots(tmp_path, monkeypatch):
    # Two readings is the point at which the sparkline actually draws; with a
    # single snapshot it short-circuits and hides shape bugs in the series.
    monkeypatch.setattr(agent, "_default_provider", lambda: None)
    db = tmp_path / "m.sqlite"
    html = tmp_path / "d.html"
    md = tmp_path / "r.md"
    for i, (ts, disk) in enumerate([("2026-08-30T10:00:00Z", 80.0), ("2026-08-30T11:00:00Z", 81.0)]):
        f = tmp_path / f"s{i}.json"
        f.write_text(Snapshot("box", "linux", ts, [Metric("disk_root_pct", disk, "%")],
                              {"probes_failed": ""}).to_json())
        cli.main(["ingest", "--store", str(db), str(f)])
    cli.main(["render", "--store", str(db), "--html", str(html), "--md", str(md)])
    assert "<polyline" in html.read_text()


def test_render_reads_enough_history_to_project_a_filling_disk(tmp_path, monkeypatch):
    # A densely-sampling box (every 5 min) packs a lot of readings into a
    # short window. If render only pulls the last 20 points it sees 95
    # minutes of history — too short a span to project from — and the disk
    # trend can never fire on exactly the machines reporting most often.
    import datetime
    from local_watch.store import Store

    monkeypatch.setattr(agent, "_default_provider", lambda: None)
    db = tmp_path / "m.sqlite"
    html = tmp_path / "d.html"
    md = tmp_path / "r.md"
    st = Store(str(db))
    base = datetime.datetime(2026, 8, 30, 0, 0, 0)
    for i in range(100):                       # 100 x 5min = 8.25h of history
        ts = (base + datetime.timedelta(minutes=5 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        st.append(Snapshot("box", "linux", ts,
                           [Metric("disk_root_pct", 80.0 + i * 0.05, "%")],
                           {"probes_failed": ""}))
    cli.main(["render", "--store", str(db), "--html", str(html), "--md", str(md)])
    assert "filling" in md.read_text()
