"""
historical_episodes.py
======================
Historical reference panel: US financial-repression episodes.

Purpose: give the LIVE regime reading something to sit against. The key
teaching point encoded here is that a negative LONG real yield is NOT a
defining condition of repression — it is a feature of *some* episodes (the
1940s peg, the QE era) and absent from others (much of the 1970s). What is
consistent is the negative SHORT real rate, which does most of the debt-
liquidation work because Treasury issuance is weighted short.

⚠️ METHODOLOGICAL BREAK — READ BEFORE BACKTESTING
   TIPS did not exist until 1997. Every "long real yield" figure before then is
   an EX-POST construct (nominal 10y minus realized CPI), which is a different,
   noisier, LAGGING measure than the market-implied, forward-looking DFII10 the
   live classifier uses. Do NOT feed pre-1997 ex-post reals into the same signal
   logic and expect comparable behavior. Figures below are approximate,
   representative of each episode, and intended for context — not for backtests.
"""

from __future__ import annotations

import datetime as _dt

import pandas as pd

# --------------------------------------------------------------------------- #
#  The episodes
# --------------------------------------------------------------------------- #
# real yields in %, approximate episode-typical / peak values.
EPISODES = [
    {
        "key": "peg_1942_51",
        "era": "1942–1951",
        "name": "WWII / Postwar Peg",
        "type": "HARD",
        "short_real": "Deeply negative",
        "long_real": "Negative (peak ≈ −10 to −15%)",
        "long_real_negative": "Yes — but not continuously",
        "mechanism": (
            "Explicit Fed peg: bills at 0.375%, long bonds capped ≈2.5%. "
            "Inflation spiked to ~14–19% YoY in 1946–47 while the cap held, "
            "forcing deeply negative real returns on bondholders."
        ),
        "nuance": (
            "Even here the long real yield was not ALWAYS negative — the 1949 "
            "deflationary dip flipped it positive. The negativity came from the "
            "cap colliding with an inflation spike, not from repression per se."
        ),
        "ended": "1951 Fed–Treasury Accord",
        "portfolio_lesson": (
            "The only episode where nominal long bonds were structurally "
            "guaranteed to lose real value. Real assets dominate."
        ),
    },
    {
        "key": "seventies",
        "era": "1970s (≈1971–1981)",
        "name": "Great Inflation",
        "type": "SOFT",
        "short_real": "Negative most of the decade",
        "long_real": "Oscillating — negative only in spikes",
        "long_real_negative": "No — positive through much of the decade",
        "mechanism": (
            "No cap. The Fed simply ran behind the curve. Long yields were FREE "
            "to rise and did: 10y went ~6% → ~8% → double digits."
        ),
        "nuance": (
            "THE COUNTEREXAMPLE. Real 10y yields were meaningfully negative in "
            "the 1974–75 and 1979–80 inflation spikes but POSITIVE in the "
            "mid-decade lull (inflation fell to ~5–6% while nominals held 7–8%). "
            "Repression ran through the SHORT rate, not the long end."
        ),
        "ended": "Volcker shock (1979–82)",
        "portfolio_lesson": (
            "Repression without a suppressed long end. Duration was a foe "
            "(rising yields), commodities/gold and trend were the winners."
        ),
    },
    {
        "key": "qe_2010_15",
        "era": "2010–2015",
        "name": "Post-GFC QE / ZIRP",
        "type": "SOFT→HARD-ish",
        "short_real": "Negative (ZIRP vs. ~2% CPI)",
        "long_real": "Negative (≈ −0.9% in 2012)",
        "long_real_negative": "Yes (market-implied TIPS)",
        "mechanism": (
            "ZIRP + QE + Operation Twist compressed term premium. First episode "
            "with a genuine MARKET-implied negative long real yield (TIPS)."
        ),
        "nuance": (
            "Suppression was via asset purchases and forward guidance rather "
            "than an explicit cap — closer to hard repression in effect than in "
            "name."
        ),
        "ended": "2013 taper / 2015 liftoff",
        "portfolio_lesson": (
            "Negative long real yields made duration a friend on the way down. "
            "Gold ran hard 2010–11, then broke when real yields turned up."
        ),
    },
    {
        "key": "covid_2020_22",
        "era": "2020–2022",
        "name": "COVID QE / Inflation Surge",
        "type": "SOFT→unwound",
        "short_real": "Deeply negative (ZIRP vs. 7–9% CPI)",
        "long_real": "Record negative (≈ −1.2% late 2021)",
        "long_real_negative": "Yes — record low",
        "mechanism": (
            "ZIRP + massive QE while inflation surged. The most negative "
            "market-implied long real yield on record."
        ),
        "nuance": (
            "Unwound violently in 2022: real yields snapped positive, and long "
            "duration suffered its worst drawdown in modern history. The "
            "REVERSAL is the lesson, not the level."
        ),
        "ended": "2022 hiking cycle",
        "portfolio_lesson": (
            "When negative long real yields normalize, TLT is the worst place "
            "to be (−33% in 2022) and trend/managed futures the best (+28%)."
        ),
    },
]


