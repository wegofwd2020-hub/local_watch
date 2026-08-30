# local_watch deploy runbook

**Nothing in this directory is enabled automatically.** These are inert unit
files, a plist, a wrapper script and instructions. Every step below is run by
hand by the operator on the target machine. `local_watch` itself only ever
calls read-only probes (see `local_watch/collectors/`) — collection never
mutates system state, and no step here installs a privileged service, opens a
network listener, or runs as root.

Fleet shape assumed below: three machines, one of which is `mambakkam` — the
box that also runs wegofwd-hub and hosts the merged store and rendered
dashboard.

| machine | runs |
|---|---|
| `mambakkam` (aggregator) | `collect` + `ingest-render` — **not** `sync` |
| 2nd Linux box | `collect` + `sync` |
| MacBook | `collect` (launchd) + `sync` |

---

## 0. Configure once, on every machine

All units read one file, so the checkout path is set in a single place rather
than edited into each unit:

```bash
mkdir -p ~/.config/local_watch
cp deploy/env.example ~/.config/local_watch/env
$EDITOR ~/.config/local_watch/env     # set LOCAL_WATCH_HOME (and LOCAL_WATCH_REMOTE, except on mambakkam)
```

systemd does not expand `~` or `$HOME` inside this file — use absolute paths.
The units declare it **without** a leading `-`, so a missing file fails the
unit loudly instead of silently collecting nothing.

## 1. Every Linux box (including mambakkam, as a collector)

```bash
cd "$LOCAL_WATCH_HOME"
python3 -m venv .venv
.venv/bin/pip install -e .

mkdir -p ~/.config/systemd/user
cp deploy/local_watch-collect.service ~/.config/systemd/user/
cp deploy/local_watch-collect.timer   ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now local_watch-collect.timer
```

`pip install -e .` is what creates `.venv/bin/local_watch`, the executable
every unit invokes (`[project.scripts]` in `pyproject.toml`). If that binary
is missing, the install failed — do not proceed.

Check it fired:

```bash
systemctl --user list-timers local_watch-collect.timer
journalctl --user -u local_watch-collect.service --since -1h
ls ~/.local/share/local_watch/spool/
```

`systemctl --user` units only run while a user session is active. On a box
with no continuous interactive login, enable lingering once:
`sudo loginctl enable-linger $USER`.

## 2. The Mac

```bash
cd "$LOCAL_WATCH_HOME"
python3 -m venv .venv
.venv/bin/pip install -e .
```

`deploy/com.wegofwd.localwatch.plist` needs **one edit**: replace
`/Users/YOURUSER` with the real home directory. launchd expands neither `~`
nor `$HOME` in these paths. The hostname is no longer a placeholder — the
command runs under `sh -c` and takes it from `hostname -s`, matching the
Linux units and the sync step.

```bash
cp deploy/com.wegofwd.localwatch.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.wegofwd.localwatch.plist
```

Check it fired:

```bash
launchctl list | grep com.wegofwd.localwatch
ls ~/.local/share/local_watch/spool/
tail ~/.local/share/local_watch/collect.err.log
```

To uninstall: `launchctl unload ~/Library/LaunchAgents/com.wegofwd.localwatch.plist`.

> **Mac-specific:** `softwareupdate --list` round-trips to Apple and can take a
> minute, so it is the one probe given a 120s budget instead of the 15s
> default (`collectors/base.py`). If the Mac still reports
> `collector_degraded: softwareupdate`, raise `SLOW_PROBE_TIMEOUT` rather than
> ignoring the flag — under fail-closed rules a timeout is reported, not
> silently rounded down to "0 updates pending".

## 3. Sync to the aggregator, over Tailscale — every box except mambakkam

This is the only unit in the fleet that touches the network. It writes exactly
one file into the remote user's ingest directory; it reads nothing back and
runs nothing remotely.

On **mambakkam**, once:

```bash
mkdir -p ~/.local/share/local_watch/ingest
```

On **each other box**, confirm passwordless ssh over the tailnet first —
Tailscale SSH provides this via ACL, so no key material needs to live on the
box:

```bash
ssh "$LOCAL_WATCH_REMOTE" true && echo "ssh ok"
```

Then:

```bash
cp deploy/local_watch-sync.service ~/.config/systemd/user/
cp deploy/local_watch-sync.timer   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now local_watch-sync.timer
```

On the Mac, launchd has no equivalent shipped here; add the same `rsync` line
as a second LaunchAgent with `StartInterval=1200`, or a cron entry:

```bash
rsync -az --rsh=ssh \
  "$HOME/.local/share/local_watch/spool/$(hostname -s).json" \
  "$LOCAL_WATCH_REMOTE:.local/share/local_watch/ingest/"
```

**mambakkam does not run this unit.** Point its own collect output straight
into the ingest directory instead, by setting
`LOCAL_WATCH_DATA=/home/sivam/.local/share/local_watch` and adding a one-line
`ExecStartPost=` copy from `spool/` to `ingest/`, or simply symlinking the two.

## 4. On mambakkam: ingest + render on a schedule

