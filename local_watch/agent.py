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

# Printed with every rules-only answer. Without it a fallback reading
# "No issues detected." is indistinguishable from the same sentence produced by
# a healthy LLM — the reader cannot tell the recommendation engine never ran.
FALLBACK_NOTICE = "[LLM unavailable - deterministic rules only]"

def _fallback(flags: list[Flag]) -> str:
    body = ("No issues detected." if not flags else
            "Issues to address:\n" + "\n".join(f"- [{f.severity}] {f.message}" for f in flags))
    return f"{FALLBACK_NOTICE}\n{body}"

def _default_provider():
    # Imported/read lazily so importing this module + running tests never needs
    # wegofwd-llm installed or a key on disk.
    import os
    from wegofwd_llm.registry import build_provider
    from wegofwd_llm.contract import LLMRequest
    key = open(os.path.expanduser("~/.config/wegofwd/anthropic_api_key")).read().strip()
    # Pinned to 4-6 deliberately. wegofwd-llm 0.2.0's generate() always sends
    # `temperature`, and the current-generation models (claude-sonnet-5,
    # claude-opus-5) reject it: 400 invalid_request_error, "`temperature` is
    # deprecated for this model". Passing temperature=None does not help — the
    # SDK serialises it as null, which is also rejected. Moving to a newer
    # model requires wegofwd-llm to stop sending temperature unconditionally.
    real = build_provider("anthropic", api_key=key, model="claude-sonnet-4-6")

    class _Adapter:
        def complete(self, prompt: str) -> str:
            return real.generate(LLMRequest(prompt=prompt)).text

    return _Adapter()

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
            out[snap.machine] = _fallback(mf); continue
        try:
            out[snap.machine] = provider.complete(build_prompt(snap.machine, snap, mf)).strip()
        except Exception:
            out[snap.machine] = _fallback(mf)
    return out
