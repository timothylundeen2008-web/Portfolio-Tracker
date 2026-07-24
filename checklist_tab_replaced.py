"""
checklist_tab.py  (v1 — July 2026)
──────────────────────────────────────────────────────────────────────────────
Renders the v5 Dashboard Analysis Checklist as an interactive, self-logging tab.

WHAT IT DOES
  - Renders every Daily and Weekly step from checklist_data.py (the canonical
    source — this module contains NO checklist text of its own, by design)
  - Auto-fills every item that has a live data source, badged 🟢 AUTO
  - Presents an input widget for every item that does not, badged 🟡 MANUAL,
    with the specific reason it can't be automated shown inline
  - Evaluates threshold alerts (HY OAS > 3.50, VIX > 30, heat > 15%, etc.)
  - Writes one row per completed run to a log, and shows history/streaks
  - Shows the "Why" for every item — the education is not a separate tab,
    it sits next to the thing it explains

⚠ STORAGE — READ THIS BEFORE RELYING ON THE LOG
  Streamlit Community Cloud has an EPHEMERAL filesystem. Files written to disk
  are lost on redeploy, on container restart, and when the app sleeps after
  inactivity. Nothing in this codebase has ever persisted state (every existing
  to_csv is a download button), so this is the first module that needs to.

  Strategy used here, in order of durability:
    1. st.session_state          — survives reruns, dies with the session
    2. Local CSV                 — survives reruns, dies on redeploy/sleep
    3. ⭐ Download the log        — THE durable path on Streamlit Cloud
    4. Upload to restore         — reload a previously downloaded log
    5. GitHub commit-back        — optional, genuinely durable (see GAPS.md G0)

  The UI nags if the log has unsaved rows. Treat the download button as part
  of the weekly routine until a real backend is wired.
"""

from __future__ import annotations

import io
import os
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from checklist_data import (
    DAILY_STEPS, WEEKLY_STEPS, DAILY_ACTION_RULE, all_items, gap_report,
)

# Gap-closing modules. Each import is guarded: a missing or failing module must
# degrade THAT item to "unavailable", never take down the tab. Availability is
# surfaced in the Data-gaps sub-tab so a silent absence is impossible.
_SRC = {}
try:
    import storage_backend as _storage; _SRC["storage"] = True
except Exception as e:
    _storage = None; _SRC["storage"] = f"unavailable: {e}"
try:
    import position_ledger as _ledger; _SRC["ledger"] = True
except Exception as e:
    _ledger = None; _SRC["ledger"] = f"unavailable: {e}"
try:
    import bls_client as _bls; _SRC["bls"] = True
except Exception as e:
    _bls = None; _SRC["bls"] = f"unavailable: {e}"
try:
    import treasury_data as _tsy; _SRC["treasury"] = True
except Exception as e:
    _tsy = None; _SRC["treasury"] = f"unavailable: {e}"
try:
    import event_calendar as _cal; _SRC["calendar"] = True
except Exception as e:
    _cal = None; _SRC["calendar"] = f"unavailable: {e}"
try:
    import rotation_bridge as _rot; _SRC["rotation"] = True
except Exception as e:
    _rot = None; _SRC["rotation"] = f"unavailable: {e}"

LOG_PATH = os.environ.get("CHECKLIST_LOG", "data/checklist_log.csv")

# FOMC meeting dates — VERIFY against federalreserve.gov each January and
# update. Hardcoded because the schedule is published a year ahead; wrong
# dates here are worse than none, so the UI states the source and vintage.
FOMC_DATES_2026 = [
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
]
FOMC_ASOF = "2026-01-15"


# ─────────────────────────────────────────────────────────────────────────────
#  AUTO-FETCH
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_market_extras() -> dict:
    """VIX, VIX3M and DXY — the pieces the classifier doesn't already return."""
    out = {"vix": None, "vix3m": None, "vix_term_spread": None, "dxy_chg_20d": None}
    try:
        import yfinance as yf
        raw = yf.download(["^VIX", "^VIX3M", "DX-Y.NYB"], period="3mo",
                          interval="1d", auto_adjust=True, progress=False,
                          threads=True, timeout=30)
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw

        if "^VIX" in close and close["^VIX"].notna().any():
            out["vix"] = round(float(close["^VIX"].dropna().iloc[-1]), 2)
        if "^VIX3M" in close and close["^VIX3M"].notna().any():
            out["vix3m"] = round(float(close["^VIX3M"].dropna().iloc[-1]), 2)
        if out["vix"] is not None and out["vix3m"] is not None:
            # Positive = backwardation = spot fear above 3-month = late-crisis tell
            out["vix_term_spread"] = round(out["vix"] - out["vix3m"], 2)
        if "DX-Y.NYB" in close:
            d = close["DX-Y.NYB"].dropna()
            if len(d) >= 21:
                out["dxy_chg_20d"] = round(float(d.iloc[-1] / d.iloc[-21] - 1) * 100, 2)
    except Exception as e:
        print(f"[checklist] market extras failed: {e}")
    return out


