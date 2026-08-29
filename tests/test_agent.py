from local_watch.schema import Metric, Snapshot
from local_watch.rules import Flag
from local_watch.agent import recommend, build_prompt

SNAP = Snapshot("box", "linux", "t", [Metric("disk_root_pct", 93.0, "%")], {})
FLAGS = [Flag("box", "disk_full", "crit", "Root filesystem 93% full")]

def test_build_prompt_mentions_flag():
    p = build_prompt("box", SNAP, FLAGS)
    assert "disk" in p.lower() and "93" in p

class _FakeProvider:
    def complete(self, prompt, **kw): return "Free space by pruning old logs."

def test_recommend_uses_provider():
    out = recommend([SNAP], FLAGS, provider=_FakeProvider())
    assert "prun" in out["box"].lower()

class _BoomProvider:
    def complete(self, prompt, **kw): raise RuntimeError("no key")

def test_recommend_falls_back_to_flags_on_error():
    out = recommend([SNAP], FLAGS, provider=_BoomProvider())
    assert "93% full" in out["box"]   # deterministic fallback lists the flags
