from __future__ import annotations
from local_watch.schema import Snapshot
from local_watch.rules import Flag

_SEV = {"crit": "#d64545", "warn": "#d9a441", "info": "#5b8def"}

def _sparkline(vals: list[float], w: int = 100, h: int = 24) -> str:
    if len(vals) < 2:
        return "<svg width='%d' height='%d'></svg>" % (w, h)
    lo, hi = min(vals), max(vals); rng = (hi - lo) or 1.0
    pts = " ".join(f"{i*(w/(len(vals)-1)):.1f},{h-(v-lo)/rng*h:.1f}" for i, v in enumerate(vals))
    return f"<svg width='{w}' height='{h}'><polyline fill='none' stroke='#5b8def' stroke-width='1.5' points='{pts}'/></svg>"

def _status(flags: list[Flag]) -> str:
    sevs = {f.severity for f in flags}
    return "crit" if "crit" in sevs else "warn" if "warn" in sevs else "info"

def render_dashboard(snapshots, flags, recs, series) -> str:
    cards = []
    for s in snapshots:
        mf = [f for f in flags if f.machine == s.machine]
        dot = _SEV[_status(mf)]
        mrows = "".join(f"<div class='m'>{m.name}: <b>{m.value}{m.unit}</b> "
                        f"{_sparkline(series.get(s.machine, {}).get(m.name, []))}</div>" for m in s.metrics)
        frows = "".join(f"<li style='color:{_SEV[f.severity]}'>[{f.severity}] {f.message}</li>" for f in mf) or "<li>OK</li>"
        cards.append(f"<section class='card'><h2><span class='dot' style='background:{dot}'></span>{s.machine}"
                     f" <small>{s.os}</small></h2>{mrows}<ul>{frows}</ul>"
                     f"<pre class='rec'>{recs.get(s.machine,'')}</pre></section>")
    issues = len(flags)
    return ("<!doctype html><html><head><meta charset='utf-8'><title>local_watch</title><style>"
            "body{font:14px system-ui;margin:1.5rem;background:#0e0b1f;color:#eee}"
            ".card{background:#1b1633;border-radius:10px;padding:1rem;margin:.75rem 0}"
            ".dot{display:inline-block;width:.7rem;height:.7rem;border-radius:50%;margin-right:.4rem}"
            ".m{margin:.2rem 0}.rec{white-space:pre-wrap;background:#0e0b1f;padding:.6rem;border-radius:6px}"
            "small{opacity:.6}</style></head><body>"
            f"<h1>local_watch — {len(snapshots)} machines · {issues} issues</h1>"
            + "".join(cards) + "</body></html>")

def render_markdown(snapshots, flags, recs) -> str:
    out = [f"# local_watch — {len(snapshots)} machines, {len(flags)} issues", ""]
    for s in snapshots:
        out.append(f"## {s.machine} ({s.os})")
        out += [f"- {m.name}: {m.value}{m.unit}" for m in s.metrics]
        for f in [fl for fl in flags if fl.machine == s.machine]:
            out.append(f"- **[{f.severity}]** {f.message}")
        out += ["", "**Recommendations:**", recs.get(s.machine, "(none)"), ""]
    return "\n".join(out)
