from __future__ import annotations
import datetime
from html import escape
from local_watch.rules import Flag, DISK_WARN_PCT, DISK_CRIT_PCT, age_label

# Status palette (fixed, never themed) on the dark chart surface. Every one of
# these clears 3:1 against #1a1a19. Status colour never carries meaning on its
# own here: each mark ships with its number or its label.
_GOOD, _WARN, _SERIOUS, _CRIT = "#0ca30c", "#fab219", "#ec835a", "#d03b3b"
_SERIES = "#3987e5"          # magnitude marks (sparklines) — not a status
_SURFACE, _CARD = "#1a1a19", "#232322"
_INK, _INK_DIM = "#ffffff", "#c3c2b7"

_SEV = {"crit": _CRIT, "warn": _WARN, "info": _SERIES, "good": _GOOD}
_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"

# A line through two points is a straight segment at whatever angle that pair
# happens to make — it reads as a trend the data has not earned, and on a
# freshly-installed machine it was the loudest mark on the card.
_MIN_SPARK_POINTS = 3


def _metric(snap, name):
    for m in snap.metrics:
        if m.name == name:
            return m
    return None


def _status(flags: list[Flag]) -> str:
    sevs = {f.severity for f in flags}
    return "crit" if "crit" in sevs else "warn" if "warn" in sevs else "info" if sevs else "good"


def _age(ts: str, now: str | None) -> str:
    """Relative age of a reading. Freshness belongs in the header: a stale card
    shows history, and the reader needs to know that before reading any number."""
    if not now:
        return ""
    try:
        seen = datetime.datetime.strptime(ts, _TS_FMT)
        current = datetime.datetime.strptime(now, _TS_FMT)
    except (ValueError, TypeError):
        return "age unknown"
    return f"{age_label(max(0, int((current - seen).total_seconds() // 60)))} ago"


def _band(pct: float) -> str:
    return "crit" if pct >= DISK_CRIT_PCT else "warn" if pct >= DISK_WARN_PCT else "good"


def _meter(pct: float, label: str, w: int = 220, h: int = 8) -> str:
    """A ratio against a known limit. Thresholds are drawn because the number
    alone does not say whether 78% is comfortable."""
    fill = max(0.0, min(100.0, pct)) / 100.0 * w
    ticks = "".join(
        f"<line class='threshold' x1='{t/100*w:.1f}' y1='0' x2='{t/100*w:.1f}' y2='{h}'/>"
        for t in (DISK_WARN_PCT, DISK_CRIT_PCT))
    return (f"<svg class='meter meter-{_band(pct)}' width='{w}' height='{h}' role='img'>"
            f"<title>{escape(label)} {pct:g}% (warn {DISK_WARN_PCT}%, crit {DISK_CRIT_PCT}%)</title>"
            f"<rect class='track' x='0' y='0' width='{w}' height='{h}' rx='4'/>"
            f"<rect class='fill' x='0' y='0' width='{fill:.1f}' height='{h}' rx='4'/>"
            f"{ticks}</svg>")


def _sparkline(points, label: str = "", w: int = 160, h: int = 18) -> str:
    """Shape over time. Points are spaced evenly rather than by elapsed time:
    at this width it reads the same, and the rules layer — not the picture —
    is what draws conclusions from the real intervals."""
    vals = [v for _, v in points]
    if len(vals) < _MIN_SPARK_POINTS:
        n = len(vals)
        return f"<span class='note'>{n} reading{'' if n == 1 else 's'}</span>"
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    pts = " ".join(f"{i*(w/(len(vals)-1)):.1f},{h-(v-lo)/rng*h:.1f}" for i, v in enumerate(vals))
    return (f"<svg class='spark' width='{w}' height='{h}' role='img'>"
            f"<title>{escape(label)}: {len(vals)} readings, {lo:g}–{hi:g}</title>"
            f"<polyline points='{pts}'/></svg>")


def _chip(text: str, kind: str) -> str:
    return f"<span class='chip chip-{kind}'>{escape(text)}</span>"


def _stat(label: str, value: str, kind: str) -> str:
    """A count is not a ratio — there is no maximum to draw it against, so it
    gets a figure rather than a bar."""
    return (f"<div class='stat stat-{kind}'><div class='stat-v'>{escape(value)}</div>"
            f"<div class='stat-l'>{escape(label)}</div></div>")


def _row(label: str, body: str) -> str:
    return f"<div class='row'><div class='rl'>{escape(label)}</div><div class='rb'>{body}</div></div>"