```bash
cp deploy/local_watch-ingest-render.service ~/.config/systemd/user/
cp deploy/local_watch-ingest-render.timer   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now local_watch-ingest-render.timer
```

The unit runs `deploy/mambakkam-ingest-render.sh`, which merges every
`ingest/*.json` into the store and re-renders. It tolerates an empty ingest
directory (renders existing history rather than going blank when a sync
breaks) and refuses to run with a helpful message if `LOCAL_WATCH_HOME` or the
venv is missing.

Ingested files are deliberately **not** deleted: each machine overwrites its
own `<hostname>.json`, so the directory stays bounded at one file per machine,
and re-ingesting is idempotent.

The `--html` path is load-bearing. It must remain
`~/.local/share/local_watch/dashboard.html` — the literal path wegofwd-hub's
"Local Watch" tile serves (`portal/tiles.py`, `{"slug": "local-watch", ...}`).
Changing it means editing that tile entry too.

### Timing

The three timers are offset so each stage sees fresh input:

| stage | first run | then |
|---|---|---|
| collect | boot + 2min | every 20min |
| sync | boot + 7min | every 20min |
| ingest + render | boot + 12min | every 20min |

That cadence matters to the rules layer: a snapshot is flagged **stale after
60 minutes** (three missed collection runs), so a healthy machine stays
comfortably inside the window. Slowing the collect timer past ~20 minutes will
start producing false stale flags.

## 5. Verify

After steps 0–4 on all three machines, wait one full cycle (~30 min) or force
one immediately:

```bash
systemctl --user start local_watch-collect.service
systemctl --user start local_watch-sync.service          # not on mambakkam
systemctl --user start local_watch-ingest-render.service # mambakkam only
```

Then open the wegofwd-hub "Local Watch" tile, or
`~/.local/share/local_watch/dashboard.html` directly, and confirm:

- **all three machines** appear as cards
- each shows a recent timestamp and no `stale` flag
- no card shows `collector_degraded`

`~/.local/share/local_watch/report.md` carries the same content as text.

> Sparklines need at least two readings, and the **disk trend rule needs 6
> readings across at least 6 hours** — so expect flat cards and no
> `disk_filling` flags for roughly the first six hours after deployment. That
> is the rule declining to extrapolate, not a fault.

## 6. Reading the flags

Three of the flags are about *trust in the data* rather than machine health,
and they are the first thing to check after a deploy:

| flag | severity | means |
|---|---|---|
| `stale` | crit | No snapshot for >60min. The card's numbers are history. Collect or sync has stopped, or the machine is asleep/off. A laptop that sleeps overnight will show this every morning — that is correct. |
| `collector_degraded` | crit | One or more probes could not run; the message names them. The affected metrics are **absent, not zero**. |
| `disk_filling` | crit/warn | Projected to reach 100% within 2 days (crit) or 7 days (warn), based on a least-squares fit over real elapsed time. |

`stale` and `collector_degraded` are listed before the threshold flags on
purpose: if the data cannot be trusted, that is the first thing to read.

## 7. Troubleshooting

**A machine is missing from the dashboard entirely** — it has never been
ingested. Check its spool file exists and is recent
(`ls -la ~/.local/share/local_watch/spool/`), that sync landed it on mambakkam
(`ls -la ~/.local/share/local_watch/ingest/`), and that the ingest unit ran
(`journalctl --user -u local_watch-ingest-render.service --since -1h`).

**A machine is present but flagged `stale`** — it was ingested once and has
stopped reporting since. The pipeline works; the break is upstream of ingest.
Check the collect timer on that box, then the sync timer, in that order.

**A machine is flagged `collector_degraded`** — read which probes the message
names. `df`/`free`/`vm_stat` failing usually means a missing binary or a PATH
problem under systemd/launchd (which do not source shell rc files).
`apt` failing usually means the dpkg lock was held. `softwareupdate` failing
means the 120s budget was exceeded — see the note in step 2.

**Recommendations say `[LLM unavailable - deterministic rules only]`** — the
flags are still correct; only the plain-language advice is missing. The agent
reads `~/.config/wegofwd/anthropic_api_key` and needs `wegofwd-llm` installed
(it is a normal dependency, so a `pip install -e .` without network access
will have skipped it).

**`ExecStart` fails with "No such file or directory"** — almost always
`LOCAL_WATCH_HOME` pointing somewhere without a built `.venv`, or a
`pip install -e .` that failed. Re-run step 1 and confirm
`.venv/bin/local_watch --help` works.

## Read-only invariant

Every unit here runs only `local_watch collect`, `local_watch ingest`,
`local_watch render`, or an `rsync` of one JSON file. None write outside
`~/.local/share/local_watch/` (and the same path on the aggregator), none
require sudo or root, and `collect` itself only calls the read-only probes in
`local_watch/collectors/{linux,macos}.py` — `df`, `free`, `vm_stat`,
`apt list --upgradable`, `systemctl --failed`, `launchctl list`,
`softwareupdate --list`. Grep those files for `runner(`/`probe(` to confirm no
probe passes a mutating flag. No unit starts, stops, restarts or reconfigures
any other service on the machine it runs on.
