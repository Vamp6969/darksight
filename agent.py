"""Send TinyFish agents undercover and save what they see.

    python agent.py                         all scenarios, in parallel -> evidence/*.json
    python agent.py blinkit_blr             one scenario
    python agent.py blinkit_blr --cities bengaluru,mumbai,delhi
                                            same audit in several cities, in parallel
    python agent.py --discover "online grocery delivery Bangalore"
                                            TinyFish Search finds the sites, agents audit them
"""
import asyncio, json, os, re, sys, time, pathlib, urllib.request
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
    "payment. urgency lists scarcity or time-pressure claims (e.g. 'Only 1 left', countdown timers); delivery time estimates and plain discount badges are NOT urgency. preticked "
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
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(v))  # must start with a digit: '₹', ',' or '' mean no price
    return float(m.group().replace(",", "")) if m else None


def normalise(result):
    ev = dict(result)
    for s in ev.get("steps", []):
        s["price_shown_inr"] = inr(s.get("price_shown_inr"))
    ev["final_total_inr"] = inr(ev.get("final_total_inr"))
    ev["item_price_inr"] = inr(ev.get("item_price_inr"))
    ev["urgency"] = ev.pop("urgency_messages", ev.get("urgency", []))
    return ev


PROFILES = ROOT / "profiles.json"  # site -> TinyFish Browser Context Profile id (local, gitignored)


def needs_login(ev):
    """Bill not reached: most shops hide it until you log in, so offer 'sign in yourself, then retry'.
    Skipped when this run already used the saved session."""
    return not ev.get("final_total_inr") and not ev.get("signed_in")


def host_of(url):
    return urlparse(url).netloc.removeprefix("www.")


def profile_for(host):
    """Saved profile id for a site, or None."""
    return json.loads(PROFILES.read_text()).get(host) if PROFILES.exists() else None


def login_link(host):
    """Create (once) a TinyFish profile for the site and return the page where the user signs in themselves."""
    pid = profile_for(host)
    if not pid:
        req = urllib.request.Request("https://agent.tinyfish.ai/v1/profiles", method="POST",
            data=json.dumps({"name": f"DarkSight {host}"[:100], "proxy_country_code": "IN"}).encode(),
            headers={"X-API-Key": os.environ["TINYFISH_API_KEY"], "Content-Type": "application/json"})
        pid = json.load(urllib.request.urlopen(req, timeout=30))["id"]
        saved = json.loads(PROFILES.read_text()) if PROFILES.exists() else {}
        PROFILES.write_text(json.dumps({**saved, host: pid}, indent=2))
    return {"profile_id": pid, "setup_url": f"https://agent.tinyfish.ai/profiles/{pid}/setup?domain={host}"}


CITIES = {  # key -> (delivery area used in goals, city name used in search URLs)
    "bengaluru": ("Koramangala, Bengaluru", "Bengaluru"),
    "mumbai": ("Andheri West, Mumbai", "Mumbai"),
    "delhi": ("Connaught Place, New Delhi", "New Delhi"),
    "hyderabad": ("HITEC City, Hyderabad", "Hyderabad"),
}


def localize(name, sc, city):
    """Same scenario, different city: swaps the delivery area / search city. Evidence goes to <name>__<city>.json."""
    area, town = CITIES[city]
    swap = lambda t: t.replace("Koramangala, Bengaluru", area).replace("Bengaluru", town)
    url = sc["url"].replace("Bengaluru", town.replace(" ", "+"))
    return f"{name}__{city}", {**sc, "url": url, "goal": swap(sc["goal"]), "city": town}


def scenario_for(url):
    """Ad-hoc scenario for a site found by Search."""
    host = urlparse(url).netloc.removeprefix("www.")
    return re.sub(r"\W", "_", host), {"platform": host, "category": "Discovered", "url": url, "goal": GENERIC_GOAL}


async def run_one(name, sc, on_event=lambda kind, data: None, signed_in=False):
    """Stream one agent run; on_event('live'|'step', ...) lets the UI follow along.
    signed_in=True reuses the user's saved TinyFish profile for this site (they logged in themselves)."""
    done, steps = None, 0
    pid = profile_for(host_of(sc["url"])) if signed_in else None
    login = dict(use_profile=True, profile_id=pid) if pid else {}
    goal = sc["goal"] + FIELD_RULES
    if pid:  # the saved session is already logged in, so the agent may go past the login wall now
        goal = goal.replace("Do NOT log in, ", "You are already signed in with the user's own saved session; do not sign in again. ")
    async with AsyncTinyFish().agent.stream(**login,
        url=sc["url"], goal=goal, output_schema=SCHEMA,
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
          "agent_steps": steps, "signed_in": bool(pid), "city": sc.get("city", "Bengaluru"), "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **normalise(result)}
    (ROOT / "evidence" / f"{name}.json").write_text(json.dumps(ev, indent=2, ensure_ascii=False))
    return ev


def discover(query, n=3):
    """TinyFish Search (free) -> candidate sites to audit."""
    hits = TinyFish().search.query(query=query, location="India")
    skip = ("google.", "reddit.", "quora.", "wikipedia.", "youtube.", "apple.com", "facebook.", "instagram.", "linkedin.")
    shops = [r for r in hits.results if not any(d in host_of(r.url) for d in skip)]  # shops only, not app stores/forums
    return [{"title": r.title, "url": r.url} for r in shops[:n]]


async def audit(jobs):
    runs = await asyncio.gather(*[run_one(n, sc) for n, sc in jobs], return_exceptions=True)
    for (name, _), r in zip(jobs, runs):
        print(f"! {name}: {r}" if isinstance(r, Exception) else f"✓ {name}: {r['agent_steps']} steps -> evidence/{name}.json")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--discover"]:
        jobs = [scenario_for(h["url"]) for h in discover(" ".join(args[1:]) or "online grocery delivery Bangalore")]
        print("Search found:", ", ".join(sc["url"] for _, sc in jobs))
    elif "--cities" in args:  # python agent.py blinkit_blr --cities bengaluru,mumbai,delhi
        i = args.index("--cities")
        jobs = [localize(args[0], SCENARIOS[args[0]], c) for c in args[i + 1].split(",")]
    else:
        jobs = [(n, SCENARIOS[n]) for n in (args or SCENARIOS)]
    asyncio.run(audit(jobs))
