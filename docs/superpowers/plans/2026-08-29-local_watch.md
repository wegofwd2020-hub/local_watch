# local_watch v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only fleet monitor that collects system metrics on each machine, stores history centrally, flags problems with deterministic rules, writes LLM optimization recommendations, and renders a self-contained fleet dashboard surfaced through wegofwd-hub.

**Architecture:** A pure-Python pipeline. Per-OS collectors turn read-only shell probes into a common `Snapshot` (JSON). Snapshots land in a SQLite history store on the aggregator (`mambakkam`). A pure `rules` layer turns (history, latest) into severity-tagged `Flag`s. An `agent` sends the aggregate + flags to an LLM (via `wegofwd-llm`, BYOK) for plain-language recommendations, degrading to flags-only if the LLM is unavailable. A `report` layer renders a self-contained HTML dashboard + a Markdown report. A CLI ties the stages together; a wegofwd-hub tile serves the dashboard live.

**Tech Stack:** Python 3.11+, stdlib + `wegofwd-llm`; SQLite (stdlib `sqlite3`); pytest. No web framework (dashboard is static HTML with inline CSS + inline SVG sparklines). systemd/launchd for scheduling (deploy task).

**Spec:** `docs/superpowers/specs/2026-08-29-local_watch-design.md` (read it alongside this plan).

## Global Constraints

- **Python 3.11+.** Core (`schema`, `store`, `rules`, `report`) is **pure stdlib**; only `agent` imports `wegofwd-llm`.
- **READ-ONLY, non-negotiable.** No code path runs a state-changing command. Collectors invoke only read probes: `df`, `free`/`vm_stat`, `uptime`, `sensors`/`powermetrics`, `ps`, `apt-get -s`/`--just-print` or `apt list --upgradable`, `softwareupdate --list`, `systemctl --failed`, `who -b`. A collector must never write, kill, install, or configure. The LLM output is **text only** — nothing parses it into actions.
- **No live external calls in tests.** Collector tests parse **fixture** command output (no real shell probes of the host under test where avoidable); the agent test mocks the `wegofwd-llm` provider. No live SSH, no live machines, no live LLM in CI.
- **Common snapshot schema is the contract.** Every OS collector emits the same `Snapshot`; store/rules/agent/report are OS-agnostic and never branch on OS.
- **Commit after every task.** Run `ruff`/`pytest` green before each commit.
- Repo: `local_watch` (private). Runs from the repo root; `pyproject.toml` sets `pythonpath`/package.

---

## File Structure

```
local_watch/
  pyproject.toml
  local_watch/
    __init__.py
    schema.py          # Metric, Snapshot dataclasses + to_json/from_json
    collectors/
      __init__.py
      base.py          # probe() helper (read-only subprocess) + Collector protocol
      linux.py         # collect() -> Snapshot   (Linux probes)
      macos.py         # collect() -> Snapshot   (macOS probes)
    store.py           # SQLite: append(snapshot), latest(machine), series(machine, metric, n)
    rules.py           # evaluate(latest, history) -> list[Flag]   (pure)
    agent.py           # recommend(snapshots, flags) -> dict[str,str]   (wegofwd-llm; fallback)
    report.py          # render_dashboard(...) -> str(html) ; render_markdown(...) -> str
    cli.py             # collect | ingest | review | render
  tests/
    test_schema.py test_linux_collector.py test_store.py test_rules.py
    test_agent.py test_report.py test_cli.py
  fixtures/            # captured read-only command outputs (linux_*.txt, macos_*.txt)
  deploy/              # systemd .timer/.service, launchd plist, sync notes (operator task)
```

One responsibility per file; `rules.py` and `report.py` are pure (no I/O) and carry the correctness weight.

---

### Task 1: Scaffold + snapshot schema

**Files:**
- Create: `pyproject.toml`, `local_watch/__init__.py`, `local_watch/schema.py`
- Test: `tests/test_schema.py`

**Interfaces:**
- Produces: `Metric(name:str, value:float, unit:str)`; `Snapshot(machine:str, os:str, ts:str, metrics:list[Metric], facts:dict[str,str])`; `Snapshot.to_json()->str`, `Snapshot.from_json(s:str)->Snapshot`. `facts` holds non-numeric state (e.g. `{"reboot_required":"true","updates_pending":"3","failed_units":"nginx.service"}`).

