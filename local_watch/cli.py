from __future__ import annotations
import argparse, platform, datetime
from local_watch.schema import Snapshot
from local_watch.store import Store
from local_watch import rules, agent, report

def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _collect(machine: str) -> Snapshot:
    if platform.system() == "Darwin":
        from local_watch.collectors import macos as c
    else:
        from local_watch.collectors import linux as c
    return c.collect(machine=machine or platform.node(), now=_now())

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="local_watch")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect"); c.add_argument("--machine", default=""); c.add_argument("--out", required=True)
    i = sub.add_parser("ingest"); i.add_argument("--store", required=True); i.add_argument("files", nargs="+")
    r = sub.add_parser("render"); r.add_argument("--store", required=True)
    r.add_argument("--html", required=True); r.add_argument("--md", required=True)
    sub.add_parser("review")  # alias handled below
    a = ap.parse_args(argv)

    if a.cmd == "collect":
        open(a.out, "w").write(_collect(a.machine).to_json()); return 0
    if a.cmd == "ingest":
        st = Store(a.store)
        for fp in a.files:
            st.append(Snapshot.from_json(open(fp).read()))
        return 0
    if a.cmd in ("render", "review"):
        st = Store(a.store)
        snaps = [st.latest(m) for m in st.machines()]
        flags = []
        series = {}
        for s in snaps:
            ser = {m.name: st.series(s.machine, m.name, 20) for m in s.metrics}
            series[s.machine] = ser
            flags += rules.evaluate(s, ser)
        recs = agent.recommend(snaps, flags)
        open(a.html, "w").write(report.render_dashboard(snaps, flags, recs, series))
        open(a.md, "w").write(report.render_markdown(snaps, flags, recs))
        return 0
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
