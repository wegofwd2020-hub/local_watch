# Installing local_watch on the MacBook

Step-by-step. Follow it top to bottom on the Mac. Everything runs as your own
user — **no step here uses `sudo`**, nothing installs a system daemon, and
nothing changes any other software on the machine.

Time: about 10 minutes, plus a wait to see the first cycle.

---

## What gets installed

Two LaunchAgents, both running as you, both on a 20-minute interval:

| Agent | Does |
|---|---|
| `com.wegofwd.localwatch` | Takes one read-only snapshot of this Mac |
| `com.wegofwd.localwatch-sync` | Copies that snapshot to `mambakkam` over Tailscale |

The Mac never merges or renders anything — that happens on the aggregator.

You need:

- Python 3.11 or newer (`python3 --version`; install via Homebrew or
  python.org if the system Python is older)
- Command Line Tools for `git` — `xcode-select --install` if missing
- This Mac and `mambakkam` both on the Tailscale tailnet, with Tailscale SSH
  working

---

## Step 1 — Get the code

```bash
git clone https://github.com/wegofwd2020-hub/local_watch.git ~/local_watch
cd ~/local_watch
```

Any path works — you record the real one in Step 3, and nothing has it baked
in.

## Step 2 — Build the virtualenv

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

**Verify before moving on.** This is what creates the `local_watch`
executable that both agents call:

```bash
.venv/bin/local_watch --help
```

Expected: a usage line listing `{collect,ingest,render}`. If you get "No such
file or directory" instead, the install failed — re-read the `pip` output and
do not continue.

## Step 3 — Configure

Both agents read one file, the same one the Linux machines use.

```bash
mkdir -p ~/.config/local_watch
cp deploy/env.example ~/.config/local_watch/env
```

Edit `~/.config/local_watch/env`:

- `LOCAL_WATCH_HOME` — absolute path to the checkout from Step 1. Run `pwd`.
  On macOS this will start `/Users/`, not `/home/`, so the example value
  **must** be changed.
- `LOCAL_WATCH_DATA` — `/Users/YOU/.local/share/local_watch`.
- `LOCAL_WATCH_REMOTE` — `user@mambakkam-magicdns-name`, e.g.
  `sivam@mambakkam.tail242406.ts.net`.

**Verify:**

```bash
( . ~/.config/local_watch/env; ls "$LOCAL_WATCH_HOME/.venv/bin/local_watch" )
```

Expected: the path prints back.

## Step 4 — Test a collection by hand

Before handing it to launchd, confirm the collector works on this Mac. This is
worth doing deliberately: the macOS collector was written against synthetic
fixtures and this may be its first run on real hardware.

```bash
( . ~/.config/local_watch/env
  mkdir -p "$LOCAL_WATCH_DATA/spool"
  "$LOCAL_WATCH_HOME/.venv/bin/local_watch" collect \
    --machine "$(hostname -s)" \
    --out "$LOCAL_WATCH_DATA/spool/$(hostname -s).json" )

python3 -m json.tool ~/.local/share/local_watch/spool/$(hostname -s).json
```

Read the output before continuing. You want:

- `"probes_failed": ""` — **empty**. If it names probes, see
  "If `probes_failed` is not empty" below.
- `disk_root_pct` reflecting your real disk use. On APFS the collector reports
  `/System/Volumes/Data`, not the sealed `/` snapshot, so this should look like
  what Finder shows — not a near-empty number.
- `failed_units` listing any launch agents whose last exit code was non-zero.

This step can take up to two minutes, because `softwareupdate --list` talks to
Apple's servers.

### If `probes_failed` is not empty

- **`softwareupdate`** — the probe exceeded its 120-second budget. Time it by
  hand with `time softwareupdate --list`. If it genuinely takes longer on your
  network, raise `SLOW_PROBE_TIMEOUT` in `local_watch/collectors/base.py`.
  Do not ignore the flag: under this project's rules a timeout is *reported*
  rather than quietly rounded down to "0 updates pending".
- **`df` / `vm_stat` / `launchctl`** — unexpected; these are all built in.
  Run the command by hand to see what it says.

## Step 5 — Install the collect agent

```bash
mkdir -p ~/Library/LaunchAgents
cp deploy/com.wegofwd.localwatch.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.wegofwd.localwatch.plist
```