def _cfg_bls_key() -> str:
    """BLS v1 works with no key (3y history, enough for the cross-check);
    a free v2 key raises the limits."""
    try:
        if "BLS_API_KEY" in st.secrets:
            return str(st.secrets["BLS_API_KEY"])
    except Exception:
        pass
    return os.environ.get("BLS_API_KEY", "")


def _safe_assessment(fred_key: str) -> dict:
    """full_assessment() with every failure mode caught — a dead FRED key must
    degrade the tab to manual entry, never crash the whole app tab."""
    try:
        from regime_classifier import full_assessment
        return full_assessment(fred_api_key=fred_key) or {}
    except Exception as e:
        print(f"[checklist] full_assessment failed: {e}")
        return {}


def autofetch(fred_key: str, live_weights: dict | None = None) -> dict:
    """
    Collect every auto-fillable field. Missing values are None, never guessed —
    a None renders as an explicit 'unavailable' badge so a gap is visible
    rather than silently absent.
    """
    a = _safe_assessment(fred_key)
    sig = a.get("signals", {}) or {}
    regime = a.get("regime", {}) or {}
    score = a.get("repression", {}) or a.get("score", {}) or {}
    kmlm = a.get("kmlm", {}) or {}
    extras = _fetch_market_extras()

    vals: dict = {
        "hy_oas":           sig.get("hy_oas"),
        "hy_oas_mom_2w":    sig.get("hy_oas_mom_2w"),
        "long_real_yield":  sig.get("long_real_yield"),
        "long_real_mom_3m": sig.get("long_real_mom_3m"),
        "spread_2s10s":     sig.get("spread_2s10s"),
        "short_real_rate":  sig.get("short_real_rate"),
        "cpi_yoy":          sig.get("cpi_yoy"),
        "eff_funds":        sig.get("eff_funds"),
        "regime_key":       regime.get("key"),
        "regime_drivers":   "; ".join(regime.get("drivers", []) or []),
        "fed_flag":         (a.get("fed_flag") or {}).get("state"),
        "repression_score": score.get("score"),
        "repression_band":  score.get("band"),
        "repression_missing": ", ".join(score.get("missing", []) or []) or "none",
        "kmlm_stance":      kmlm.get("stance"),
        "kmlm_score":       kmlm.get("score"),
        "gold_gate":        a.get("gold_gate"),
    }
    vals.update(extras)

    # Degraded-input flag (Weekly Step 1)
    drivers = regime.get("drivers", []) or []
    vals["degraded"] = "YES — " + "; ".join(d for d in drivers if "unavailable" in d.lower()) \
        if any("unavailable" in str(d).lower() for d in drivers) else "No — inputs complete"

    # Regime transition vs last logged run (Weekly Step 1)
    prev = _last_logged_value("regime_key")
    if prev and vals.get("regime_key"):
        vals["regime_changed"] = (
            f"⚠ CHANGED: {prev} → {vals['regime_key']} — two-close confirmation required, "
            f"execute cuts→hedges→adds over 2–5 sessions"
            if prev != vals["regime_key"] else f"Unchanged ({prev})")
    else:
        vals["regime_changed"] = "No prior log to compare"

    # KMLM overlay-vs-signal conflict (Weekly Step 4)
    try:
        from regime_classifier import target_weights
        tgt = target_weights(vals.get("regime_key") or "neutral").get("KMLM")
        stance = (vals.get("kmlm_stance") or "").upper()
        if tgt is not None and stance:
            overlay_cuts = tgt <= 4
            sig_holds = "HOLD" in stance or "INCREASE" in stance
            vals["kmlm_conflict"] = (
                f"⚠ CONFLICT: overlay target {tgt}% vs live signal {stance} — "
                f"SLOWER move governs; log the disagreement"
                if overlay_cuts and sig_holds else
                f"Aligned (target {tgt}%, signal {stance})")
    except Exception:
        vals["kmlm_conflict"] = None

    # Drift bands (Weekly Step 8) — uses the app's current weights as a proxy
    # for live holdings, which is NOT the same thing. See GAPS.md G1.
    if live_weights:
        try:
            from regime_classifier import target_weights
            tgt = target_weights(vals.get("regime_key") or "neutral")
            breaches = []
            for tk, t in tgt.items():
                live = live_weights.get(tk)
                if live is None or t == 0:
                    continue
                if abs(live - t) / t > 0.20:
                    breaches.append(f"{tk} {live:.0f}% vs {t:.0f}%")
            vals["drift_summary"] = ("BREACH: " + "; ".join(breaches)) if breaches \
                else "All sleeves within ±20% relative band"
        except Exception:
            vals["drift_summary"] = None

    # ── G1 position ledger: stops, heat, options, real drift ──
    if _ledger:
        try:
            ev = _ledger.evaluate_positions()
            pos = ev.get("positions")
            if pos is not None and not pos.empty:
                hit = (pos["status"] == "STOP HIT").sum()
                near = (pos["status"] == "WITHIN 1 ATR").sum()
                vals["stop_status"] = ("🚨 " + f"{hit} STOP HIT — exit now" if hit else
                                       f"⚠ {near} within 1 ATR" if near else
                                       f"OK — {len(pos)} positions, none near stop")
                vals["heat_pct"] = ev.get("heat_pct")
                vals["ledger_alerts"] = ev.get("alerts", [])
            else:
                vals["stop_status"] = "Ledger empty — add positions to enable"
            opt = _ledger.check_options_rules()
            acts = opt.get("actions", [])
            vals["options_status"] = (f"⚠ {len(acts)} rule trigger(s)" if acts
                                      else opt.get("message", "no options"))
            if live_weights is None:
                try:
                    from regime_classifier import target_weights
                    dr = _ledger.drift_vs_targets(
                        target_weights(vals.get("regime_key") or "neutral"))
                    if dr.get("available"):
                        vals["drift_summary"] = dr["message"]
                except Exception:
                    pass
        except Exception as e:
            print(f"[checklist] ledger failed: {e}")

    # ── G6 BLS CPI cross-check ──
    if _bls:
        try:
            cc = _bls.cross_check(vals.get("cpi_yoy"), _cfg_bls_key())
            vals["cpi_crosscheck"] = (
                f"✅ {cc['status']} — dashboard {cc.get('dashboard_yoy')}% vs BLS "
                f"{cc.get('bls_yoy')}%" if cc["status"] == "MATCH" else
                f"🚨 {cc['status']} — dashboard {cc.get('dashboard_yoy')}% vs BLS "
                f"{cc.get('bls_yoy')}% ({cc.get('difference_pp'):+}pp)"
                if cc["status"] == "MISMATCH" else f"{cc['status']}")
            vals["cpi_crosscheck_detail"] = cc.get("action")
        except Exception as e:
            print(f"[checklist] BLS failed: {e}")

    # ── G2/G3 Treasury auctions + curve regime ──
    if _tsy:
        try:
            a = _tsy.auction_demand("10-Year")
            vals["auction_btc"] = (f"{a['latest_btc']} ({a['level']}, {a['trend']})"
                                   if a.get("available") else None)
            vals["auction_detail"] = a.get("message")
        except Exception as e:
            print(f"[checklist] auctions failed: {e}")
        try:
            c = _tsy.curve_signal()
            if c.get("available"):
                vals["curve_regime"] = (f"{c['regime']}"
                                        + (" 🚨" if c["urgency"] == "HIGH" else ""))
                vals["curve_detail"] = c.get("note")
        except Exception as e:
            print(f"[checklist] curve failed: {e}")

    # ── G5 event calendar ──
    if _cal:
        try:
            holdings = list(live_weights.keys()) if live_weights else None
            ec = _cal.event_check(holdings)
            vals["event_clear"] = ("✅ Clear for entry" if ec["clear_for_entry"]
                                   else "🚫 NO NEW ENTRIES")
            vals["event_detail"] = ec.get("message")
            vals["event_upcoming"] = ec.get("upcoming", [])
        except Exception as e:
            print(f"[checklist] calendar failed: {e}")

    # ── G4/G7 rotation bridge ──
    if _rot:
        try:
            rs = _rot.read_summary()
            if rs.get("available") and not rs.get("very_stale"):
                secs = rs.get("sectors", [])
                if secs:
                    top = secs[0]
                    vals["rot_top_accum"] = (f"{top.get('ticker')} "
                                             f"accum {top.get('accumulation_score')}")
                    st_names = [x.get("ticker") for x in secs
                                if "Stealth" in str(x.get("stealth_label", ""))][:3]
                    vals["rot_stealth"] = ", ".join(st_names) if st_names else "none flagged"
                    vals["rot_quadrants"] = f"{len(secs)} sectors published"
                divs = [d for d in rs.get("flow_divergences", []) if d.get("divergence")]
                vals["rot_flow_div"] = (f"⚠ {len(divs)} divergence(s): "
                                        + ", ".join(d["ticker"] for d in divs[:4])
                                        if divs else "no price/flow divergence")
                cot = rs.get("cot", [])
                extremes = [c for c in cot if "crowded" in str(c.get("flag", "")).lower()]
                vals["rot_cot"] = (f"⚠ {len(extremes)} at positioning extreme"
                                   if extremes else f"{len(cot)} contracts, none extreme")
                br = rs.get("breadth", [])
                conc = [b["etf"] for b in br if b.get("signal_quality") == "CONCENTRATED"]
                vals["rot_breadth"] = (f"⚠ CONCENTRATED: {', '.join(conc[:4])}"
                                       if conc else f"{len(br)} sectors, none concentrated")
                gold = [x for x in secs if x.get("ticker") in ("GLD", "GDX", "RING")]
                vals["rot_gold_rrg"] = (f"{gold[0].get('quadrant', 'n/a')}" if gold
                                        else "gold not in published set")
            vals["rot_staleness"] = rs.get("message")
        except Exception as e:
            print(f"[checklist] rotation bridge failed: {e}")

    # Upcoming FOMC (Daily Step 8 assist)
    try:
        today = date.today()
        nxt = [d for d in (datetime.strptime(x, "%Y-%m-%d").date() for x in FOMC_DATES_2026)
               if d >= today]
        if nxt:
            days = (nxt[0] - today).days
            vals["next_fomc"] = f"{nxt[0].isoformat()} ({days}d)" + (" ⚠ BLACKOUT" if days <= 2 else "")
    except Exception:
        vals["next_fomc"] = None

    return vals


