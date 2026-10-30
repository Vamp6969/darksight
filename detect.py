"""Turn agent evidence into findings mapped to India's CCPA dark-pattern list (2023)."""
import re

FAIL, WARN, PASS = "fail", "warn", "pass"

FEE_INFO = [  # keyword in the fee label -> plain-English explanation for the report card
    ("small cart", "Charged because the order is below the platform's minimum order value."),
    ("handling", "A per-order processing fee. It is not part of the product price shown on the listing."),
    ("delivery", "Cost of delivering the order. Often waived above a minimum order, but not shown on the product card."),
    ("platform", "A fee the platform adds to every order for using the app."),
    ("packaging", "Charge for packing the order, set by the restaurant or store."),
    ("convenience", "A booking or payment fee added on top of the listed price."),
    ("surge", "Extra charge during busy hours, rain or high demand."),
    ("rain", "Extra charge during bad weather."),
    ("gst", "Goods and Services Tax. Legally due, but the listed price did not include it."),
    ("tax", "Tax added on top of the listed price instead of being included in it."),
    ("tip", "A tip for the delivery partner. It should only be added if the user chooses it."),
    ("donation", "A charity donation. It should only be added if the user chooses it."),
    ("discount", "A discount applied to the listed price."),
]
WHY = {
    "Drip pricing": "CCPA 2023 bans revealing parts of the price only later in the buying journey. "
                    "The price a shopper commits to should be the price they pay.",
    "False urgency": "CCPA 2023 bans fake scarcity or time pressure ('only 1 left', countdowns) that pushes people to buy fast.",
    "Basket sneaking": "CCPA 2023 bans adding items, tips or donations to the cart without the user choosing them.",
    "Subscription trap": "CCPA 2023 bans making a subscription easy to start but hard to cancel.",
    "Bill not reached": "DarkSight only judges what the agent actually saw. Without the final bill, pricing cannot be checked.",
}


def explain_fees(ev):
    """Fee lines (totals removed) with an explanation for each."""
    out, fees = [], ev.get("fees", [])
    marked = any("late" in f for f in fees)  # curated evidence marks which lines were added late
    for f in fees:
        label = str(f.get("label", ""))
        low = label.lower()
        if (marked and not f.get("late")) or any(w in low for w in ("total", "original", "item", "mrp")) \
                or (f.get("amount_inr") or 0) <= 0:  # prices, totals and discounts are not added charges
            continue
        info = next((txt for key, txt in FEE_INFO if key in label.lower()), "An extra charge added on top of the listed price.")
        out.append({"label": label, "amount_inr": f.get("amount_inr"), "explanation": info})
    return out


def drip_pricing(ev):
    steps = [s for s in ev.get("steps", []) if s.get("price_shown_inr")]
    total = ev.get("final_total_inr")
    first = ev.get("item_price_inr") or (steps[0]["price_shown_inr"] if steps else None)  # price when picked
    if not first or not total:
        return None
    jump = (total - first) / first * 100
    # ponytail: flat thresholds (2% rounding, 10% = clear drip); tune per category if needed
    if jump <= 2:
        return PASS, "Drip pricing", f"Price held: ₹{first:,.0f} → ₹{total:,.0f}"
    late = ", ".join(f["label"] for f in ev.get("fees", [])
                     if f.get("late", True) and "total" not in f["label"].lower()) or "unlisted charges"
    return (FAIL if jump > 10 else WARN), "Drip pricing", \
        f"₹{first:,.0f} → ₹{total:,.0f} (+{jump:.0f}%) at the last step; added: {late}"


# delivery ETAs and plain discount badges are information, not pressure ("sale ends in 2h" still counts)
NOT_URGENCY = re.compile(r"deliver|arriv|\bETA\b|^\W*\d+\s*%\s*off\W*(label|badge|tag)?\W*$", re.I)


def false_urgency(ev, rerun=None):
    claims = [m for m in ev.get("urgency", []) if not NOT_URGENCY.search(m)]
    msgs = [m if len(m) < 70 else m[:67] + "…" for m in claims]
    if not msgs:
        return PASS, "False urgency", "No urgency claims"
    if rerun is not None and set(claims) == set(rerun.get("urgency", [])):
        return FAIL, "False urgency", f"Same claim after re-run: “{msgs[0]}”"
    return WARN, "False urgency", f"Urgency claim seen: “{msgs[0]}” (re-run to verify)"


