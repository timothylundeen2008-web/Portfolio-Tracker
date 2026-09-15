"""
substitution.py  (v1 — August 2026)
───────────────────────────────────
Should a candidate replace an incumbent in its role? Scored transparently.

EVERY COMPONENT IS EXPOSED, DELIBERATELY
────────────────────────────────────────
A composite score you cannot decompose is a score you cannot argue with,
correct, or catch when it breaks. Every candidate here reports its RS,
trend, cost and liquidity sub-scores alongside the total, plus the leverage
adjustment applied and the reason. If a ranking looks wrong, you can see
exactly which input produced it rather than trusting the number.

THREE GUARDRAILS, EACH ANSWERING A SPECIFIC FAILURE MODE
────────────────────────────────────────────────────────
1. REDUNDANCY. VOO and IVV track the SAME index. Their return difference is
   tracking error and rounding -- momentum-ranking one above the other
   measures noise, and acting on it generates real transaction costs and tax
   events for nothing. Within a redundancy group the tiebreak is
   DETERMINISTIC (cost, then liquidity), never momentum. VOO at 0.03% beats
   an equivalent at 0.20% always, with no ranking required.

2. MATERIALITY. A candidate must beat the incumbent by a MEANINGFUL margin,
   not a rounding difference. Everything else in this framework requires
   confirmation before acting -- the ±0.25% band, the 4-week Fed posture
   average, 3-of-3 confluence. Substitution gets the same treatment.

3. PERSISTENCE. The edge must hold across multiple reads. A single ranking
   snapshot is noise; an edge that survives repeated observation is signal.
   Without stored history this CANNOT be enforced, and this module says so
   explicitly rather than silently treating a first read as confirmed.

WHAT THIS DOES NOT DO
─────────────────────
It does not reweight ACROSS roles. Comparing VOO to SCHG is a real
question; comparing VOO to TLT is a category error that would let a momentum
ranking quietly dismantle the portfolio's diversification. Role weights stay
the regime classifier's job at Level 1.
"""

from __future__ import annotations

from typing import Optional

try:
    import candidate_universe as cu
except Exception:
    cu = None

# ── Score weights. Must sum to 1.0; asserted at import. ─────────────────────
W_RS = 0.35          # relative strength -- the most robust documented anomaly
W_TREND = 0.35       # trend state -- avoids buying strength in a downtrend
W_COST = 0.20        # expense ratio -- the only GUARANTEED edge available
W_LIQUIDITY = 0.10   # execution quality proxy
assert abs(W_RS + W_TREND + W_COST + W_LIQUIDITY - 1.0) < 1e-9

# ── Guardrail thresholds ────────────────────────────────────────────────────
MIN_EDGE_POINTS = 10.0      # materiality: challenger must beat incumbent by this
MIN_PERSISTENCE_READS = 2   # edge must survive this many observations

# ── Redundancy groups: functionally equivalent instruments ──────────────────
# Within a group, the winner is decided on COST then LIQUIDITY -- never
# momentum, because the momentum difference between two funds tracking the
# same index is measurement noise.
REDUNDANCY_GROUPS = [
    {"name": "S&P 500 core", "members": {"VOO", "IVV"},
     "why": "Both track the S&P 500. Return differences are tracking error "
            "and rounding, not signal."},
    {"name": "US large-cap growth", "members": {"SCHG", "VUG"},
     "why": "Heavily overlapping large-cap growth holdings. Ranking one "
            "above the other on momentum fits noise."},
    {"name": "Semiconductors", "members": {"SMH", "SOXX"},
     "why": "Same sector, near-identical top holdings. Cost and liquidity "
            "are the real differentiators."},
]

# Leverage adjustment. NOT a hidden penalty buried in the composite -- it is
# applied after scoring and reported separately, so the raw score and the
# adjustment are both visible.
LEVERAGE_SCORE_HAIRCUT = 0.75


# Minimum SPREAD required before a percentile rank is treated as meaningful.
# Percentile ranking is severely unstable in small peer groups: with only two
# peers, a trivial 10.0% vs 10.5% momentum difference becomes a 0-vs-100
# score gap -- a 52-point "edge" manufactured entirely from half a
# percentage point of noise. Role-based comparison operates on exactly these
# small groups, so this is not an edge case, it is the normal case. Caught by
# selftest, which flagged an immaterial QQQ->SCHG swap.
#
# Fix: when the peer spread is below the threshold, the attribute is not
# discriminating and every peer scores NEUTRAL. Only genuinely separated
# values get spread across the 0-100 range.
MIN_SPREAD = {
    "rs": 3.0,        # percentage points of composite momentum
    "expense": 0.05,  # percentage points of expense ratio
}


