"""Send a TinyFish agent undercover through one scenario and save the evidence.

    python agent.py booking_blr            -> evidence/booking_blr.json
"""
import json, os, re, sys, time, pathlib, requests

API = "https://agent.tinyfish.ai/v1/automation/run"
ROOT = pathlib.Path(__file__).parent


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


def run(name):
    sc = json.loads((ROOT / "scenarios.json").read_text())[name]
    key = os.environ.get("TINYFISH_API_KEY")
    if not key:
        sys.exit("Set TINYFISH_API_KEY (see .env.example)")
    r = requests.post(API, timeout=900, headers={"X-API-Key": key}, json={
        "url": sc["url"],
        "goal": sc["goal"],
        "browser_profile": "stealth",          # real sites block plain headless browsers
        "agent_config": {"max_duration_seconds": 420},
        "api_integration": "darksight",
    })
    r.raise_for_status()
    run = r.json()
    if run.get("status") != "COMPLETED":
        sys.exit(f"Run failed: {run.get('error')}")
    ev = {"scenario": name, "platform": sc["platform"], "category": sc["category"],
          "run_id": run.get("run_id"), "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
          **normalise(run["result"])}
    out = ROOT / "evidence" / f"{name}.json"
    out.write_text(json.dumps(ev, indent=2, ensure_ascii=False))
    print("saved", out)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "booking_blr")