# ─────────────────────────────────────────────────────────────────────────────
#  LOG PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

def load_log() -> pd.DataFrame:
    """Read through storage_backend so the log survives redeploys when GitHub
    credentials are configured. Falls back to session state otherwise."""
    if _storage:
        try:
            df = _storage.read_df("checklist_log.csv")
            st.session_state["checklist_log"] = df
            return df
        except Exception as e:
            print(f"[checklist] storage read failed: {e}")
    return st.session_state.get("checklist_log", pd.DataFrame())


def append_log(row: dict) -> pd.DataFrame:
    """
    One row per cadence per day — re-running a checklist overwrites rather than
    duplicating, so an interrupted run can simply be redone.

    Durability is reported honestly: if the write did not reach a durable
    backend, the UI nags to download. Silently losing a log is the failure this
    whole storage layer exists to prevent.
    """
    if _storage:
        try:
            df = _storage.append_row("checklist_log.csv", row,
                                     dedupe_on=["date", "cadence"])
            st.session_state["checklist_log"] = df
            st.session_state["log_unsaved"] = not _storage.backend_status()["durable"]
            return df
        except Exception as e:
            print(f"[checklist] storage append failed: {e}")

    df = load_log()
    if not df.empty and {"date", "cadence"}.issubset(df.columns):
        df = df[~((df["date"] == row["date"]) & (df["cadence"] == row["cadence"]))]
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True).sort_values("date")
    st.session_state["checklist_log"] = df
    st.session_state["log_unsaved"] = True
    return df