def _facts(snap) -> str:
    """Facts used to appear only as flag prose. Each gets the form that fits:
    a count is a figure, a list of names is one chip per name, a boolean is a
    pill, and absent data is said out loud rather than shown as zero."""
    out = []
    failed = snap.facts.get("probes_failed", "")
    if failed:
        out.append(_row("Probes", "".join(_chip(p, "warn") for p in failed.split(",") if p)
                        + "<span class='note'>readings missing, not zero</span>"))
    if "updates_pending" in snap.facts:
        raw = snap.facts["updates_pending"]
        n = int(raw) if raw.isdigit() else 0
        out.append(_row("Updates", _stat("packages pending", raw, "warn" if n >= 20 else "info" if n else "good")))
    if "failed_units" in snap.facts:
        units = [u for u in snap.facts["failed_units"].split(",") if u]
        out.append(_row("Services", "".join(_chip(u, "crit") for u in units)
                        if units else _chip("none failed", "good")))
    if snap.facts.get("reboot_required") == "true":
        out.append(_row("Reboot", _chip("reboot required", "warn")))
    return "".join(out)


def _metrics(snap, series) -> str:
    out = []
    disk = _metric(snap, "disk_root_pct")
    if disk is not None:
        pts = series.get(snap.machine, {}).get("disk_root_pct", [])
        out.append(_row("Disk", f"{_meter(disk.value, 'disk')}"
                                f"<span class='v'>{disk.value:g}{escape(disk.unit)}</span>"
                                f"<span class='note'>warn {DISK_WARN_PCT} · crit {DISK_CRIT_PCT}</span>"
                                + (f"<span class='note'>trend</span>"
                                   f"{_sparkline(pts, 'disk', w=120, h=18)}" if len(pts) > 1 else "")))
    mem = _metric(snap, "mem_used_pct")
    if mem is not None:
        pts = series.get(snap.machine, {}).get("mem_used_pct", [])
        out.append(_row("Memory", f"{_sparkline(pts, 'memory')}"
                                  f"<span class='v'>{mem.value:g}{escape(mem.unit)}</span>"))
    for m in snap.metrics:
        if m.name not in ("disk_root_pct", "mem_used_pct"):
            pts = series.get(snap.machine, {}).get(m.name, [])
            out.append(_row(m.name, f"{_sparkline(pts, m.name)}"
                                    f"<span class='v'>{m.value:g}{escape(m.unit)}</span>"))
    return "".join(out)


def _fleet_row(snap, flags, now) -> str:
    sev = _status(flags)
    disk = _metric(snap, "disk_root_pct")
    mem = _metric(snap, "mem_used_pct")
    cells = [f"<span class='dot' style='background:{_SEV[sev]}'></span>"
             f"<span class='fm'>{escape(snap.machine)}</span>",
             f"<span class='fa'>{escape(_age(snap.ts, now))}</span>",
             _meter(disk.value, "disk", w=90, h=6) + f"<span class='v'>{disk.value:g}%</span>"
             if disk is not None else "<span class='note'>disk —</span>",
             f"<span class='v'>{mem.value:g}%</span>" if mem is not None else "<span class='note'>mem —</span>",
             f"<span class='v'>{escape(snap.facts.get('updates_pending','—'))}</span><span class='note'>upd</span>"]
    return f"<div class='fleet-row sev-{sev}'>" + "".join(f"<div>{c}</div>" for c in cells) + "</div>"


