# local_watch

Read-only monitoring of a small personal fleet, with **LLM-assisted, plain-language
optimization recommendations**. It watches your machines, spots problems and trends, and
tells you what to do about them — **it never changes system state itself** (v1).

> **Status:** v1 implemented and merged to `main`. Collectors, history store, rules,
> LLM recommendations and the HTML/Markdown report all work end-to-end; see
> `deploy/README.md` for the operator runbook. Not yet running on the fleet —
> the units are inert until an operator enables them.

## Why

Three machines drift out of shape in ways that are easy to miss until they bite: a disk
creeping toward full, a runaway process, a box that's been asking to reboot for weeks,
pending security updates, a service that quietly died, thermals climbing. `local_watch`
keeps a continuous read-only eye on all of them and turns the raw metrics into a short,
prioritized "here's what's wrong and here's what to do" per machine.

## The fleet

| machine | OS | role |
|---|---|---|
| `mambakkam` | Linux (Mint) | primary desktop; also the **central aggregator** |
| 2nd Linux box | Linux | secondary |
| MacBook | macOS | laptop |

All three are on the Tailscale tailnet (`tail242406.ts.net`), which is how metrics sync to
the aggregator.

## Principles

- **Read-only in v1.** No writes, no killing processes, no config changes, no package
  installs. Every finding is *advice*; the human acts. This is the safety floor the whole
  design rests on.
- **Deterministic where it matters, smart where it helps.** Collection + threshold
  detection are plain, fast, offline code. The LLM only *reads* the aggregate and writes
  recommendations — it is never in the control path.
- **Fleet-aware but resilient.** A machine that's asleep or offline doesn't break the run;
  its last-known state and history persist centrally.
- **Private + local.** Metrics are non-sensitive system stats and stay on your own
  machines / tailnet. No third-party telemetry.

## Architecture

```
 ┌──────────── each machine (Linux ×2, macOS ×1) ────────────┐
 │  collector (read-only, per-OS adapter)                     │
 │    · systemd timer (Linux) / launchd agent (macOS)         │
 │    · emits a timestamped metric snapshot (JSON)            │
 └───────────────┬───────────────────────────────────────────┘
                 │  sync over Tailscale
                 ▼
 ┌──────────── mambakkam (central aggregator) ───────────────┐
 │  store        · metric history per machine (SQLite/JSONL)  │
 │  rules layer  · thresholds → deterministic flags           │
 │  LLM agent    · reviews aggregate+trends → recommendations │
 │  output       · fleet dashboard (HTML) + report; wegofwd-hub  │
 └────────────────────────────────────────────────────────────┘
```

### 1. Collectors (read-only, per-OS)
A small collector runs on a timer on each machine and emits a snapshot. Metric domains:

- **Compute:** CPU/load average, memory + swap pressure, uptime.
- **Storage:** per-filesystem usage + growth rate, inode pressure, largest dirs/files, disk
  SMART health where available.
- **Thermals/power:** temperatures / thermal throttling, fan state, battery health + cycles
  (laptops).
- **Processes:** top CPU/memory consumers, runaway / zombie processes.
- **Updates & hygiene:** pending OS/package updates (apt on Linux, `softwareupdate` on
  macOS), **reboot-required** flag, failed units (`systemctl --failed` / failed launchd
  agents), log volume + journal size.
- **Network:** interface up/down, Tailscale reachability, basic throughput.

Per-OS adapters isolate the platform differences behind a common snapshot schema, so the
store, rules, and agent are OS-agnostic.

### 2. Sync + central store
Snapshots sync to `mambakkam` over Tailscale and land in a per-machine history store
(SQLite or append-only JSONL). History enables trend detection ("disk +2%/day → full in ~6
days") and survives a machine being offline.

### 3. Rules layer (deterministic)
Threshold + trend rules produce structured **flags** with severity — e.g. disk >90% (or
projected-full soon), sustained high temperature, memory pressure, a process pegged for N
intervals, updates pending > N days, reboot required, a failed service. Fast, free,
predictable; runs with or without the LLM.

### 4. LLM agent layer (recommendations)
On a schedule (or on demand), an agent reads the aggregate + the active flags + recent
trends and writes, **per machine**, a short health summary and a **prioritized list of
optimization recommendations** in plain language ("*Docker build cache is 45 GB and growing;
`docker system prune` would reclaim it*"). It reasons about *what to do and why* — it does
**not** execute anything. Uses the `wegofwd-llm` seam (BYOK).

### 5. Output — fleet dashboard + report
- A **fleet dashboard**: a single self-contained HTML page, regenerated each run, with
  **one card per machine** — a status light (green/amber/red), key metrics (CPU · memory ·
  disk · temperature), tiny **trend sparklines** drawn from the history store, the machine's
  **active flags** (severity-colored), and its **latest LLM recommendations**. A
  fleet-summary header shows machines up · open issues · last-refreshed. Theme-aware,
  offline, inline CSS (no external assets).
- Surfaced **live through a "Local Watch" `wegofwd-hub` tile** (:8088) — the hub reads the
  dashboard file fresh from disk on each view, exactly as it does for `portfolio.html` /
  `doc-digest.html`. No new service or port.
- A plain **health report** (Markdown) is also written per run for archival / diffing.

## Scheduling
- **Collectors:** short interval (~15–30 min) via systemd timer / launchd.
- **LLM review + report:** daily (and runnable on demand). Deterministic flags update every
  collection; the LLM narrative refreshes on the review cadence to keep token cost bounded.

## Tech stack
- **Python** (project default) for collectors, store, rules, agent, report.
- **Tailscale** for cross-machine sync (SSH/`tailscale` file transfer over the tailnet).
- **systemd** timers (Linux) + **launchd** agents (macOS) for scheduling.
- **`wegofwd-llm`** for the LLM recommendation layer (BYOK; local key).
- Output as a self-contained static **fleet dashboard** (HTML, per-machine cards + sparklines)
  + a Markdown report, surfaced live via a `wegofwd-hub` tile.

## Proposed layout
```
local_watch/
  collectors/        # per-OS read-only probes → common snapshot schema
    linux.py  macos.py  schema.py
  store/             # central metric history (SQLite/JSONL)
  rules/             # deterministic threshold + trend flags
  agent/             # LLM review → recommendations (wegofwd-llm)
  report/            # fleet dashboard (HTML, per-machine cards + sparklines) + MD report + hub tile hook
  deploy/            # systemd units, launchd plist, sync setup
  tests/
  pyproject.toml
```

## Roadmap
- **v1 (this scope):** observe + recommend only. Read-only fleet monitoring, deterministic
  flags, LLM recommendations, report + hub tile.
- **v2:** *act with approval* — a whitelisted set of optimizations (prune caches, rotate
  logs, clear tmp, apply updates) that the agent proposes and executes **only** after an
  explicit per-action yes. Gated on trusting v1's recommendations.
- **v3 (maybe):** autonomous bounded actions for a small, provably-safe whitelist; everything
  risky still escalates.

## Explicitly out of scope (v1)
Any system modification; autonomous or approval-gated actions; remote *control* (vs.
read-only collection); external alerting/paging integrations; monitoring machines outside
the personal fleet. All deferred to v2+.

## Security & privacy
Read-only by construction. Metrics are non-sensitive system statistics and never leave your
machines/tailnet. No credentials are collected; the LLM key is a local BYOK file. Private
repo.

## Getting started
_TBD once implemented._ Build proceeds from the design spec
(`docs/superpowers/specs/2026-08-29-local_watch-design.md`) through the plan → SDD cycle.
