# Installing local_watch on a Linux machine

Step-by-step. Follow it top to bottom on the machine you are installing on.
Everything runs as your own user — **no step here uses `sudo`** except the
optional lingering step, and nothing installs a system service, opens a
network listener, or changes any other software on the box.

Time: about 10 minutes, plus a wait to see the first cycle.

---

## Before you start: pick this machine's role

Every Linux machine collects its own readings. What differs is what it does
with them.

| Role | Machines | Collects | Sends to aggregator | Merges + renders |
|---|---|---|---|---|
| **Aggregator** | `mambakkam` | yes | no — it *is* the destination | yes |
| **Collector** | every other Linux box | yes | yes | no |

Steps 1–4 are identical for both. **Step 5 differs** — do 5A *or* 5B, not
both.

You need:

- Python 3.11 or newer (`python3 --version`)
- `git`, and `rsync` if this is a Collector
- For a Collector: this machine and the aggregator both on the Tailscale
  tailnet, with Tailscale SSH working

---

## Step 1 — Get the code

```bash
git clone https://github.com/wegofwd2020-hub/local_watch.git ~/local_watch
cd ~/local_watch
```

Any path works — you will record the real one in Step 3, and nothing has it
baked in. If the repo is already checked out somewhere, just `cd` there.

## Step 2 — Build the virtualenv

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

**Verify before moving on.** This step is what creates the `local_watch`
executable that every unit calls by absolute path:

```bash
.venv/bin/local_watch --help
```

Expected: a usage line listing `{collect,ingest,render}`. If you instead get
"No such file or directory", the install failed — re-read the `pip` output.
Do not continue; every later step depends on this binary existing.

## Step 3 — Configure

All units read one file, so paths are set once here rather than edited into
each unit.

```bash
mkdir -p ~/.config/local_watch
cp deploy/env.example ~/.config/local_watch/env
```

Now edit `~/.config/local_watch/env`:

- `LOCAL_WATCH_HOME` — absolute path to the checkout from Step 1 (the
  directory containing `.venv/`). Run `pwd` to get it.
- `LOCAL_WATCH_DATA` — leave as `/home/YOU/.local/share/local_watch` unless
  you have a reason. The dashboard path under it is what wegofwd-hub serves.
- `LOCAL_WATCH_REMOTE` — ships **commented out**. On a **Collector**,
  uncomment it and set `user@aggregator-magicdns-name`. On the **Aggregator**,
  leave it commented: it is the destination, and pointing it at its own
  hostname makes it try to rsync to itself.

systemd does not expand `~` or `$HOME` in this file. **Use absolute paths.**

**Verify:**

```bash
( . ~/.config/local_watch/env; ls "$LOCAL_WATCH_HOME/.venv/bin/local_watch" )
```

Expected: the path prints back. An error means `LOCAL_WATCH_HOME` is wrong.

## Step 4 — Install the collector timer (both roles)

```bash
mkdir -p ~/.config/systemd/user
cp deploy/local_watch-collect.service ~/.config/systemd/user/
cp deploy/local_watch-collect.timer   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now local_watch-collect.timer
```

**Verify** by forcing one run immediately rather than waiting:

```bash
systemctl --user start local_watch-collect.service
ls -la ~/.local/share/local_watch/spool/
```

Expected: one file named after this machine, e.g. `mambakkam.json`, with a
timestamp from seconds ago. If it is missing:

```bash
journalctl --user -u local_watch-collect.service -n 30 --no-pager
```

### If this box has no continuous login session

`systemctl --user` timers only run while a user session exists. On a headless
or rarely-logged-in box, enable lingering once (this is the only `sudo` in
the guide):

```bash
sudo loginctl enable-linger $USER
```

---

## Step 5A — Collector role only: send snapshots to the aggregator

Skip to 5B if this machine is the aggregator.

**First confirm passwordless ssh over the tailnet.** Tailscale SSH provides
this through tailnet ACL, so no key material needs to live on this box:

```bash
( . ~/.config/local_watch/env; ssh "$LOCAL_WATCH_REMOTE" true ) && echo "ssh ok"
```

If that prompts for a password or fails, fix it before continuing — the sync
unit is non-interactive and will simply fail every cycle.

Make sure the destination directory exists **on the aggregator**:

```bash
( . ~/.config/local_watch/env; ssh "$LOCAL_WATCH_REMOTE" 'mkdir -p ~/.local/share/local_watch/ingest' )
```

Then install the timer:

```bash
cp deploy/local_watch-sync.service ~/.config/systemd/user/
cp deploy/local_watch-sync.timer   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now local_watch-sync.timer
```

**Verify:**

```bash
systemctl --user start local_watch-sync.service
journalctl --user -u local_watch-sync.service -n 10 --no-pager
```

Expected: no output from `rsync` and a clean exit. Then check on the
aggregator that your file arrived:

```bash
( . ~/.config/local_watch/env; ssh "$LOCAL_WATCH_REMOTE" 'ls -la ~/.local/share/local_watch/ingest/' )
```

**You are done.** Skip to "Checking it works".

---

## Step 5B — Aggregator role only: merge and render

Skip this if you did 5A.

```bash
cp deploy/local_watch-ingest-render.service ~/.config/systemd/user/
cp deploy/local_watch-ingest-render.timer   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now local_watch-ingest-render.timer
```