- [ ] **Step 1: pyproject.toml**
```toml
[project]
name = "local_watch"
version = "0.0.1"
requires-python = ">=3.11"
dependencies = []            # wegofwd-llm added in Task 5
[project.optional-dependencies]
dev = ["pytest", "ruff"]
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 2: Write the failing test** — `tests/test_schema.py`
```python
from local_watch.schema import Metric, Snapshot

def test_snapshot_roundtrip():
    s = Snapshot(machine="mambakkam", os="linux", ts="2026-08-29T12:00:00Z",
                 metrics=[Metric("disk_root_pct", 87.5, "%"), Metric("mem_used_pct", 61.0, "%")],
                 facts={"reboot_required": "false", "updates_pending": "4"})
    back = Snapshot.from_json(s.to_json())
    assert back == s
    assert back.metrics[0].name == "disk_root_pct" and back.metrics[0].value == 87.5

def test_metric_defaults_and_types():
    m = Metric("cpu_load1", 0.4, "")
    assert isinstance(m.value, float)
```

- [ ] **Step 3: Run test to verify it fails** — `pytest tests/test_schema.py -v` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 4: Minimal implementation** — `local_watch/schema.py`
```python
from __future__ import annotations
import json
from dataclasses import dataclass, asdict, field

@dataclass(frozen=True)
class Metric:
    name: str
    value: float
    unit: str = ""

@dataclass(frozen=True)
class Snapshot:
    machine: str
    os: str
    ts: str                       # ISO-8601 UTC
    metrics: list[Metric] = field(default_factory=list)
    facts: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> "Snapshot":
        d = json.loads(s)
        return cls(machine=d["machine"], os=d["os"], ts=d["ts"],
                   metrics=[Metric(**m) for m in d.get("metrics", [])],
                   facts=d.get("facts", {}))
```

- [ ] **Step 5: Run tests** — `pytest tests/test_schema.py -v` → PASS (2).

- [ ] **Step 6: Commit**
```bash
git add pyproject.toml local_watch/__init__.py local_watch/schema.py tests/test_schema.py
git commit -m "feat(schema): Snapshot/Metric contract + JSON roundtrip"
```

---

### Task 2: Linux collector (read-only)

**Files:**
- Create: `local_watch/collectors/__init__.py`, `local_watch/collectors/base.py`, `local_watch/collectors/linux.py`
- Create fixtures: `fixtures/linux_df.txt`, `linux_free.txt`, `linux_uptime.txt`, `linux_aptlist.txt`, `linux_failed.txt`
- Test: `tests/test_linux_collector.py`

**Interfaces:**
- Consumes: `Snapshot`, `Metric` (Task 1).
- Produces: `base.probe(cmd:list[str]) -> str` (runs a read-only command, returns stdout, `""` on error); `linux.collect(runner=probe, machine:str, now:str) -> Snapshot`. `runner` is injected so tests pass a fixture-reader instead of the real shell.

- [ ] **Step 1: Capture fixtures** — save real read-only outputs (safe to run) to `fixtures/`:
```bash
df -P            > fixtures/linux_df.txt
free -b          > fixtures/linux_free.txt
uptime           > fixtures/linux_uptime.txt
apt list --upgradable 2>/dev/null > fixtures/linux_aptlist.txt
systemctl --failed --no-legend    > fixtures/linux_failed.txt
```

- [ ] **Step 2: Write the failing test** — `tests/test_linux_collector.py`
```python
from pathlib import Path
from local_watch.collectors import linux

FX = Path(__file__).parent.parent / "fixtures"

def fake_runner(cmd):
    key = " ".join(cmd)
    table = {
        "df -P": "linux_df.txt", "free -b": "linux_free.txt", "uptime": "linux_uptime.txt",
        "apt list --upgradable": "linux_aptlist.txt", "systemctl --failed --no-legend": "linux_failed.txt",
    }
    for k, f in table.items():
        if key.startswith(k):
            return (FX / f).read_text()
    return ""

def test_linux_collect_produces_snapshot():
    snap = linux.collect(runner=fake_runner, machine="testbox", now="2026-08-29T00:00:00Z")
    assert snap.machine == "testbox" and snap.os == "linux"
    names = {m.name for m in snap.metrics}
    assert "disk_root_pct" in names and "mem_used_pct" in names
    assert "updates_pending" in snap.facts   # a count string
    assert 0.0 <= next(m.value for m in snap.metrics if m.name == "disk_root_pct") <= 100.0
