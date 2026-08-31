from pathlib import Path
from local_watch.collectors import macos

FX = Path(__file__).parent.parent / "fixtures"

def fake_runner(cmd, timeout=None):
    key = " ".join(cmd)
    table = {
        "df -P": "macos_df.txt",
        "vm_stat": "macos_vm_stat.txt",
        "softwareupdate --list": "macos_swupdate.txt",
        "launchctl list": "macos_launchctl.txt",
    }
    for k, f in table.items():
        if key.startswith(k):
            return (FX / f).read_text()
    return ""

def test_macos_collect_produces_snapshot():
    snap = macos.collect(runner=fake_runner, machine="testmac", now="2026-08-29T00:00:00Z")
    assert snap.machine == "testmac" and snap.os == "macos"
    names = {m.name for m in snap.metrics}
    assert "disk_root_pct" in names and "mem_used_pct" in names
    assert 0.0 <= next(m.value for m in snap.metrics if m.name == "disk_root_pct") <= 100.0
    assert 0.0 <= next(m.value for m in snap.metrics if m.name == "mem_used_pct") <= 100.0
    assert "updates_pending" in snap.facts
    assert "reboot_required" in snap.facts

def test_macos_collect_parses_disk_and_updates():
    snap = macos.collect(runner=fake_runner, machine="testmac", now="2026-08-29T00:00:00Z")
    disk_pct = next(m.value for m in snap.metrics if m.name == "disk_root_pct")
    # "/" is the sealed read-only APFS system snapshot (~5%); real user data
    # lives on "/System/Volumes/Data" (~67%), which is what should be reported.
    assert disk_pct == 67.0
    assert snap.facts["updates_pending"] == "2"
    assert snap.facts["reboot_required"] == "false"


def test_macos_collect_reports_failed_launch_agents():
    # macOS analogue of `systemctl --failed`: a launchctl entry whose Status
    # column is non-zero exited badly. Without this the failed_units rule
    # could never fire on a Mac, so a dead service was invisible there.
    # The fixture also contains a signal-killed com.apple.BiomeAgent, which is
    # crash/respawn noise and must NOT appear here.
    snap = macos.collect(runner=fake_runner, machine="testmac", now="2026-08-29T00:00:00Z")
    assert snap.facts["failed_units"] == "com.example.brokenagent,com.example.killedagent"


def test_macos_collect_ignores_healthy_launch_agents():
    snap = macos.collect(runner=fake_runner, machine="testmac", now="2026-08-29T00:00:00Z")
    assert "com.apple.Finder" not in snap.facts["failed_units"]
    assert "com.wegofwd.localwatch" not in snap.facts["failed_units"]


def test_macos_collect_filters_apple_crash_respawn_noise():
    # com.apple.BiomeAgent segfaults (status -11) and is relaunched by launchd
    # constantly; it is not an actionable fleet failure, so it must be filtered
    # out rather than raising a permanent false `crit` on every Mac.
    snap = macos.collect(runner=fake_runner, machine="testmac", now="2026-08-29T00:00:00Z")
    assert "com.apple.BiomeAgent" not in snap.facts["failed_units"]


def test_failed_agents_keeps_non_apple_signal_kills():
    # A third-party agent killed by a signal is a real failure the operator can
    # act on; only Apple's own respawning daemons are treated as noise.
    out = "PID\tStatus\tLabel\n-\t-9\tcom.example.killedagent\n"
    assert macos._failed_agents(out) == "com.example.killedagent"


def test_failed_agents_keeps_apple_clean_nonzero_exit():
    # A positive (non-signal) exit code from an Apple agent is a clean failure,
    # not a crash-respawn, so it is still surfaced.
    out = "PID\tStatus\tLabel\n-\t1\tcom.apple.somethingbroken\n"
    assert macos._failed_agents(out) == "com.apple.somethingbroken"


def test_failed_agents_filters_apple_signal_kill():
    out = "PID\tStatus\tLabel\n1567\t-11\tcom.apple.BiomeAgent\n"
    assert macos._failed_agents(out) == ""