**No editing of the plist is required** — every path is read at runtime from
the file you wrote in Step 3.

`RunAtLoad` means it collects immediately. **Verify:**

```bash
launchctl list | grep localwatch
ls -la ~/.local/share/local_watch/spool/
cat ~/.local/share/local_watch/collect.log
```

Expected: the agent listed with exit status `0` in the second column, a
freshly-timestamped snapshot in `spool/`, and a log with a `--- collect`
line and no errors after it.

A non-zero status in `launchctl list` means the last run failed — read
`collect.log`.

## Step 6 — Set up the sync

**First confirm passwordless ssh over the tailnet.** Tailscale SSH provides
this via tailnet ACL, so no key material needs to live on this Mac:

```bash
( . ~/.config/local_watch/env; ssh "$LOCAL_WATCH_REMOTE" true ) && echo "ssh ok"
```

If that prompts for anything or fails, fix it first — the sync agent is
non-interactive and will just fail every cycle.

Make sure the destination exists on the aggregator:

```bash
( . ~/.config/local_watch/env; ssh "$LOCAL_WATCH_REMOTE" 'mkdir -p ~/.local/share/local_watch/ingest' )
```

Install the agent:

```bash
cp deploy/com.wegofwd.localwatch-sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.wegofwd.localwatch-sync.plist
```

**Verify:**

```bash
cat ~/.local/share/local_watch/sync.log
( . ~/.config/local_watch/env; ssh "$LOCAL_WATCH_REMOTE" 'ls -la ~/.local/share/local_watch/ingest/' )
```

Expected: a `--- sync` line with no `rsync` error after it, and this Mac's
`<hostname>.json` present on the aggregator.

---

## Checking it works

Both agents run every 20 minutes from the moment they were loaded. Wait one
cycle, then check on the aggregator (or open the wegofwd-hub "Local Watch"
tile) that this Mac has a card with a recent timestamp and no `stale` flag.

Two things look like faults but are not:

- **No `disk_filling` flag for the first ~6 hours.** The trend rule needs 6
  readings spanning at least 6 hours before projecting a fill rate.
- **A `stale` flag every morning** if the Mac sleeps overnight. Snapshots go
  stale after 60 minutes, and a sleeping laptop is genuinely not reporting.
  That is the rule working.

### Sleep and lids

launchd does not run `StartInterval` agents while the Mac is asleep. It fires
once shortly after wake, so a closed laptop reports nothing until you open it.
This is expected and is exactly what the `stale` flag is for — the fleet view
will correctly show the Mac as not-currently-known rather than showing you
yesterday's numbers as if they were current.

## Troubleshooting

**`launchctl list` shows a non-zero status** — read
`~/.local/share/local_watch/collect.log` or `sync.log`. Both agents log every
run with a UTC timestamp.

**The agent does nothing and the log is empty** — the plist may not have
loaded. `launchctl list | grep localwatch` should show it. If not, re-run
`launchctl load` and read the error.

**"missing ~/.config/local_watch/env"** in the log — Step 3 was skipped or the
file is somewhere else.

**Sync fails with an `rsync` error** — usually ssh. Re-run the `ssh ... true`
check from Step 6. A `connection unexpectedly closed` means the aggregator
was unreachable, which on a laptop often just means the tailnet had not come
up yet after wake; it will succeed on the next cycle.

**`failed_units` lists a lot of Apple agents** — `launchctl list` reports the
last exit code, and some system agents legitimately exit non-zero. If the
noise is unhelpful, that filter is worth tuning in
`local_watch/collectors/macos.py` (`_failed_agents`).

## Uninstalling

```bash
launchctl unload ~/Library/LaunchAgents/com.wegofwd.localwatch.plist
launchctl unload ~/Library/LaunchAgents/com.wegofwd.localwatch-sync.plist
rm -f ~/Library/LaunchAgents/com.wegofwd.localwatch*.plist
```

Collected data stays in `~/.local/share/local_watch/`; delete it separately if
you want it gone.

## What this actually runs

`collect` shells out only to read-only probes — `df -P`, `vm_stat`,
`softwareupdate --list`, `launchctl list`. `launchctl list` only *lists*; it
never loads or unloads anything. `sync` runs one `rsync` of one JSON file to
one directory. Nothing starts, stops or reconfigures any service on this Mac.
