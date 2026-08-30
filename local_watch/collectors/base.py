from __future__ import annotations
import subprocess

DEFAULT_PROBE_TIMEOUT = 15
# `softwareupdate --list` round-trips to Apple's servers and routinely runs
# well past the default. Under fail-closed rules a timeout is a crit flag, not
# a silent zero, so a probe known to be slow must be given room rather than
# reporting the Mac as degraded on every cycle.
SLOW_PROBE_TIMEOUT = 120

def probe(cmd: list[str], timeout: int | None = None) -> str | None:
    """Run a READ-ONLY command. Never raises.

    Returns stdout on success, or None if the probe could not run at all
    (binary missing, timeout, or a non-zero exit with nothing on stdout).

    The None-vs-"" distinction matters: an empty stdout from a command that
    *did* run is a real answer (`systemctl --failed` on a healthy box prints
    nothing), whereas a probe that never ran means "unknown". Collapsing both
    into "" is what made a broken collector render as a healthy machine.
    """
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout or DEFAULT_PROBE_TIMEOUT)
    except Exception:
        return None
    if r.returncode != 0 and not r.stdout.strip():
        return None
    return r.stdout
