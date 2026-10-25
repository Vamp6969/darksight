"""Render a DarkSight report card.   python report.py evidence/booking_blr.json"""
import json, sys, html, pathlib
from detect import audit

ICON = {"fail": ("✕", "#FF5A36"), "warn": ("!", "#FACC15"), "pass": ("✓", "#22C55E")}


def render(path):
    ev = json.loads(pathlib.Path(path).read_text())
    grade, findings = audit(ev)
    rows = "".join(
        f'<div class="row"><span class="dot" style="background:{ICON[v][1]}">{ICON[v][0]}</span>'
        f'<b>{html.escape(n)}</b><span class="muted">{html.escape(d)}</span></div>'
        for v, n, d in findings)
    steps = "".join(
        f'<li><b>Step {s.get("step", i + 1)}</b> · {html.escape(str(s.get("page", "")))} — '
        f'₹{s["price_shown_inr"]:,.0f}<span class="muted"> {html.escape(s.get("note") or "")}</span></li>'
        for i, s in enumerate(ev.get("steps", [])) if s.get("price_shown_inr"))
    title = ev.get("hotel_name") or ev.get("platform")
    page = f"""<!doctype html><meta charset="utf-8"><title>DarkSight · {html.escape(title)}</title>
<style>body{{background:#0E1015;color:#F5F5F4;font:16px system-ui;max-width:760px;margin:40px auto;padding:0 16px}}
.card{{background:#1A1D26;border-radius:14px;padding:24px;margin:16px 0}}.muted{{color:#A1A1AA;font-size:14px}}
.row{{display:grid;grid-template-columns:32px 180px 1fr;gap:12px;align-items:center;padding:10px 0}}
.dot{{width:24px;height:24px;border-radius:50%;display:grid;place-items:center;color:#0E1015;font-weight:700}}
.grade{{font-size:64px;font-weight:800;color:#FF5A36;float:right;line-height:1}}h1{{margin:0}}li{{margin:6px 0}}
@media(max-width:600px){{.row{{grid-template-columns:32px 1fr}}.row .muted{{grid-column:2}}}}</style>
<p class="muted">DARKSIGHT REPORT CARD · {html.escape(ev.get("category", ""))} · run {html.escape(str(ev.get("run_id", ""))[:8])}</p>
<div class="card"><span class="grade">{grade}</span><h1>{html.escape(title)}</h1>
<p class="muted">{html.escape(ev.get("platform", ""))} · captured {html.escape(ev.get("captured_at", ""))}</p>{rows}</div>
<div class="card"><b>Price trail recorded by the TinyFish agent</b><ul>{steps}</ul></div>"""
    dest = pathlib.Path(f"report_{pathlib.Path(path).stem}.html")
    dest.write_text(page)
    print("wrote", dest)


if __name__ == "__main__":
    render(sys.argv[1])
