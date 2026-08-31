# local_watch deploy

**Nothing in this directory is enabled automatically.** These are inert unit
files, LaunchAgents, a wrapper script and instructions. Every step is run by
hand by an operator on the target machine.

## Install guides

Follow the one for the machine you are standing at:

- **[INSTALL-linux.md](INSTALL-linux.md)** — any Linux box, covering both the
  aggregator (`mambakkam`) and plain collector roles
- **[INSTALL-macos.md](INSTALL-macos.md)** — the MacBook

## The fleet

| Machine | OS | Collects | Syncs to aggregator | Merges + renders |
|---|---|---|---|---|
| `mambakkam` | Linux | yes | no — it *is* the destination | yes |
| 2nd Linux box | Linux | yes | yes | no |
| MacBook | macOS | yes | yes | no |

Snapshots flow one way: each machine writes a JSON snapshot to its own spool
directory, syncs it to `mambakkam` over Tailscale, and `mambakkam` merges
every snapshot into a SQLite history and re-renders the dashboard.

## What is here

| File | Machine | Purpose |
|---|---|---|
| `env.example` | all | Copied to `~/.config/local_watch/env`; the single place paths are configured |
| `local_watch-collect.{service,timer}` | Linux, all | Take one read-only snapshot every 20 min |
| `local_watch-sync.{service,timer}` | Linux collectors | rsync that snapshot to the aggregator |
| `sync-to-aggregator.sh` | collectors, both OSes | The sync body and its guards, shared by the Linux unit and the Mac agent |
| `local_watch-ingest-render.{service,timer}` | `mambakkam` | Merge all snapshots and re-render |
| `mambakkam-ingest-render.sh` | `mambakkam` | The two-command body of the above, with guards |
| `com.wegofwd.localwatch.plist` | Mac | Collect, every 20 min |
| `com.wegofwd.localwatch-sync.plist` | Mac | Runs `sync-to-aggregator.sh`, every 20 min |

Both plists and all four units read `~/.config/local_watch/env` at runtime, so
**none of them need editing** — the checkout path is configured once per
machine.

## Timing

The Linux timers are staggered so each stage sees fresh input:

| Stage | First run after boot | Then |
|---|---|---|
| collect | +2 min | every 20 min |
| sync | +7 min | every 20 min |
| ingest + render | +12 min | every 20 min |

This cadence is load-bearing. The rules layer flags a snapshot as `stale`
after **60 minutes** — three missed collection runs — so slowing collect much
past 20 minutes will start producing false staleness.

## Read-only invariant

Every unit here runs only `local_watch collect`, `local_watch ingest`,
`local_watch render`, or an `rsync` of one JSON file. None write outside
`~/.local/share/local_watch/` (and the same path on the aggregator), none
require `sudo` or root, and `collect` itself only calls the read-only probes
in `local_watch/collectors/{linux,macos}.py` — `df -P`, `free -b`,
`apt list --upgradable`, `systemctl --failed`, `vm_stat`,
`softwareupdate --list`, `launchctl list`. `launchctl list` only lists; it
never loads or unloads. Grep those two files for `read(` to confirm no probe
passes a mutating flag.

No unit here starts, stops, restarts or reconfigures any other service on the
machine it runs on.