def render_dashboard(snapshots, flags, recs, series, now: str | None = None) -> str:
    # Every value here is attacker-influenced: `recs` is LLM output, flag
    # messages carry service names, and machine/OS come from hostnames. Escape
    # all of it — the only markup in a card is markup written above.
    strip = "".join(_fleet_row(s, [f for f in flags if f.machine == s.machine], now) for s in snapshots)
    cards = []
    for s in snapshots:
        mf = [f for f in flags if f.machine == s.machine]
        sev = _status(mf)
        issues = "".join(
            f"<li class='sev-{escape(f.severity)}'><span class='tag' style='background:{_SEV.get(f.severity,'#888')}'>"
            f"{escape(f.severity)}</span>{escape(f.message)}</li>" for f in mf
        ) or f"<li class='sev-good'>{_chip('no issues', 'good')}</li>"
        cards.append(
            f"<section class='card'>"
            f"<h2><span class='dot' style='background:{_SEV[sev]}'></span>{escape(s.machine)}"
            f"<small>{escape(s.os)}</small><small class='age'>{escape(_age(s.ts, now))}</small></h2>"
            f"{_metrics(s, series)}{_facts(s)}"
            f"<ul class='issues'>{issues}</ul>"
            f"<details open><summary>Recommendations</summary>"
            f"<pre class='rec'>{escape(recs.get(s.machine, ''))}</pre></details>"
            f"</section>")
    worst = _status(flags)
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>local_watch</title><style>"
        f"body{{font:14px/1.5 system-ui,sans-serif;margin:0;padding:1.5rem;background:{_SURFACE};color:{_INK}}}"
        "h1{font-size:1.1rem;font-weight:600;margin:0 0 .25rem;letter-spacing:.01em}"
        f".sub{{color:{_INK_DIM};font-size:.85rem;margin-bottom:1rem}}"
        f".fleet{{background:{_CARD};border-radius:10px;padding:.25rem .75rem;margin-bottom:1.25rem}}"
        ".fleet-row{display:grid;grid-template-columns:1.4fr .7fr 1.6fr .6fr .7fr;gap:.75rem;"
        "align-items:center;padding:.5rem 0;border-top:1px solid #2e2e2c}"
        ".fleet-row:first-child{border-top:0}"
        ".fm{font-weight:600}"
        f".fa,.note{{color:{_INK_DIM};font-size:.78rem}}"
        ".note{margin-left:.5rem}"
        f".card{{background:{_CARD};border-radius:10px;padding:1rem 1.15rem;margin:0 0 1rem}}"
        "h2{font-size:1rem;font-weight:600;margin:0 0 .75rem;display:flex;align-items:center;gap:.5rem}"
        f"h2 small{{font-weight:400;color:{_INK_DIM};font-size:.8rem}}"
        "h2 .age{margin-left:auto}"
        ".dot{display:inline-block;width:.6rem;height:.6rem;border-radius:50%;flex:none}"
        ".row{display:grid;grid-template-columns:5.5rem 1fr;gap:.75rem;align-items:center;padding:.3rem 0}"
        f".rl{{color:{_INK_DIM};font-size:.78rem;text-transform:uppercase;letter-spacing:.06em}}"
        ".rb{display:flex;align-items:center;flex-wrap:wrap;gap:.4rem}"
        ".v{font-variant-numeric:tabular-nums;font-weight:600}"
        ".trend{flex-basis:100%}"
        # Thin marks on a recessive track; solid hairline thresholds (a dash
        # would read as a projection).
        ".meter .track{fill:#333331}"
        f".meter-good .fill{{fill:{_GOOD}}}.meter-warn .fill{{fill:{_WARN}}}.meter-crit .fill{{fill:{_CRIT}}}"
        ".meter .threshold{stroke:#6f6f6a;stroke-width:1}"
        f".spark polyline{{fill:none;stroke:{_SERIES};stroke-width:2;stroke-linejoin:round;stroke-linecap:round}}"
        ".chip{display:inline-block;padding:.1rem .5rem;border-radius:999px;font-size:.78rem;"
        "border:1px solid currentColor}"
        f".chip-good{{color:{_GOOD}}}.chip-warn{{color:{_WARN}}}.chip-crit{{color:{_CRIT}}}"
        ".stat{display:flex;align-items:baseline;gap:.4rem}"
        ".stat-v{font-size:1.5rem;font-weight:600;font-variant-numeric:tabular-nums}"
        f".stat-l{{color:{_INK_DIM};font-size:.78rem}}"
        f".stat-warn .stat-v{{color:{_WARN}}}.stat-crit .stat-v{{color:{_CRIT}}}.stat-good .stat-v{{color:{_GOOD}}}"
        ".issues{list-style:none;padding:0;margin:.75rem 0 0}"
        ".issues li{display:flex;gap:.5rem;align-items:baseline;padding:.15rem 0;font-size:.9rem}"
        f".tag{{color:{_SURFACE};border-radius:4px;padding:0 .35rem;font-size:.7rem;font-weight:700;"
        "text-transform:uppercase;flex:none}"
        "details{margin-top:.75rem}"
        f"summary{{cursor:pointer;color:{_INK_DIM};font-size:.78rem;text-transform:uppercase;letter-spacing:.06em}}"
        f".rec{{white-space:pre-wrap;background:{_SURFACE};padding:.75rem;border-radius:6px;margin:.5rem 0 0;"
        "font:12.5px/1.55 ui-monospace,monospace;overflow-x:auto}"
        "@media (max-width:720px){"
        ".fleet-row{grid-template-columns:1fr 1fr;gap:.35rem .75rem}"
        ".row{grid-template-columns:1fr;gap:.15rem}"
        "h2{flex-wrap:wrap}h2 .age{margin-left:0}"
        "}"
        "</style></head><body>"
        f"<h1>local_watch</h1><div class='sub'>{len(snapshots)} machines · {len(flags)} issues"
        f" · worst: {escape(worst)}</div>"
        f"<div class='fleet'>{strip}</div>{''.join(cards)}</body></html>")


def render_markdown(snapshots, flags, recs) -> str:
    out = [f"# local_watch — {len(snapshots)} machines, {len(flags)} issues", ""]
    for s in snapshots:
        out.append(f"## {s.machine} ({s.os})")
        out += [f"- {m.name}: {m.value}{m.unit}" for m in s.metrics]
        for f in [fl for fl in flags if fl.machine == s.machine]:
            out.append(f"- **[{f.severity}]** {f.message}")
        out += ["", "**Recommendations:**", recs.get(s.machine, "(none)"), ""]
    return "\n".join(out)
