import json, sys
from pathlib import Path
from local_watch.schema import Metric, Snapshot
from local_watch import cli

def test_ingest_then_render(tmp_path, monkeypatch):
    snapf = tmp_path / "s.json"
    snapf.write_text(Snapshot("box", "linux", "2026-08-29T00:00:00Z",
                              [Metric("disk_root_pct", 93.0, "%")], {}).to_json())
    db = tmp_path / "m.sqlite"; html = tmp_path / "d.html"; md = tmp_path / "r.md"
    # no LLM: agent falls back to flags-only (no provider/key in test env)
    cli.main(["ingest", "--store", str(db), str(snapf)])
    cli.main(["render", "--store", str(db), "--html", str(html), "--md", str(md)])
    assert "box" in html.read_text() and "93" in html.read_text()
    assert "Root filesystem 93% full" in md.read_text()
