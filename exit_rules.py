"""
exit_rules.py  (v1 — August 2026)
─────────────────────────────────
Exits for EVERY position, not just the satellite sleeve.

WHY THIS IS THE MOST IMPORTANT MODULE HERE
──────────────────────────────────────────
Entries are optional. Exits are not. A framework that can identify what to
buy but has no rule for when to sell is a framework that will eventually
give back everything it made, because the decision gets made under stress
with no pre-commitment to fall back on.

Growth Satellite already had Level 6.5 exit discipline. Every other position
in the book had nothing systematic. This generalises it.

FOUR INDEPENDENT EXIT TRIGGERS, ANY ONE SUFFICIENT
──────────────────────────────────────────────────
1. STRUCTURAL STOP    price closes below a trailing ATR-based stop
2. TREND BREAK        price loses a rising 200-day (the gold gate, applied
                      universally -- see trend_filter.py)
3. PROFIT LADDER      Level 6.5 R-multiple scaling on the way up
4. THESIS INVALIDATION the regime or role rationale that justified the
                      position no longer holds

They are deliberately independent. A position can be profitable, trending,
and still exit on #4 -- "it's still going up" is not a reason to keep
something the framework no longer has a reason to own.

LEVERAGE CHANGES THE MATH, SO IT CHANGES THE STOPS
──────────────────────────────────────────────────
A 3x fund's daily reset means a -20% underlying move is roughly -60%, and
recovering from -60% requires +150%. Volatility decay compounds against a
holder even in a FLAT market. So leveraged positions get:

    * a TIGHTER ATR multiple (2.0x vs 2.5x) -- less room before the exit
    * a HARD maximum loss floor -- an absolute % that overrides ATR entirely
    * a shorter maximum holding period -- decay makes indefinite holds
      structurally negative-expectancy even if direction is right

That is not caution for its own sake; it is the arithmetic of the
instrument. Any framework that applies identical stop logic to a 1x and a
3x product has not accounted for the instrument it is holding.
"""

from __future__ import annotations

from typing import Optional

try:
    from candidate_universe import leverage_of, is_leveraged
except Exception:
    leverage_of, is_leveraged = (lambda t: 1.0), (lambda t: False)

# ── Stop parameters ─────────────────────────────────────────────────────────
ATR_MULT_STANDARD = 2.5
ATR_MULT_LEVERAGED = 2.0        # tighter -- see module docstring

# Hard floors. ATR adapts to volatility, which is right most of the time and
# wrong exactly when volatility explodes. These override it.
MAX_LOSS_STANDARD_PCT = 20.0
MAX_LOSS_LEVERAGED_PCT = 12.0

# Leveraged holding-period ceiling. Volatility decay makes an indefinite hold
# structurally negative-expectancy even when direction is correct.
MAX_HOLD_DAYS_LEVERAGED = 90

# ── Level 6.5 profit ladder, in R-multiples ─────────────────────────────────
PROFIT_LADDER = [
    (2.0, 0.25, "Trim 25%. Bank the position's own risk back — from here it "
                "is playing with house money."),
    (4.0, 0.25, "Trim another 25%. Half realised; the remainder rides with a "
                "raised stop."),
    (8.0, 0.25, "Trim another 25%. Parabolic territory — this is where "
                "positions round-trip."),
]
PROFIT_LADDER_RUNNER_PCT = 0.25   # deliberately left to run


