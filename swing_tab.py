"""
swing_tab.py  (v1 — September 2026)
───────────────────────────────────
The Swing Desk tab, rebuilt as the AGENT'S surface rather than a scanner.

    1. Today's brief   — the latest logs/swing/<date>_brief.json, rendered
    2. Decisions       — per card: Took it / Pass / Watch
                          per open-position recommendation: Done / Decline
                          every click -> swing_journal (append-only, GitHub-backed)
    3. Journal & review — open positions, closed trades, expectancy, watchlist
    4. Ad-hoc scan      — the old manual scanner, clearly NOT journaled

The brief is produced by swing_agent.py in the scheduled job and is read
here, never computed here. The tab is where you answer; it never acts on
your behalf and never writes a journal row you did not click.

Two dates matter and are both shown: when the brief was generated, and
when the journal was last written. If you decided in chat after the brief
ran, the live state (PE step, heat, open positions) is recomputed from the
journal on every render so the tab never shows a stale step.
"""

from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timezone

import pandas as pd

import swing_journal as sj

BRIEF_DIR = "logs/swing"


# ── Brief loading ───────────────────────────────────────────────────────────

def _brief_from_github() -> dict | None:
    """Latest brief via the GitHub contents API (the app on Streamlit Cloud may
    not have redeployed since the job committed it). Uses the same token as
    storage_backend; returns None when not configured."""
    try:
        import requests
        import storage_backend as sb
        token, repo = sb._cfg("GITHUB_TOKEN"), sb._cfg("GITHUB_REPO")
        if not token or not repo:
            return None
        branch = sb._cfg("GITHUB_BRANCH", "main")
        r = requests.get(f"{sb.GITHUB_API}/repos/{repo}/contents/{BRIEF_DIR}",
                         headers=sb._gh_headers(token), params={"ref": branch}, timeout=20)
        if r.status_code != 200:
            return None
        names = sorted(f["name"] for f in r.json() if f["name"].endswith("_brief.json"))
        if not names:
            return None
        content, _ = sb._gh_get(f"{BRIEF_DIR}/{names[-1]}")
        return json.loads(content) if content else None
    except Exception:
        return None


def _brief_from_disk() -> dict | None:
    files = sorted(glob.glob(os.path.join(BRIEF_DIR, "*_brief.json")))
    if not files:
        return None
    try:
        return json.loads(open(files[-1]).read())
    except Exception:
        return None


def load_latest_brief() -> dict | None:
    a, b = _brief_from_github(), _brief_from_disk()
    if a and b:
        return a if a.get("generated_at", "") >= b.get("generated_at", "") else b
    return a or b


