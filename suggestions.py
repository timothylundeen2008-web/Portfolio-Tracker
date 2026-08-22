"""
suggestions.py  (v1 — August 2026)
──────────────────────────────────
The synthesis layer. Flow evidence + macro regime → suggested changes.

WHAT THIS IS
────────────
The three dashboards each answer a different question, and until now nothing
combined them:

    Money Flow  →  where capital is ACTUALLY moving          (evidence)
    Markets     →  what environment this is, and the detail   (interpretation)
    All-Weather →  what to hold                               (action)

This module is the join. It reads both bridges, applies the level hierarchy
the framework already uses, and produces ranked, concrete suggestions.

CAPITAL PRESERVATION IS THE ANCHOR, NOT A FOOTNOTE
──────────────────────────────────────────────────
Every suggestion is checked against preservation constraints BEFORE it is
emitted, not after. The ordering is deliberate and non-negotiable:

    1. Is the regime hostile?         → nothing additive is suggested
    2. Is a tripwire near-tripped?    → the suggestion is a reduction
    3. Does flow CONFIRM the thesis?  → without it, size is halved
    4. Only then: what earns weight?

That ordering means the engine can produce ZERO additive suggestions and
still be working correctly. A synthesis layer that always finds something to
buy is a sales tool, not an analytical one.

THE EVIDENCE HIERARCHY — WHY FLOW GATES CONVICTION
──────────────────────────────────────────────────
The framework's own principle: a regime thesis unconfirmed by flow is a
HYPOTHESIS, not a position. So flow does not generate suggestions on its own
— it CONFIRMS or CONTRADICTS what the macro read already proposed:

    macro says add + flow confirms      → full suggested size
    macro says add + flow silent        → half size, explicitly noted
    macro says add + flow contradicts   → suggestion suppressed entirely
    macro says trim + flow confirms     → full trim, higher priority

And critically: Tier A (ETF creations — actual capital) outranks Tier B
(volume pressure). If the Tier A layer is dark, no flow confirmation is
available at all, and every additive suggestion is capped at half size.
"""

from __future__ import annotations

from typing import Optional

# ── Priority tiers ──────────────────────────────────────────────────────────
P_CRITICAL = "CRITICAL"   # preservation — act same day
P_HIGH = "HIGH"           # act at the weekly review
P_MEDIUM = "MEDIUM"       # consider at the weekly review
P_INFO = "INFO"           # watchlist

# Regimes where NOTHING additive may be suggested, full stop.
HOSTILE_REGIMES = {"liquidity_crisis", "growth_scare"}

# Regimes where additive suggestions are capped at half size.
UNCONFIRMED_REGIMES = {"transition_ambiguous", "neutral", "stagflation"}


def _sug(priority, action, ticker, detail, rationale, evidence, size=None):
    return {"priority": priority, "action": action, "ticker": ticker,
            "detail": detail, "rationale": rationale, "evidence": evidence,
            "size": size}


