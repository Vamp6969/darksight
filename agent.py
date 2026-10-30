"""Send TinyFish agents undercover and save what they see.

    python agent.py                         all scenarios, in parallel -> evidence/*.json
    python agent.py blinkit_blr             one scenario
    python agent.py --discover "online grocery delivery Bangalore"
                                            TinyFish Search finds the sites, agents audit them
"""
import asyncio, json, os, re, sys, time, pathlib
from urllib.parse import urlparse
from tinyfish import (TinyFish, AsyncTinyFish, AgentConfig, BrowserProfile,
                      StreamingUrlEvent, ProgressEvent, CompleteEvent)

ROOT = pathlib.Path(__file__).parent
for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
    k, _, v = line.partition("=")  # KEY=value lines from the local .env (never committed)
    if k.strip() and not k.lstrip().startswith("#") and v.strip():
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

if not os.getenv("TINYFISH_API_KEY"):
    sys.exit("Add your key to darksight/.env as TINYFISH_API_KEY=... (see .env.example).")
SCENARIOS = json.loads((ROOT / "scenarios.json").read_text())
SCHEMA = {  # every platform returns the same evidence fields
    "type": "object",
    "required": ["item", "item_price_inr", "fees", "final_total_inr", "steps"],
    "properties": {
        "item": {"type": "string"},
        "item_price_inr": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "object", "properties": {
            "step": {"type": "integer"}, "page": {"type": "string"},
            "price_shown_inr": {"type": "string"}, "note": {"type": "string"}}}},
        "fees": {"type": "array", "items": {"type": "object", "properties": {
            "label": {"type": "string"}, "amount_inr": {"type": "number"}}}},
        "final_total_inr": {"type": "string"},
        "urgency": {"type": "array", "items": {"type": "string"}},
        "preticked": {"type": "array", "items": {"type": "string"}},
    },
}
FIELD_RULES = (  # TinyFish schemas take no descriptions, so the field meanings go in the goal
    " Field rules: item is the product or room you picked and item_price_inr its price as first listed. "
    "steps must contain one entry per page you priced (at least the listing price and the final bill). "
    "fees must list every fee, charge or tax line on the bill with its amount. final_total_inr is the amount payable INCLUDING all taxes and fees on the last page before "
    "payment. urgency lists scarcity or time-pressure claims (e.g. 'Only 1 left', countdown timers). preticked "
    "lists only PAID extras already selected without the user choosing them (insurance, tips, donations, add-ons "
    "that change the total); leave it empty if none, and never include payment terms or free perks."
)
GENERIC_GOAL = (  # used for sites found by Search
    "Audit checkout pricing. Do NOT log in, do NOT pay, do NOT enter personal details. "
    "If asked for a location, use Koramangala, Bengaluru. Find a cheap product, note its listed price, "
    "add it to the cart, open the cart or checkout and record every fee line and the final total. "
    "If a login is required before the bill is shown, stop and say so in the first step's note."
)


def inr(v):
    """'Rs. 1,917 per night' -> 1917.0"""
    if isinstance(v, (int, float)) or v is None:
        return v
    m = re.search(r"[\d,]+(?:\.\d+)?", str(v))
    return float(m.group().replace(",", "")) if m else None


def normalise(result):
    ev = dict(result)
    for s in ev.get("steps", []):
        s["price_shown_inr"] = inr(s.get("price_shown_inr"))
    ev["final_total_inr"] = inr(ev.get("final_total_inr"))
    ev["item_price_inr"] = inr(ev.get("item_price_inr"))
    ev["urgency"] = ev.pop("urgency_messages", ev.get("urgency", []))
    return ev


def scenario_for(url):
    """Ad-hoc scenario for a site found by Search."""
    host = urlparse(url).netloc.removeprefix("www.")
    return re.sub(r"\W", "_", host), {"platform": host, "category": "Discovered", "url": url, "goal": GENERIC_GOAL}


async def run_one(name, sc, on_event=lambda kind, data: None):
    """Stream one agent run; on_event('live'|'step', ...) lets the UI follow along."""
    done, steps = None, 0
    async with AsyncTinyFish().agent.stream(
        url=sc["url"], goal=sc["goal"] + FIELD_RULES, output_schema=SCHEMA,
        browser_profile=BrowserProfile.STEALTH,  # real shops block plain headless browsers
        agent_config=AgentConfig(max_duration_seconds=420),
    ) as stream:
        async for e in stream:
            if isinstance(e, StreamingUrlEvent):
                on_event("live", e.streaming_url)
            elif isinstance(e, ProgressEvent):
                steps += 1
                on_event("step", e.purpose)
            elif isinstance(e, CompleteEvent):
                done = e
    if done is None or getattr(done.status, "value", done.status) != "COMPLETED":
        raise RuntimeError(getattr(done, "error", None) or "run did not complete")
    result = json.loads(done.result_json) if isinstance(done.result_json, str) else (done.result_json or {})
    ev = {"scenario": name, "platform": sc["platform"], "category": sc["category"], "run_id": done.run_id,
          "agent_steps": steps, "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **normalise(result)}
    (ROOT / "evidence" / f"{name}.json").write_text(json.dumps(ev, indent=2, ensure_ascii=False))
    return ev


def discover(query, n=3):
    """TinyFish Search (free) -> candidate sites to audit."""
    hits = TinyFish().search.query(query=query, location="India")
    return [{"title": r.title, "url": r.url} for r in hits.results[:n]]


async def audit(jobs):
    runs = await asyncio.gather(*[run_one(n, sc) for n, sc in jobs], return_exceptions=True)
    for (name, _), r in zip(jobs, runs):
        print(f"! {name}: {r}" if isinstance(r, Exception) else f"✓ {name}: {r['agent_steps']} steps -> evidence/{name}.json")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--discover"]:
        jobs = [scenario_for(h["url"]) for h in discover(" ".join(args[1:]) or "online grocery delivery Bangalore")]
        print("Search found:", ", ".join(sc["url"] for _, sc in jobs))
    else:
        jobs = [(n, SCENARIOS[n]) for n in (args or SCENARIOS)]
    asyncio.run(audit(jobs))
