"""Send TinyFish agents undercover and save what they see.

    python agent.py                 all scenarios, in parallel -> evidence/*.json
    python agent.py booking_blr     one scenario
"""
import asyncio, json, os, re, sys, time, pathlib
from tinyfish import AsyncTinyFish, AgentConfig, BrowserProfile, RunStatus

if not os.getenv("TINYFISH_API_KEY"):
    sys.exit("Set TINYFISH_API_KEY first (see .env.example).")

ROOT = pathlib.Path(__file__).parent
SCENARIOS = json.loads((ROOT / "scenarios.json").read_text())
SCHEMA = {  # every platform returns the same evidence fields
    "type": "object",
    "properties": {
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
    ev["urgency"] = ev.pop("urgency_messages", ev.get("urgency", []))
    return ev


async def audit(names):
    agents = AsyncTinyFish()  # reads TINYFISH_API_KEY
    runs = await asyncio.gather(*[
        agents.agent.run(
            url=SCENARIOS[n]["url"], goal=SCENARIOS[n]["goal"], output_schema=SCHEMA,
            browser_profile=BrowserProfile.STEALTH,  # real shops block plain headless browsers
            agent_config=AgentConfig(max_duration_seconds=420),
        ) for n in names], return_exceptions=True)
    for name, run in zip(names, runs):
        if isinstance(run, Exception) or run.status != RunStatus.COMPLETED:
            print(f"! {name}: no result ({run if isinstance(run, Exception) else run.error or run.status})")
            continue
        sc = SCENARIOS[name]
        ev = {"scenario": name, "platform": sc["platform"], "category": sc["category"], "run_id": run.run_id,
              "agent_steps": run.num_of_steps, "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              **normalise(run.result or {})}
        out = ROOT / "evidence" / f"{name}.json"
        out.write_text(json.dumps(ev, indent=2, ensure_ascii=False))
        print(f"✓ {name}: {run.num_of_steps} steps -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(audit(sys.argv[1:] or list(SCENARIOS)))