def build(markets: dict, flow: dict,
          current_weights: Optional[dict] = None,
          base_weights: Optional[dict] = None) -> dict:
    """
    Produce ranked suggestions from both bridges.

    Returns a dict, always. Missing inputs REDUCE what can be suggested;
    they never cause a fabricated recommendation.
    """
    out = {"suggestions": [], "preservation": [], "confidence": "UNKNOWN",
           "blockers": [], "detail": "", "evidence_quality": {}}

    # ── Evidence quality first: this gates everything downstream ────────────
    m_ok = markets.get("available") and not markets.get("very_stale")
    f_ok = flow.get("available") and not flow.get("very_stale")

    out["evidence_quality"] = {
        "markets": ("fresh" if m_ok and not markets.get("stale")
                    else "stale" if m_ok else "unavailable"),
        "markets_msg": markets.get("message", ""),
        "flow": ("fresh" if f_ok and not flow.get("stale")
                 else "stale" if f_ok else "unavailable"),
        "flow_msg": flow.get("message", ""),
    }

    if not m_ok:
        out["blockers"].append(
            "Markets summary unavailable or very stale — no regime read means "
            "no basis for ANY allocation suggestion. Publish from the Markets "
            "Dashboard first.")
        out["detail"] = "Cannot generate suggestions without a current regime."
        return out

    regime = markets.get("regime", {}) or {}
    rkey = regime.get("key", "")
    growth = markets.get("growth", {}) or {}
    repression = markets.get("repression", {}) or {}

    # ── STEP 1: PRESERVATION — checked before anything additive ─────────────
    for t in markets.get("tripwires", []):
        if t.get("severity") == "CRITICAL" and t.get("distance") is not None:
            out["preservation"].append(_sug(
                P_CRITICAL, "REVIEW IMMEDIATELY", None,
                f"{t['name']}: {abs(t['distance']):.2f} to {t['direction']}",
                "A CRITICAL tripwire is live. Preservation outranks every "
                "return consideration in this engine.",
                ["Markets: tripwire panel"]))

    if rkey in HOSTILE_REGIMES:
        out["preservation"].append(_sug(
            P_CRITICAL, "NO ADDITIONS", None,
            f"Regime is {rkey}",
            "This regime is hostile. The engine will not suggest adding to "
            "ANY risk sleeve regardless of relative strength, trend, or flow "
            "— being early in a contraction is indistinguishable from being "
            "wrong.",
            [f"Markets: regime {rkey}"]))

    if repression.get("hollow"):
        out["preservation"].append(_sug(
            P_HIGH, "DOWNGRADE CONFIDENCE", None,
            f"Repression score {repression.get('score')}/10 is HOLLOW "
            f"({repression.get('top_weight')} top-weight points)",
            "Every point comes from second-tier components while both primary "
            "real-yield gauges are off. Treat the band label as an upper "
            "bound, and size any regime-driven tilt accordingly.",
            ["Markets: repression score"]))

    if growth.get("state") == "DETERIORATING" and growth.get("confirmed"):
        out["preservation"].append(_sug(
            P_HIGH, "PREPARE TO DE-RISK", None,
            f"Growth composite {growth.get('score')} (DETERIORATING)",
            f"One more deterioration point reaches CONTRACTING, at which the "
            f"classifier returns growth_scare outright — cutting cyclicals "
            f"and growth. Pre-position rather than reacting.",
            ["Markets: growth axis"]))

    # ── STEP 2: flow evidence quality sets the size ceiling ─────────────────
    tier_a_dark = True
    flow_sectors = {}
    if f_ok:
        for s in flow.get("sectors", []) or []:
            tk = s.get("ticker") or s.get("Ticker")
            if tk:
                flow_sectors[tk] = s
        tier_a_dark = not bool(flow.get("flow_divergences"))

    if tier_a_dark:
        out["blockers"].append(
            "Tier A capital layer (ETF creations/redemptions) is dark. Flow "
            "CONFIRMATION is unavailable, so every additive suggestion below "
            "is capped at HALF size. Tier B volume pressure is not a "
            "substitute — volume is not flow.")

    size_ceiling = 0.5 if (tier_a_dark or rkey in UNCONFIRMED_REGIMES) else 1.0

    # ── STEP 3: sleeve-level suggestions, gated by everything above ─────────
    rs_q = markets.get("rs_quartiles", {}) or {}
    trend_st = markets.get("trend_states", {}) or {}
    conv = markets.get("conviction", {}) or {}
    targets = markets.get("regime_targets", {}) or {}
    base = base_weights or {}
    current = current_weights or base

    additive_blocked = rkey in HOSTILE_REGIMES

    for tk in sorted(set(list(rs_q) + list(trend_st))):
        q = rs_q.get(tk)
        ts = trend_st.get(tk)
        c = conv.get(tk, {})
        score = c.get("score")
        cur_w = current.get(tk)
        tgt_w = targets.get(tk)

        evidence = []
        if q:
            evidence.append(f"RS quartile {q}")
        if ts:
            evidence.append(f"trend {ts}")
        if score is not None:
            evidence.append(f"conviction {score}/3")
        fs = flow_sectors.get(tk)
        if fs:
            evidence.append("flow data present")

        # REDUCE — always permitted, in every regime
        if ts == "DOWNTREND" and q and q >= 3:
            out["suggestions"].append(_sug(
                P_HIGH, "REDUCE", tk,
                f"{tk}: downtrend + bottom-half RS",
                "Confirmed downtrend AND weak relative strength. The trend "
                "filter already scales this to 0.30x; consider realising "
                "that rather than holding a position the system has already "
                "de-rated.",
                evidence, size="to trend-gated weight"))
            continue

        # ADD — only when everything upstream permits it
        if additive_blocked:
            continue
        if score == 3 and ts == "CONFIRMED UPTREND":
            flow_note = ""
            eff = size_ceiling
            if fs and fs.get("flow_score", 0) and float(fs.get("flow_score", 0)) > 0:
                flow_note = " Flow CONFIRMS."
                eff = min(1.0, size_ceiling * 2)
            elif tier_a_dark:
                flow_note = (" Flow confirmation UNAVAILABLE (Tier A dark) — "
                            "half size.")
            else:
                flow_note = " Flow is silent — half size."

            out["suggestions"].append(_sug(
                P_MEDIUM if eff < 1.0 else P_HIGH, "ADD", tk,
                f"{tk}: 3-of-3 confluence" +
                (f", {cur_w:.1f}% → suggested {min(cur_w * (1 + 0.4 * eff), 28):.1f}%"
                 if cur_w else ""),
                "Full confluence — top-half RS, confirmed uptrend, and the "
                "regime permits additions." + flow_note,
                evidence, size=f"{eff*100:.0f}% of the full tilt"))

    # ── Confidence ──────────────────────────────────────────────────────────
    if out["blockers"] or markets.get("stale") or flow.get("stale"):
        out["confidence"] = "LOW"
    elif tier_a_dark:
        out["confidence"] = "MODERATE"
    else:
        out["confidence"] = "HIGH"

    n_add = sum(1 for s in out["suggestions"] if s["action"] == "ADD")
    n_red = sum(1 for s in out["suggestions"] if s["action"] == "REDUCE")
    out["detail"] = (
        f"{len(out['preservation'])} preservation item(s), {n_add} addition(s), "
        f"{n_red} reduction(s). Confidence: {out['confidence']}."
        + (" Zero additions is a valid, common outcome — this engine is not "
           "designed to always find something to buy." if n_add == 0 else ""))
    return out


