# local_watch deploy runbook

**Nothing in this directory is enabled automatically.** These are inert unit
files, a plist, and instructions. Every step below is run by hand by the
operator on the target machine. `local_watch` itself only ever calls
read-only probes (see `local_watch/collectors/linux.py` and
`local_watch/collectors/macos.py`) — collection never mutates system state,
and none of these deploy steps install a privileged service, open a network
listener, or run as root.

Fleet shape assumed below: three machines total, one of which is
`mambakkam` (the box that also runs wegofwd-hub and will host the merged
store + rendered dashboard). Substitute real hostnames as needed.

---

## 1. Every Linux box (including mambakkam itself, as a collector)

```bash
cd ~/local_watch   # or wherever this repo is checked out
python3 -m venv .venv
.venv/bin/pip install -e .

mkdir -p ~/.local/share/local_watch/spool
mkdir -p ~/.config/systemd/user

cp deploy/local_watch-collect.service ~/.config/systemd/user/
cp deploy/local_watch-collect.timer   ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now local_watch-collect.timer
```

Check it fired:

```bash
systemctl --user list-timers local_watch-collect.timer
journalctl --user -u local_watch-collect.service --since -1h
ls ~/.local/share/local_watch/spool/
```

Note: `systemctl --user` units only run while a user session/systemd-user
instance is active. If this box has no interactive login session running
continuously, enable lingering once so the timer still fires:
`sudo loginctl enable-linger $USER`.

## 2. The Mac

```bash
cd ~/local_watch
pip install -e .   # or: python3 -m venv .venv && .venv/bin/pip install -e .

mkdir -p ~/.local/share/local_watch/spool
```

Edit `deploy/com.wegofwd.localwatch.plist` first: replace every
`/Users/YOURUSER` with the real home directory, and every `%HOST%` with the
machine's actual hostname (`scutil --get LocalHostName` or `hostname -s`) —
launchd does not do systemd-style `%H` expansion.

```bash
cp deploy/com.wegofwd.localwatch.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.wegofwd.localwatch.plist
```

Check it fired:

```bash
launchctl list | grep com.wegofwd.localwatch
ls ~/.local/share/local_watch/spool/
tail ~/.local/share/local_watch/collect.out.log
```

To stop/uninstall later: `launchctl unload ~/Library/LaunchAgents/com.wegofwd.localwatch.plist`.

## 3. Sync each box's spool to mambakkam, over Tailscale

Every box (mambakkam included, trivially) has exactly one spool file that
matters, `<hostname>.json`, refreshed every ~20 min by step 1/2 above. Sync
it into an ingest directory on mambakkam using the tailnet MagicDNS name
(`*.tail242406.ts.net`) — never a public/LAN address.

On **mambakkam**, once, create the ingest dir:

```bash
mkdir -p ~/.local/share/local_watch/ingest
```

On **each remote box**, add a second small user timer/cron (or just extend
the existing collect timer's `OnUnitActiveSec` schedule with a follow-up
oneshot — either is fine) that pushes the spool file after collecting.
Simplest form, run every 20 min right after collect, via `rsync` over ssh
on the tailnet:

```bash
rsync -az --rsh=ssh \
  ~/.local/share/local_watch/spool/$(hostname -s).json \
  sivam@mambakkam.tail242406.ts.net:~/.local/share/local_watch/ingest/
```

Equivalent with `scp`:

```bash
scp ~/.local/share/local_watch/spool/$(hostname -s).json \
  sivam@mambakkam.tail242406.ts.net:~/.local/share/local_watch/ingest/
```

Or, if the box has the Tailscale CLI's file-sharing enabled instead of SSH:

```bash
tailscale file cp \
  ~/.local/share/local_watch/spool/$(hostname -s).json \
  mambakkam.tail242406.ts.net:
```

(`tailscale file cp` drops files into the receiving node's Taildrop inbox —
on mambakkam that lands under `~/Downloads` by default unless
`tailscale file get` is configured to move them into the ingest dir; prefer
`rsync`/`scp` above for a direct, scriptable drop into the ingest dir.)

Wrap whichever command you pick in its own oneshot unit
(`local_watch-sync.service` + `.timer`, same pattern as the collect unit —
not included here since the exact transport is a per-box choice) or a cron
line, scheduled a few minutes after the collect timer so the file exists
before the sync runs, e.g. `OnUnitActiveSec=20min` offset by
`OnBootSec=5min`.

**mambakkam itself** doesn't need this sync step — its own collect timer
can write straight into the ingest directory instead of (or in addition
to) the spool dir, or a trivial local `cp` after collect works too.

## 4. On mambakkam: ingest + render on a schedule

Add one more systemd user timer on mambakkam (same pattern as
`local_watch-collect.timer`, not shipped as a separate file here since it's
a single box's job) that runs, every ~20-25 minutes (a little after the
sync step above so newly-synced files are picked up):

```bash
local_watch ingest --store ~/.local/share/local_watch/store.db \
  ~/.local/share/local_watch/ingest/*.json

local_watch render --store ~/.local/share/local_watch/store.db \
  --html ~/.local/share/local_watch/dashboard.html \
  --md   ~/.local/share/local_watch/report.md
```

The `--html` path **must** be exactly
`~/.local/share/local_watch/dashboard.html` — that is the literal path the
wegofwd-hub "Local Watch" tile serves (`portal/tiles.py`,
`{"slug": "local-watch", ..., "path": "~/.local/share/local_watch/dashboard.html"}`).
Do not change it without also updating that tile entry.

Minimal example unit/timer pair for this step (create these two files
directly on mambakkam under `~/.config/systemd/user/`, following the same
shape as `deploy/local_watch-collect.service`/`.timer` in this repo, but
with `ExecStart` running the two `local_watch` commands above via a small
wrapper script, e.g. `~/local_watch/deploy/mambakkam-ingest-render.sh`,
since a oneshot unit's `ExecStart` runs one command — chain the two calls
in a one-line shell script or an `ExecStart=` + `ExecStartPost=` pair).

## 5. Verify

After steps 1–4 are enabled on all three machines and at least one
collect+sync+ingest+render cycle has run (wait ~20-30 min, or invoke the
oneshot services manually with `systemctl --user start
local_watch-collect.service` to test without waiting for the timer):

- Open the wegofwd-hub launcher and click the "Local Watch" tile (or open
  `~/.local/share/local_watch/dashboard.html` directly in a browser) on
  mambakkam.
- Confirm the dashboard shows **all three machines** as cards, each with a
  recent-looking timestamp and sparklines.
- Confirm `~/.local/share/local_watch/report.md` also lists all three.

If a machine is missing: check that its spool file exists and is recent
(`ls -la ~/.local/share/local_watch/spool/`), that the sync step actually
landed the file in mambakkam's ingest dir, and that `local_watch ingest`
ran after the sync (check `journalctl --user -u <ingest-unit>`).

## Read-only invariant

Every unit in this directory (and the ad hoc ingest/render unit described
in step 4) only ever runs `local_watch collect`, `local_watch ingest`, or
`local_watch render`, plus a file-copy (`rsync`/`scp`/`tailscale file cp`).
None of these write to any location outside `~/.local/share/local_watch/`
(and, for sync, the same path on the remote), none require sudo/root, and
`collect` itself only calls the read-only probes in
`local_watch/collectors/{linux,macos}.py` (uptime/disk/mem/service-status
style reads — grep those files for `subprocess`/`run` calls to confirm no
probe passes a mutating flag). No unit here starts, stops, restarts, or
reconfigures any other service on the machine it runs on.