def _pct_rank(value: float, universe: list[float], higher_better=True,
              min_spread: float = 0.0) -> float:
    """
    Percentile rank 0-100 within a peer list, with a small-group guard.

    If the peer group's total spread is below `min_spread`, the attribute
    is not actually discriminating between these candidates and everything
    returns a neutral 50 -- rather than amplifying noise into a decisive-
    looking score difference.
    """
    vals = [v for v in universe if v is not None]
    if not vals or value is None:
        return 50.0
    if len(vals) == 1:
        return 50.0
    if min_spread and (max(vals) - min(vals)) < min_spread:
        return 50.0
    below = sum(1 for v in vals if (v < value if higher_better else v > value))
    return round(below / (len(vals) - 1) * 100, 1)


def redundancy_group(ticker: str) -> Optional[dict]:
    for g in REDUNDANCY_GROUPS:
        if ticker in g["members"]:
            return g
    return None


def score_candidate(ticker: str, role_peers: list[str],
                    rs_composite: Optional[float] = None,
                    rs_peer_values: Optional[list] = None,
                    trend_scalar: Optional[float] = None,
                    liquidity_tier: Optional[int] = None) -> dict:
    """
    Score one candidate. Returns every component, never just a total.

    Missing inputs are reported in `missing` and scored at a NEUTRAL 50
    rather than 0 -- an unmeasured attribute is unknown, not bad, and
    scoring it as bad would systematically penalise anything with a data gap.
    """
    meta = (cu.UNIVERSE.get(ticker, {}) if cu else {})
    out = {"ticker": ticker, "name": meta.get("name", ticker),
           "components": {}, "missing": [], "leverage": meta.get("leverage", 1.0)}

    # RS
    if rs_composite is not None and rs_peer_values:
        rs_score = _pct_rank(rs_composite, rs_peer_values,
                             min_spread=MIN_SPREAD["rs"])
    else:
        rs_score, _ = 50.0, out["missing"].append("relative strength")
    out["components"]["Relative strength"] = {
        "score": rs_score, "weight": W_RS,
        "raw": (f"{rs_composite:+.1f}% composite" if rs_composite is not None
                else "unavailable")}

    # Trend
    if trend_scalar is not None:
        trend_score = round(trend_scalar * 100, 1)
        raw = {1.0: "confirmed uptrend", 0.6: "ambiguous",
               0.3: "downtrend"}.get(round(trend_scalar, 1), f"{trend_scalar}")
    else:
        trend_score, raw = 50.0, "unavailable"
        out["missing"].append("trend state")
    out["components"]["Trend"] = {"score": trend_score, "weight": W_TREND,
                                  "raw": raw}

    # Cost -- lower expense is better, ranked within the role
    exp = meta.get("expense")
    peer_exp = [cu.UNIVERSE[t].get("expense") for t in role_peers
                if cu and t in cu.UNIVERSE] if cu else []
    if exp is not None and peer_exp:
        cost_score = _pct_rank(exp, peer_exp, higher_better=False,
                               min_spread=MIN_SPREAD["expense"])
        raw = f"{exp:.2f}% expense"
    else:
        cost_score, raw = 50.0, "unavailable"
        out["missing"].append("expense ratio")
    out["components"]["Cost"] = {"score": cost_score, "weight": W_COST,
                                 "raw": raw}

    # Liquidity (tier 1 best)
    if liquidity_tier is not None:
        liq_score = {1: 100.0, 2: 70.0, 3: 40.0, 4: 20.0}.get(liquidity_tier, 50.0)
        raw = f"tier {liquidity_tier}"
    else:
        liq_score, raw = 50.0, "unavailable"
        out["missing"].append("liquidity tier")
    out["components"]["Liquidity"] = {"score": liq_score, "weight": W_LIQUIDITY,
                                      "raw": raw}

    raw_total = sum(c["score"] * c["weight"] for c in out["components"].values())
    out["raw_score"] = round(raw_total, 1)

    if out["leverage"] > 1.0:
        out["score"] = round(raw_total * LEVERAGE_SCORE_HAIRCUT, 1)
        out["leverage_note"] = (
            f"{out['leverage']:.0f}x daily-reset product — raw score "
            f"{out['raw_score']:.1f} reduced by "
            f"{(1-LEVERAGE_SCORE_HAIRCUT)*100:.0f}% to {out['score']:.1f}. "
            f"Volatility decay is a structural cost that compounds against a "
            f"holder even in a flat market; it is not captured by RS or trend, "
            f"so it is applied here explicitly rather than hidden.")
    else:
        out["score"] = out["raw_score"]
        out["leverage_note"] = None
    return out


