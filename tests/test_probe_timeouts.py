"""Not every read-only probe is fast.

`softwareupdate --list` round-trips to Apple and routinely runs far past the
15s default. Under the fail-closed rules that is no longer a silent "0
updates" — it lands in probes_failed and raises a crit collector_degraded on
the Mac every single cycle, which would make the dashboard useless on exactly
one machine. Slow probes therefore ask for more time explicitly.
"""
from pathlib import Path

from local_watch.collectors import base, linux, macos

FX = Path(__file__).parent.parent / "fixtures"
_MACOS = {"df": "macos_df.txt", "vm_stat": "macos_vm_stat.txt",
          "softwareupdate": "macos_swupdate.txt", "launchctl": "macos_launchctl.txt"}
_LINUX = {"df": "linux_df.txt", "free": "linux_free.txt",
          "apt": "linux_aptlist.txt", "systemctl": "linux_failed.txt"}


def spy(fixtures):
    """Runner that records the timeout each probe asked for."""
    seen = {}

    def run(cmd, timeout=None):
        seen[cmd[0]] = timeout
        return (FX / fixtures[cmd[0]]).read_text()

    return run, seen


def test_slow_probe_constant_allows_more_than_a_minute():
    assert base.SLOW_PROBE_TIMEOUT > 60


def test_macos_gives_softwareupdate_the_slow_timeout():
    run, seen = spy(_MACOS)
    macos.collect(runner=run, machine="mac", now="t")
    assert seen["softwareupdate"] == base.SLOW_PROBE_TIMEOUT


def test_macos_leaves_fast_probes_on_the_default_timeout():
    run, seen = spy(_MACOS)
    macos.collect(runner=run, machine="mac", now="t")
    assert seen["df"] is None and seen["vm_stat"] is None and seen["launchctl"] is None


def test_linux_probes_all_use_the_default_timeout():
    # apt list --upgradable measured 0.48s on the deployed box; no case for
    # widening the window without evidence.
    run, seen = spy(_LINUX)
    linux.collect(runner=run, machine="box", now="t")
    assert set(seen.values()) == {None}


def test_probe_accepts_an_explicit_timeout():
    assert base.probe(["echo", "hi"], timeout=base.SLOW_PROBE_TIMEOUT) == "hi\n"


def test_probe_defaults_to_the_fast_timeout():
    assert base.DEFAULT_PROBE_TIMEOUT == 15