def _last_logged_value(field: str):
    df = load_log()
    if df.empty or field not in df.columns:
        return None
    s = df[field].dropna()
    return s.iloc[-1] if len(s) else None


def _streak(cadence: str) -> int:
    """Consecutive days/weeks completed, counting back from today."""
    df = load_log()
    if df.empty or "cadence" not in df.columns:
        return 0
    d = df[df["cadence"] == cadence]["date"].dropna().sort_values(ascending=False)
    if d.empty:
        return 0
    step = timedelta(days=1) if cadence == "daily" else timedelta(days=7)
    dates = [datetime.strptime(x, "%Y-%m-%d").date() for x in d]
    streak, cursor = 0, date.today()
    for dt in dates:
        if abs((cursor - dt).days) <= step.days:
            streak += 1
            cursor = dt - step
        else:
            break
    return streak


# ─────────────────────────────────────────────────────────────────────────────
#  ALERTS
# ─────────────────────────────────────────────────────────────────────────────

def _eval_alert(item: dict, value) -> tuple[str, str] | None:
    """Returns (level, message) where level is 'alarm' or 'warn'."""
    spec = item.get("alert")
    if not spec or value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    for level in ("alarm", "warn"):
        if level not in spec:
            continue
        op, threshold = spec[level]
        hit = (v > threshold) if op == "gt" else (v < threshold)
        if hit:
            return (level, f"{v:g} {'>' if op == 'gt' else '<'} {threshold:g}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  RENDER
# ─────────────────────────────────────────────────────────────────────────────

_BADGE = {
    "auto":        ("🟢", "AUTO", "#1D9E75"),
    "manual_num":  ("🟡", "MANUAL", "#D9A441"),
    "manual_bool": ("🟡", "MANUAL", "#D9A441"),
    "manual_text": ("🟡", "MANUAL", "#D9A441"),
    "action":      ("🔵", "ACTION", "#378ADD"),
}


def _render_item(item: dict, vals: dict, responses: dict, key_prefix: str):
    kind = item["kind"]
    icon, label, color = _BADGE.get(kind, ("⚪", "—", "#888"))
    wkey = f"{key_prefix}_{item['id']}"

    c1, c2 = st.columns([7, 3])

    with c1:
        st.markdown(
            f"<span style='font-size:10px;color:{color};font-weight:700'>{icon} {label}</span>"
            f"<span style='font-size:13px;color:var(--text-color);margin-left:6px'>{item['text']}</span>",
            unsafe_allow_html=True)

    with c2:
        if kind == "auto":
            v = vals.get(item.get("field"))
            if v is None:
                st.markdown("<span style='color:#D85A30;font-size:12px'>⚠ unavailable</span>",
                            unsafe_allow_html=True)
                responses[item["id"]] = None
            else:
                unit = item.get("unit", "")
                disp = f"{v:g}{unit}" if isinstance(v, (int, float)) else str(v)
                alert = _eval_alert(item, v)
                col = "#D85A30" if alert and alert[0] == "alarm" else \
                      "#D9A441" if alert else "#1D9E75"
                st.markdown(
                    f"<div style='font-size:16px;font-weight:700;color:{col}'>{disp}</div>",
                    unsafe_allow_html=True)
                responses[item["id"]] = v
                if alert:
                    st.markdown(
                        f"<span style='font-size:10px;color:{col}'>"
                        f"{'🚨 ALARM' if alert[0]=='alarm' else '⚠ WARN'} {alert[1]}</span>",
                        unsafe_allow_html=True)
        elif kind == "manual_num":
            responses[item["id"]] = st.number_input(
                item.get("unit", "value"), key=wkey, value=None, step=0.01,
                format="%.2f", label_visibility="collapsed",
                placeholder=item.get("unit") or "enter value")
        elif kind == "manual_bool":
            responses[item["id"]] = st.checkbox("Confirmed", key=wkey)
        else:  # manual_text
            responses[item["id"]] = st.text_input(
                "note", key=wkey, label_visibility="collapsed",
                placeholder="record observation…")

    with st.expander("Why this check exists", expanded=False):
        st.markdown(item["why"])
        if item.get("gap"):
            st.warning(f"**Data gap:** {item['gap']}", icon="⚠️")


def _render_cadence(cadence: str, vals: dict, fred_key: str):
    steps = DAILY_STEPS if cadence == "daily" else WEEKLY_STEPS
    responses: dict = {}

    streak = _streak(cadence)
    c1, c2, c3 = st.columns(3)
    c1.metric("Streak", f"{streak} {'days' if cadence=='daily' else 'weeks'}")
    items = all_items(cadence)
    n_auto = sum(1 for i in items if i["kind"] == "auto")
    c2.metric("Auto-filled", f"{n_auto}/{len(items)}")
    filled = sum(1 for i in items if i["kind"] == "auto" and vals.get(i.get("field")) is not None)
    c3.metric("Live data", f"{filled}/{n_auto}",
              help="Auto items whose data source actually returned a value this run")

    if vals.get("next_fomc"):
        st.info(f"**Next FOMC:** {vals['next_fomc']}  ·  schedule as-of {FOMC_ASOF} — "
                f"verify annually at federalreserve.gov", icon="📅")

    st.markdown("---")

    for step in steps:
        tier = step.get("tier", "—")
        tier_badge = (f"<span style='font-size:10px;background:rgba(55,138,221,0.2);"
                      f"color:#7FB3E8;padding:2px 6px;border-radius:4px;margin-left:8px'>"
                      f"Tier {tier}</span>") if tier != "—" else ""
        st.markdown(
            f"<div style='font-size:15px;font-weight:700;color:var(--text-color);"
            f"margin-top:14px'>{step['id'].upper()} — {step['title']}{tier_badge}</div>",
            unsafe_allow_html=True)
        for item in step["items"]:
            _render_item(item, vals, responses, cadence)
        st.markdown("<hr style='margin:8px 0;opacity:0.15'>", unsafe_allow_html=True)

    if cadence == "daily":
        st.error(f"**DAILY ACTION RULE** — {DAILY_ACTION_RULE}", icon="🛑")

    # ── Commit the run ──
    st.markdown("### Log this run")
    notes = st.text_area("Free-form notes (what you saw, what you're watching)",
                         key=f"{cadence}_notes", height=80)

    if st.button(f"✅ Log {cadence} run for {date.today().isoformat()}",
                 key=f"{cadence}_commit", type="primary"):
        row = {"date": date.today().isoformat(),
               "cadence": cadence,
               "logged_at": datetime.now().isoformat(timespec="seconds"),
               "notes": notes}
        row.update({k: v for k, v in vals.items() if not isinstance(v, (list, dict))})
        row.update({f"resp_{k}": v for k, v in responses.items()})
        append_log(row)
        st.success(f"Logged. Streak: {_streak(cadence)}. "
                   f"⚠ Download the log below — Streamlit Cloud will not keep it.")


def render_checklist_tab(fred_key: str = "", live_weights: dict | None = None):
    """Entry point. Call this inside a `with tabN:` block in app.py."""
    st.markdown("## ✅ Operating Checklist (v5)")
    st.caption(
        "The v5 checklist rendered from its canonical source, auto-filled where a "
        "live data source exists and marked MANUAL where none does. Every item "
        "carries its 'Why' — the reasoning is the point, the checkbox is just the "
        "receipt."
    )

    # Storage warning — the single most important operational caveat
    if st.session_state.get("log_unsaved"):
        st.warning(
            "**Unsaved log rows.** This app's filesystem is ephemeral on Streamlit "
            "Cloud — rows are lost on redeploy, restart, or sleep. Download the log "
            "below to keep it.", icon="💾")

    with st.spinner("Fetching live data…"):
        vals = autofetch(fred_key, live_weights)

    tab_d, tab_w, tab_pos, tab_log, tab_gaps = st.tabs(
        ["📅 Daily (~10 min)", "🗓️ Weekly (45–60 min)", "💼 Positions",
         "📖 Log & history", "🔌 Data sources"])

    with tab_d:
        _render_cadence("daily", vals, fred_key)
    with tab_w:
        st.info("Run this when you cannot act on impulse — weekend, markets closed. "
                "Work strictly top-down: regime first, rotation second, positions last. "
                "Reversing the order is how a good chart talks you out of a bad regime.",
                icon="🧭")
        _render_cadence("weekly", vals, fred_key)

    with tab_pos:
        _render_positions_tab()

    with tab_log:
        _render_log_tab()

    with tab_gaps:
        _render_gaps_tab()


def _render_positions_tab():
    """
    The ledger UI. Without this, five checklist items stay dark: stop checks,
    options mechanics, portfolio heat, weekly position review, and TRUE drift
    bands (as opposed to slider drift, which is zero by construction).
    """
    st.markdown("### Position ledger")
    if not _ledger:
        st.error("position_ledger.py not found.", icon="🚨")
        return

    st.caption(
        "Heat, stop proximity in ATR units, and real drift bands all compute from "
        "this. An empty ledger is why those checks read 'unavailable'."
    )

    try:
        ev = _ledger.evaluate_positions()
    except Exception as e:
        st.error(f"Could not evaluate positions: {e}")
        return

    for a in ev.get("alerts", []):
        (st.error if "🚨" in a else st.warning)(a)

    df = ev.get("positions")
    if df is not None and not df.empty:
        c1, c2, c3 = st.columns(3)
        c1.metric("Positions", len(df))
        heat = ev.get("heat_pct")
        c2.metric("Portfolio heat", f"{heat:.1f}%" if heat is not None else "—",
                  delta=f"cap {_ledger.HEAT_CAP_PCT}%",
                  delta_color="inverse" if heat and heat > _ledger.HEAT_CAP_PCT else "normal")
        c3.metric("Equity", f"${ev.get('equity', 0):,.0f}")
        st.dataframe(df, use_container_width=True, height=260)
        with st.expander("Invalidation sentences — Weekly Step 7"):
            for _, r in df.iterrows():
                st.markdown(f"**{r['ticker']}** — {r['invalidation'] or '⚠️ MISSING'}")
            st.caption("A position without a written invalidation condition can never "
                       "be wrong, which means it can never be managed.")
    else:
        st.info("Ledger is empty.", icon="📭")

    st.markdown("---")
    ca, cb = st.columns(2)

    with ca:
        st.markdown("#### Add / update position")
        tk = st.text_input("Ticker", key="pl_tk").upper()
        sh = st.number_input("Shares", key="pl_sh", value=0.0, step=1.0)
        ep = st.number_input("Entry price", key="pl_ep", value=0.0, step=0.01, format="%.2f")
        sp = st.number_input("Stop", key="pl_sp", value=0.0, step=0.01, format="%.2f")
        sl = st.text_input("Sleeve (optional)", key="pl_sl")
        inv = st.text_area("This position is invalidated when…", key="pl_inv", height=70)
        if st.button("Add position", key="pl_add", type="primary"):
            if not tk or sh == 0 or ep <= 0:
                st.error("Ticker, shares, and entry price are required.")
            else:
                r = _ledger.add_position(tk, sh, ep, sp, inv, sleeve=sl)
                (st.success if r["ok"] else st.error)(
                    f"Added {tk}." if r["ok"] else r["error"])

    with cb:
        st.markdown("#### Trail a stop")
        st.caption("Stops trail UP only — lowering is refused, by design.")
        if df is not None and not df.empty:
            t2 = st.selectbox("Position", df["ticker"].tolist(), key="pl_t2")
            ns = st.number_input("New stop", key="pl_ns", value=0.0, step=0.01, format="%.2f")
            if st.button("Update stop", key="pl_us"):
                r = _ledger.update_stop(t2, ns)
                (st.success if r["ok"] else st.error)(
                    f"{t2}: {r['old_stop']} → {r['new_stop']}" if r["ok"] else r["error"])
            st.markdown("#### Close")
            t3 = st.selectbox("Close position", df["ticker"].tolist(), key="pl_t3")
            if st.button("Close", key="pl_close"):
                r = _ledger.close_position(t3)
                (st.success if r["ok"] else st.error)(
                    f"Closed {t3}." if r["ok"] else r["error"])
        else:
            st.caption("Add a position first.")

    st.markdown("---")
    st.markdown("#### Options book")
    try:
        opt = _ledger.check_options_rules()
        for a in opt.get("actions", []):
            (st.error if "🚨" in a else st.warning)(a)
        if not opt["table"].empty:
            st.dataframe(opt["table"], use_container_width=True, height=180)
        else:
            st.caption("No options logged.")
    except Exception as e:
        st.caption(f"Options check unavailable: {e}")

    with st.expander("Add option position"):
        o1, o2, o3 = st.columns(3)
        otk = o1.text_input("Ticker", key="op_tk").upper()
        ostr = o1.text_input("Strategy", key="op_st", placeholder="short put")
        oexp = o2.text_input("Expiry (YYYY-MM-DD)", key="op_ex")
        ostk = o2.number_input("Strike", key="op_sk", value=0.0, step=1.0)
        octr = o3.number_input("Contracts", key="op_ct", value=1, step=1)
        ocr = o3.number_input("Credit received", key="op_cr", value=0.0, step=0.01, format="%.2f")
        if st.button("Add option", key="op_add"):
            if otk and oexp:
                _ledger.add_option(otk, ostr, oexp, ostk, octr, ocr)
                st.success(f"Added {otk} {ostk} {oexp}.")
            else:
                st.error("Ticker and expiry are required.")


def _render_log_tab():
    st.markdown("### Log history")
    df = load_log()

    if df.empty:
        st.info("No entries yet. Complete a daily or weekly run to start the log.",
                icon="📭")
    else:
        st.caption(f"{len(df)} entries · "
                   f"{len(df[df.cadence=='daily']) if 'cadence' in df else 0} daily · "
                   f"{len(df[df.cadence=='weekly']) if 'cadence' in df else 0} weekly")
        show = ["date", "cadence", "regime_key", "fed_flag", "repression_score",
                "hy_oas", "vix", "long_real_yield", "short_real_rate", "notes"]
        st.dataframe(df[[c for c in show if c in df.columns]].sort_values(
            "date", ascending=False), use_container_width=True, height=320)

        # Trend of the daily numbers — the whole point of logging them
        daily = df[df["cadence"] == "daily"] if "cadence" in df else pd.DataFrame()
        if len(daily) >= 3:
            st.markdown("#### Daily series trend")
            plot_cols = [c for c in ("hy_oas", "vix", "long_real_yield", "spread_2s10s")
                         if c in daily.columns and daily[c].notna().sum() >= 3]
            if plot_cols:
                chart = daily.set_index("date")[plot_cols].apply(pd.to_numeric, errors="coerce")
                st.line_chart(chart, height=220)
                st.caption("A single reading means nothing; the trend against your own "
                           "record is the signal. This is the same logic behind the CPI "
                           "cross-check — eight months of logged entries would have shown "
                           "that figure diverging from BLS every single week.")

    st.markdown("---")
    st.markdown("### Storage durability")
    if _storage:
        stt = _storage.backend_status()
        if stt["durable"]:
            st.success(f"**Durable — {stt['backend']}.** {stt['detail']}", icon="🔒")
        else:
            st.warning(f"**NOT durable — {stt['backend']}.** {stt['detail']}", icon="⚠️")
            with st.expander("How to make storage durable (2 minutes)"):
                st.markdown(
                    "1. Create a **fine-grained** GitHub PAT scoped to this repo only, "
                    "with **Contents: read and write** (nothing else).\n"
                    "2. Add to Streamlit secrets:\n"
                    "```toml\nGITHUB_TOKEN = \"github_pat_...\"\n"
                    "GITHUB_REPO = \"you/all-weather-dashboard\"\n"
                    "GITHUB_BRANCH = \"main\"\n```\n"
                    "3. Reboot the app, then run the storage self-test below.\n\n"
                    "The log then commits to your repo — durable, versioned, and "
                    "diffable, so you can see exactly what changed each week.")
        if st.button("🔍 Run storage self-test", key="storage_selftest"):
            with st.spinner("Testing write → read round-trip…"):
                r = _storage.selftest()
            (st.success if r["roundtrip_ok"] else st.error)(r["message"])
            st.json(r)
    else:
        st.error("storage_backend.py not found — the log lives in session state "
                 "only and dies when this session ends.", icon="🚨")
    st.caption(
        "Downloading remains a good habit regardless. On Streamlit Community Cloud "
        "without GitHub credentials it is the ONLY durable path — the filesystem is "
        "wiped on redeploy, restart, and sleep."
    )
    c1, c2 = st.columns(2)
    with c1:
        if not df.empty:
            st.download_button("⬇️ Download log (CSV)", df.to_csv(index=False),
                               f"checklist_log_{date.today().isoformat()}.csv",
                               "text/csv", type="primary", use_container_width=True)
            st.session_state["log_unsaved"] = False
    with c2:
        up = st.file_uploader("⬆️ Restore a downloaded log", type="csv",
                              label_visibility="collapsed")
        if up is not None:
            try:
                restored = pd.read_csv(up)
                existing = load_log()
                merged = (pd.concat([existing, restored], ignore_index=True)
                          .drop_duplicates(subset=["date", "cadence"], keep="last")
                          .sort_values("date"))
                st.session_state["checklist_log"] = merged
                st.success(f"Restored — {len(merged)} entries after merge.")
            except Exception as e:
                st.error(f"Could not read that file: {e}")


def _render_gaps_tab():
    st.markdown("### Data sources & coverage")
    st.caption("Computed from the checklist itself, not maintained separately — "
               "so it cannot drift out of sync with the actual items.")

    rep = gap_report()
    c1, c2 = st.columns(2)
    for col, cad in ((c1, "daily"), (c2, "weekly")):
        d = rep[cad]
        col.metric(f"{cad.title()} auto-coverage", f"{d['auto_pct']}%",
                   f"{d['auto']} of {d['total']} items")

    st.markdown("#### Module availability")
    rows = []
    labels = {"storage": "storage_backend (G0 — durable log)",
              "ledger": "position_ledger (G1 — stops, heat, drift)",
              "bls": "bls_client (G6 — CPI cross-check)",
              "treasury": "treasury_data (G2/G3 — auctions, curve)",
              "calendar": "event_calendar (G5 — event blackouts)",
              "rotation": "rotation_bridge (G4/G7 — flow, COT, breadth)"}
    for k, label in labels.items():
        v = _SRC.get(k, "not imported")
        rows.append({"module": label,
                     "status": "✅ loaded" if v is True else f"❌ {v}"})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if _rot:
        try:
            rs = _rot.read_summary()
            (st.success if rs.get("available") and not rs.get("stale")
             else st.warning)(f"Rotation bridge: {rs.get('message')}")
            cs = _rot.cot_status()
            if not cs["ok"]:
                st.warning(f"COT: {cs['message']}", icon="📊")
        except Exception:
            pass

    st.markdown("---")
    st.markdown(
        "**What remains manual is judgment, not missing data.** The eight "
        "remaining weekly items are: flagging counter-clockwise rotation, scoring "
        "the confluence test, deciding how to express a CONCENTRATED signal, "
        "placing positions on the valuation matrix, writing invalidation "
        "sentences, confirming a rebalance trigger, running the stress tab, and "
        "naming what would change your mind.\n\n"
        "Those should stay manual. Automating them would be automating the "
        "decision itself, which is the opposite of what this framework is for — "
        "the machine assembles evidence, you decide."
    )

    st.markdown("#### One-time setup checks")
    b1, b2 = st.columns(2)
    with b1:
        if _bls and st.button("Test BLS connection", key="t_bls"):
            with st.spinner("Contacting api.bls.gov…"):
                r = _bls.selftest(_cfg_bls_key())
            (st.success if r["ok"] else st.error)(r["message"])
    with b2:
        if _tsy and st.button("Test Treasury endpoints", key="t_tsy"):
            with st.spinner("Contacting TreasuryDirect + FRED…"):
                r = _tsy.selftest()
            for k, v in r.items():
                (st.success if v.get("ok") else st.warning)(f"**{k}** — {v.get('message')}")
