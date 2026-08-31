from __future__ import annotations
import argparse, platform, datetime, os, sys, tempfile
from local_watch.schema import Snapshot
from local_watch.store import Store
from local_watch import rules, agent, report

# How many readings to pull per metric when rendering. At the deployed
# 20-minute cadence this is ~4 days of history — enough for the trend rules
# to fit a rate against, and still enough on a box sampling far more often.
_HISTORY_POINTS = 288

def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _collect(machine: str) -> Snapshot:
    if platform.system() == "Darwin":
        from local_watch.collectors import macos as c
    else:
        from local_watch.collectors import linux as c
    return c.collect(machine=machine or platform.node(), now=_now())

def _write_atomic(path: str, data: str) -> None:
    """Write `data` to `path` atomically via a same-directory temp file plus
    os.replace, so a concurrent reader sees either the old complete file or
    the new one — never the truncated-then-half-written middle.

    collect and sync both carry RunAtLoad=true, so at every login/reboot they
    fire at once; a plain open(path, "w") truncates in place, and the sync
    rsync can grab the spool file inside that window and ship a 0-byte
    snapshot to the aggregator. os.replace is atomic on the same filesystem,
    which the temp file is guaranteed to share by living in the same dir."""
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="local_watch")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect"); c.add_argument("--machine", default=""); c.add_argument("--out", required=True)
    i = sub.add_parser("ingest"); i.add_argument("--store", required=True); i.add_argument("files", nargs="+")
    r = sub.add_parser("render"); r.add_argument("--store", required=True)
    r.add_argument("--html", required=True); r.add_argument("--md", required=True)
    a = ap.parse_args(argv)

    if a.cmd == "collect":
        _write_atomic(a.out, _collect(a.machine).to_json()); return 0
    if a.cmd == "ingest":
        st = Store(a.store)
        for fp in a.files:
            try:
                snap = Snapshot.from_json(open(fp).read())
            except (OSError, ValueError, KeyError, TypeError) as e:
                # A truncated or empty snapshot — e.g. a sync that raced a
                # non-atomic collect write — must not abort ingest of the whole
                # fleet: mambakkam-ingest-render.sh passes every machine's file
                # in one call, so one bad file would otherwise sink the entire
                # render. Skip it loudly; the machine's staleness rule reports
                # the gap if no good snapshot ever lands.
                print(f"local_watch ingest: skipping {fp}: {e}", file=sys.stderr)
                continue
            st.append(snap)
        return 0
    if a.cmd == "render":
        st = Store(a.store)
        snaps = [st.latest(m) for m in st.machines()]
        flags = []
        series = {}
        # One clock for the whole render, so every machine is judged
        # stale-or-fresh against the same instant.
        now = _now()
        for s in snaps:
            ser = {m.name: st.series(s.machine, m.name, _HISTORY_POINTS) for m in s.metrics}
            series[s.machine] = ser
            flags += rules.evaluate(s, ser, now=now)
        recs = agent.recommend(snaps, flags)
        open(a.html, "w").write(report.render_dashboard(snaps, flags, recs, series, now=now))
        open(a.md, "w").write(report.render_markdown(snaps, flags, recs))
        return 0
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
