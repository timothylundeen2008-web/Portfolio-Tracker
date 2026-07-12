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
    {
        "key": "today",
        "era": "2025–2026 (today)",
        "name": "Partial / Early Repression",
        "type": "SOFT",
        "short_real": "Negative (≈ −0.6%: EFFR ~3.63% − CPI ~4.2%)",
        "long_real": "POSITIVE and RISING (≈ +2.25% DFII10)",
        "long_real_negative": "NO — historically high",
        "mechanism": (
            "Liquidation channel runs quietly at the FRONT end. The long end is "
            "NOT suppressed — it is demanding term/fiscal risk premium."
        ),
        "nuance": (
            "A +2.25% long real yield is nowhere near any repression episode's "
            "long end. This is PARTIAL repression: the front end is repressed, "
            "the long end is refusing to cooperate."
        ),
        "ended": "—",
        "portfolio_lesson": (
            "Duration is a FOE here (TLT → 0%). Real assets + trend do the work. "
            "WATCH FOR: long real yields FALLING while inflation stays hot — "
            "that is hard repression (YCC) arriving, and the moment TLT flips "
            "from foe to friend."
        ),
    },
]

TYPE_COLOR = {
    "HARD": "#dc2626",
    "SOFT": "#d97706",
    "SOFT→HARD-ish": "#c026d3",
    "SOFT→unwound": "#7c3aed",
}


def episodes_table() -> pd.DataFrame:
    """Compact comparison table — the headline answer to 'was the 10y always
    negative?' (No.)"""
    return pd.DataFrame([{
        "Episode": f"{e['era']} · {e['name']}",
        "Type": e["type"],
        "SHORT real rate": e["short_real"],
        "LONG real yield": e["long_real"],
        "Long real NEGATIVE?": e["long_real_negative"],
    } for e in EPISODES])


def render_historical_panel(st):
    """Render the panel. `st` is passed in so this module stays import-safe."""
    st.markdown("#### 📜 Historical US repression episodes")
    st.caption(
        "Context for the live reading. The headline finding: a negative LONG "
        "real yield is NOT a defining condition of repression — the 1970s ran a "
        "decade of repression with a mostly POSITIVE long real yield. The "
        "constant is the negative SHORT real rate."
    )

    st.dataframe(episodes_table(), hide_index=True, use_container_width=True)

    st.info(
        "**Why the long end need not be negative:** debt liquidation depends on "
        "the real rate paid on debt *actually outstanding*, and Treasury issues "
        "heavily short (weighted-average maturity ≈6 years). A negative SHORT "
        "real rate does most of the liquidation work regardless of the 10-year. "
        "Repression is a front-end and captive-audience phenomenon."
    )

    for e in EPISODES:
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