def _age_hours(iso: str | None) -> float | None:
    try:
        return round((datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 3600, 1)
    except Exception:
        return None


# ── Render ──────────────────────────────────────────────────────────────────

def render(st, fetch_ohlcv=None):
    brief = load_latest_brief()
    journal = sj.load()
    cfg = sj.load_config()
    decided = set(zip(journal["ticker"].fillna(""), journal["card_date"].fillna("")))

    t_brief, t_decide, t_journal, t_adhoc = st.tabs(
        ["📄 Today's brief", "✅ Decisions", "📒 Journal & review", "🔎 Ad-hoc scan (not journaled)"])

    # ── live state from the journal (never from the brief) ─────────────────
    regime_key = (brief or {}).get("regime", {}).get("key") if brief else None
    live_pe = sj.pe_step(regime_key, journal)
    live_eq = sj.equity(journal)
    live_heat = sj.heat_used_pct(journal)
    opens = sj.open_positions(journal)

    with t_brief:
        if not brief:
            st.warning("No brief yet. The Swing Desk Brief job writes one at 6:45 PM ET on trading days "
                       "(Actions → Swing Desk Brief → Run workflow to produce one now).")
        else:
            age = _age_hours(brief.get("generated_at"))
            r, x = brief["regime"], brief["exposure"]
            hdr = st.columns([2, 1, 1, 1])
            hdr[0].markdown(f"### Brief for **{brief['date']}**")
            hdr[1].metric("Brief age", f"{age}h" if age is not None else "?")
            hdr[2].metric("Regime", r["key"])
            hdr[3].metric("Size ×", r["size_mult"])
            if age is not None and age > 30:
                st.warning("This brief is more than a trading day old. Read it as context, not as tonight's cards.")
            st.markdown(f"**Long book {r['long_book']} · short book {r['short_book']}** — "
                        + "; ".join(r.get("drivers", [])[:2]))
            if r.get("regime_read"):
                st.info(r["regime_read"])

            you = st.columns(4)
            you[0].metric("PE step (live)", f"{live_pe['step']} → {live_pe['risk_pct']}%",
                          help=live_pe["why"])
            you[1].metric("Equity (live)", f"${live_eq['equity']:,.0f}" if live_eq["equity"] else "unset",
                          f"{live_eq['realized_pnl']:+,.0f} realized")
            you[2].metric("Heat (live)", f"{live_heat['heat_pct']}% / {cfg['heat_cap_pct']}%")
            you[3].metric("Slots open", f"{live_heat['slots_open']} of {cfg['max_positions']}")
            if live_pe["step"] != x.get("step"):
                st.caption(f"The brief was built at step {x.get('step')}; the journal now says step "
                           f"{live_pe['step']}. Sizes on the cards are from the brief — re-run the job to resize.")
            b = brief.get("breadth", {})
            st.caption(f"Breadth proxy: {b.get('pct_above_200')}% above 200-day ({b.get('read')}) · {b.get('source')}")

            if brief.get("refusals"):
                st.error("**Refused:** " + " · ".join(brief["refusals"]))
            if brief.get("unconfirmed_from_prior"):
                st.warning("**Unconfirmed from the previous brief — the desk assumed nothing:** "
                           + ", ".join(f"{p['ticker']} ({p['kind']})" for p in brief["unconfirmed_from_prior"]))

            hg = brief.get("hunting_grounds", {})
            st.markdown("**Hunting grounds** — long: "
                        + (", ".join(f"{s['ticker']} ({s['quadrant']}, {s.get('direction')})" for s in hg.get("long", [])) or "none")
                        + " · short: " + (", ".join(s["ticker"] for s in hg.get("short", [])) or "none")
                        + " · watchlist: " + (", ".join(hg.get("watchlist", [])) or "empty"))
            if brief.get("events", {}).get("blackout"):
                st.error("Event block: " + "; ".join(f"{e['event']} in {e['days_away']}d" for e in brief["events"]["blackout"]))

            st.markdown(f"#### Trade cards ({len(brief.get('cards', []))})")
            if not brief.get("cards"):
                st.info("No card today. That is a valid answer, not a gap.")
            for c in brief.get("cards", []):
                _card(st, c, decided, brief["date"])

            if brief.get("open_positions"):
                st.markdown("#### Open positions — exit triggers")
                for p in brief["open_positions"]:
                    _position(st, p)

            with st.expander(f"Watch ({len(brief.get('watch', []))}) · Not a setup ({len(brief.get('avoid', []))}) · data gaps"):
                for w in brief.get("watch", []):
                    st.markdown(f"- **{w['ticker']}** [{w.get('sector_quadrant')}] — {w['reason']}")
                for a in brief.get("avoid", []):
                    st.markdown(f"- {a['ticker']}: {a['reason']}")
                for g in brief.get("data_gaps", []):
                    st.markdown(f"- ⚠ {g}")
            if brief.get("question_of_the_day"):
                st.markdown("#### Question of the day")
                st.write(brief["question_of_the_day"])

    # ── Decisions ──────────────────────────────────────────────────────────
    with t_decide:
        st.caption("Every button writes one append-only journal row. Nothing here places an order. "
                   "The 6:45 PM job reads this journal to compute your step, heat and open positions.")
        if live_eq["equity"] is None:
            st.error("starting_equity is not set in swing_config.json — the desk cannot size.")

        if brief and brief.get("cards"):
            st.markdown("#### Cards")
            for c in brief["cards"]:
                key = (c["ticker"], brief["date"])
                already = key in decided
                with st.container(border=True):
                    top = st.columns([3, 1])
                    top[0].markdown(f"**{c['ticker']}** · {c['setup']} {c['side']} · {c['confluence']} · "
                                    f"entry {c['entry']} · stop {c['stop']} · {c['shares']} sh"
                                    + ("" if c["entry_permitted"] else f" · *not permitted: {c['entry_block_reason']}*"))
                    if already:
                        row = journal[(journal["ticker"] == c["ticker"]) & (journal["card_date"] == brief["date"])].iloc[-1]
                        top[1].success(f"{row['event']} ({row['source']})")
                        continue
                    with st.form(key=f"card_{c['ticker']}_{brief['date']}", border=False):
                        f = st.columns([1.2, 1, 1, 1, 1])
                        px = f[0].number_input("Fill", value=float(c["entry"]), step=0.01, format="%.2f")
                        sh = f[1].number_input("Shares", value=int(c["shares"] or 0), step=1, min_value=0)
                        note = f[2].text_input("Note", value="")
                        took = f[3].form_submit_button("Took it", type="primary", disabled=not c["entry_permitted"])
                        passed = f[4].form_submit_button("Pass")
                        watch = st.form_submit_button("Watch")
                    if took:
                        try:
                            sj.record_take("tab", c["ticker"], float(px), float(sh), float(c["stop"]),
                                           setup=c["setup"], side=c["side"], planned_entry=float(c["entry"]),
                                           regime=brief["regime"]["key"], confluence=c["confluence"],
                                           trail=c["trail"], card_date=brief["date"], note=note)
                            st.success(f"Journaled TAKE {c['ticker']} {sh} @ {px}, stop {c['stop']}.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Not journaled: {e}")
                    elif passed or watch:
                        try:
                            sj.record_decision("tab", c["ticker"], "PASS" if passed else "WATCH", brief["date"], note)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Not journaled: {e}")
        else:
            st.info("No cards to decide on.")

        st.markdown("#### Open positions")
        if not opens:
            st.info("No open swing positions in the journal.")
        rec_by_ticker = {p["ticker"]: p for p in (brief or {}).get("open_positions", [])}
        for tk, pos in opens.items():
            rec = rec_by_ticker.get(tk)
            with st.container(border=True):
                st.markdown(f"**{tk}** · {pos['setup']} {pos['side']} · {pos['shares']} sh @ {pos['avg_entry']} · "
                            f"stop {pos['stop']} · trail {pos['trail']} · trims {pos['trims']}/3")
                if rec and rec.get("pending_confirmation"):
                    st.warning(f"Desk recommends **{rec['recommendation']}** — {rec['why']}")
                with st.form(key=f"pos_{tk}", border=False):
                    f = st.columns([1.2, 1, 1.2, 1, 1, 1])
                    px = f[0].number_input("Price", value=float(rec["current"]) if rec and rec.get("current") else float(pos["avg_entry"]),
                                           step=0.01, format="%.2f")
                    sh = f[1].number_input("Shares", value=float(pos["shares"]), step=1.0, min_value=0.0,
                                           max_value=float(pos["shares"]))
                    trig = f[2].selectbox("Trigger", ["structural", "trend", "ladder", "thesis", "manual"],
                                          index=["structural", "trend", "ladder", "thesis", "manual"].index(
                                              _trigger_of(rec)) if rec else 4)
                    new_stop = f[3].number_input("New stop", value=float(rec["new_stop"]) if rec and rec.get("new_stop") else float(pos["stop"]),
                                                 step=0.01, format="%.2f")
                    done = f[4].form_submit_button("Exit/Trim", type="primary")
                    tight = f[5].form_submit_button("Tighten")
                    decl = st.form_submit_button("Decline recommendation")
                try:
                    if done:
                        sj.record_exit("tab", tk, float(px), float(sh), trigger=trig, partial=sh < pos["shares"])
                        st.success(f"Journaled {'TRIM' if sh < pos['shares'] else 'EXIT'} {tk} {sh} @ {px} ({trig}).")
                        st.rerun()
                    elif tight:
                        sj.record_tighten("tab", tk, float(new_stop))
                        st.success(f"Journaled TIGHTEN {tk} stop → {new_stop}.")
                        st.rerun()
                    elif decl:
                        sj.record_decision("tab", tk, "DECLINE", (brief or {}).get("date", ""),
                                           note=f"declined {rec['recommendation'] if rec else 'n/a'}")
                        st.rerun()
                except Exception as e:
                    st.error(f"Not journaled: {e}")

        if live_pe["step"] == 0:
            st.markdown("#### Reset")
            st.warning(live_pe["why"])
            if st.button("Acknowledge reset → step 1"):
                sj.record_reset("tab", "acknowledged in tab"); st.rerun()

        st.markdown("#### Watchlist")
        wl = sj.watchlist()
        with st.form("wl_add", border=False):
            f = st.columns([1, 3, 1])
            tk_in = f[0].text_input("Ticker")
            why_in = f[1].text_input("Reason (e.g. 'EP candidate — FDA approval 9/12')")
            if f[2].form_submit_button("Add") and tk_in.strip():
                sj.watchlist_add("tab", tk_in, why_in); st.rerun()
        if wl.empty:
            st.caption("Empty. Anything here is scanned every night alongside the sector constituents; "
                       "it adds coverage, not confluence.")
        else:
            for _, w in wl.iterrows():
                c = st.columns([1, 4, 1])
                c[0].write(f"**{w['ticker']}**"); c[1].write(w.get("reason") or "")
                if c[2].button("Remove", key=f"wl_rm_{w['ticker']}"):
                    sj.watchlist_remove(w["ticker"]); st.rerun()

    # ── Journal & review ───────────────────────────────────────────────────
    with t_journal:
        st.markdown(f"**Progressive Exposure:** step {live_pe['step']} ({live_pe['risk_pct']}%) — {live_pe['why']}")
        st.markdown(f"**Equity:** {live_eq['note']} → **${live_eq['equity']:,.2f}**" if live_eq["equity"] else live_eq["note"])
        ct = sj.closed_trades(journal)
        if not ct.empty:
            st.markdown("#### Closed trades")
            st.dataframe(ct[["ticker", "setup", "side", "regime", "confluence", "opened", "closed",
                             "planned_risk", "realized_pnl", "R", "exit_trigger", "duration_days", "slippage_pct"]],
                         use_container_width=True, hide_index=True)
            st.markdown("#### Expectancy by setup")
            st.dataframe(sj.expectancy_by_setup(None, journal), use_container_width=True, hide_index=True)
            st.caption("`evidence` = no until n ≥ %d per setup. Below that the numbers are numbers, not evidence." % cfg["min_sample_per_setup"])
        else:
            st.info("No closed trades yet. The review populates itself from your first round trip.")
        with st.expander("Raw journal (append-only)"):
            st.dataframe(journal, use_container_width=True, hide_index=True)
        with st.expander("Config"):
            st.json(cfg)

    # ── Ad-hoc scan (unchanged behaviour, explicitly not journaled) ────────
    with t_adhoc:
        st.caption("Evaluates any tickers against every method with the LIVE step/equity/heat from the journal. "
                   "Results are not journaled and do not become cards — add a ticker to the watchlist if you "
                   "want tomorrow's brief to carry it.")
        if fetch_ohlcv is None:
            st.info("Scanner unavailable in this context.")
        else:
            import swing_desk as sd
            import markets_bridge as mb, rotation_bridge as rb
            tickers_in = st.text_input("Tickers", value="XLK, SMH, XLE, XLF, IWM, QQQ")
            tks = [t.strip().upper() for t in tickers_in.split(",") if t.strip()]
            if tks and st.button("Scan", type="primary"):
                mk = mb.read(); rk = (mk.get("regime") or {}).get("key") if mk.get("available") else "transition_ambiguous"
                quads = {}
                try:
                    for s_ in rb.read_summary().get("sectors", []):
                        quads[s_["ticker"]] = s_.get("quadrant")
                except Exception:
                    pass
                with st.spinner("Scanning…"):
                    ohlcv = fetch_ohlcv(tks + ["SPY"], period="2y")
                    bench = ohlcv.get("SPY", pd.DataFrame()).get("Close")
                    res = sd.scan(tks, lambda t: ohlcv.get(t), rk, bench=bench,
                                  equity=float(live_eq["equity"] or 0), pe_step=int(live_pe["step"]),
                                  heat_used_pct=float(live_heat["heat_pct"] or 0))
                    for r_ in res["cards"] + res["avoid"]:
                        r_["sector_quadrant"] = quads.get(r_["ticker"])
                sd.render(st, res)


def _trigger_of(rec: dict | None) -> str:
    if not rec:
        return "manual"
    m = {"EXIT": "structural", "TRIM": "ladder", "TIGHTEN": "trend"}
    t = m.get(rec.get("recommendation"), "manual")
    if rec.get("recommendation") == "EXIT":
        why = (rec.get("why") or "").lower()
        t = "thesis" if "regime" in why or "sector" in why else "trend" if "trend" in why or "falling" in why else "structural"
    return t


def _card(st, c: dict, decided: set, date: str):
    tag = "✅ entry permitted" if c["entry_permitted"] else f"⛔ {c['entry_block_reason']}"
    done = (c["ticker"], date) in decided
    with st.expander(f"{'☑ ' if done else ''}{c['ticker']} — {c['setup']} ({c['side']}) · {c['confluence']} · {tag}",
                     expanded=(c["entry_permitted"] and not done)):
        m = st.columns(4)
        m[0].metric("Entry trigger", c["entry"]); m[1].metric("Stop", f"{c['stop']} ({c['stop_pct']}%)")
        m[2].metric("Shares", c["shares"], f"{c['notional_pct']}% of equity" if c.get("notional_pct") is not None else None)
        m[3].metric("Risk %", c["risk_pct"], f"heat after {c['heat_after']}%")
        legs = c.get("legs", {})
        st.markdown(f"**Legs:** rotation {'✅' if legs.get('rotation') else '❌'} · structure {'✅' if legs.get('structure') else '❌'} "
                    f"· volume {'✅' if legs.get('volume') else '❌'}"
                    + (f" · missing: {', '.join(legs.get('missing', []))}" if legs.get("missing") else ""))
        st.markdown(f"**Targets** 2R {c['targets']['2R']} · 4R {c['targets']['4R']} · 8R {c['targets']['8R']} · **trail** {c['trail']}")
        st.markdown(f"**Sector** {c.get('sector')} [{c.get('sector_quadrant')}] · close {c.get('close')} · ADR {c.get('adr_pct')}%"
                    + (" · from watchlist" if c.get("from_watchlist") else ""))
        st.markdown(f"**Why:** {c['why']}")
        st.markdown(f"**Trail read:** {c.get('trail_why')}")
        st.markdown(f"**Instrument:** {c['instrument']}")
        st.markdown(f"**Invalidated when:** {c['invalidated_when']}")
        st.markdown(f"**Event risk:** {c['event_risk']}")
        for k, lab in (("why_note", "Read"), ("what_would_make_this_wrong", "What would make this wrong"),
                       ("teaching_question", "Question for you")):
            if c.get(k):
                st.info(f"**{lab}:** {c[k]}")
        st.caption("Decide on the ✅ Decisions tab.")


def _position(st, p: dict):
    if p.get("recommendation") == "NO DATA":
        st.warning(f"{p['ticker']}: {p['why']}"); return
    with st.expander(f"{p['ticker']} — {p['recommendation']} · {p['R']}R · day {p['days_held']}",
                     expanded=bool(p.get("pending_confirmation"))):
        st.markdown(f"{p['setup']} {p['side']} · entry {p['entry']} · stop {p['stop']} · now {p['current']} · trail {p['trail']}")
        for k, v in p["triggers"].items():
            st.markdown(f"- **{k}**: {v}")
        st.markdown(f"→ {p['why']}")
        if p.get("trigger_note"):
            st.info(p["trigger_note"])
        if p.get("decline_consequence"):
            st.warning(f"If you decline: {p['decline_consequence']}")
