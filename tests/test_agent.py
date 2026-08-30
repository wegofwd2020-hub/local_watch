from local_watch.schema import Metric, Snapshot
from local_watch.rules import Flag
from local_watch.agent import recommend, build_prompt
import local_watch.agent as agent_mod

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


HEALTHY = Snapshot("box", "linux", "t", [Metric("disk_root_pct", 10.0, "%")], {})


def _offline(monkeypatch):
    """Force the no-LLM path without depending on the host lacking a key."""
    monkeypatch.setattr(agent_mod, "_default_provider", lambda: None)


def test_fallback_output_is_labelled_as_rules_only(monkeypatch):
    # Otherwise "No issues detected." from a dead LLM is byte-identical to
    # "No issues detected." from a healthy one — the reader cannot tell that
    # the recommendation engine never ran.
    _offline(monkeypatch)
    assert agent_mod.FALLBACK_NOTICE in recommend([HEALTHY], [])["box"]


def test_fallback_is_labelled_even_when_there_are_flags(monkeypatch):
    _offline(monkeypatch)
    out = recommend([SNAP], FLAGS)["box"]
    assert agent_mod.FALLBACK_NOTICE in out and "93% full" in out


def test_provider_error_produces_a_labelled_fallback():
    out = recommend([SNAP], FLAGS, provider=_BoomProvider())["box"]
    assert agent_mod.FALLBACK_NOTICE in out


def test_successful_llm_output_carries_no_fallback_label():
    out = recommend([SNAP], FLAGS, provider=_FakeProvider())["box"]
    assert agent_mod.FALLBACK_NOTICE not in out


def test_fallback_notice_says_the_llm_did_not_run():
    assert "llm" in agent_mod.FALLBACK_NOTICE.lower()