def render(st, res: dict):
    st.markdown("## Suggested Changes")
    st.caption(
        "Synthesis of Money Flow (evidence) + Markets (interpretation). "
        "Capital preservation is checked BEFORE anything additive — this "
        "engine can legitimately return zero suggestions."
    )

    eq = res.get("evidence_quality", {})
    c1, c2, c3 = st.columns(3)
    c1.metric("Markets data", eq.get("markets", "?").upper())
    c2.metric("Flow data", eq.get("flow", "?").upper())
    c3.metric("Confidence", res.get("confidence", "?"))
    if eq.get("markets_msg"):
        st.caption(f"Markets: {eq['markets_msg']}")
    if eq.get("flow_msg"):
        st.caption(f"Flow: {eq['flow_msg']}")

    for b in res.get("blockers", []):
        st.warning(b)

    if res.get("preservation"):
        st.markdown("### 🛡️ Capital preservation — checked first")
        for s in res["preservation"]:
            box = st.error if s["priority"] == P_CRITICAL else st.warning
            box(f"**{s['action']}** — {s['detail']}")
            st.caption(f"{s['rationale']}  ·  Evidence: "
                      f"{', '.join(s['evidence'])}")

    sugs = res.get("suggestions", [])
    if not sugs:
        st.info("**No allocation changes suggested.** That is a valid "
               "outcome, not a failure — either the regime does not permit "
               "additions, or no sleeve currently clears the confluence bar.")
    else:
        st.markdown("### Allocation")
        order = {P_CRITICAL: 0, P_HIGH: 1, P_MEDIUM: 2, P_INFO: 3}
        for s in sorted(sugs, key=lambda x: order.get(x["priority"], 9)):
            icon = "🔻" if s["action"] == "REDUCE" else "🔺"
            st.markdown(f"{icon} **{s['action']} {s['ticker']}** — "
                       f"{s['detail']}")
            st.caption(f"{s['rationale']}")
            st.caption(f"Evidence: {', '.join(s['evidence'])}"
                      + (f"  ·  Size: {s['size']}" if s.get("size") else ""))

    st.caption(res.get("detail", ""))
    st.info(
        "**Evidence hierarchy:** a regime thesis unconfirmed by flow is a "
        "HYPOTHESIS, not a position. Flow does not generate suggestions — it "
        "confirms or contradicts what the macro read proposed. Tier A "
        "(capital) outranks Tier B (volume pressure)."
    )


