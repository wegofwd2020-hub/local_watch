#!/usr/bin/env bash
# Merge every synced snapshot into the history store, then re-render the
# dashboard and markdown report. Invoked by local_watch-ingest-render.service;
# safe to run by hand for a manual cycle.
#
# Reads $LOCAL_WATCH_DATA/ingest and writes only inside $LOCAL_WATCH_DATA.
# Ingested files are deliberately NOT deleted: each machine overwrites its own
# <hostname>.json, so the directory stays bounded at one file per machine, and
# re-ingesting is idempotent (the store keys on machine+timestamp). Leaving a
# dead machine's last file in place costs nothing — its snapshot is already in
# the store, and the staleness rule is what reports the machine as gone.
set -euo pipefail

: "${LOCAL_WATCH_HOME:?set it in ~/.config/local_watch/env (see deploy/env.example)}"
DATA="${LOCAL_WATCH_DATA:-$HOME/.local/share/local_watch}"
BIN="$LOCAL_WATCH_HOME/.venv/bin/local_watch"

if [ ! -x "$BIN" ]; then
    echo "local_watch: no executable at $BIN — run 'python3 -m venv .venv && .venv/bin/pip install -e .' in $LOCAL_WATCH_HOME" >&2
    exit 1
fi

mkdir -p "$DATA/ingest"

# An unmatched glob would otherwise be passed through literally and read as a
# filename, so expand it explicitly and check.
shopt -s nullglob
snapshots=("$DATA/ingest"/*.json)

if [ ${#snapshots[@]} -gt 0 ]; then
    "$BIN" ingest --store "$DATA/store.db" "${snapshots[@]}"
else
    # Not an error: render anyway, so the dashboard keeps showing the fleet's
    # existing history with staleness flags rather than going blank the moment
    # a sync breaks.
    echo "local_watch: no snapshots in $DATA/ingest; rendering existing history" >&2
fi

# This --html path is load-bearing: wegofwd-hub's "Local Watch" tile serves
# exactly $DATA/dashboard.html. Changing it means editing portal/tiles.py too.
"$BIN" render \
    --store "$DATA/store.db" \
    --html "$DATA/dashboard.html" \
    --md "$DATA/report.md"
