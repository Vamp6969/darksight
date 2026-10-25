"""Turn agent evidence into findings mapped to India's CCPA dark-pattern list (2023)."""

FAIL, WARN, PASS = "fail", "warn", "pass"


def drip_pricing(ev):
    steps = [s for s in ev.get("steps", []) if s.get("price_shown_inr")]
    total = ev.get("final_total_inr")
    if not steps or not total:
        return None
    first = ev.get("item_price_inr") or steps[0]["price_shown_inr"]  # price when the user picked the item
    jump = (total - first) / first * 100
    # ponytail: flat thresholds (2% rounding, 10% = clear drip); tune per category if needed
    if jump <= 2:
        return PASS, "Drip pricing", f"Price held: ₹{first:,.0f} → ₹{total:,.0f}"
    late = ", ".join(f["label"] for f in ev.get("fees", []) if f.get("late", True)) or "unlisted charges"
    return (FAIL if jump > 10 else WARN), "Drip pricing", \
        f"₹{first:,.0f} → ₹{total:,.0f} (+{jump:.0f}%) at the last step; added: {late}"


def false_urgency(ev, rerun=None):
    msgs = [m if len(m) < 70 else m[:67] + "…" for m in ev.get("urgency", [])]
    if not msgs:
        return PASS, "False urgency", "No urgency claims"
    if rerun is not None and set(ev["urgency"]) == set(rerun.get("urgency", [])):
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
    found = [drip_pricing(ev), false_urgency(ev, rerun), basket_sneaking(ev), subscription_trap(ev)]
    found = [f for f in found if f]
    score = sum({FAIL: 2, WARN: 1, PASS: 0}[f[0]] for f in found)
    grade = "ABCDF"[min(score, 4)]
    return grade, found


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
    assert audit({"urgency": []})[0] == "A"
    print("detect.py self-check ok")