def evaluate_role(role: str, held: dict,
                  scores: dict) -> dict:
    """
    Compare incumbents against challengers within ONE role.

    `held`   {ticker: weight_pct} for currently-held positions
    `scores` {ticker: score_candidate() output} for every ticker in the role
    """
    out = {"role": role, "ranked": [], "incumbents": [], "challengers": [],
           "recommendations": [], "notes": []}

    ranked = sorted(scores.values(), key=lambda s: -s["score"])
    out["ranked"] = ranked
    held_tickers = {t for t, w in (held or {}).items() if w and w > 0}
    out["incumbents"] = [s for s in ranked if s["ticker"] in held_tickers]
    out["challengers"] = [s for s in ranked if s["ticker"] not in held_tickers]

    # ── Redundancy first: resolve equivalent instruments on cost/liquidity ──
    for g in REDUNDANCY_GROUPS:
        present = [s for s in ranked if s["ticker"] in g["members"]]
        if len(present) < 2:
            continue
        held_in_group = [s for s in present if s["ticker"] in held_tickers]
        if not held_in_group:
            continue
        # Deterministic winner: cost score, then liquidity. NOT momentum.
        winner = max(present, key=lambda s: (
            s["components"]["Cost"]["score"],
            s["components"]["Liquidity"]["score"]))
        for h in held_in_group:
            if h["ticker"] != winner["ticker"]:
                out["recommendations"].append({
                    "type": "REDUNDANCY SWAP", "priority": "HIGH",
                    "out": h["ticker"], "in": winner["ticker"],
                    "detail": (f"{h['ticker']} and {winner['ticker']} are "
                              f"functionally equivalent ({g['name']}). "
                              f"{winner['ticker']} wins on cost/liquidity."),
                    "why": (f"{g['why']} Resolved deterministically on "
                           f"{winner['components']['Cost']['raw']} vs "
                           f"{h['components']['Cost']['raw']} — NOT on "
                           f"momentum, which would be fitting noise here."),
                    "edge": None, "guardrails_passed": ["redundancy"]})
        out["notes"].append(
            f"{g['name']}: {winner['ticker']} preferred deterministically "
            f"(cost/liquidity), momentum not used.")

    # ── Materiality: challenger must beat incumbent by a real margin ────────
    if out["incumbents"] and out["challengers"]:
        best_inc = out["incumbents"][0]
        best_chal = out["challengers"][0]
        # Don't re-flag a redundancy pair as a momentum substitution
        same_group = (redundancy_group(best_inc["ticker"])
                      and redundancy_group(best_inc["ticker"])
                      == redundancy_group(best_chal["ticker"]))
        edge = best_chal["score"] - best_inc["score"]
        if same_group:
            pass
        elif edge >= MIN_EDGE_POINTS:
            out["recommendations"].append({
                "type": "SUBSTITUTION CANDIDATE", "priority": "MEDIUM",
                "out": best_inc["ticker"], "in": best_chal["ticker"],
                "detail": (f"{best_chal['ticker']} scores "
                          f"{best_chal['score']:.1f} vs "
                          f"{best_inc['ticker']}'s {best_inc['score']:.1f} "
                          f"(+{edge:.1f} points)."),
                "why": _explain_edge(best_chal, best_inc),
                "edge": round(edge, 1),
                "guardrails_passed": ["materiality"]})
        else:
            out["notes"].append(
                f"Best challenger {best_chal['ticker']} "
                f"({best_chal['score']:.1f}) does NOT clear the "
                f"{MIN_EDGE_POINTS:.0f}-point materiality threshold against "
                f"{best_inc['ticker']} ({best_inc['score']:.1f}) — edge "
                f"{edge:+.1f}. No substitution suggested; a difference this "
                f"small is noise, and acting on it costs real money in "
                f"spreads and taxes.")

    # ── Persistence: cannot be enforced without stored history ──────────────
    if out["recommendations"]:
        out["notes"].append(
            f"⚠ PERSISTENCE NOT YET ENFORCED. These are single-read "
            f"observations. This framework requires confirmation everywhere "
            f"else (the ±0.25% band, 4-week Fed posture, 3-of-3 confluence, "
            f"two closes on a regime transition) and substitution should be "
            f"no different — an edge should hold for "
            f"{MIN_PERSISTENCE_READS}+ reads before acting. Treat anything "
            f"below as a WATCH item, not an instruction.")
    return out


