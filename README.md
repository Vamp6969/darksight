# DarkSight 🕵️

**An undercover web agent that catches dark patterns before they catch you.**

Team Vamp (Tushar, Padmashree, Pranav) · *Swim with TinyFish*, Presidency University, 2026

▶️ **[Watch the 70-second demo video](https://drive.google.com/file/d/1VoETRMvHSoaRGO3CaDJKCZgXF1-PZz9T/view?usp=sharing)**

---

Online platforms show you one price and charge you another. India's CCPA *Guidelines for Prevention and Regulation of Dark Patterns, 2023* ban 13 of these tricks, but there is no tool that checks platforms from the outside. Dark patterns don't appear in any API. They only exist on the live page, in the middle of a checkout, for a real-looking user.

DarkSight sends a **TinyFish web agent** through real shopping, booking and subscription flows. The agent stops before payment and records the price at every step. The findings are mapped to the CCPA list.

| Pattern (CCPA name) | What the agent does |
|---|---|
| Drip pricing | Logs the price at every step and flags charges that appear late |
| False urgency | Records "only 1 left" / "limited-time" claims, then re-runs to see if they reset |
| Basket sneaking | Flags pre-ticked add-ons, tips and donations |
| Subscription trap | Counts clicks to join vs. clicks to cancel |

## First real run

`evidence/booking_blr.json` is the raw output of a real TinyFish run (17 agent steps, 25 Oct 2026). The agent went from Booking.com search results for Bengaluru to the reservation page and stopped before any personal details:

- Room picked at **₹1,749** → reservation page total **₹1,836.80** (+5%, GST added at the last step) → ⚠️ *drip pricing (minor)*
- "Original price" **₹4,373** struck through to ₹1,749 under a **"Limited-time Deal"** banner → ⚠️ *urgency claim, needs a re-run to verify*
- Nothing pre-ticked → ✅

Report card grade: **C**. These are signals for review, not legal conclusions.

## How it works

```
scenarios.json ──► agent.py ──► TinyFish agent (stealth browser, stops before payment)
                                       │
                                       ▼
                         evidence/<scenario>.json  (steps, prices, fees, urgency text)
                                       │
                         detect.py ──► findings + A–F grade
                                       │
                         report.py ──► report_<scenario>.html
```

## Run it

```bash
pip install -r requirements.txt
export TINYFISH_API_KEY=...            # https://agent.tinyfish.ai
python agent.py booking_blr            # send the agent undercover -> evidence/booking_blr.json
python report.py evidence/booking_blr.json   # -> report_booking_blr.html
python detect.py                       # detector self-check
```

To add a platform, add an entry to `scenarios.json` with a URL and a plain-English goal.


## Roles

- **Tushar**: TinyFish agents & backend
- **Padmashree**: detection & LLM
- **Pranav**: frontend & demo

## Credits

Demo music: "The Technology" from [Mixkit](https://mixkit.co) (Mixkit License), via [repotovideo](https://github.com/Shubhamsaboo/repotovideo).
