# local_watch — Design

| Field | Value |
|---|---|
| Project | **local_watch** — read-only fleet monitoring + LLM optimization recommendations |
| Goal | Watch 3 personal machines, detect problems/trends, recommend fixes; never modify state (v1) |
| Status | Approved (brainstorming) 2026-08-29 → ready for implementation plan |
| Owner | Sivakumar Mambakkam |
| Home | new private repo `local_watch` under the STEM_studybuddy hub |

The authoritative scope is [`README.md`](../../../README.md). This spec restates the design
for the SDD cycle and pins the decisions made during brainstorming.

## Decisions locked (brainstorming 2026-08-29)
- **D1 — Autonomy:** *Observe + recommend only.* Read-only; no writes/kills/config changes in v1.
- **D2 — Topology:** *Per-machine collector + central aggregator.* Collectors run on each box
  (systemd/launchd), snapshots sync over Tailscale to `mambakkam`, which stores history and
  analyzes. (Chosen over agentless central-pull for resilience + history.)
- **D3 — Engine:** *Hybrid.* Deterministic collectors + threshold/trend rules do detection;
  an LLM agent reviews the aggregate and writes recommendations. LLM never in the control path.

## Architecture
Four layers (see README for the diagram): **collectors** (per-OS, read-only, common snapshot
schema) → **sync + store** (Tailscale → per-machine history on mambakkam, SQLite/JSONL) →
**rules** (deterministic flags with severity) → **LLM agent** (recommendations via
`wegofwd-llm`) → **output** (fleet dashboard + report, surfaced via wegofwd-hub).

## Components & boundaries
- `collectors/schema.py` — the snapshot contract every OS adapter emits (OS-agnostic downstream).
- `collectors/linux.py`, `collectors/macos.py` — read-only probes only; no side effects.
- `store/` — append + query metric history; pure data, no analysis.
- `rules/` — pure functions: (history, latest) → list[Flag]. No I/O, no LLM. Unit-testable.
- `agent/` — takes aggregate + flags → recommendations string(s) via `wegofwd-llm`. The only
  component that calls out; degrades to "flags only" if the LLM/key is unavailable.
- `report/` — pure render: (snapshots, flags, recommendations) → a self-contained **fleet
  dashboard** HTML (per-machine cards: status light, key metrics, trend sparklines from
  history, active flags, latest recommendations; fleet-summary header) + a Markdown report.
  No external assets (inline CSS/SVG sparklines), theme-aware. Surfaced live by a
  `wegofwd-hub` tile that reads the file fresh per view (same as portfolio.html/doc-digest).
- `deploy/` — systemd timer units, launchd plist, Tailscale sync setup.

## Testing posture
- Collectors: parse fixture command outputs into the schema (mock the shell, per-OS fixtures).
- Rules: pure-function unit tests over synthetic histories (the core correctness surface).
- Agent: mock the `wegofwd-llm` provider (no live calls in CI), assert prompt assembly + the
  flags-only fallback.
- No live SSH / no live machines in tests.

## Safety invariants (must hold in v1)
- No collector or any code path executes a state-changing command. Probes are read-only
  (`df`, `free`, `sensors`, `ps`, `apt-get -s`/`--just-print`, `softwareupdate --list`,
  `systemctl --failed`, etc.). A review gate on every collector PR checks this.
- The LLM output is text only; nothing parses it into actions.

## Out of scope (v1)
System modification; approval-gated or autonomous actions; remote control; external alerting.
Deferred to v2 (act-with-approval).

## Open questions for the plan stage
- Snapshot store: SQLite vs per-machine JSONL (lean toward SQLite on the aggregator).
- Sync mechanism over Tailscale: pull via `tailscale ssh` vs push via `tailscale file`/rsync.
- Report cadence + whether the hub tile is `file`/`index`/`link` kind.
