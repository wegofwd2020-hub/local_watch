"""A probe that fails must NOT render as a healthy machine.

Before this, base.probe swallowed every failure into "" and each parser then
returned 0.0 / 0 — so a broken collector produced a snapshot that looked
perfect. These tests pin the opposite: a failed probe drops the metric it
would have fed and names itself in the `probes_failed` fact.
"""
from pathlib import Path

from local_watch.collectors import linux, macos
from local_watch.collectors.base import probe

FX = Path(__file__).parent.parent / "fixtures"

_LINUX_FIXTURES = {
    "df": "linux_df.txt", "free": "linux_free.txt",
    "apt": "linux_aptlist.txt", "systemctl": "linux_failed.txt",
}
_MACOS_FIXTURES = {
    "df": "macos_df.txt", "vm_stat": "macos_vm_stat.txt",
    "softwareupdate": "macos_swupdate.txt", "launchctl": "macos_launchctl.txt",
}


def _runner(fixtures, failing=(), blank=()):
    """Fixture-backed runner; `failing` commands return None (probe failure),
    `blank` commands return "" (probe ran, produced nothing parseable)."""
    def run(cmd, timeout=None):
        if cmd[0] in failing:
            return None
        if cmd[0] in blank:
            return ""
        return (FX / fixtures[cmd[0]]).read_text()
    return run


def _metric_names(snap):
    return {m.name for m in snap.metrics}


# --- base.probe: distinguish "ran, said nothing" from "did not run" ---------

def test_probe_returns_none_when_binary_is_missing():
    assert probe(["local-watch-no-such-binary-xyz"]) is None


def test_probe_returns_none_on_nonzero_exit_with_no_output():
    assert probe(["false"]) is None


def test_probe_returns_empty_string_when_command_succeeds_silently():
    # `true` exits 0 and prints nothing. That is a real, healthy answer
    # (e.g. `systemctl --failed` on a box with no failed units) and must be
    # distinguishable from a probe that could not run at all.
    assert probe(["true"]) == ""


def test_probe_returns_stdout_on_success():
    assert probe(["echo", "hi"]) == "hi\n"


# --- linux ------------------------------------------------------------------

def test_linux_healthy_collect_reports_no_failed_probes():
    snap = linux.collect(runner=_runner(_LINUX_FIXTURES), machine="box", now="t")
    assert snap.facts["probes_failed"] == ""


def test_linux_failed_df_drops_disk_metric_instead_of_reporting_zero():
    snap = linux.collect(runner=_runner(_LINUX_FIXTURES, failing=["df"]), machine="box", now="t")
    assert "disk_root_pct" not in _metric_names(snap)
    assert "df" in snap.facts["probes_failed"]


def test_linux_unparseable_df_counts_as_a_failed_probe():
    # df ran but emitted nothing with a "/" row — 0.0% is a lie, not a reading.
    snap = linux.collect(runner=_runner(_LINUX_FIXTURES, blank=["df"]), machine="box", now="t")
    assert "disk_root_pct" not in _metric_names(snap)
    assert "df" in snap.facts["probes_failed"]


def test_linux_failed_apt_omits_updates_pending_fact():
    snap = linux.collect(runner=_runner(_LINUX_FIXTURES, failing=["apt"]), machine="box", now="t")
    assert "updates_pending" not in snap.facts
    assert "apt" in snap.facts["probes_failed"]


def test_linux_failed_systemctl_omits_failed_units_fact():
    # An empty `systemctl --failed` legitimately means "nothing failed"; a
    # systemctl that could not run means "unknown" and must not read as OK.
    snap = linux.collect(runner=_runner(_LINUX_FIXTURES, failing=["systemctl"]), machine="box", now="t")
    assert "failed_units" not in snap.facts
    assert "systemctl" in snap.facts["probes_failed"]


def test_linux_silent_systemctl_means_no_failed_units():
    snap = linux.collect(runner=_runner(_LINUX_FIXTURES, blank=["systemctl"]), machine="box", now="t")
    assert snap.facts["failed_units"] == ""
    assert "systemctl" not in snap.facts["probes_failed"]


def test_linux_lists_every_failed_probe():
    snap = linux.collect(runner=_runner(_LINUX_FIXTURES, failing=["df", "free"]), machine="box", now="t")
    assert snap.facts["probes_failed"] == "df,free"
    assert _metric_names(snap) == set()


# --- macos ------------------------------------------------------------------

def test_macos_healthy_collect_reports_no_failed_probes():
    snap = macos.collect(runner=_runner(_MACOS_FIXTURES), machine="mac", now="t")
    assert snap.facts["probes_failed"] == ""


def test_macos_failed_vm_stat_drops_mem_metric():
    snap = macos.collect(runner=_runner(_MACOS_FIXTURES, failing=["vm_stat"]), machine="mac", now="t")
    assert "mem_used_pct" not in _metric_names(snap)
    assert "vm_stat" in snap.facts["probes_failed"]


def test_macos_failed_softwareupdate_omits_updates_pending_fact():
    snap = macos.collect(runner=_runner(_MACOS_FIXTURES, failing=["softwareupdate"]), machine="mac", now="t")
    assert "updates_pending" not in snap.facts
    assert "softwareupdate" in snap.facts["probes_failed"]


def test_macos_failed_launchctl_omits_failed_units_fact():
    # Same discipline as Linux systemctl: "could not ask" must not read as
    # "nothing is broken".
    snap = macos.collect(runner=_runner(_MACOS_FIXTURES, failing=["launchctl"]), machine="mac", now="t")
    assert "failed_units" not in snap.facts
    assert "launchctl" in snap.facts["probes_failed"]


def test_macos_silent_launchctl_means_no_failed_agents():
    snap = macos.collect(runner=_runner(_MACOS_FIXTURES, blank=["launchctl"]), machine="mac", now="t")
    assert snap.facts["failed_units"] == ""
    assert "launchctl" not in snap.facts["probes_failed"]
