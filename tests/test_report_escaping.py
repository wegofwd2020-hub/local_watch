"""Everything rendered into the dashboard is attacker-influenced text.

`recs` is LLM-generated, `failed_units` comes from systemctl output, and
machine names come from hostnames. All of it was interpolated raw into the
HTML, so an LLM that emitted "</pre><script>" got script execution on open.
"""
from local_watch.schema import Metric, Snapshot
from local_watch.rules import Flag
from local_watch.report import render_dashboard

PAYLOAD = "</pre><script>alert(1)</script>"


def dash(machine="box1", os_name="linux", metric_name="disk_root_pct",
         unit="%", message="all good", rec="fine"):
    snaps = [Snapshot(machine, os_name, "t", [Metric(metric_name, 93.0, unit)], {})]
    flags = [Flag(machine, "disk_full", "crit", message)]
    return render_dashboard(snaps, flags, {machine: rec}, {})


def test_llm_recommendation_cannot_inject_script():
    html = dash(rec=PAYLOAD)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_flag_message_cannot_inject_markup():
    # failed_units flows straight from systemctl output into this message.
    assert "<img" not in dash(message="Failed services: <img src=x onerror=alert(1)>")


def test_machine_name_cannot_inject_markup():
    assert "<script>" not in dash(machine="<script>alert(1)</script>")


def test_os_name_cannot_inject_markup():
    assert "<script>" not in dash(os_name="<script>alert(1)</script>")


def test_metric_name_and_unit_cannot_inject_markup():
    assert "<script>" not in dash(metric_name="<script>alert(1)</script>", unit="<b>%</b>")


def test_escaping_preserves_the_readable_text():
    html = dash(rec="Prune logs in /var/log & restart nothing")
    assert "Prune logs in /var/log &amp; restart nothing" in html