def plan(ticker: str, entry: float, current: float,
         atr: Optional[float] = None,
         ma200: Optional[float] = None,
         ma200_rising: Optional[bool] = None,
         held_days: Optional[int] = None,
         regime_supports: Optional[bool] = None,
         highest_since_entry: Optional[float] = None) -> dict:
    """
    Full exit plan for one position. Every field optional -- a missing input
    disables ONLY the trigger that needs it, and says so, rather than
    silently passing.
    """
    lev = leverage_of(ticker)
    levered = lev > 1.0
    out = {"ticker": ticker, "leverage": lev, "leveraged": levered,
           "entry": entry, "current": current, "triggers": [],
           "exit_now": False, "unavailable": [], "stop": None,
           "pnl_pct": None, "r_multiple": None}

    if entry and current:
        out["pnl_pct"] = round((current / entry - 1) * 100, 2)

    atr_mult = ATR_MULT_LEVERAGED if levered else ATR_MULT_STANDARD
    max_loss = MAX_LOSS_LEVERAGED_PCT if levered else MAX_LOSS_STANDARD_PCT

    # ── 1. Structural (trailing ATR) stop ───────────────────────────────────
    if atr and entry:
        anchor = highest_since_entry or max(entry, current or entry)
        atr_stop = anchor - atr * atr_mult
        floor_stop = entry * (1 - max_loss / 100)
        # The TIGHTER of the two governs -- ATR adapts, the floor is absolute.
        stop = max(atr_stop, floor_stop)
        out["stop"] = round(stop, 2)
        out["stop_basis"] = ("ATR trail" if atr_stop >= floor_stop
                             else f"hard {max_loss:.0f}% floor")
        out["r_multiple"] = (round((current - entry) / (entry - floor_stop), 2)
                             if entry > floor_stop and current else None)
        if current and current <= stop:
            out["exit_now"] = True
            out["triggers"].append({
                "type": "STRUCTURAL STOP", "severity": "CRITICAL",
                "detail": (f"{current:.2f} is at or below the {out['stop_basis']} "
                          f"stop of {stop:.2f}."),
                "action": "EXIT. The stop was set before entry, when you were "
                         "objective. Never move it down."})
    else:
        out["unavailable"].append("ATR stop (needs ATR + entry)")

    # ── 2. Trend break ──────────────────────────────────────────────────────
    if ma200 and current:
        if current < ma200 and ma200_rising is False:
            out["exit_now"] = True
            out["triggers"].append({
                "type": "TREND BREAK", "severity": "CRITICAL",
                "detail": (f"{current:.2f} is below a FALLING 200-day "
                          f"({ma200:.2f})."),
                "action": "EXIT or reduce to the trend-gated weight. Price "
                         "below a falling long-term average is the condition "
                         "the gold gate refuses to add into — the same logic "
                         "applies to exiting."})
        elif current < ma200:
            out["triggers"].append({
                "type": "TREND WARNING", "severity": "WARNING",
                "detail": (f"{current:.2f} is below the 200-day ({ma200:.2f}), "
                          f"but the average is still rising."),
                "action": "A pullback within an uptrend, not a break. Tighten "
                         "rather than exit; a close below a FALLING average "
                         "is the actual trigger."})
    else:
        out["unavailable"].append("trend break (needs 200-day + price)")

    # ── 3. Profit ladder ────────────────────────────────────────────────────
    if out["r_multiple"] is not None and out["r_multiple"] > 0:
        for r_target, trim, note in PROFIT_LADDER:
            if out["r_multiple"] >= r_target:
                out["triggers"].append({
                    "type": f"PROFIT LADDER {r_target:.0f}R",
                    "severity": "INFO",
                    "detail": (f"Up {out['r_multiple']:.1f}R "
                              f"({out['pnl_pct']:+.1f}%) — past the "
                              f"{r_target:.0f}R rung."),
                    "action": note})

    # ── 4. Thesis invalidation ──────────────────────────────────────────────
    if regime_supports is False:
        out["exit_now"] = True
        out["triggers"].append({
            "type": "THESIS INVALIDATED", "severity": "CRITICAL",
            "detail": "The regime/role rationale that justified this position "
                     "no longer holds.",
            "action": "EXIT regardless of P&L. 'It is still going up' is not "
                     "a reason to keep something the framework no longer has "
                     "a reason to own — that is how a thesis-driven position "
                     "silently becomes a momentum bet."})
    elif regime_supports is None:
        out["unavailable"].append("thesis check (needs regime context)")

    # ── Leverage-specific ───────────────────────────────────────────────────
    if levered:
        out["triggers"].append({
            "type": "LEVERAGE DISCIPLINE", "severity": "WARNING",
            "detail": (f"{lev:.0f}x daily-reset product. Stops are tighter "
                      f"({atr_mult}x ATR vs {ATR_MULT_STANDARD}x; "
                      f"{max_loss:.0f}% hard floor vs "
                      f"{MAX_LOSS_STANDARD_PCT:.0f}%) because a -20% "
                      f"underlying move is roughly {-20*lev:.0f}% here."),
            "action": (f"Maximum hold {MAX_HOLD_DAYS_LEVERAGED} days — "
                      f"volatility decay makes indefinite holds "
                      f"negative-expectancy even when direction is right.")})
        if held_days and held_days > MAX_HOLD_DAYS_LEVERAGED:
            out["exit_now"] = True
            out["triggers"].append({
                "type": "LEVERAGE HOLD LIMIT", "severity": "CRITICAL",
                "detail": (f"Held {held_days} days, past the "
                          f"{MAX_HOLD_DAYS_LEVERAGED}-day ceiling for a "
                          f"{lev:.0f}x product."),
                "action": "EXIT or roll. Decay compounds against the holder "
                         "the longer this runs."})
    return out