The unit runs `deploy/mambakkam-ingest-render.sh`, which reads **both** the
`ingest/` directory (snapshots synced from the rest of the fleet) and this
machine's own `spool/` — so the aggregator needs no extra step to include
its own readings.

**Verify:**

```bash
systemctl --user start local_watch-ingest-render.service
ls -la ~/.local/share/local_watch/
```

Expected: `dashboard.html`, `report.md` and `store.db`. Open the report:

```bash
head -20 ~/.local/share/local_watch/report.md
```

At this point it should list at least this machine. Other machines appear
once their Step 5A sync has run.

`dashboard.html` must stay at exactly
`~/.local/share/local_watch/dashboard.html` — that is the literal path the
wegofwd-hub "Local Watch" tile serves.

---

## Checking it works

The three timers are deliberately staggered so each stage sees fresh input:

| Stage | First run after boot | Then |
|---|---|---|
| collect | +2 min | every 20 min |
| sync | +7 min | every 20 min |
| ingest + render | +12 min | every 20 min |

```bash
systemctl --user list-timers 'local_watch-*'
```

After every machine in the fleet has finished its install, wait one full cycle
(about 30 minutes) and open the wegofwd-hub "Local Watch" tile, or
`~/.local/share/local_watch/dashboard.html` directly on the aggregator.

You should see one card per machine, each with a recent timestamp, and no
`stale` or `collector_degraded` flags.

Two things look like faults but are not:

- **No `disk_filling` flags for the first ~6 hours.** The trend rule needs 6
  readings spanning at least 6 hours before it will project a fill rate. It is
  declining to extrapolate from thin data.
- **Sparklines are flat or absent at first.** They need at least two readings.

## Reading the flags

Three flags are about *trust in the data* rather than machine health, and they
are listed before the threshold flags on purpose — if the data cannot be
trusted, that is the first thing to read.

| Flag | Severity | Means |
|---|---|---|
| `stale` | crit | No snapshot for over 60 minutes. The numbers on that card are history. Collect or sync has stopped, or the machine is off. A laptop that sleeps overnight shows this every morning — correctly. |
| `collector_degraded` | crit | One or more probes could not run; the message names them. The affected metrics are **absent, not zero**. |
| `disk_filling` | crit / warn | Projected to hit 100% within 2 days (crit) or 7 days (warn), fitted against real elapsed time. |

## Troubleshooting

**A machine never appears on the dashboard at all** — it has never been
ingested. Check its spool file exists and is recent, that sync landed it in
the aggregator's `ingest/`, and that the ingest unit ran:

```bash
ls -la ~/.local/share/local_watch/spool/                                   # on the collector
journalctl --user -u local_watch-sync.service -n 20 --no-pager             # on the collector
ls -la ~/.local/share/local_watch/ingest/                                  # on the aggregator
journalctl --user -u local_watch-ingest-render.service -n 20 --no-pager    # on the aggregator
```

**A machine appears but is flagged `stale`** — it was ingested once and has
stopped reporting since. The merge pipeline is fine; the break is upstream.
Check the collect timer on that box first, then its sync timer.

**A machine is flagged `collector_degraded`** — read which probes the message
names. `df`, `free` failing usually means a PATH problem (systemd does not
source your shell rc files). `apt` failing usually means the dpkg lock was
held by another process.

**Recommendations say `[LLM unavailable - deterministic rules only]`** — the
flags are still correct; only the plain-language advice is missing. The agent
reads `~/.config/wegofwd/anthropic_api_key` and needs `wegofwd-llm` installed,
which `pip install -e .` pulls in when it has network access.

**Sync fails with `LOCAL_WATCH_REMOTE points at this machine`** — this box is
the aggregator but was set up with step 5A. Remove the sync units, comment out
`LOCAL_WATCH_REMOTE`, and do step 5B instead:

```bash
systemctl --user disable --now local_watch-sync.timer
rm -f ~/.config/systemd/user/local_watch-sync.*
systemctl --user daemon-reload
```

**Sync fails with an ssh `Permission denied` or `Too many authentication
failures`** — the aggregator is genuinely refusing this box. Re-run the
`ssh "$LOCAL_WATCH_REMOTE" true` check from Step 5A.

**A unit fails with "No such file or directory"** — almost always
`LOCAL_WATCH_HOME` pointing at a directory with no built `.venv`. Re-run
Step 2 and confirm `.venv/bin/local_watch --help` works.

## Uninstalling

```bash
systemctl --user disable --now local_watch-collect.timer
systemctl --user disable --now local_watch-sync.timer            # collector
systemctl --user disable --now local_watch-ingest-render.timer   # aggregator
rm -f ~/.config/systemd/user/local_watch-*
systemctl --user daemon-reload
```

Collected data stays in `~/.local/share/local_watch/`; delete it separately if
you want it gone.

## What this actually runs

`collect` shells out only to read-only probes — `df -P`, `free -b`,
`apt list --upgradable`, `systemctl --failed`. `sync` runs one `rsync` of one
JSON file. `ingest`/`render` read that JSON and write inside
`~/.local/share/local_watch/`. Nothing starts, stops, restarts or
reconfigures any other service on this machine.