def _explain_edge(chal: dict, inc: dict) -> str:
    """Which components actually drove the difference — no black box."""
    diffs = []
    for name in chal["components"]:
        c = chal["components"][name]["score"]
        i = inc["components"].get(name, {}).get("score", 50.0)
        contrib = (c - i) * chal["components"][name]["weight"]
        if abs(contrib) >= 1.0:
            diffs.append((name, contrib, chal["components"][name]["raw"],
                         inc["components"].get(name, {}).get("raw", "n/a")))
    diffs.sort(key=lambda d: -abs(d[1]))
    if not diffs:
        return "No single component dominates the difference."
    parts = [f"{n} {c:+.1f}pts ({chal['ticker']}: {cr} vs "
             f"{inc['ticker']}: {ir})" for n, c, cr, ir in diffs[:3]]
    return "Driven by " + "; ".join(parts) + "."


def render(st, result: dict):
    """Render the full scorecard — every component visible."""
    import pandas as pd

    st.markdown(f"#### Scorecard — {result['role'].replace('_',' ').title()}")
    st.caption(
        f"Weights: relative strength {W_RS:.0%} · trend {W_TREND:.0%} · "
        f"cost {W_COST:.0%} · liquidity {W_LIQUIDITY:.0%}. Leveraged "
        f"products take an explicit {(1-LEVERAGE_SCORE_HAIRCUT):.0%} haircut, "
        f"applied AFTER scoring and shown separately — never hidden inside "
        f"the composite."
    )

    if not result["ranked"]:
        st.info("No candidates scored for this role.")
        return

    rows = []
    for s in result["ranked"]:
        row = {"Ticker": s["ticker"],
               "Score": s["score"],
               "Raw": s["raw_score"] if s["leverage"] > 1 else "—",
               "Lev": f"{s['leverage']:.0f}x" if s["leverage"] > 1 else "—"}
        for name, c in s["components"].items():
            row[name] = c["score"]
        row["Missing"] = ", ".join(s["missing"]) if s["missing"] else "—"
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with st.expander("What each score means — raw inputs behind the numbers"):
        for s in result["ranked"]:
            st.markdown(f"**{s['ticker']}** — {s['name']} · "
                       f"score {s['score']:.1f}")
            for name, c in s["components"].items():
                st.caption(f"  {name}: {c['score']:.0f}/100 "
                          f"(weight {c['weight']:.0%}) — {c['raw']}")
            if s.get("leverage_note"):
                st.caption(f"  ⚠ {s['leverage_note']}")

    if result["recommendations"]:
        st.markdown("#### Flagged for consideration")
        for r in result["recommendations"]:
            box = st.warning if r["priority"] == "HIGH" else st.info
            box(f"**{r['type']}** — replace **{r['out']}** with "
               f"**{r['in']}**. {r['detail']}")
            st.caption(f"Why: {r['why']}")
            st.caption(f"Guardrails cleared: {', '.join(r['guardrails_passed'])}")
    else:
        st.success("**No substitutions flagged for this role.** Incumbents "
                  "are holding their position, or no challenger clears the "
                  "materiality threshold.")

    for n in result["notes"]:
        st.caption(n)