# --------------------------------------------------------------------------- #
#  The live "today" row — DERIVED, never stored
# --------------------------------------------------------------------------- #
# v3 fix. This row used to be a hardcoded literal reading:
#
#     short_real: "Negative (≈ −0.6%: EFFR ~3.63% − CPI ~4.2%)"
#     long_real:  "POSITIVE and RISING (≈ +2.25% DFII10)"
#     name:       "Partial / Early Repression"
#
# By 2026-07-29 all three were wrong — the short real rate had risen to roughly
# +0.10% (EFFR ~3.58% − CPI 3.50%), DFII10 had reached ~2.44%, and the live
# classifier no longer returned a repression regime at all. The panel and the
# regime banner sat on the same screen asserting opposite things, and the panel
# is the one that reads as curated analysis.
#
# It is the ONLY episode in the list that can go stale, so it is now computed
# from live signals at render time. Anything unavailable renders as "n/a"
# rather than as a stale figure: a blank is recoverable, an authoritative-
# looking wrong number is not.

def live_today_episode(sig=None, regime: dict | None = None) -> dict:
    """Build the 'today' row from live signals. Never raises."""

    def g(name, default=None):
        if sig is None:
            return default
        if isinstance(sig, dict):
            return sig.get(name, default)
        return getattr(sig, name, default)

    sr = g("short_real_rate")
    lr = g("long_real_yield")
    lm = g("long_real_mom_3m")
    cpi = g("cpi_yoy")
    eff = g("eff_funds")

    # Keep the band width in sync with the classifier rather than restating it.
    try:
        from regime_bands import TRANSITION_BAND as _BAND
    except Exception:
        _BAND = 0.25

    if sr is None:
        sr_txt = "n/a — short real policy rate unavailable"
    else:
        sign = ("Negative" if sr < -_BAND else
                "Positive" if sr > _BAND else
                f"AT ZERO (inside ±{_BAND:.2f}% band)")
        detail = (f"EFFR ~{eff:.2f}% − CPI ~{cpi:.2f}%"
                  if eff is not None and cpi is not None else "")
        sr_txt = f"{sign} (≈ {sr:+.2f}%{': ' + detail if detail else ''})"

    if lr is None:
        lr_txt = "n/a — DFII10 unavailable"
        lr_neg = "n/a"
    else:
        direction = ("RISING" if (lm or 0) > 0 else
                     "FALLING" if (lm or 0) < 0 else "FLAT")
        lr_txt = (f"{'POSITIVE' if lr > 0 else 'NEGATIVE'} and {direction} "
                  f"(≈ {lr:+.2f}% DFII10)")
        lr_neg = "YES" if lr < 0 else "NO — historically high"

    reg = regime or {}
    nuance = (
        "Derived from live signals at render time. If this row disagrees with "
        "the Regime Classifier banner, that is a bug — they now share one "
        "source."
    )
    if lr is not None and lr > 1.0:
        nuance += (
            f" A {lr:+.2f}% long real yield is nowhere near any repression "
            f"episode's long end: the front end may or may not be repressed, "
            f"but the long end is demanding term and fiscal risk premium "
            f"rather than being suppressed."
        )

    return {
        "key": "today",
        "era": f"{_dt.date.today():%Y-%m-%d} (live)",
        "name": reg.get("label", "Live regime — see classifier"),
        "type": "SOFT",
        "short_real": sr_txt,
        "long_real": lr_txt,
        "long_real_negative": lr_neg,
        "mechanism": reg.get(
            "blurb",
            "See the Regime Classifier panel for the live read."),
        "nuance": nuance,
        "ended": "—",
        "portfolio_lesson": (
            "Read the live overlay from target_weights(). This row is context, "
            "not an allocation."),
    }


