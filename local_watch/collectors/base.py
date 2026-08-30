from __future__ import annotations
import subprocess

def probe(cmd: list[str]) -> str | None:
    """Run a READ-ONLY command. Never raises.

    Returns stdout on success, or None if the probe could not run at all
    (binary missing, timeout, or a non-zero exit with nothing on stdout).

    The None-vs-"" distinction matters: an empty stdout from a command that
    *did* run is a real answer (`systemctl --failed` on a healthy box prints
    nothing), whereas a probe that never ran means "unknown". Collapsing both
    into "" is what made a broken collector render as a healthy machine.
    """
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except Exception:
        return None
    if r.returncode != 0 and not r.stdout.strip():
        return None
    return r.stdout