```

- [ ] **Step 3: Run test to verify it fails** — `pytest tests/test_linux_collector.py -v` → FAIL.

- [ ] **Step 4: Minimal implementation**

`local_watch/collectors/base.py`:
```python
from __future__ import annotations
import subprocess

def probe(cmd: list[str]) -> str:
    """Run a READ-ONLY command; return stdout, or "" on any failure. Never raises."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return ""
```

`local_watch/collectors/linux.py`:
```python
from __future__ import annotations
from local_watch.schema import Metric, Snapshot
from local_watch.collectors.base import probe

def _disk_root_pct(df_out: str) -> float:
    for line in df_out.splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[5] == "/":
            return float(parts[4].rstrip("%"))
    return 0.0

def _mem_used_pct(free_out: str) -> float:
    for line in free_out.splitlines():
        if line.startswith("Mem:"):
            p = line.split()
            total, used = float(p[1]), float(p[2])
            return round(100.0 * used / total, 1) if total else 0.0
    return 0.0

def _updates_pending(apt_out: str) -> int:
    return sum(1 for ln in apt_out.splitlines() if "/" in ln and "upgradable" in ln)

def collect(runner=probe, machine: str = "", now: str = "") -> Snapshot:
    df = runner(["df", "-P"]); free = runner(["free", "-b"])
    apt = runner(["apt", "list", "--upgradable"]); failed = runner(["systemctl", "--failed", "--no-legend"])
    metrics = [Metric("disk_root_pct", _disk_root_pct(df), "%"),
               Metric("mem_used_pct", _mem_used_pct(free), "%")]
    failed_units = ",".join(ln.split()[0] for ln in failed.splitlines() if ln.strip())
    facts = {"updates_pending": str(_updates_pending(apt)),
             "failed_units": failed_units,
             "reboot_required": "false"}   # refined in a later step / task 2b if desired
    return Snapshot(machine=machine, os="linux", ts=now, metrics=metrics, facts=facts)
```

- [ ] **Step 5: Run tests** — `pytest tests/test_linux_collector.py -v` → PASS.

- [ ] **Step 6: Commit**
```bash
git add local_watch/collectors tests/test_linux_collector.py fixtures/linux_*.txt
git commit -m "feat(collectors): read-only Linux collector -> Snapshot"
```

> Extend later (same pattern, injected runner + fixture): `cpu_load1` from `uptime`, `temp_c` from `sensors`, top process from `ps`, `reboot_required` from `/var/run/reboot-required`. Each is one metric/fact + one assertion.

---

### Task 3: History store (SQLite)

**Files:**
- Create: `local_watch/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `Snapshot`.
- Produces: `Store(path:str)`; `.append(snap:Snapshot)->None`; `.latest(machine:str)->Snapshot|None`; `.series(machine:str, metric:str, n:int)->list[float]` (oldest→newest, up to n); `.machines()->list[str]`.

- [ ] **Step 1: Write the failing test** — `tests/test_store.py`
```python
from local_watch.schema import Metric, Snapshot
from local_watch.store import Store

def _snap(ts, disk):
    return Snapshot("box", "linux", ts, [Metric("disk_root_pct", disk, "%")], {})

def test_append_latest_series(tmp_path):
    st = Store(str(tmp_path / "m.sqlite"))
    st.append(_snap("2026-08-29T00:00:00Z", 80.0))
    st.append(_snap("2026-08-29T01:00:00Z", 82.0))
    assert st.machines() == ["box"]
    assert st.latest("box").metrics[0].value == 82.0
    assert st.series("box", "disk_root_pct", 5) == [80.0, 82.0]
```

- [ ] **Step 2: Run test to verify it fails** — → FAIL.

- [ ] **Step 3: Minimal implementation** — `local_watch/store.py`
```python
from __future__ import annotations
import sqlite3
from local_watch.schema import Snapshot

class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.execute("create table if not exists snapshots("
                        "machine text, ts text, json text, primary key(machine, ts))")

    def append(self, snap: Snapshot) -> None:
        self.db.execute("insert or replace into snapshots values(?,?,?)",
                        (snap.machine, snap.ts, snap.to_json()))
        self.db.commit()

    def latest(self, machine: str) -> Snapshot | None:
        row = self.db.execute("select json from snapshots where machine=? order by ts desc limit 1",
                              (machine,)).fetchone()
        return Snapshot.from_json(row[0]) if row else None

    def series(self, machine: str, metric: str, n: int) -> list[float]:
        rows = self.db.execute("select json from snapshots where machine=? order by ts desc limit ?",
                               (machine, n)).fetchall()
        out = []
        for (j,) in rows:
            s = Snapshot.from_json(j)
            out += [m.value for m in s.metrics if m.name == metric]
        return out[::-1]

    def machines(self) -> list[str]:
        return [r[0] for r in self.db.execute("select distinct machine from snapshots order by machine")]
```

- [ ] **Step 4: Run tests** — PASS.
- [ ] **Step 5: Commit**
```bash
git add local_watch/store.py tests/test_store.py
git commit -m "feat(store): SQLite snapshot history (append/latest/series)"
```

---

### Task 4: Rules layer (deterministic flags)

**Files:**
- Create: `local_watch/rules.py`
- Test: `tests/test_rules.py`

**Interfaces:**
- Consumes: `Snapshot` (latest), `Store` (for series) — but keep `evaluate` **pure**: pass it the data, not the store.
- Produces: `Flag(machine:str, key:str, severity:str, message:str)` (`severity in {"info","warn","crit"}`); `evaluate(latest:Snapshot, series:dict[str,list[float]]) -> list[Flag]`. `series` maps metric name → recent values (oldest→newest), supplied by the caller from the store.

- [ ] **Step 1: Write the failing test** — `tests/test_rules.py`
```python
from local_watch.schema import Metric, Snapshot
from local_watch.rules import evaluate, Flag

def snap(disk, facts=None):
    return Snapshot("box", "linux", "t", [Metric("disk_root_pct", disk, "%")], facts or {})

def test_disk_crit_over_90():
    flags = evaluate(snap(93.0), {"disk_root_pct": [93.0]})
    assert any(f.key == "disk_full" and f.severity == "crit" for f in flags)

def test_disk_ok_under_threshold():
    assert not [f for f in evaluate(snap(40.0), {"disk_root_pct": [40.0]}) if f.key == "disk_full"]

def test_reboot_required_flag():
    flags = evaluate(snap(10.0, {"reboot_required": "true"}), {"disk_root_pct": [10.0]})
    assert any(f.key == "reboot_required" and f.severity == "warn" for f in flags)

def test_updates_pending_flag():
    flags = evaluate(snap(10.0, {"updates_pending": "12"}), {"disk_root_pct": [10.0]})
    assert any(f.key == "updates_pending" for f in flags)

def test_failed_unit_is_crit():
    flags = evaluate(snap(10.0, {"failed_units": "nginx.service"}), {"disk_root_pct": [10.0]})
    assert any(f.key == "failed_units" and f.severity == "crit" for f in flags)
```

- [ ] **Step 2: Run test to verify it fails** — → FAIL.

- [ ] **Step 3: Minimal implementation** — `local_watch/rules.py`
```python
from __future__ import annotations
from dataclasses import dataclass
from local_watch.schema import Snapshot

@dataclass(frozen=True)
class Flag:
    machine: str
    key: str
    severity: str   # info | warn | crit
    message: str

def _metric(latest: Snapshot, name: str) -> float | None:
    for m in latest.metrics:
        if m.name == name:
            return m.value
    return None

def evaluate(latest: Snapshot, series: dict[str, list[float]]) -> list[Flag]:
    f: list[Flag] = []
    mc = latest.machine
    disk = _metric(latest, "disk_root_pct")
    if disk is not None:
        if disk >= 90:
            f.append(Flag(mc, "disk_full", "crit", f"Root filesystem {disk:.0f}% full"))
        elif disk >= 80:
            f.append(Flag(mc, "disk_full", "warn", f"Root filesystem {disk:.0f}% full"))
    mem = _metric(latest, "mem_used_pct")
    if mem is not None and mem >= 90:
        f.append(Flag(mc, "mem_pressure", "warn", f"Memory {mem:.0f}% used"))
    if latest.facts.get("reboot_required") == "true":
        f.append(Flag(mc, "reboot_required", "warn", "Reboot required"))
    up = int(latest.facts.get("updates_pending", "0") or 0)
    if up > 0:
        f.append(Flag(mc, "updates_pending", "info" if up < 20 else "warn", f"{up} package updates pending"))
    failed = latest.facts.get("failed_units", "")
    if failed:
        f.append(Flag(mc, "failed_units", "crit", f"Failed services: {failed}"))
    return f
```

- [ ] **Step 4: Run tests** — PASS (5).
- [ ] **Step 5: Commit**
```bash
git add local_watch/rules.py tests/test_rules.py
git commit -m "feat(rules): deterministic severity flags (disk/mem/reboot/updates/failed)"
```

> Trend rule to add later (same shape): disk projected-full from `series["disk_root_pct"]` slope → `Flag(..., "disk_trend", ...)`. One test with a rising series.

---

### Task 5: LLM agent (recommendations, with fallback)

**Files:**
- Create: `local_watch/agent.py`
- Modify: `pyproject.toml` (add `wegofwd-llm` dependency)
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: `Snapshot`, `Flag`.
- Produces: `recommend(snapshots:list[Snapshot], flags:list[Flag], provider=None) -> dict[str,str]` — machine → recommendation text. If `provider` is None it builds the default `wegofwd-llm` provider; on any LLM failure it returns a deterministic **flags-only** fallback string per machine. `build_prompt(machine, snap, machine_flags) -> str` is separate and pure (testable without the LLM).

- [ ] **Step 1: Add dependency** — `pyproject.toml` `dependencies = ["wegofwd-llm @ git+https://github.com/wegofwd2020-hub/wegofwd-llm@v0.2.0"]`.

- [ ] **Step 2: Write the failing test** — `tests/test_agent.py`
```python
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
```

- [ ] **Step 3: Run test to verify it fails** — → FAIL.

- [ ] **Step 4: Minimal implementation** — `local_watch/agent.py`
```python
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
```

- [ ] **Step 5: Run tests** — `pytest tests/test_agent.py -v` → PASS (3). (No key needed — provider is injected/mocked; the lazy import + try/except cover the real path.)

- [ ] **Step 6: Commit**
```bash
git add local_watch/agent.py pyproject.toml tests/test_agent.py
git commit -m "feat(agent): LLM recommendations via wegofwd-llm with flags-only fallback"
```

> **Verify the real provider interface** against `wegofwd-llm` before wiring live: confirm the call is `build_provider(...)` + a `.complete(prompt)`-style method; if the seam's method differs (e.g. `LLMRequest`), adapt `_default_provider`/`recommend` accordingly. The tests pin the injected shape; the live shape is confirmed at integration.

---

### Task 6: Dashboard + Markdown report (pure render)

**Files:**
- Create: `local_watch/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `Snapshot`, `Flag`, recommendations `dict[str,str]`, sparkline series `dict[str, dict[str,list[float]]]` (machine → metric → values).
- Produces: `render_dashboard(snapshots, flags, recs, series) -> str` (self-contained HTML, inline CSS, inline-SVG sparklines, one card per machine, fleet-summary header); `render_markdown(snapshots, flags, recs) -> str`.

- [ ] **Step 1: Write the failing test** — `tests/test_report.py`
```python
from local_watch.schema import Metric, Snapshot
from local_watch.rules import Flag
from local_watch.report import render_dashboard, render_markdown

SNAPS = [Snapshot("box1", "linux", "t", [Metric("disk_root_pct", 93.0, "%")], {})]
FLAGS = [Flag("box1", "disk_full", "crit", "Root filesystem 93% full")]
RECS = {"box1": "Prune old logs."}
SERIES = {"box1": {"disk_root_pct": [80.0, 85.0, 93.0]}}

def test_dashboard_is_self_contained_html():
    html = render_dashboard(SNAPS, FLAGS, RECS, SERIES)
    assert "<html" in html.lower() and "box1" in html
    assert "93" in html and "Prune old logs." in html
    assert "http://" not in html and "https://" not in html   # no external assets
    assert "<svg" in html   # sparkline present

def test_markdown_lists_machine_and_flags():
    md = render_markdown(SNAPS, FLAGS, RECS)
    assert "box1" in md and "Root filesystem 93% full" in md and "Prune old logs." in md
```

- [ ] **Step 2: Run test to verify it fails** — → FAIL.

- [ ] **Step 3: Minimal implementation** — `local_watch/report.py`
```python
from __future__ import annotations
from local_watch.schema import Snapshot
from local_watch.rules import Flag

_SEV = {"crit": "#d64545", "warn": "#d9a441", "info": "#5b8def"}

def _sparkline(vals: list[float], w: int = 100, h: int = 24) -> str:
    if len(vals) < 2:
        return "<svg width='%d' height='%d'></svg>" % (w, h)
    lo, hi = min(vals), max(vals); rng = (hi - lo) or 1.0
    pts = " ".join(f"{i*(w/(len(vals)-1)):.1f},{h-(v-lo)/rng*h:.1f}" for i, v in enumerate(vals))
    return f"<svg width='{w}' height='{h}'><polyline fill='none' stroke='#5b8def' stroke-width='1.5' points='{pts}'/></svg>"

def _status(flags: list[Flag]) -> str:
    sevs = {f.severity for f in flags}
    return "crit" if "crit" in sevs else "warn" if "warn" in sevs else "info"

def render_dashboard(snapshots, flags, recs, series) -> str:
    cards = []
    for s in snapshots:
        mf = [f for f in flags if f.machine == s.machine]
        dot = _SEV[_status(mf)]
        mrows = "".join(f"<div class='m'>{m.name}: <b>{m.value}{m.unit}</b> "
                        f"{_sparkline(series.get(s.machine, {}).get(m.name, []))}</div>" for m in s.metrics)
        frows = "".join(f"<li style='color:{_SEV[f.severity]}'>[{f.severity}] {f.message}</li>" for f in mf) or "<li>OK</li>"
        cards.append(f"<section class='card'><h2><span class='dot' style='background:{dot}'></span>{s.machine}"
                     f" <small>{s.os}</small></h2>{mrows}<ul>{frows}</ul>"
                     f"<pre class='rec'>{recs.get(s.machine,'')}</pre></section>")
    issues = len(flags)
    return ("<!doctype html><html><head><meta charset='utf-8'><title>local_watch</title><style>"
            "body{font:14px system-ui;margin:1.5rem;background:#0e0b1f;color:#eee}"
            ".card{background:#1b1633;border-radius:10px;padding:1rem;margin:.75rem 0}"
            ".dot{display:inline-block;width:.7rem;height:.7rem;border-radius:50%;margin-right:.4rem}"
            ".m{margin:.2rem 0}.rec{white-space:pre-wrap;background:#0e0b1f;padding:.6rem;border-radius:6px}"
            "small{opacity:.6}</style></head><body>"
            f"<h1>local_watch — {len(snapshots)} machines · {issues} issues</h1>"
            + "".join(cards) + "</body></html>")

def render_markdown(snapshots, flags, recs) -> str:
    out = [f"# local_watch — {len(snapshots)} machines, {len(flags)} issues", ""]
    for s in snapshots:
        out.append(f"## {s.machine} ({s.os})")
        out += [f"- {m.name}: {m.value}{m.unit}" for m in s.metrics]
        for f in [fl for fl in flags if fl.machine == s.machine]:
            out.append(f"- **[{f.severity}]** {f.message}")
        out += ["", "**Recommendations:**", recs.get(s.machine, "(none)"), ""]
    return "\n".join(out)
```

- [ ] **Step 4: Run tests** — PASS (2).
- [ ] **Step 5: Commit**
```bash
git add local_watch/report.py tests/test_report.py
git commit -m "feat(report): self-contained fleet dashboard (cards+sparklines) + markdown"
```

---

### Task 7: CLI wiring + end-to-end

**Files:**
- Create: `local_watch/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces four subcommands (argparse):
  - `collect --machine <name> --out <file.json>` — run this host's OS collector, write a Snapshot JSON.
  - `ingest --store <db> <file.json>...` — append snapshot files into the store.
  - `render --store <db> --html <out.html> --md <out.md>` — read latest per machine, evaluate rules, get recommendations, write dashboard + report.
  - (`review` = alias of render for now.)
- OS dispatch: `collect` picks `linux.collect` vs `macos.collect` from `platform.system()`.

- [ ] **Step 1: Write the failing test** — `tests/test_cli.py`
```python
import json, sys
from pathlib import Path
from local_watch.schema import Metric, Snapshot
from local_watch import cli

def test_ingest_then_render(tmp_path, monkeypatch):
    snapf = tmp_path / "s.json"
    snapf.write_text(Snapshot("box", "linux", "2026-08-29T00:00:00Z",
                              [Metric("disk_root_pct", 93.0, "%")], {}).to_json())
    db = tmp_path / "m.sqlite"; html = tmp_path / "d.html"; md = tmp_path / "r.md"
    # no LLM: agent falls back to flags-only (no provider/key in test env)
    cli.main(["ingest", "--store", str(db), str(snapf)])
    cli.main(["render", "--store", str(db), "--html", str(html), "--md", str(md)])
    assert "box" in html.read_text() and "93" in html.read_text()
    assert "Root filesystem 93% full" in md.read_text()
```

- [ ] **Step 2: Run test to verify it fails** — → FAIL.

- [ ] **Step 3: Minimal implementation** — `local_watch/cli.py`
```python
from __future__ import annotations
import argparse, platform, datetime
from local_watch.schema import Snapshot
from local_watch.store import Store
from local_watch import rules, agent, report

def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _collect(machine: str) -> Snapshot:
    if platform.system() == "Darwin":
        from local_watch.collectors import macos as c
    else:
        from local_watch.collectors import linux as c
    return c.collect(machine=machine or platform.node(), now=_now())

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="local_watch")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect"); c.add_argument("--machine", default=""); c.add_argument("--out", required=True)
    i = sub.add_parser("ingest"); i.add_argument("--store", required=True); i.add_argument("files", nargs="+")
    r = sub.add_parser("render"); r.add_argument("--store", required=True)
    r.add_argument("--html", required=True); r.add_argument("--md", required=True)
    sub.add_parser("review")  # alias handled below
    a = ap.parse_args(argv)

    if a.cmd == "collect":
        open(a.out, "w").write(_collect(a.machine).to_json()); return 0
    if a.cmd == "ingest":
        st = Store(a.store)
        for fp in a.files:
            st.append(Snapshot.from_json(open(fp).read()))
        return 0
    if a.cmd in ("render", "review"):
        st = Store(a.store)
        snaps = [st.latest(m) for m in st.machines()]
        flags = []
        series = {}
        for s in snaps:
            ser = {m.name: st.series(s.machine, m.name, 20) for m in s.metrics}
            series[s.machine] = ser
            flags += rules.evaluate(s, ser)
        recs = agent.recommend(snaps, flags)
        open(a.html, "w").write(report.render_dashboard(snaps, flags, recs, series))
        open(a.md, "w").write(report.render_markdown(snaps, flags, recs))
        return 0
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the whole suite** — `pytest -q` → all green.
- [ ] **Step 5: Commit**
```bash
git add local_watch/cli.py tests/test_cli.py
git commit -m "feat(cli): collect/ingest/render pipeline end-to-end"
```

---

### Task 8: wegofwd-hub tile (cross-repo)

**Files:**
- Modify: `wegofwd-hub/portal/tiles.py` (the hub repo, a sibling under the STEM_studybuddy hub) — add a `file` tile.
- Modify: hub tests if they assert the tile list.

**Interfaces:**
- Consumes: the dashboard HTML that `local_watch render --html` writes (a fixed path, e.g. `~/.local/share/local_watch/dashboard.html`).
- Produces: a "Local Watch" tile of kind `file` pointing at that path, so the hub serves it live.

- [ ] **Step 1** — In `wegofwd-hub/portal/tiles.py`, add to `TILES`:
```python
{"slug": "local-watch", "name": "Local Watch", "kind": "file",
 "target": Path(os.path.expanduser("~/.local/share/local_watch/dashboard.html"))},
```
- [ ] **Step 2** — Update the hub test that counts/lists tiles (`tests/test_portal.py`) to expect the new tile; run `python manage.py test` (or the repo's pytest) → green.
- [ ] **Step 3: Commit (in the wegofwd-hub repo)**
```bash
git -C ../wegofwd-hub add portal/tiles.py tests/test_portal.py
git -C ../wegofwd-hub commit -m "feat(tiles): add Local Watch dashboard tile"
```
> Cross-repo task — commit lands in `wegofwd-hub`, not `local_watch`. `render` must write to the tile's target path (make it the deploy default in Task 10).

---

### Task 9: macOS collector

**Files:**
- Create: `local_watch/collectors/macos.py`
- Create fixtures: `fixtures/macos_df.txt`, `macos_vm_stat.txt`, `macos_swupdate.txt`
- Test: `tests/test_macos_collector.py`

**Interfaces:** mirrors Task 2 — `macos.collect(runner=probe, machine, now) -> Snapshot`, emitting the **same** metric names (`disk_root_pct`, `mem_used_pct`) + facts (`updates_pending`, `reboot_required`), so store/rules/report are unchanged.

- [ ] **Step 1: Capture fixtures on the Mac** (read-only): `df -P > macos_df.txt`, `vm_stat > macos_vm_stat.txt`, `softwareupdate --list 2>&1 > macos_swupdate.txt`.
- [ ] **Step 2: Write the failing test** — same shape as `test_linux_collector.py`, asserting `snap.os == "macos"`, `disk_root_pct` in range, `mem_used_pct` present, `updates_pending` in facts (parsed from `softwareupdate --list` lines).
- [ ] **Step 3: Implement** `macos.collect` — `_disk_root_pct` reuses the `df -P` parser (identical format); `_mem_used_pct` computes used% from `vm_stat` page counts (pages active+wired+compressed over total); `updates_pending` counts `* Label:` lines in `softwareupdate --list`.
- [ ] **Step 4: Run tests** — PASS.
- [ ] **Step 5: Commit** — `feat(collectors): read-only macOS collector -> Snapshot`.

---

### Task 10: Deploy + cross-machine sync (operator, human-run)

**Files:**
- Create: `deploy/local_watch-collect.service` + `.timer` (Linux), `deploy/com.wegofwd.localwatch.plist` (macOS), `deploy/README.md`.

Not TDD (touches real machines + the tailnet). Deliverables:
- [ ] **systemd** (each Linux box): a `--user` timer runs `local_watch collect --machine <host> --out <spool>/<host>.json` every ~20 min. `deploy/README.md` documents `systemctl --user enable --now local_watch-collect.timer`.
- [ ] **launchd** (Mac): a `LaunchAgent` plist runs the same `collect` on an interval.
- [ ] **Sync**: each box's spool file syncs to `mambakkam` over Tailscale (`tailscale file cp` or `rsync` over the tailnet DNS names) into an ingest dir; a timer on `mambakkam` runs `ingest` + `render --html ~/.local/share/local_watch/dashboard.html --md …` (the hub tile target from Task 8). Document the exact commands + intervals.
- [ ] **Verify**: after enabling, `mambakkam` dashboard shows all three machines; confirm collectors invoke only read-only probes (grep the units).
- [ ] Commit `deploy/` + `deploy/README.md`.

> This task is the fleet fan-out. Keep it last; the pipeline (Tasks 1–7) already produces a working dashboard for any machine whose snapshot reaches the store.

---

## Definition of Done (v1)
- `pytest -q` green; `ruff` clean.
- `local_watch collect` on Linux + macOS produces valid Snapshots from read-only probes only.
- Store accumulates history; rules flag disk/mem/reboot/updates/failed-units; agent writes recommendations (LLM when keyed, flags-only fallback otherwise).
- `render` writes a self-contained fleet dashboard (cards + sparklines, no external assets) + a Markdown report.
- The wegofwd-hub "Local Watch" tile serves the live dashboard.
- Deploy docs stand up collectors on all three machines syncing to `mambakkam`.
- **No state-changing command anywhere in the codebase** (read-only invariant holds).

## Self-review notes
- Spec coverage: collectors (T2,T9) · store (T3) · rules (T4) · agent (T5) · dashboard+report (T6) · hub tile (T8) · scheduling/sync/deploy (T10) · read-only invariant (Global Constraints + T2/T9 probe lists + DoD). All spec sections map to a task.
- Types consistent across tasks: `Snapshot`/`Metric` (T1) used verbatim by T2–T9; `Flag` (T4) used by T5/T6/T7; `recommend()`/`render_dashboard()` signatures match their call in T7.
- Open items deliberately deferred (documented, not placeholders): extra metrics (cpu/temp/top-proc) and the disk-trend rule are noted as "same-pattern" extensions after their base task; the live `wegofwd-llm` method shape is confirmed at T5 integration.
