from __future__ import annotations
import subprocess

def probe(cmd: list[str]) -> str:
    """Run a READ-ONLY command; return stdout, or "" on any failure. Never raises."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return ""
