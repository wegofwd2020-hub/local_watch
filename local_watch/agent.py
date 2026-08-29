from __future__ import annotations
from local_watch.schema import Snapshot
from local_watch.rules import Flag

def build_prompt(machine: str, snap: Snapshot, flags: list[Flag]) -> str:
    lines = [f"Machine: {machine} ({snap.os})", "Metrics:"]
    lines += [f"  {m.name} = {m.value}{m.unit}" for m in snap.metrics]
    lines.append("Active issues:")
    lines += [f"  [{fl.severity}] {fl.message}" for fl in flags] or ["  (none)"]
    lines.append("Give a short, prioritized list of safe, read-only-friendly optimization "
                 "recommendations for this machine. Do not suggest anything destructive without warning.")
    return "\n".join(lines)

def _fallback(machine: str, flags: list[Flag]) -> str:
    if not flags:
        return "No issues detected."
    return "Issues to address:\n" + "\n".join(f"- [{f.severity}] {f.message}" for f in flags)

def _default_provider():
    from wegofwd_llm.registry import build_provider   # imported lazily so tests need no key
    return build_provider(role="authoring")

def recommend(snapshots: list[Snapshot], flags: list[Flag], provider=None) -> dict[str, str]:
    if provider is None:
        try:
            provider = _default_provider()
        except Exception:
            provider = None
    out: dict[str, str] = {}
    for snap in snapshots:
        mf = [f for f in flags if f.machine == snap.machine]
        if provider is None:
            out[snap.machine] = _fallback(snap.machine, mf); continue
        try:
            out[snap.machine] = provider.complete(build_prompt(snap.machine, snap, mf)).strip()
        except Exception:
            out[snap.machine] = _fallback(snap.machine, mf)
    return out