def all_rows(sig=None, regime: dict | None = None) -> list:
    """Historical episodes plus the live row. Use this instead of EPISODES."""
    return list(EPISODES) + [live_today_episode(sig, regime)]


TYPE_COLOR = {
    "HARD": "#dc2626",
    "SOFT": "#d97706",
    "SOFT→HARD-ish": "#c026d3",
    "SOFT→unwound": "#7c3aed",
}


def episodes_table(sig=None, regime: dict | None = None) -> pd.DataFrame:
    """Compact comparison table — the headline answer to 'was the 10y always
    negative?' (No.)

    Both arguments default to None so any call site not yet updated degrades to
    "n/a" in the live row rather than raising.
    """
    return pd.DataFrame([{
        "Episode": f"{e['era']} · {e['name']}",
        "Type": e["type"],
        "SHORT real rate": e["short_real"],
        "LONG real yield": e["long_real"],
        "Long real NEGATIVE?": e["long_real_negative"],
    } for e in all_rows(sig, regime)])


def render_historical_panel(st, sig=None, regime: dict | None = None):
    """Render the panel. `st` is passed in so this module stays import-safe.

    Pass the live SignalSet and regime dict so the 'today' row reflects current
    data instead of a frozen snapshot.
    """
    st.markdown("#### 📜 Historical US repression episodes")
    st.caption(
        "Context for the live reading. The headline finding: a negative LONG "
        "real yield is NOT a defining condition of repression — the 1970s ran a "
        "decade of repression with a mostly POSITIVE long real yield. The "
        "constant is the negative SHORT real rate."
    )

    st.dataframe(episodes_table(sig, regime), hide_index=True,
                 use_container_width=True)

    st.info(
        "**Why the long end need not be negative:** debt liquidation depends on "
        "the real rate paid on debt *actually outstanding*, and Treasury issues "
        "heavily short (weighted-average maturity ≈6 years). A negative SHORT "
        "real rate does most of the liquidation work regardless of the 10-year. "
        "Repression is a front-end and captive-audience phenomenon."
    )

    if sig is None:
        st.caption("⚠ Live signals not supplied to this panel — the "
                   "'today' row will render as n/a. Pass sig= and regime= "
                   "from full_assessment().")

    for e in all_rows(sig, regime):
        is_today = e["key"] == "today"
        title = ("🔴 " if is_today else "") + f"{e['era']} — {e['name']}"
        with st.expander(title, expanded=is_today):
            c = TYPE_COLOR.get(e["type"], "#6b7280")
            st.markdown(
                f"<span style='background:{c}22;color:{c};padding:2px 10px;"
                f"border-radius:10px;font-weight:600;'>{e['type']} repression"
                f"</span>", unsafe_allow_html=True)
            a, b = st.columns(2)
            a.metric("SHORT real rate", e["short_real"])
            b.metric("LONG real yield", e["long_real"])
            st.markdown(f"**Mechanism:** {e['mechanism']}")
            st.markdown(f"**Nuance:** {e['nuance']}")
            if e["ended"] != "—":
                st.markdown(f"**Ended by:** {e['ended']}")
            st.success(f"**Portfolio lesson:** {e['portfolio_lesson']}")

    with st.expander("⚠️ Methodological break — read before backtesting"):
        st.markdown(
            "**TIPS did not exist until 1997.** Every long-real-yield figure "
            "before then is an **ex-post** construct (nominal 10y − realized "
            "CPI): a *lagging, noisier, backward-looking* measure.\n\n"
            "The live classifier uses **DFII10** — a *market-implied, "
            "forward-looking* yield. These are different objects.\n\n"
            "If you run the regime classifier back through the 1940s or 1970s, "
            "this is where it will quietly mislead you. Do not treat pre-1997 "
            "ex-post reals as drop-in substitutes for DFII10."
        )
        st.caption(
            "Figures above are approximate and episode-typical — for context, "
            "not for backtests."
        )