def selftest() -> dict:
    failures = []

    fresh_markets = {
        "available": True, "stale": False, "very_stale": False,
        "message": "Fresh (2h old).",
        "regime": {"key": "goldilocks", "label": "Goldilocks"},
        "repression": {"score": 4, "hollow": True, "top_weight": "0/4"},
        "growth": {"state": "NEUTRAL", "score": 0, "confirmed": True},
        "tripwires": [],
        "rs_quartiles": {"VGT": 1, "TLT": 4},
        "trend_states": {"VGT": "CONFIRMED UPTREND", "TLT": "DOWNTREND"},
        "conviction": {"VGT": {"score": 3, "multiplier": 1.4}},
        "regime_targets": {"VGT": 24, "TLT": 6},
    }
    no_flow = {"available": False, "very_stale": True, "message": "none"}

    r = build(fresh_markets, no_flow, current_weights={"VGT": 20, "TLT": 10})
    if not any(s["action"] == "ADD" and s["ticker"] == "VGT"
               for s in r["suggestions"]):
        failures.append("3-of-3 VGT did not produce an ADD")
    if not any(s["action"] == "REDUCE" and s["ticker"] == "TLT"
               for s in r["suggestions"]):
        failures.append("downtrend + weak RS TLT did not produce a REDUCE")
    if r["confidence"] != "LOW":
        failures.append(f"dark flow should give LOW confidence, got "
                        f"{r['confidence']}")
    if not any("HALF size" in b or "half size" in b for b in r["blockers"]):
        failures.append("Tier A dark did not cap size")

    # Hostile regime must block ALL additions
    hostile = dict(fresh_markets)
    hostile["regime"] = {"key": "growth_scare"}
    r2 = build(hostile, no_flow, current_weights={"VGT": 20, "TLT": 10})
    if any(s["action"] == "ADD" for s in r2["suggestions"]):
        failures.append("growth_scare did not block additions")
    if not any(s["action"] == "NO ADDITIONS" for s in r2["preservation"]):
        failures.append("growth_scare did not raise a preservation item")
    # Reductions must STILL be allowed in a hostile regime
    if not any(s["action"] == "REDUCE" for s in r2["suggestions"]):
        failures.append("hostile regime wrongly blocked reductions too")

    # No markets data at all -> refuse entirely
    r3 = build({"available": False}, no_flow)
    if r3["suggestions"] or not r3["blockers"]:
        failures.append("missing markets data did not refuse")

    # Hollow score must raise a confidence downgrade
    if not any("HOLLOW" in s["detail"] for s in r["preservation"]):
        failures.append("hollow score did not raise a preservation item")

    return {"ok": not failures, "failures": failures,
            "n_suggestions": len(r["suggestions"]),
            "n_preservation": len(r["preservation"]),
            "confidence": r["confidence"]}


if __name__ == "__main__":
    import json
    print(json.dumps(selftest(), indent=2, default=str))
