#!/usr/bin/env bash
# Push this machine's one spool snapshot to the aggregator's ingest directory
# over Tailscale. Used by local_watch-sync.service (Linux) and
# com.wegofwd.localwatch-sync.plist (macOS) so both platforms guard
# identically — the checks below used to be duplicated in a unit file and a
# plist XML string, which is how they drifted apart.
#
# Writes exactly one file to a path under the remote user's home. Reads
# nothing back and runs nothing remotely.
set -euo pipefail

# systemd supplies these via EnvironmentFile; launchd does not, so source the
# same file here. Re-sourcing under systemd is harmless: same file, same values.
if [ -f "$HOME/.config/local_watch/env" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.config/local_watch/env"
fi
: "${LOCAL_WATCH_DATA:=$HOME/.local/share/local_watch}"

if [ -z "${LOCAL_WATCH_REMOTE:-}" ]; then
    echo "local_watch-sync: LOCAL_WATCH_REMOTE is not set in ~/.config/local_watch/env." >&2
    echo "  If this machine is the aggregator it should not run this unit at all —" >&2
    echo "  see deploy/INSTALL-linux.md step 5B." >&2
    exit 1
fi

# Refuse to sync to ourselves. Getting this wrong is the single easiest deploy
# mistake — the aggregator's own hostname is the value every other machine
# needs — and left unguarded it surfaces as an ssh "Too many authentication
# failures", which sends the operator looking at ssh keys instead of at roles.
this_host="$(hostname -s | tr '[:upper:]' '[:lower:]')"
remote_host="${LOCAL_WATCH_REMOTE#*@}"      # drop user@, if present
remote_host="${remote_host%%.*}"            # drop the domain, keep the short name
remote_host="$(printf '%s' "$remote_host" | tr '[:upper:]' '[:lower:]')"

if [ "$remote_host" = "$this_host" ]; then
    echo "local_watch-sync: LOCAL_WATCH_REMOTE points at this machine ($this_host)." >&2
    echo "  This machine is the aggregator: it is the destination, so it has" >&2
    echo "  nothing to sync to. Blank LOCAL_WATCH_REMOTE in" >&2
    echo "  ~/.config/local_watch/env and install local_watch-ingest-render" >&2
    echo "  instead — deploy/INSTALL-linux.md step 5B." >&2
    exit 1
fi

snapshot="$LOCAL_WATCH_DATA/spool/$(hostname -s).json"
if [ ! -f "$snapshot" ]; then
    # Not an error. The aggregator's staleness rule is what reports a machine
    # that has stopped producing snapshots; failing here would only add noise.
    echo "local_watch-sync: no snapshot at $snapshot yet; nothing to push" >&2
    exit 0
fi

exec rsync -az --rsh=ssh "$snapshot" "$LOCAL_WATCH_REMOTE:.local/share/local_watch/ingest/"