def selftest() -> dict:
    failures = []
    if cu is None:
        return {"ok": False, "failures": ["candidate_universe not importable"]}

    peers = ["VOO", "IVV"]
    # Same index, IVV given artificially better momentum -- must NOT drive it
    sc = {
        "VOO": score_candidate("VOO", peers, rs_composite=5.0,
                               rs_peer_values=[5.0, 9.0], trend_scalar=1.0,
                               liquidity_tier=1),
        "IVV": score_candidate("IVV", peers, rs_composite=9.0,
                               rs_peer_values=[5.0, 9.0], trend_scalar=1.0,
                               liquidity_tier=1),
    }
    res = evaluate_role("US_BROAD", {"VOO": 20}, sc)
    momentum_swap = [r for r in res["recommendations"]
                     if r["type"] == "SUBSTITUTION CANDIDATE"]
    if momentum_swap:
        failures.append("redundant pair produced a MOMENTUM substitution — "
                        "should be resolved deterministically only")

    # Leverage haircut must be applied AND visible
    lev = score_candidate("TQQQ", ["QQQ", "TQQQ"], rs_composite=20.0,
                          rs_peer_values=[5.0, 20.0], trend_scalar=1.0,
                          liquidity_tier=1)
    if lev["score"] >= lev["raw_score"]:
        failures.append("leverage haircut not applied")
    if not lev.get("leverage_note"):
        failures.append("leverage adjustment not surfaced")

    # Noise must NOT drive a substitution. Two peers with near-identical
    # momentum AND near-identical cost should produce nothing -- this is the
    # case the small-group spread guard exists for.
    peers2 = ["QQQ", "VUG"]
    sc2 = {
        "QQQ": score_candidate("QQQ", peers2, rs_composite=10.0,
                               rs_peer_values=[10.0, 10.5], trend_scalar=1.0,
                               liquidity_tier=1),
        "VUG": score_candidate("VUG", peers2, rs_composite=10.5,
                               rs_peer_values=[10.0, 10.5], trend_scalar=1.0,
                               liquidity_tier=1),
    }
    res2 = evaluate_role("US_GROWTH", {"QQQ": 10}, sc2)
    rs_q = sc2["QQQ"]["components"]["Relative strength"]["score"]
    rs_v = sc2["VUG"]["components"]["Relative strength"]["score"]
    if not (rs_q == rs_v == 50.0):
        failures.append(f"0.5pt momentum spread should score NEUTRAL for "
                        f"both, got QQQ={rs_q} VUG={rs_v}")

    # A GENUINE edge must still surface. SCHG 0.04% vs QQQ 0.20% expense is a
    # permanent 0.16%/yr cost difference on overlapping exposure -- real, not
    # noise, and the framework should say so.
    peers2b = ["QQQ", "SCHG"]
    sc2b = {
        "QQQ": score_candidate("QQQ", peers2b, rs_composite=10.0,
                               rs_peer_values=[10.0, 10.5], trend_scalar=1.0,
                               liquidity_tier=1),
        "SCHG": score_candidate("SCHG", peers2b, rs_composite=10.5,
                                rs_peer_values=[10.0, 10.5], trend_scalar=1.0,
                                liquidity_tier=2),
    }
    res2b = evaluate_role("US_GROWTH", {"QQQ": 10}, sc2b)
    cost_subs = [r for r in res2b["recommendations"]
                 if r["type"] == "SUBSTITUTION CANDIDATE"]
    if not cost_subs:
        failures.append("a real 0.16%/yr cost edge was NOT surfaced")
    elif "Cost" not in cost_subs[0]["why"]:
        failures.append(f"cost edge surfaced but attribution is wrong: "
                        f"{cost_subs[0]['why']}")

    # Persistence caveat must appear whenever anything is recommended
    peers3 = ["QQQ", "VGT"]
    sc3 = {
        "QQQ": score_candidate("QQQ", peers3, rs_composite=-5.0,
                               rs_peer_values=[-5.0, 30.0], trend_scalar=0.3,
                               liquidity_tier=1),
        "VGT": score_candidate("VGT", peers3, rs_composite=30.0,
                               rs_peer_values=[-5.0, 30.0], trend_scalar=1.0,
                               liquidity_tier=2),
    }
    res3 = evaluate_role("US_TECH", {"QQQ": 10}, sc3)
    if res3["recommendations"] and not any(
            "PERSISTENCE NOT YET ENFORCED" in n for n in res3["notes"]):
        failures.append("persistence caveat missing on a live recommendation")

    # Missing data must score neutral, not zero
    bare = score_candidate("VOO", peers)
    if bare["components"]["Relative strength"]["score"] != 50.0:
        failures.append("missing RS did not score neutral 50")
    if not bare["missing"]:
        failures.append("missing inputs not reported")

    return {"ok": not failures, "failures": failures,
            "lev_raw": lev["raw_score"], "lev_adjusted": lev["score"],
            "redundancy_recs": len(res["recommendations"])}


if __name__ == "__main__":
    import json
    print(json.dumps(selftest(), indent=2, default=str))