def render(st, plans: list[dict]):
    """Render exit status across positions."""
    st.markdown("##### Exit discipline")
    st.caption(
        "Four independent triggers, any one sufficient: structural stop, "
        "trend break, profit ladder, thesis invalidation. Entries are "
        "optional; exits are not."
    )
    if not plans:
        st.caption("No positions to evaluate.")
        return

    exiting = [p for p in plans if p.get("exit_now")]
    if exiting:
        st.error(f"🔴 {len(exiting)} position(s) at an exit trigger: "
                f"{', '.join(p['ticker'] for p in exiting)}")

    for p in sorted(plans, key=lambda x: (not x.get("exit_now"), x["ticker"])):
        lev_tag = f" ⚠{p['leverage']:.0f}x" if p.get("leveraged") else ""
        head = f"**{p['ticker']}**{lev_tag}"
        if p.get("pnl_pct") is not None:
            head += f" — {p['pnl_pct']:+.1f}%"
        if p.get("r_multiple") is not None:
            head += f" ({p['r_multiple']:+.1f}R)"
        if p.get("stop"):
            head += f" · stop {p['stop']:.2f} ({p.get('stop_basis','')})"
        st.markdown(head)
        for t in p.get("triggers", []):
            icon = {"CRITICAL": "🔴", "WARNING": "⚠️", "INFO": "ℹ️"}.get(
                t["severity"], "·")
            st.caption(f"{icon} **{t['type']}** — {t['detail']} {t['action']}")
        if p.get("unavailable"):
            st.caption(f"○ Not evaluated (missing data): "
                      f"{', '.join(p['unavailable'])}")


def selftest() -> dict:
    failures = []

    # Leveraged must get tighter stops than unleveraged, same inputs
    std = plan("VOO", entry=100, current=95, atr=2.0,
               highest_since_entry=105)
    lev = plan("TQQQ", entry=100, current=95, atr=2.0,
               highest_since_entry=105)
    if not (lev["stop"] > std["stop"]):
        failures.append(f"leveraged stop {lev['stop']} should be TIGHTER "
                        f"(higher) than standard {std['stop']}")
    if not lev["leveraged"]:
        failures.append("TQQQ not flagged as leveraged")

    # Hard floor must override ATR when ATR is very wide
    wide = plan("TQQQ", entry=100, current=95, atr=50.0,
                highest_since_entry=100)
    if wide["stop_basis"] != "hard 12% floor":
        failures.append(f"expected hard floor to govern, got "
                        f"{wide['stop_basis']}")

    # Thesis invalidation must force exit even when profitable
    thesis = plan("VOO", entry=100, current=150, atr=2.0,
                  regime_supports=False)
    if not thesis["exit_now"]:
        failures.append("thesis invalidation did not force exit on a winner")

    # Trend break on a falling MA must exit; on a rising MA must only warn
    brk = plan("VOO", entry=100, current=90, ma200=95, ma200_rising=False)
    if not brk["exit_now"]:
        failures.append("break below falling MA did not exit")
    pull = plan("VOO", entry=100, current=94, ma200=95, ma200_rising=True)
    if pull["exit_now"]:
        failures.append("pullback below RISING MA should warn, not exit")

    # Leveraged hold ceiling
    old = plan("SOXL", entry=100, current=120, held_days=200)
    if not old["exit_now"]:
        failures.append("leveraged hold-period ceiling not enforced")

    # Missing data must be named, not silently passed
    bare = plan("VOO", entry=100, current=110)
    if not bare["unavailable"]:
        failures.append("missing inputs not reported")
    if bare["exit_now"]:
        failures.append("bare position with no data should not force exit")

    return {"ok": not failures, "failures": failures,
            "std_stop": std["stop"], "lev_stop": lev["stop"]}


if __name__ == "__main__":
    import json
    print(json.dumps(selftest(), indent=2, default=str))