def basket_sneaking(ev):
    pre = ev.get("preticked", [])
    if pre:
        return FAIL, "Basket sneaking", "Pre-selected: " + ", ".join(pre)
    return PASS, "Basket sneaking", "Nothing pre-ticked"


def subscription_trap(ev):
    j, c = ev.get("join_clicks"), ev.get("cancel_clicks")
    if not j or not c:
        return None
    verdict = FAIL if c >= 3 * j else PASS
    return verdict, "Subscription trap", f"{j} click(s) to join, {c} to cancel"


def audit(ev, rerun=None):
    if not ev.get("final_total_inr"):  # agent never saw the bill (e.g. login wall): no grade, say why
        steps = ev.get("steps") or [{}]
        reason = ev.get("blocked_reason") or steps[0].get("note") or "The agent could not reach the final bill."
        return "?", [(WARN, "Bill not reached", reason[:160])]
    found = [drip_pricing(ev), false_urgency(ev, rerun), basket_sneaking(ev), subscription_trap(ev)]
    found = [f for f in found if f]
    score = sum({FAIL: 2, WARN: 1, PASS: 0}[f[0]] for f in found)
    grade = "ABCDF"[min(score, 4)]
    return grade, found


def report(ev):
    """Everything the report card shows."""
    grade, findings = audit(ev)
    first = ev.get("item_price_inr") or next((s["price_shown_inr"] for s in ev.get("steps", []) if s.get("price_shown_inr")), None)
    total = ev.get("final_total_inr")
    fees = explain_fees(ev)
    return {"grade": grade, "evidence": ev, "listed_price": first, "total": total,
            "markup_pct": round((total - first) / first * 100) if first and total else None,
            "fees": fees, "fees_sum": sum(f["amount_inr"] or 0 for f in fees),
            "findings": [{"verdict": v, "name": n, "detail": d, "why": WHY.get(n, "")} for v, n, d in findings]}


if __name__ == "__main__":
    # one runnable check: fails loudly if detector logic breaks
    ev = {"steps": [{"price_shown_inr": 199}], "final_total_inr": 287,
          "fees": [{"label": "Platform fee"}], "urgency": ["Only 2 left!"], "preticked": ["Tip ₹20"],
          "join_clicks": 1, "cancel_clicks": 7}
    grade, f = audit(ev, rerun={"urgency": ["Only 2 left!"]})
    assert [x[0] for x in f] == [FAIL, FAIL, FAIL, FAIL], f
    assert "+44%" in f[0][2] and grade == "F"
    assert drip_pricing({"steps": [{"price_shown_inr": 100}], "final_total_inr": 101})[0] == PASS
    assert drip_pricing({"item_price_inr": 1749, "steps": [{"price_shown_inr": 1917}], "final_total_inr": 1836.8})[0] == WARN
    assert audit({"urgency": [], "final_total_inr": 100, "item_price_inr": 100})[0] == "A"
    assert drip_pricing({"item_price_inr": 16, "final_total_inr": 43, "steps": []})[0] == FAIL  # no step list needed
    assert false_urgency({"urgency": ["22 MINS delivery estimate"]})[0] == PASS
    assert false_urgency({"urgency": ["Only 1 room left"]})[0] == WARN
    assert false_urgency({"urgency": ["20% OFF label"]})[0] == PASS
    assert false_urgency({"urgency": ["Sale ends in 2 hours"]})[0] == WARN
    assert audit({"steps": [{"note": "Login required"}]}) == ("?", [(WARN, "Bill not reached", "Login required")])
    r = report({"item_price_inr": 16, "final_total_inr": 43, "fees": [{"label": "Item total", "amount_inr": 16},
               {"label": "Delivery charge", "amount_inr": 25}, {"label": "Handling charge", "amount_inr": 2}]})
    assert [f["label"] for f in explain_fees({"fees": [{"label": "Original price", "amount_inr": 4373},
            {"label": "Deal discount", "amount_inr": -2536}, {"label": "GST", "amount_inr": 87}]})] == ["GST"]
    assert r["markup_pct"] == 169 and r["fees_sum"] == 27 and "minimum order" in r["fees"][0]["explanation"]
    print("detect.py self-check ok")
