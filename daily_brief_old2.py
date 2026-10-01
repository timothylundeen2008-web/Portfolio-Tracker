"""
daily_brief.py  (v1 — September 2026)
─────────────────────────────────────
ONE consolidated daily brief that reads every layer of the system and says
what the readings mean TOGETHER. Replaces reading three logs side by side.

    Level 1  regime          regime_classifier + macro_flags (live FRED)
    Level 2  rotation/flow   rotation_summary.json (Money Flow bridge)
    Level 3  valuation       macro_flags guard inputs (CAPE, top-20)
    Level 4  entries         logs/swing/<session>_brief.json (Swing Desk)
    Level 5-7 positions      data/positions.csv (ledger) + live prices

WHY A SEPARATE MODULE (and not more lines in auto_log.py)
  auto_log is an EXCEPTION report: silence is its normal output. This brief
  is the opposite: it always explains. Keeping them apart keeps auto_log's
  pre-committed alert discipline intact while this file does interpretation.
  Every number here is computed from data, and every interpretive sentence is
  a rule applied to that number -- nothing is free-typed. When an input is
  missing, the section says which input and what decision it affects.

SECTIONS  (each ends with a one-line Conclusion)
   1 Headline          what changed, what it means, what is authorized today
   2 Scoreboard        Δ1d/Δ5d/Δ20d, 1-yr percentile, size of today's move in σ
   3 Regime            days in regime, two-close status, band, NEAREST FLIP
   4 Cross-asset       credit / rates / vol / dollar votes vs the regime
   5 Rotation          RRG sectors, quadrant changes, counter-clockwise flags, compass
   6 Flow              Tier A (integrity-passed only) + COT with report age
   7 Breadth           % above 50/200-day, 52-wk highs-lows, equal vs cap weight
   8 Portfolio         stops, machine-checked invalidations, heat, drift
   9 Swing             flow-signed grounds, cards, near-misses
  10 Next 48h          scheduled events + pre-committed if/then lines
  11 Conclusions       base case, what would change it, weekend list
  12 Data health       every input's as-of date and status

NEAREST FLIP -- how it is computed
  The classifier is re-run with ONE input nudged at a time (everything else
  held at today's values) until the regime key changes. The smallest nudge is
  the distance to that flip. It is expressed in the input's own units and in
  "typical days" (distance / σ of that input's daily change over a year), so
  a 0.10pp gap on a slow series and a 0.10pp gap on a fast one are not
  confused. This is exact for the classifier as coded, not an approximation
  of its thresholds -- if the thresholds change, this section follows.

Outputs
  logs/summaries/<session>_brief.md   (shown in the Logs tab)
  logs/brief/<session>_brief.json     (machine state; day-over-day diffs)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

import market_time as mt

SUMMARY_DIR = Path("logs/summaries")
STATE_DIR = Path("logs/brief")
DAILY_CSV = Path("logs/daily_log.csv")
SWING_DIR = Path("logs/swing")
ROTATION_FILE = "rotation_summary.json"
MARKETS_FILE = "markets_summary.json"

BAND = 0.25                      # regime_bands.TRANSITION_BAND
CASH_SLEEVES = {"SGOV", "USFR", "BIL", "SHV"}   # ATR stops do not apply to cash
HEAT_CAP_PCT = 15.0
DRIFT_BAND_REL = 0.20
LEDGER_STALE_DAYS = 7

# FRED series used for the scoreboard. (label, series, unit, kind)
#   kind "rate": Δ shown in bp;  "level": Δ in %;  "index": Δ in %
FRED_SCORE = [
    ("10Y real yield (DFII10)", "DFII10", "%", "rate"),
    ("10Y Treasury", "DGS10", "%", "rate"),
    ("2Y Treasury", "DGS2", "%", "rate"),
    ("10Y breakeven", "T10YIE", "%", "rate"),
    ("HY OAS", "BAMLH0A0HYM2", "%", "rate"),
    ("IG OAS", "BAMLC0A0CM", "%", "rate"),
    ("Broad dollar (DTWEXBGS)", "DTWEXBGS", "", "index"),
    ("VIX", "VIXCLS", "", "level"),
    ("WTI crude", "DCOILWTICO", "$", "index"),
]
EXTRA_FRED = ["DGS30"]
FRESHER = {"VIXCLS": "^VIX", "DCOILWTICO": "CL=F"}      # yfinance splices for lagging FRED series
FRED_MAX_AGE = {"DTWEXBGS": 10}                         # H.10 dollar index is published weekly
PRICE_SCORE = [("S&P 500 (SPY)", "SPY"), ("Nasdaq 100 (QQQ)", "QQQ"),
               ("Gold (GLD)", "GLD"), ("Long Treasuries (TLT)", "TLT")]

COMPASS = [
    ("Growth vs value", ["VUG"], ["VTV"]),
    ("Small vs large", ["IWM"], ["SPY"]),
    ("Equal vs cap weight", ["RSP"], ["SPY"]),
    ("Cyclicals vs defensives", ["XLY", "XLI", "XLF"], ["XLP", "XLU", "XLV"]),
    ("Intl developed vs US", ["EFA"], ["SPY"]),
    ("Emerging vs US", ["EEM"], ["SPY"]),
    ("Stocks vs long bonds", ["SPY"], ["TLT"]),
    ("Gold vs stocks", ["GLD"], ["SPY"]),
    ("Credit risk appetite (HY vs IG)", ["HYG"], ["LQD"]),
    ("Semis vs software", ["SMH"], ["IGV"]),
    ("Dollar (UUP)", ["UUP"], []),
]
COMPASS_READ = {   # what "numerator outperforming" means
    "Growth vs value": ("growth leading", "value leading"),
    "Small vs large": ("small caps leading (broadening)", "large caps leading (narrowing)"),
    "Equal vs cap weight": ("broadening participation", "narrow, cap-weighted leadership"),
    "Cyclicals vs defensives": ("risk-on rotation", "defensive rotation"),
    "Intl developed vs US": ("money leaving the US for developed intl", "US leadership"),
    "Emerging vs US": ("EM leadership", "US over EM"),
    "Stocks vs long bonds": ("equities over duration", "duration over equities"),
    "Gold vs stocks": ("hard-asset bid over equities", "equities over gold"),
    "Credit risk appetite (HY vs IG)": ("credit risk appetite rising", "credit risk appetite fading"),
    "Semis vs software": ("hardware/semis leading tech", "software leading tech"),
    "Dollar (UUP)": ("dollar strengthening", "dollar weakening"),
}

# Perturbation fields for the nearest-flip search:
# (attr, label, unit, fine_step, max_range)
FLIP_FIELDS = [
    ("short_real_rate", "Short real rate", "pp", 0.01, 3.0),
    ("long_real_mom_3m", "DFII10 3-month momentum", "pp", 0.01, 2.0),
    ("hy_oas", "HY OAS", "pp", 0.01, 6.0),
    ("hy_oas_mom_2w", "HY OAS 2-week change", "pp", 0.01, 3.0),
    ("spread_2s10s_mom_3m", "2s10s 3-month change", "pp", 0.01, 2.0),
    ("dxy_20d_change_pct", "Dollar 20-day change", "%", 0.05, 8.0),
]
FLIP_GUARDS = [("cape", "Shiller CAPE", "", 0.1, 25.0),
               ("top20", "Top-20 concentration", "%", 0.1, 25.0)]

RRG_CLOCKWISE = {"Improving": "Leading", "Leading": "Weakening",
                 "Weakening": "Lagging", "Lagging": "Improving"}

DAILY_RULE = ("the only trades authorized on a weekday are the HY crisis override, a stop "
              "execution, and the three mechanical options rules. Everything else waits for "
              "the weekend review.")


# ═══════════════════════════════════════════════════════════════════════════
#  Small helpers
# ═══════════════════════════════════════════════════════════════════════════

def _f(v) -> Optional[float]:
    try:
        x = float(v)
        return None if math.isnan(x) else x
    except (TypeError, ValueError):
        return None


def _fmt(v, dp=2, suffix="", plus=False) -> str:
    x = _f(v)
    if x is None:
        return "n/a"
    s = f"{x:+.{dp}f}" if plus else f"{x:.{dp}f}"
    return s + suffix


def _bp(v) -> str:
    x = _f(v)
    return "n/a" if x is None else f"{x * 100:+.0f}bp"


def _series_clean(s) -> pd.Series:
    if s is None:
        return pd.Series(dtype=float)
    s = pd.to_numeric(pd.Series(s), errors="coerce").dropna()
    try:
        s.index = pd.to_datetime(s.index)
        if getattr(s.index, "tz", None) is not None:      # yfinance can be tz-aware; FRED is naive
            s.index = s.index.tz_localize(None)
        s.index = s.index.normalize()
    except Exception:
        pass
    return s[~s.index.duplicated(keep="last")].sort_index()


def _pctile(s: pd.Series, n: int = 252) -> Optional[float]:
    s = s.dropna().iloc[-n:]
    if len(s) < 20:
        return None
    return round(float((s <= s.iloc[-1]).mean() * 100), 0)


def _age_days(asof, today: date) -> Optional[int]:
    if asof is None:
        return None
    try:
        d = pd.to_datetime(asof).date()
    except Exception:
        return None
    return (today - d).days


def _is_stealth(label) -> bool:
    try:
        from swing_screener import is_stealth
        return is_stealth(label)
    except Exception:
        return str(label or "").strip().lower() in ("stealth", "strong stealth")


def _read_json_file(name: str, data_dir: str) -> dict:
    """Bridge files: storage_backend first (GitHub-durable), then local."""
    try:
        from storage_backend import read_json
        d = read_json(name)
        if d:
            return d
    except Exception:
        pass
    p = Path(data_dir) / name
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════════════════
#  Gathering (all network access lives here; everything is injectable)
# ═══════════════════════════════════════════════════════════════════════════

def _default_prices(tickers: list[str], period: str = "2y") -> dict:
    import swing_agent
    return swing_agent._default_fetch(tickers, period=period)


def _memo_prices(fetch: Callable) -> Callable:
    cache: dict = {}

    def f(ticker, period="1y"):
        k = (ticker, period)
        if k not in cache:
            cache[k] = fetch(ticker, period)
        return cache[k]
    return f


def gather(today_et: Optional[datetime] = None, fred_key: str = "",
           fetch_fred: Optional[Callable] = None, fetch_prices: Optional[Callable] = None,
           assess: Optional[Callable] = None, macro_lookup: Optional[Callable] = None,
           data_dir: Optional[str] = None) -> dict:
    """Collect every input. Failures are recorded, never raised."""
    now = today_et or mt.now_et()
    session = mt.last_trading_day(now.date())
    if now.date() == session and now.hour < 16 and mt.is_trading_day(now.date()):
        # before today's close the latest COMPLETE session is the prior one
        session = mt.last_trading_day(now.date() - timedelta(days=1))
    data_dir = data_dir or os.environ.get("DATA_DIR", "data")
    errors: list[str] = []
    inp = {"now_et": now, "session": session, "errors": errors}

    # ── Level 1: live assessment (same call auto_log makes) ────────────────
    if fetch_fred is None:
        try:
            from fred_client import fetch_fred as _ff
            fetch_fred = _ff
        except Exception as e:
            errors.append(f"fred_client unavailable: {e}")
    try:
        if assess is not None:
            inp["assessment"] = assess()
        else:
            import regime_classifier as rc
            import macro_flags
            flags = macro_flags.get_flags(fetch_fred=fetch_fred, api_key=fred_key)
            memo = _memo_prices(rc._inline_fetch_prices)
            ckw = macro_flags.classifier_kwargs(flags)
            out = rc.full_assessment(fred_key, fetch_fred=fetch_fred, fetch_prices=memo, **ckw)
            out["macro_flags"] = flags
            out["classifier_kwargs"] = ckw
            out["_fetch_prices"] = memo
            inp["assessment"] = out
    except Exception as e:
        errors.append(f"Regime assessment failed: {type(e).__name__}: {e}")
        inp["assessment"] = None

    # ── FRED histories for the scoreboard ─────────────────────────────────
    hist = {}
    start = (session - timedelta(days=800)).isoformat()
    for sid in [x[1] for x in FRED_SCORE] + EXTRA_FRED:
        try:
            hist[sid] = _series_clean(fetch_fred(sid, fred_key, start)) if fetch_fred else pd.Series(dtype=float)
        except Exception as e:
            hist[sid] = pd.Series(dtype=float)
            errors.append(f"FRED {sid}: {type(e).__name__}")
    inp["fred"] = hist

    # ── Files: bridges, logs, ledger ──────────────────────────────────────
    inp["rotation"] = _read_json_file(ROTATION_FILE, data_dir)
    inp["markets"] = _read_json_file(MARKETS_FILE, data_dir)
    try:
        inp["daily_log"] = pd.read_csv(DAILY_CSV) if DAILY_CSV.exists() else pd.DataFrame()
    except Exception as e:
        inp["daily_log"] = pd.DataFrame(); errors.append(f"daily_log.csv unreadable: {e}")
    inp["swing"], inp["swing_file"] = _latest_swing(session, now.date())
    try:
        import position_ledger as pl
        inp["ledger"] = pl.load_positions()
    except Exception as e:
        inp["ledger"] = pd.DataFrame(); errors.append(f"ledger unreadable: {e}")
    inp["prior_brief"] = _prior_brief(session)

    # ── Prices: scoreboard + compass + ledger + breadth universe ──────────
    constituents = (inp["rotation"] or {}).get("constituents") or {}
    universe = sorted({t for names in constituents.values() for t in names})
    comp = sorted({t for _, a, b in COMPASS for t in a + b})
    ledger_tk = sorted(set(inp["ledger"]["ticker"].astype(str))) if not inp["ledger"].empty else []
    tickers = sorted(set(universe) | set(comp) | set(ledger_tk) | {t for _, t in PRICE_SCORE}
                     | set(FRESHER.values()))
    inp["universe"] = universe
    try:
        inp["prices"] = (fetch_prices or _default_prices)(tickers)
    except Exception as e:
        inp["prices"] = {}; errors.append(f"price fetch failed: {type(e).__name__}: {e}")
    # FRED's VIXCLS and DCOILWTICO lag the market by 1-3 sessions; splice the
    # yfinance closes after FRED's last date so the level is current but the
    # 1-year history (percentile, σ) stays FRED's.
    inp["fred_src"] = {}
    for sid, yf_tk in FRESHER.items():
        fs, ys = hist.get(sid, pd.Series(dtype=float)), _price_close(inp["prices"], yf_tk)
        if len(ys) and (not len(fs) or ys.index[-1] > fs.index[-1]):
            tail = ys[ys.index > fs.index[-1]] if len(fs) else ys
            hist[sid] = pd.concat([fs, tail]).sort_index()
            inp["fred_src"][sid] = f"FRED + yfinance {yf_tk} after {fs.index[-1].date() if len(fs) else 'n/a'}"
    missing = [t for t in tickers if t not in inp["prices"]]
    if missing:
        errors.append(f"prices missing for {len(missing)} of {len(tickers)} tickers"
                      + (f" ({', '.join(missing[:8])}{'…' if len(missing) > 8 else ''})"))

    # ── Events ────────────────────────────────────────────────────────────
    try:
        import event_calendar as ec
        inp["events"] = (macro_lookup or (lambda d: ec.upcoming_macro(d, today=now.date())))(10)
        inp["calendar_asof"] = getattr(ec, "CALENDAR_ASOF", None)
    except Exception as e:
        inp["events"] = []; inp["calendar_asof"] = None
        errors.append(f"event calendar: {e}")
    return inp


def _latest_swing(session: date, wall: Optional[date] = None) -> tuple:
    """The Swing Desk names its brief by the date it RAN, not the session it
    scanned: a Saturday run is a scan of Friday's close. So any brief dated
    from the session through today is this session's scan (27 Sep 2026: the
    first live run skipped the 09-26 brief and fell back to 09-24's)."""
    if not SWING_DIR.exists():
        return {}, None
    cutoff = (wall or session).isoformat()
    files = sorted(p for p in SWING_DIR.glob("*_brief.json") if p.name[:10] <= cutoff)
    if not files:
        return {}, None
    try:
        return json.loads(files[-1].read_text()), files[-1].name
    except Exception:
        return {}, files[-1].name


def _prior_brief(session: date) -> dict:
    if not STATE_DIR.exists():
        return {}
    files = sorted(p for p in STATE_DIR.glob("*_brief.json") if p.name[:10] < session.isoformat())
    if not files:
        return {}
    try:
        return json.loads(files[-1].read_text())
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════════════════
#  Section builders (pure functions of the gathered inputs)
# ═══════════════════════════════════════════════════════════════════════════

def _price_close(prices: dict, tk: str) -> pd.Series:
    df = prices.get(tk)
    if df is None or getattr(df, "empty", True) or "Close" not in df:
        return pd.Series(dtype=float)
    return _series_clean(df["Close"])


def scoreboard(inp: dict) -> dict:
    rows = []
    for label, sid, unit, kind in FRED_SCORE:
        s = inp["fred"].get(sid, pd.Series(dtype=float))
        rows.append(_score_row(label, s, unit, kind, source=f"FRED {sid}"))
    # short real rate: from the live signal, deltas from the logged history
    sig = (inp.get("assessment") or {}).get("signals")
    srr = _f(getattr(sig, "short_real_rate", None)) if sig is not None else None
    log = inp.get("daily_log")
    if srr is not None:
        h = pd.Series(dtype=float)
        if log is not None and not log.empty and "short_real_rate" in log:
            lg = log[log["et_date"] < inp["session"].isoformat()]
            h = pd.to_numeric(lg["short_real_rate"], errors="coerce").dropna().reset_index(drop=True)
        s = pd.concat([h, pd.Series([srr])], ignore_index=True)
        r = _score_row("Short real rate (EFFR − CPI YoY)", s, "%", "rate",
                       source="classifier + daily log", pctile_ok=False)
        r["asof"] = "live (EFFR − latest CPI)"
        rows.insert(0, r)
    for label, tk in PRICE_SCORE:
        rows.append(_score_row(label, _price_close(inp["prices"], tk), "$", "index", source="yfinance"))
    rsp, spy = _price_close(inp["prices"], "RSP"), _price_close(inp["prices"], "SPY")
    if len(rsp) and len(spy):
        ratio = (rsp / spy).dropna()
        rows.append(_score_row("Equal/cap weight (RSP/SPY)", ratio, "", "index", source="yfinance"))
    big = [r for r in rows if r["z1d"] is not None and abs(r["z1d"]) >= 1.5]
    big.sort(key=lambda r: -abs(r["z1d"]))
    ext = [r for r in rows if r["pctile_1y"] is not None and (r["pctile_1y"] >= 95 or r["pctile_1y"] <= 5)]
    if big:
        concl = ("Unusual moves today: " + "; ".join(f"{r['name']} {r['d1_txt']} ({r['z1d']:+.1f}σ)" for r in big[:3])
                 + ". Everything else moved inside its normal daily range.")
    else:
        concl = "No input moved more than 1.5σ today — a normal-range session on every tracked series."
    if ext:
        concl += " At a 1-year extreme: " + ", ".join(f"{r['name']} ({r['pctile_1y']:.0f}th pctile)" for r in ext[:4]) + "."
    return {"rows": rows, "movers": big, "extremes": ext, "conclusion": concl}


def _score_row(name, s: pd.Series, unit, kind, source, pctile_ok=True) -> dict:
    s = s.dropna() if s is not None else pd.Series(dtype=float)
    row = {"name": name, "value": None, "unit": unit, "kind": kind, "d1": None, "d5": None, "d20": None,
           "d1_txt": "n/a", "d5_txt": "n/a", "d20_txt": "n/a", "pctile_1y": None, "z1d": None,
           "asof": None, "source": source}
    if s.empty:
        return row
    v = float(s.iloc[-1])
    row["value"] = v
    try:
        row["asof"] = pd.to_datetime(s.index[-1]).date().isoformat() if isinstance(s.index, pd.DatetimeIndex) else None
    except Exception:
        pass

    def d(n):
        if len(s) <= n:
            return None
        prev = float(s.iloc[-1 - n])
        if kind == "rate":
            return v - prev
        return (v / prev - 1) * 100 if prev else None

    for n, k in ((1, "d1"), (5, "d5"), (20, "d20")):
        row[k] = d(n)
        row[k + "_txt"] = (_bp(row[k]) if kind == "rate" else _fmt(row[k], 1, "%", plus=True)) if row[k] is not None else "n/a"
    if pctile_ok:
        row["pctile_1y"] = _pctile(s)
    ch = (s.diff() if kind == "rate" else s.pct_change() * 100).dropna().iloc[-253:-1]
    if len(ch) >= 40 and row["d1"] is not None:
        sd = float(ch.std())
        if sd > 0:
            row["z1d"] = round(row["d1"] / sd, 1)
    return row


# ── Regime ─────────────────────────────────────────────────────────────────

def _sigma_for(attr: str, fred: dict) -> Optional[float]:
    """σ of the daily change of the INPUT as the classifier sees it."""
    r10, hy = fred.get("DFII10"), fred.get("BAMLH0A0HYM2")
    n10, n2, dxy = fred.get("DGS10"), fred.get("DGS2"), fred.get("DTWEXBGS")
    s = None
    try:
        if attr == "long_real_mom_3m" and r10 is not None and len(r10) > 100:
            s = r10.diff(63).diff()
        elif attr == "hy_oas" and hy is not None and len(hy) > 40:
            s = hy.diff()
        elif attr == "hy_oas_mom_2w" and hy is not None and len(hy) > 40:
            s = hy.diff(10).diff()
        elif attr == "spread_2s10s_mom_3m" and n10 is not None and n2 is not None and len(n10) > 100:
            c = (n10 - n2).dropna()
            s = c.diff(63).diff()
        elif attr == "dxy_20d_change_pct" and dxy is not None and len(dxy) > 40:
            s = (dxy.pct_change(20) * 100).diff()
    except Exception:
        s = None
    if s is None:
        return None
    s = s.dropna().iloc[-252:]
    return float(s.std()) if len(s) >= 40 and s.std() > 0 else None


def nearest_flips(assessment: dict) -> list[dict]:
    """Re-run the classifier with one input nudged at a time."""
    if not assessment or assessment.get("signals") is None:
        return []
    import copy
    import regime_classifier as rc
    sig0 = assessment["signals"]
    kw = assessment.get("classifier_kwargs")
    if kw is None:
        flags = assessment.get("macro_flags") or {}
        try:
            import macro_flags
            kw = macro_flags.classifier_kwargs(flags) if flags else {}
        except Exception:
            kw = {}
    cape, top20 = kw.get("cape"), kw.get("top20_concentration_pct")
    fp = assessment.get("_fetch_prices")
    base_key = assessment["regime"]["key"]

    def key_for(sig, cape_=cape, top_=top20):
        try:
            return rc.classify_regime(sig, fetch_prices=fp, cape=cape_,
                                      top20_concentration_pct=top_)["key"]
        except Exception:
            return None

    # Guard: the replay must reproduce today's call, or the search is meaningless
    if key_for(sig0) != base_key:
        return [{"error": "replay did not reproduce today's regime (a guard input is "
                          "path-dependent); nearest-flip skipped rather than guessed"}]

    out = []

    def search(get_key, v0, step, rng):
        best = None
        for sgn in (+1, -1):
            coarse = step * 4
            prev_d, d, hit = 0.0, coarse, None
            while d <= rng + 1e-9:
                k = get_key(v0 + sgn * d)
                if k is not None and k != base_key:
                    hit = (prev_d, d, k); break
                prev_d, d = d, d + coarse
            if not hit:
                continue
            lo, hi, k = hit
            while hi - lo > step + 1e-9:
                mid = (lo + hi) / 2
                km = get_key(v0 + sgn * mid)
                if km is not None and km != base_key:
                    hi, k = mid, km
                else:
                    lo = mid
            cand = {"delta": round(sgn * hi, 3), "to": k}
            if best is None or abs(cand["delta"]) < abs(best["delta"]):
                best = cand
        return best

    for attr, label, unit, step, rng in FLIP_FIELDS:
        v0 = _f(getattr(sig0, attr, None))
        if v0 is None:
            continue

        def gk(v, attr=attr):
            s = copy.copy(sig0)
            setattr(s, attr, v)
            return key_for(s)
        b = search(gk, v0, step, rng)
        if b:
            out.append({"input": attr, "label": label, "unit": unit, "now": v0,
                        "delta": b["delta"], "at": round(v0 + b["delta"], 3), "to": b["to"]})
    for attr, label, unit, step, rng in FLIP_GUARDS:
        v0 = cape if attr == "cape" else top20
        if _f(v0) is None:
            continue
        gk = ((lambda v: key_for(sig0, cape_=v)) if attr == "cape"
              else (lambda v: key_for(sig0, top_=v)))
        b = search(gk, float(v0), step, rng)
        if b:
            out.append({"input": attr, "label": label, "unit": unit, "now": float(v0),
                        "delta": b["delta"], "at": round(float(v0) + b["delta"], 2), "to": b["to"]})
    return out


def regime_section(inp: dict) -> dict:
    a = inp.get("assessment")
    log = inp.get("daily_log")
    out = {"available": bool(a), "conclusion": ""}
    if not a:
        mk = (inp.get("markets") or {}).get("regime") or {}
        out.update(key=mk.get("key"), label=mk.get("label"), drivers=mk.get("drivers", []),
                   source="markets bridge (live assessment failed)")
        out["conclusion"] = ("Live regime assessment failed — showing the Markets bridge's last published "
                             "read. Treat every downstream section as degraded.")
        return out
    reg, sig = a["regime"], a["signals"]
    key = reg["key"]
    out.update(key=key, label=reg.get("label"), drivers=reg.get("drivers", []),
               transition_reason=reg.get("transition_reason"), source="live (FRED)")
    # days in regime
    prior = []
    if log is not None and not log.empty and "regime" in log:
        lg = log[log["et_date"] < inp["session"].isoformat()].sort_values("et_date")
        prior = lg["regime"].astype(str).tolist()
    n = 1
    for k in reversed(prior):
        if k == key:
            n += 1
        else:
            break
    prev_key = next((k for k in reversed(prior) if k != key), None)
    out["days_in_regime"] = n
    out["previous_regime"] = prev_key
    if n == 1 and prior:
        out["confirm"] = (f"Day 1 under `{key}` (previous close: `{prior[-1]}`). Per the two-close protocol, "
                          "nothing executes on a new regime until a second consecutive close confirms it.")
    elif n == 2:
        out["confirm"] = ("Confirmed on two consecutive closes. Regime changes are executed at the weekend "
                          "review in the protocol's order: cuts first, hedges second, adds last.")
    else:
        out["confirm"] = f"{n} consecutive sessions under this regime."
    # band
    srr = _f(getattr(sig, "short_real_rate", None))
    out["short_real"] = srr
    band = None if srr is None else ("POSITIVE" if srr > BAND else "NEGATIVE" if srr < -BAND else "AMBIGUOUS")
    out["band_state"] = band
    days_since = None
    if band and log is not None and not log.empty and "short_real_rate" in log:
        vals = pd.to_numeric(log[log["et_date"] < inp["session"].isoformat()]
                             .sort_values("et_date")["short_real_rate"], errors="coerce").tolist()
        days_since = 1
        for v in reversed(vals):
            if v is None or (isinstance(v, float) and math.isnan(v)):
                days_since += 1; continue
            st = "POSITIVE" if v > BAND else "NEGATIVE" if v < -BAND else "AMBIGUOUS"
            if st != band:
                break
            days_since += 1
        else:
            days_since = None     # never crossed inside the logged history
    out["band_sessions"] = days_since
    # nearest flips
    flips = nearest_flips(a)
    fred = inp.get("fred") or {}
    for fl in flips:
        if "error" in fl:
            continue
        sd = _sigma_for(fl["input"], fred)
        fl["typical_days"] = round(abs(fl["delta"]) / sd, 1) if sd else None
        if fl["input"] == "short_real_rate":
            fl["note"] = f"≈{abs(fl['delta']) / 0.25:.1f} × a 25bp policy move, or the CPI equivalent"
    ok = [f for f in flips if "error" not in f]
    ok.sort(key=lambda f: (f["typical_days"] is None, f["typical_days"] if f["typical_days"] is not None else abs(f["delta"])))
    out["flips"] = ok
    out["flip_error"] = next((f["error"] for f in flips if "error" in f), None)
    # guards
    mf = a.get("macro_flags") or {}
    out["guards"] = []
    try:
        import macro_flags
        out["guards"] = [l.replace("**", "") for l in macro_flags.summary_lines(mf)] if mf else []
        out["guard_warnings"] = mf.get("warnings", []) if mf else []
    except Exception:
        out["guard_warnings"] = []
    rep = a.get("repression") or {}
    out["repression"] = {"score": rep.get("score"), "band": rep.get("band"), "hollow": rep.get("hollow")}
    bridge_key = ((inp.get("markets") or {}).get("regime") or {}).get("key")
    out["bridge_key"] = bridge_key
    out["bridge_agrees"] = (bridge_key == key) if bridge_key else None
    # conclusion
    near = ok[0] if ok else None
    c = f"`{key}` — {reg.get('label', '')}. {out['confirm'].split('.')[0]}."
    if near:
        c += (f" Nearest flip: {near['label']} {_fmt(near['now'], 2)}{near['unit']} → "
              f"{_fmt(near['at'], 2)}{near['unit']} ({near['delta']:+.2f}{near['unit']}"
              + (f", ~{near['typical_days']:.0f} typical days" if near.get("typical_days") is not None else "")
              + f") would make it `{near['to']}`.")
    if out["bridge_agrees"] is False:
        c += f" ⚠ The Markets bridge last published `{bridge_key}` — republish it from the Markets dashboard."
    out["conclusion"] = c
    return out


# ── Cross-asset ────────────────────────────────────────────────────────────

def cross_asset_section(inp: dict, regime_key: Optional[str]) -> dict:
    a = inp.get("assessment")
    sig = a.get("signals") if a else None
    try:
        import cross_asset as ca
    except Exception as e:
        return {"available": False, "conclusion": f"cross_asset.py unavailable: {e}"}
    fred = inp.get("fred") or {}
    dxy = fred.get("DTWEXBGS", pd.Series(dtype=float))
    vix_s = fred.get("VIXCLS", pd.Series(dtype=float))
    n30 = fred.get("DGS30", pd.Series(dtype=float))
    g = lambda n: _f(getattr(sig, n, None)) if sig is not None else None
    d = ca.divergence(hy_oas=g("hy_oas"), hy_mom_2w=g("hy_oas_mom_2w"),
                      long_real=g("long_real_yield"), long_real_mom_3m=g("long_real_mom_3m"),
                      breakeven=g("breakeven_10y"),
                      nom_30y=_f(n30.iloc[-1]) if len(n30) else None,
                      vix=_f(vix_s.iloc[-1]) if len(vix_s) else None,
                      dxy=_f(dxy.iloc[-1]) if len(dxy) else None,
                      dxy_20d_change_pct=g("dxy_20d_change_pct"),
                      dxy_52w_high=_f(dxy.iloc[-252:].max()) if len(dxy) else None)
    lanes = d.get("lanes", {})
    st = {k: v.get("state") for k, v in lanes.items()}
    if st.get("credit") == "STRESS":
        c = ("Credit is voting STRESS — the one lane that turns a rates story into a solvency story. "
             "Check the HY crisis override before anything else.")
    elif st.get("rates") in ("STRESS", "WATCH") and st.get("credit") == "CALM" and st.get("vol") == "CALM":
        c = ("The pressure is confined to rates: credit and vol are calm, so this is multiple COMPRESSION "
             "(a discount-rate problem for long-duration assets), not stress. It becomes stress only if credit joins.")
    elif d.get("dissenters"):
        c = f"{d.get('headline')}. {d.get('flag', '')[:220]}"
    else:
        c = d.get("headline") or "Cross-asset read unavailable."
    fit = None
    if regime_key == "restrictive_tightening":
        fit = st.get("rates") in ("STRESS", "WATCH") and st.get("credit") != "STRESS"
    elif regime_key == "liquidity_crisis":
        fit = st.get("credit") == "STRESS"
    elif regime_key == "goldilocks":
        fit = st.get("credit") == "CALM" and st.get("rates") != "STRESS"
    if fit is False:
        c += f" ⚠ The lanes do not fit the `{regime_key}` label — treat the regime read as lower-confidence."
    elif fit:
        c += f" The lanes fit the `{regime_key}` label."
    return {"available": True, **d, "fits_regime": fit, "conclusion": c}


# ── Rotation ───────────────────────────────────────────────────────────────

def rotation_section(inp: dict) -> dict:
    rot = inp.get("rotation") or {}
    rows = [r for r in rot.get("sectors", []) if isinstance(r, dict) and r.get("ticker")]
    out = {"available": bool(rows), "published_at": rot.get("published_at")}
    prior = {r["ticker"]: r.get("quadrant") for r in ((inp.get("prior_brief") or {}).get("rotation", {}) or {}).get("sectors", [])}
    sectors, changes, ccw = [], [], []
    for r in rows:
        tk, q = r["ticker"], r.get("quadrant")
        acc = _f(r.get("accumulation_score"))
        pq = prior.get(tk)
        rec = {"ticker": tk, "sector": r.get("sector"), "quadrant": q, "direction": r.get("rotation_direction"),
               "accumulation": acc, "stealth": _is_stealth(r.get("stealth_label")), "prior_quadrant": pq,
               "agree": (q in ("Improving", "Leading") and (acc or 0) > 0) or (q in ("Weakening", "Lagging") and (acc or 0) < 0)}
        sectors.append(rec)
        if pq and q and pq != q:
            changes.append(f"{tk} {pq} → {q}")
            if RRG_CLOCKWISE.get(q) == pq:          # moved backwards around the RRG
                ccw.append(f"{tk} {pq} → {q} (counter-clockwise: the prior phase is reversing)")
    order = {"Leading": 0, "Improving": 1, "Weakening": 2, "Lagging": 3}
    sectors.sort(key=lambda r: (order.get(r["quadrant"], 9), -(r["accumulation"] or 0)))
    out.update(sectors=sectors, changes=changes, ccw=ccw, has_prior=bool(prior))
    out["compass"] = compass(inp.get("prices") or {})
    longs = [s["ticker"] for s in sectors if s["quadrant"] in ("Improving", "Leading") and (s["accumulation"] or 0) > 0]
    price_only = [s["ticker"] for s in sectors if s["quadrant"] in ("Improving", "Leading") and (s["accumulation"] or 0) <= 0]
    shorts = [s["ticker"] for s in sectors if s["quadrant"] in ("Weakening", "Lagging") and (s["accumulation"] or 0) < 0]
    if not rows:
        c = "No rotation data — the Money Flow bridge has not published."
    else:
        if len(longs) == 0:
            c = "No sector has price and money rotating in together — there is no confirmed leadership."
        elif len(longs) == 1:
            c = f"Leadership is singular: {longs[0]} is the only sector where price and money agree."
        else:
            c = f"Confirmed leadership in {', '.join(longs)} (price and money agree)."
        if price_only:
            c += (f" {', '.join(price_only)} {'is' if len(price_only) == 1 else 'are'} rotating in on price with "
                  f"negative accumulation — a bounce without sponsorship, not a rotation.")
        if ccw:
            c += " Counter-clockwise moves today: " + "; ".join(ccw) + "."
        brd = [x for x in out["compass"] if x["name"] == "Equal vs cap weight" and x.get("r20") is not None]
        if brd and brd[0]["r20"] < -1:
            c += f" Equal-weight has lagged cap-weight by {abs(brd[0]['r20']):.1f}% over 20 days — narrow tape."
    out["grounds"] = {"long": longs, "price_only": price_only, "short": shorts}
    out["conclusion"] = c
    return out


def compass(prices: dict) -> list[dict]:
    out = []
    for name, num, den in COMPASS:
        def basket(tks):
            ss = [_price_close(prices, t) for t in tks]
            ss = [s / s.iloc[0] for s in ss if len(s) > 70]
            if len(ss) != len(tks):
                return None
            return pd.concat(ss, axis=1).dropna().mean(axis=1)
        a = basket(num)
        b = basket(den) if den else None
        if a is None or (den and b is None):
            out.append({"name": name, "r20": None, "r60": None, "arrow": "?", "read": "data unavailable"})
            continue
        ratio = (a / b).dropna() if b is not None else a
        if len(ratio) < 61:
            out.append({"name": name, "r20": None, "r60": None, "arrow": "?", "read": "history too short"})
            continue
        r20 = float(ratio.iloc[-1] / ratio.iloc[-21] - 1) * 100
        r60 = float(ratio.iloc[-1] / ratio.iloc[-61] - 1) * 100
        arrow = "↑" if r20 > 1 else "↓" if r20 < -1 else "→"
        up, down = COMPASS_READ.get(name, ("numerator leading", "denominator leading"))
        read = up if r20 > 1 else down if r20 < -1 else "no clear trend"
        if arrow != "→" and ((r20 > 0) != (r60 > 0)):
            read += " (reversing the 60-day trend)"
        out.append({"name": name, "r20": round(r20, 1), "r60": round(r60, 1), "arrow": arrow, "read": read})
    return out


# ── Flow ───────────────────────────────────────────────────────────────────

def flow_section(inp: dict) -> dict:
    rot = inp.get("rotation") or {}
    divs = rot.get("flow_divergences") or []
    ok = [d for d in divs if not str(d.get("verdict", "")).startswith("UNRELIABLE")]
    bad = [d for d in divs if str(d.get("verdict", "")).startswith("UNRELIABLE")]
    ok.sort(key=lambda d: -(_f(d.get("net_flow_pct_aum")) or 0))
    cot = rot.get("cot") or []
    today = inp["session"]
    cot_rows = []
    for c in cot:
        age = _f(c.get("age_days"))
        if age is None:
            age = _age_days(c.get("report_date"), today)
        cot_rows.append({"contract": c.get("contract"), "sleeve": c.get("sleeve"), "report_date": c.get("report_date"),
                         "age_days": age, "stale": bool(c.get("stale")) or (age is not None and age > 14),
                         "flag": c.get("flag")})
    ins = [d["ticker"] for d in ok if (_f(d.get("net_flow_pct_aum")) or 0) > 1]
    outs = [d["ticker"] for d in ok if (_f(d.get("net_flow_pct_aum")) or 0) < -1]
    acc_div = [d["ticker"] for d in ok if "ACCUMULATION" in str(d.get("verdict"))]
    crowded = [f"{c['contract']} ({c['flag']})" for c in cot_rows if not c["stale"] and c["flag"] and "crowded" in c["flag"]]
    if not divs and not cot:
        c = "No flow data published."
    else:
        c = (f"{len(ok)} of {len(divs)} ETFs pass the integrity test (20-session window). "
             + (f"Inflows >1% of AUM: {', '.join(ins[:6])}. " if ins else "")
             + (f"Outflows >1%: {', '.join(outs[:6])}. " if outs else ""))
        if acc_div:
            c += (f"Price down / money in (possible stealth accumulation): {', '.join(acc_div[:6])} — "
                  "a watch signal only until price structure confirms. ")
        if crowded:
            c += "Crowded COT positioning: " + "; ".join(crowded[:3]) + "."
    return {"available": bool(divs or cot), "confirmed": ok, "unreliable": [d["ticker"] for d in bad],
            "cot": cot_rows, "conclusion": c.strip()}


# ── Breadth ────────────────────────────────────────────────────────────────

def breadth_section(inp: dict) -> dict:
    prices, uni = inp.get("prices") or {}, inp.get("universe") or []
    a50 = a200 = n50 = n200 = hi = lo = n252 = 0
    for tk in uni:
        s = _price_close(prices, tk)
        if len(s) >= 50:
            n50 += 1; a50 += int(s.iloc[-1] > s.iloc[-50:].mean())
        if len(s) >= 200:
            n200 += 1; a200 += int(s.iloc[-1] > s.iloc[-200:].mean())
        if len(s) >= 252:
            n252 += 1
            w = s.iloc[-252:]
            hi += int(s.iloc[-1] >= w.max()); lo += int(s.iloc[-1] <= w.min())
    p50 = round(a50 / n50 * 100, 1) if n50 else None
    p200 = round(a200 / n200 * 100, 1) if n200 else None
    out = {"pct_above_50": p50, "pct_above_200": p200, "n": n50, "new_highs": hi if n252 else None,
           "new_lows": lo if n252 else None, "universe": f"{n50}-name sector-constituent proxy (not the full S&P 500)"}
    spy, rsp = _price_close(prices, "SPY"), _price_close(prices, "RSP")
    spy20 = float(spy.iloc[-1] / spy.iloc[-21] - 1) * 100 if len(spy) > 21 else None
    rsp20 = float(rsp.iloc[-1] / rsp.iloc[-21] - 1) * 100 if len(rsp) > 21 else None
    out["spy_20d"], out["rsp_20d"] = spy20, rsp20
    if p50 is None:
        out["conclusion"] = "Breadth unavailable — constituent prices did not load."
        return out
    c = f"{p50:.0f}% of the proxy universe is above its 50-day and {_fmt(p200, 0)}% above its 200-day"
    if out["new_highs"] is not None:
        c += f"; {hi} new 52-week highs vs {lo} new lows"
    c += ". "
    if spy20 is not None and rsp20 is not None and spy20 - rsp20 > 1.5 and p50 < 50:
        c += (f"The index is up {spy20:+.1f}% over 20 days while equal-weight is {rsp20:+.1f}% and most names are "
              "below their 50-day — the rally is carried by a few mega-caps. Narrow rallies fail more often; size accordingly.")
    elif p50 >= 60:
        c += "Participation is broad enough to support new longs."
    elif p50 < 40:
        c += "Most names are in short-term downtrends — a headwind for any long breakout."
    else:
        c += "Participation is mixed."
    out["conclusion"] = c
    return out


# ── Portfolio ──────────────────────────────────────────────────────────────

_INV_RULES = [
    (re.compile(r"DFII10 closes? (?:back )?above ([\d.]+)%", re.I),
     lambda m, ctx: (ctx.get("dfii10") is not None and ctx["dfii10"] > float(m.group(1)),
                     f"DFII10 {_fmt(ctx.get('dfii10'))}% vs {m.group(1)}%")),
    (re.compile(r"DFII10 momentum flips positive", re.I),
     lambda m, ctx: (ctx.get("dfii10_mom") is not None and ctx["dfii10_mom"] > 0,
                     f"DFII10 3m momentum {_fmt(ctx.get('dfii10_mom'), 2, 'pp', True)}")),
    (re.compile(r"gold gate flips PASS", re.I),
     lambda m, ctx: (ctx.get("gold_gate") == "PASS", f"gold gate {ctx.get('gold_gate') or 'n/a'}")),
    (re.compile(r"correlation confirms below (-?[\d.]+)", re.I),
     lambda m, ctx: (ctx.get("sb_corr") is not None and ctx["sb_corr"] < float(m.group(1)),
                     f"stock/bond corr {_fmt(ctx.get('sb_corr'))} vs {m.group(1)}")),
    (re.compile(r"price drops below ([\d.]+)", re.I),
     lambda m, ctx: (ctx.get("last") is not None and ctx["last"] < float(m.group(1)),
                     f"close {_fmt(ctx.get('last'))} vs {m.group(1)}")),
    (re.compile(r"regime reverts toward ([a-z_/]+)", re.I),
     lambda m, ctx: (any(k in (ctx.get("regime") or "") for k in m.group(1).split("/")),
                     f"regime `{ctx.get('regime')}`")),
]


def check_invalidation(text: str, ctx: dict) -> dict:
    """Machine-check the parts of a free-text invalidation we can recognise."""
    text = str(text or "")
    if not text.strip() or text == "nan":
        return {"status": "NONE", "detail": "no invalidation written — a position without one fails the checklist"}
    hits = []
    for rx, fn in _INV_RULES:
        m = rx.search(text)
        if m:
            fired, detail = fn(m, ctx)
            hits.append((fired, detail))
    if not hits:
        return {"status": "MANUAL", "detail": "not machine-checkable — review by hand"}
    fired = [d for f, d in hits if f]
    if fired:
        return {"status": "FIRED", "detail": "; ".join(fired)}
    return {"status": "INTACT", "detail": "; ".join(d for _, d in hits)}


def portfolio_section(inp: dict, targets: dict, regime_key: Optional[str]) -> dict:
    led = inp.get("ledger")
    if led is None or led.empty:
        return {"available": False, "conclusion": "Ledger is empty — no stop, heat or drift checks are possible."}
    import position_ledger as pl
    a = inp.get("assessment") or {}
    sig = a.get("signals")
    today = inp["session"]
    last_upd = pd.to_datetime(led.get("last_updated"), errors="coerce").max()
    ledger_age = (inp["now_et"].date() - last_upd.date()).days if pd.notna(last_upd) else None
    gold_gate = None
    log = inp.get("daily_log")
    if log is not None and not log.empty and "gold_gate" in log:
        gold_gate = str(log.sort_values("et_date")["gold_gate"].iloc[-1])
    rows, authorized, weekend = [], [], []
    tot_mv = tot_risk = 0.0
    for _, p in led.iterrows():
        tk = str(p["ticker"])
        df = (inp.get("prices") or {}).get(tk)
        last = _f(df["Close"].dropna().iloc[-1]) if df is not None and not df.empty else None
        at = _f(pl.atr(df)) if df is not None and not df.empty else None
        sh, entry, stop = _f(p.get("shares")) or 0, _f(p.get("entry_price")), _f(p.get("stop"))
        mv = last * sh if last is not None else None
        tot_mv += mv or 0
        cash = tk in CASH_SLEEVES
        if not cash and entry is not None and stop is not None:
            tot_risk += max(entry - stop, 0) * abs(sh)
        if cash:
            st, note = "CASH", "cash sleeve — ATR stop not applicable"
        elif last is None or stop is None:
            st, note = "UNKNOWN", "no price" if last is None else "no stop"
        elif last <= stop:
            st, note = "STOP HIT", f"close {last:.2f} ≤ stop {stop:.2f}"
            authorized.append(f"{tk}: stop hit (close {last:.2f} vs stop {stop:.2f}) — a stop exit is a daily-authorized trade")
        elif at and (last - stop) / at <= 1:
            st, note = "WITHIN 1 ATR", f"{(last - stop) / at:.2f} ATR above stop"
        else:
            st, note = "OK", f"{(last - stop) / at:.1f} ATR above stop" if at else "ATR n/a"
        ctx = {"dfii10": _f(getattr(sig, "long_real_yield", None)) if sig else None,
               "dfii10_mom": _f(getattr(sig, "long_real_mom_3m", None)) if sig else None,
               "sb_corr": _f(getattr(sig, "stock_bond_corr_60d", None)) if sig else None,
               "gold_gate": gold_gate, "last": last, "regime": regime_key}
        inv = check_invalidation(p.get("invalidation"), ctx)
        if inv["status"] == "FIRED":
            weekend.append(f"{tk}: written invalidation has fired ({inv['detail']}) — exit or rewrite the thesis")
        rows.append({"ticker": tk, "shares": sh, "entry": entry, "last": last, "stop": stop, "status": st,
                     "note": note, "mv": mv, "invalidation": str(p.get("invalidation") or ""), "inv_status": inv["status"],
                     "inv_detail": inv["detail"]})
    heat = round(tot_risk / tot_mv * 100, 2) if tot_mv else None
    drift = []
    if targets and tot_mv:
        live = {}
        for r in rows:
            live[r["ticker"]] = live.get(r["ticker"], 0) + (r["mv"] or 0) / tot_mv * 100
        for tk, tgt in sorted(targets.items(), key=lambda kv: -kv[1]):
            cur = live.get(tk, 0.0)
            rel = (cur - tgt) / tgt if tgt else None
            breach = (cur > 1.0) if not tgt else abs(rel) > DRIFT_BAND_REL
            drift.append({"sleeve": tk, "target": round(tgt, 1), "live": round(cur, 1),
                          "rel": round(rel * 100, 0) if rel is not None else None, "breach": breach})
        for tk in live:
            if tk not in targets and live[tk] > 1:
                drift.append({"sleeve": tk, "target": 0.0, "live": round(live[tk], 1), "rel": None, "breach": True})
        br = [d for d in drift if d["breach"]]
        if br:
            weekend.append("Drift outside ±20% band: " + ", ".join(
                f"{d['sleeve']} {d['live']:.0f}% vs {d['target']:.0f}%" for d in br[:8]))
    if heat is not None and heat > HEAT_CAP_PCT:
        weekend.append(f"Heat {heat:.1f}% exceeds the {HEAT_CAP_PCT:.0f}% cap")
    stale = ledger_age is not None and ledger_age > LEDGER_STALE_DAYS
    c = ""
    if stale:
        c += (f"⚠ The ledger was last updated {ledger_age} days ago — every line below assumes those positions "
              "still exist. Update it before acting on any of them. ")
    hits = [r["ticker"] for r in rows if r["status"] == "STOP HIT"]
    fired = [r["ticker"] for r in rows if r["inv_status"] == "FIRED"]
    if hits:
        c += f"Stops hit: {', '.join(hits)} — daily-authorized exits. "
    if fired:
        c += f"Invalidations fired: {', '.join(fired)} (weekend list). "
    if not hits and not fired:
        c += "No stop hit and no machine-checkable invalidation fired. "
    if heat is not None:
        c += f"Heat {heat:.1f}% of {HEAT_CAP_PCT:.0f}% cap (ledger market value basis; cash not in the ledger is excluded)."
    return {"available": True, "ledger_age_days": ledger_age, "stale": stale, "positions": rows,
            "heat_pct": heat, "drift": drift, "authorized_today": authorized, "weekend": weekend,
            "conclusion": c.strip()}


# ── Swing ──────────────────────────────────────────────────────────────────

def swing_section(inp: dict) -> dict:
    b, fname = inp.get("swing") or {}, inp.get("swing_file")
    if not b:
        return {"available": False, "conclusion": "No swing brief found for this session."}
    same = inp["session"].isoformat() <= str(b.get("date")) <= inp["now_et"].date().isoformat()
    cards = b.get("cards", [])
    ok = [c for c in cards if c.get("entry_permitted")]
    watch = b.get("watch", [])
    near = [w for w in watch if "2-of-3" in str(w.get("reason")) or "demoted" in str(w.get("reason"))]
    hg = b.get("hunting_grounds", {})
    c = "" if same else f"⚠ Latest swing brief is from {b.get('date')}, not this session. "
    if (b.get("data_health") or {}).get("failed"):
        c += "The swing scan FAILED on data — no verdict on setups today. "
    c += (f"{len(ok)} entry-permitted card{'s' if len(ok) != 1 else ''}"
          + (f" ({', '.join(x['ticker'] + ' ' + x['side'] + ' ' + x['confluence'] for x in ok)})" if ok else "")
          + f"; {len(near)} near-miss{'es' if len(near) != 1 else ''} building on watch.")
    secs = {c2.get("sector") for c2 in ok if c2.get("sector")}
    if len(ok) >= 2 and len(secs) == 1:
        c += f" All permitted cards are in {secs.pop()} — one sector bet, size them as one position."
    return {"available": True, "date": b.get("date"), "file": fname, "same_session": same,
            "regime": (b.get("regime") or {}).get("key"), "grounds": hg,
            "cards": cards, "permitted": ok, "near_misses": near, "refusals": b.get("refusals", []),
            "breadth": b.get("breadth"), "conclusion": c}


# ── Next 48h ───────────────────────────────────────────────────────────────

def next48_section(inp: dict, regime: dict) -> dict:
    now, session = inp["now_et"], inp["session"]
    horizon, d, n = now.date(), now.date(), 0
    while n < 2:
        d += timedelta(days=1)
        if mt.is_trading_day(d):
            n += 1
    horizon = d
    # the brief is written after the close: an event dated on the session day has already printed
    evs = [e for e in (inp.get("events") or []) if e.get("date") and e["date"] > session.isoformat()]
    within = [e for e in evs if e.get("date") and e["date"] <= horizon.isoformat()]
    nxt = next((e for e in evs if e.get("date") and e["date"] > horizon.isoformat()), None)
    flips = {f["input"]: f for f in regime.get("flips", [])}
    srr = regime.get("short_real")
    lines = []
    for e in within:
        lines.append(_if_then(e["event"], srr, flips))
    if within:
        c = ("Binary event inside the window: " + ", ".join(f"{e['event']} {e['date']}" for e in within)
             + ". No new entries in the affected sleeves until it prints.")
    else:
        c = "No scheduled binary event in the next two sessions — the event block is clear."
        if nxt:
            c += f" Next: {nxt['event']} on {nxt['date']} ({nxt['days_away']} days)."
            lines.append(_if_then(nxt["event"], srr, flips))
    return {"horizon": horizon.isoformat(), "events": within, "next_event": nxt, "if_then": lines,
            "calendar_asof": inp.get("calendar_asof"), "conclusion": c}


def _if_then(ev: str, srr, flips: dict) -> str:
    """Pre-committed lines. A flip distance is only quoted on the side of the
    outcome that moves TOWARD it, so the line says which result matters."""
    sr, lm = flips.get("short_real_rate"), flips.get("long_real_mom_3m")

    def lm_txt(direction):          # direction: +1 = yields up, -1 = yields down
        if not lm:
            return ""
        toward = (lm["delta"] > 0) == (direction > 0)
        if toward:
            return (f" DFII10 3m momentum is {abs(lm['delta']):.2f}pp from the level that flips the regime to "
                    f"`{lm['to']}` — this outcome moves toward it.")
        return " This moves away from the nearest DFII10 flip — the current regime is reinforced."

    def sr_txt(direction):          # direction of the short real rate
        if not sr:
            return ""
        toward = (sr["delta"] > 0) == (direction > 0)
        return (f" The short real rate ({_fmt(srr, 2, '%', True)}) is {abs(sr['delta']):.2f}pp from flipping the regime "
                f"to `{sr['to']}`." if toward else " The short real rate moves away from its flip.")
    if ev == "CPI":
        return ("CPI — hot (MoM ≥ 0.4%): YoY rises, so the short real rate FALLS." + sr_txt(-1)
                + " Cool (MoM ≤ 0.1%): the short real rate rises and the tightening read strengthens.")
    if ev == "FOMC":
        return ("FOMC — a 25bp cut lowers the short real rate by 0.25pp." + sr_txt(-1)
                + " A hike raises it by 0.25pp (tightening read strengthens); a hold changes the regime inputs only through DFII10.")
    if ev == "PCE":
        return ("PCE — hot core PCE pushes DFII10 up." + lm_txt(+1)
                + " Cool PCE with DFII10 reversing lower:" + lm_txt(-1).replace(" DFII10 3m", " DFII10 3m", 1))
    if ev == "NFP":
        return ("Payrolls — strong: yields up." + lm_txt(+1) + " Weak: yields down." + lm_txt(-1)
                + " Weak payrolls WITH HY widening opens the growth-scare path — watch the HY 2-week change.")
    return f"{ev} — no pre-committed rule."


# ── Alerts (from the daily log) with repetition counts ─────────────────────

def alerts_section(inp: dict) -> list[dict]:
    log = inp.get("daily_log")
    if log is None or log.empty or "alert_rules" not in log:
        return []
    lg = log.sort_values("et_date")
    today_rows = lg[lg["et_date"] == inp["session"].isoformat()]
    if today_rows.empty:
        return []
    rules = [r for r in str(today_rows["alert_rules"].iloc[-1]).split(";") if r and r != "nan"]
    hist = lg[lg["et_date"] < inp["session"].isoformat()]["alert_rules"].astype(str).tolist()
    out = []
    for r in rules:
        n = 1
        for h in reversed(hist):
            if r in h.split(";"):
                n += 1
            else:
                break
        out.append({"rule": r, "sessions": n, "repeat": n > 1})
    return out


# ── Data health ────────────────────────────────────────────────────────────

def data_health(inp: dict) -> list[dict]:
    today = inp["session"]
    wall = inp["now_et"].date()
    out = []

    def add(name, asof, max_age, note="", ref=None):
        age = _age_days(asof, ref or today)
        st = "MISSING" if asof is None else ("OK" if age is not None and age <= max_age else "STALE")
        out.append({"input": name, "asof": str(asof) if asof is not None else None, "age_days": age,
                    "status": st, "note": note})
    for label, sid, _, _ in FRED_SCORE:
        s = inp["fred"].get(sid, pd.Series(dtype=float))
        note = (inp.get("fred_src") or {}).get(sid, "")
        if sid in FRED_MAX_AGE:
            note = (note + "; " if note else "") + "weekly release (Mondays) — a week's lag is normal"
        add(f"FRED {sid}", s.index[-1].date().isoformat() if len(s) else None, FRED_MAX_AGE.get(sid, 4), note)
    a = inp.get("assessment")
    add("Regime assessment", today.isoformat() if a else None, 0, "" if a else "live assessment failed")
    rot = inp.get("rotation") or {}
    add("Money Flow bridge", (rot.get("published_at") or "")[:10] or None, 1, ref=wall)
    mk = inp.get("markets") or {}
    add("Markets bridge", (mk.get("published_at") or "")[:10] or None, 1, ref=wall)
    b = inp.get("swing") or {}
    add("Swing brief", b.get("date"), 0 if not b.get("date") or b.get("date") <= today.isoformat() else 9,
        "" if not b.get("date") or b.get("date") <= today.isoformat() else "run after the close — scans this session")
    led = inp.get("ledger")
    lu = pd.to_datetime(led.get("last_updated"), errors="coerce").max() if led is not None and not led.empty else None
    add("Position ledger", lu.date().isoformat() if lu is not None and pd.notna(lu) else None, LEDGER_STALE_DAYS, ref=wall)
    log = inp.get("daily_log")
    last_log = str(log["et_date"].max()) if log is not None and not log.empty else None
    add("Daily log row", last_log, 0, "" if last_log == today.isoformat() else "today's daily log not written yet — alerts section uses no row")
    cot = (rot.get("cot") or [])
    if cot:
        add("COT (freshest)", max(str(c.get("report_date")) for c in cot), 14)
    mf = (a or {}).get("macro_flags") or {}
    for w in mf.get("warnings", []) if mf else []:
        out.append({"input": "macro_flags", "asof": None, "age_days": None, "status": "WARN", "note": w})
    px = inp.get("prices") or {}
    if not px:
        out.append({"input": "Prices (yfinance)", "asof": None, "age_days": None, "status": "MISSING", "note": ""})
    else:
        lasts = [df.index[-1] for df in px.values() if df is not None and not df.empty]
        ref = max(lasts) if lasts else None
        add("Prices (yfinance)", pd.to_datetime(ref).date().isoformat() if ref is not None else None, 0,
            f"{len(px)} tickers")
    if inp.get("calendar_asof"):
        out.append({"input": "Event calendar", "asof": inp["calendar_asof"], "age_days": None, "status": "OK",
                    "note": "hardcoded dates; re-verify every January"})
    return out


# ═══════════════════════════════════════════════════════════════════════════
#  Assembly
# ═══════════════════════════════════════════════════════════════════════════

def build(inp: dict) -> dict:
    a = inp.get("assessment") or {}
    sb = scoreboard(inp)
    rg = regime_section(inp)
    xa = cross_asset_section(inp, rg.get("key"))
    ro = rotation_section(inp)
    fl = flow_section(inp)
    br = breadth_section(inp)
    targets = a.get("targets") or (inp.get("markets") or {}).get("regime_targets") or {}
    pf = portfolio_section(inp, targets, rg.get("key"))
    sw = swing_section(inp)
    nx = next48_section(inp, rg)
    al = alerts_section(inp)
    dh = data_health(inp)
    brief = {"session": inp["session"].isoformat(), "generated_et": mt.fmt_et(inp["now_et"]),
             "scoreboard": sb, "regime": rg, "cross_asset": xa, "rotation": ro, "flow": fl,
             "breadth": br, "portfolio": pf, "swing": sw, "next48": nx, "alerts": al,
             "data_health": dh, "errors": inp.get("errors", []), "targets": targets}
    brief["headline"] = headline(brief)
    brief["conclusions"] = conclusions(brief)
    return brief


def headline(b: dict) -> list[str]:
    sb, rg, pf, sw = b["scoreboard"], b["regime"], b["portfolio"], b["swing"]
    # 1 — what changed
    mv = sb.get("movers") or []
    if mv:
        sess = b["session"]

        def _when(r):
            a = r.get("asof") or ""
            return f", print dated {a[5:]}" if a[:4].isdigit() and a < sess else ""
        s1 = "Biggest moves: " + "; ".join(
            f"{r['name']} {r['d1_txt']} to {_fmt(r['value'], 2)}{r['unit'] if r['unit'] in ('%',) else ''} "
            f"({r['z1d']:+.1f}σ{', ' + format(r['pctile_1y'], '.0f') + 'th pctile' if r['pctile_1y'] is not None else ''}{_when(r)})"
            for r in mv[:2]) + "."
    else:
        s1 = "A normal-range session: no scoreboard input moved more than 1.5σ."
        ext = [r for r in sb.get("extremes") or [] if r["name"] != "Equal/cap weight (RSP/SPY)"][:2]
        if ext:
            s1 += " Still at 1-year extremes: " + ", ".join(
                f"{r['name']} {_fmt(r['value'], 2)}{'%' if r['unit'] == '%' else ''} ({r['pctile_1y']:.0f}th pctile)" for r in ext) + "."
    if rg.get("previous_regime") and rg.get("days_in_regime") == 1:
        s1 += f" The regime changed to `{rg['key']}` from `{rg['previous_regime']}`."
    # 2 — what it means
    s2 = f"Regime `{rg.get('key')}`"
    if rg.get("days_in_regime"):
        s2 += f" (session {rg['days_in_regime']}{' — needs a second close' if rg['days_in_regime'] == 1 else ''})"
    xa = b["cross_asset"]
    if xa.get("available"):
        s2 += f"; cross-asset majority {xa.get('majority')}"
    near = (rg.get("flips") or [None])[0]
    if near:
        s2 += (f"; nearest flip is {near['label']} {near['delta']:+.2f}{near['unit']} to `{near['to']}`"
               + (f" (~{near['typical_days']:.0f} typical days)" if near.get("typical_days") is not None else ""))
    s2 += "."
    # 3 — what is authorized
    auth = (pf.get("authorized_today") or []) if pf.get("available") else []
    if auth:
        s3 = "Authorized today: " + "; ".join(a.split(" —")[0] for a in auth) + "."
        if pf.get("stale"):
            s3 += f" (Ledger is {pf['ledger_age_days']} days old — confirm the positions exist first.)"
    else:
        s3 = "Nothing is authorized today under the daily rule"
        wk = len(pf.get("weekend") or []) if pf.get("available") else 0
        s3 += f"; {wk} item{'s' if wk != 1 else ''} queued for the weekend review." if wk else "."
    if sw.get("available") and sw.get("permitted"):
        s3 += f" Swing: {len(sw['permitted'])} entry-permitted card{'s' if len(sw['permitted']) != 1 else ''}."
    return [s1, s2, s3]


def conclusions(b: dict) -> dict:
    rg, xa, ro, pf, br = b["regime"], b["cross_asset"], b["rotation"], b["portfolio"], b["breadth"]
    base = f"Base case: `{rg.get('key')}` holds."
    if xa.get("available"):
        base += f" Cross-asset: {xa.get('majority')} majority" + (
            f", dissent from {', '.join(xa.get('dissenters') or [])}." if xa.get("dissenters") else ", aligned.")
    if ro.get("grounds", {}).get("long"):
        base += f" Money is confirming only {', '.join(ro['grounds']['long'])}."
    change = []
    top = list((rg.get("flips") or [])[:3])
    sr = next((f for f in (rg.get("flips") or []) if f["input"] == "short_real_rate"), None)
    if sr and sr not in top and abs(sr["delta"]) <= 0.5:
        top.append(sr)                       # one FOMC/CPI print away: always worth naming
    for f in top:
        change.append(f"{f['label']} {_fmt(f['now'], 2)}{f['unit']} → {_fmt(f['at'], 2)}{f['unit']} flips to `{f['to']}`"
                      + (f" (~{f['typical_days']:.0f} typical days)" if f.get("typical_days") is not None else "")
                      + (f" — {f['note']}" if f.get("note") else ""))
    weekend = list(pf.get("weekend") or []) if pf.get("available") else []
    if rg.get("days_in_regime") == 2:
        weekend.insert(0, f"Regime `{rg['key']}` confirmed on two closes — rebalance to its targets (cuts, then hedges, then adds)")
    if pf.get("stale"):
        weekend.insert(0, f"Update the position ledger (last touched {pf['ledger_age_days']} days ago)")
    return {"base_case": base, "what_would_change": change, "weekend": weekend}


# ═══════════════════════════════════════════════════════════════════════════
#  Rendering
# ═══════════════════════════════════════════════════════════════════════════

def render_md(b: dict) -> str:
    L = [f"# Consolidated daily brief — {b['session']}",
         f"*Generated {b['generated_et']} · every number computed from data; every interpretive line is a rule "
         f"applied to it. Desk research, not personalized advice.*", ""]
    L += ["## 1 · Headline", *[f"{s}" for s in b["headline"]], ""]

    sb = b["scoreboard"]
    L += ["## 2 · Scoreboard", "| Metric | Value | Δ1d | Δ5d | Δ20d | 1-yr pctile | Today in σ | As of |",
          "|---|---|---|---|---|---|---|---|"]
    for r in sb["rows"]:
        L.append(f"| {r['name']} | {_fmt(r['value'], 2)}{r['unit'] if r['unit'] == '%' else ''} | {r['d1_txt']} | {r['d5_txt']} | "
                 f"{r['d20_txt']} | {_fmt(r['pctile_1y'], 0)} | {_fmt(r['z1d'], 1, 'σ', True) if r['z1d'] is not None else 'n/a'} | {r['asof'] or 'n/a'} |")
    L += ["", f"**Conclusion:** {sb['conclusion']}", ""]

    rg = b["regime"]
    L += ["## 3 · Regime (Level 1)",
          f"- **`{rg.get('key')}`** — {rg.get('label', '')} · source: {rg.get('source')}"]
    if rg.get("repression"):
        r = rg["repression"]
        L.append(f"- Repression score {r.get('score')}/10 ({r.get('band')}){' · HOLLOW' if r.get('hollow') else ''}")
    if rg.get("confirm"):
        L.append(f"- {rg['confirm']}")
    if rg.get("band_state"):
        L.append(f"- Short real rate {_fmt(rg.get('short_real'), 2, '%', True)} — band {rg['band_state']} (±{BAND:.2f}%)"
                 + (f", {rg['band_sessions']} logged sessions on this side" if rg.get("band_sessions") else ""))
    for d in rg.get("drivers", [])[:6]:
        L.append(f"  - {d}")
    if rg.get("flips"):
        L += ["", "**Nearest flips** (classifier re-run with one input moved, all else held):", "",
              "| Input | Now | Flips at | Move needed | Typical days | Becomes |", "|---|---|---|---|---|---|"]
        for f in rg["flips"]:
            L.append(f"| {f['label']} | {_fmt(f['now'], 2)}{f['unit']} | {_fmt(f['at'], 2)}{f['unit']} | "
                     f"{f['delta']:+.2f}{f['unit']} | {_fmt(f.get('typical_days'), 0) if f.get('typical_days') is not None else (f.get('note') or 'n/a')} | `{f['to']}` |")
    elif rg.get("flip_error"):
        L.append(f"- Nearest flip: {rg['flip_error']}")
    if rg.get("guards"):
        L += ["", "Guard inputs:", *[f"- {g}" for g in rg["guards"]]]
    L += ["", f"**Conclusion:** {rg['conclusion']}", ""]

    xa = b["cross_asset"]
    L += ["## 4 · Cross-asset confirmation"]
    if xa.get("available"):
        L += ["| Lane | Vote | Reading | Why |", "|---|---|---|---|"]
        for k, v in xa.get("lanes", {}).items():
            L.append(f"| {k} | {v.get('state')} | {v.get('reading')} | {str(v.get('note', ''))[:160]} |")
    L += ["", f"**Conclusion:** {xa['conclusion']}", ""]

    ro = b["rotation"]
    L += ["## 5 · Rotation (Level 2)"]
    if ro.get("available"):
        L += ["| Sector | Quadrant | Direction | Accumulation | Price & money agree | Prior |", "|---|---|---|---|---|---|"]
        for s in ro["sectors"]:
            L.append(f"| {s['ticker']} {s.get('sector') or ''} | {s['quadrant']} | {s.get('direction') or ''} | "
                     f"{_fmt(s['accumulation'], 1)}{' 🔍' if s.get('stealth') else ''} | {'✅' if s['agree'] else '—'} | {s.get('prior_quadrant') or ''} |")
        L.append("")
        L.append("Quadrant changes since the last brief: " + ("; ".join(ro["changes"]) if ro["changes"] else
                 ("none" if ro.get("has_prior") else "no prior brief to compare (first run)")))
    L += ["", "**Rotation compass** (ratio change; ↑ = first leg outperforming)", "",
          "| Pair | 20d | 60d | Trend | Read |", "|---|---|---|---|---|"]
    for c in ro.get("compass", []):
        L.append(f"| {c['name']} | {_fmt(c['r20'], 1, '%', True)} | {_fmt(c['r60'], 1, '%', True)} | {c['arrow']} | {c['read']} |")
    L += ["", f"**Conclusion:** {ro['conclusion']}", ""]

    fl = b["flow"]
    L += ["## 6 · Flow (Tier A integrity-passed only, + COT)"]
    if fl.get("confirmed"):
        L += ["| ETF | Price 20d | Net flow % AUM | Verdict |", "|---|---|---|---|"]
        for d in fl["confirmed"]:
            L.append(f"| {d['ticker']} | {_fmt(d.get('price_chg_pct'), 1, '%', True)} | {_fmt(d.get('net_flow_pct_aum'), 2, '%', True)} | {d.get('verdict')} |")
    if fl.get("unreliable"):
        L.append(f"\nExcluded as unreliable (source too new or artifact): {', '.join(fl['unreliable'])}")
    if fl.get("cot"):
        L += ["", "| COT contract | Sleeve | Report | Age | Read |", "|---|---|---|---|---|"]
        for c in fl["cot"]:
            L.append(f"| {c['contract']} | {c['sleeve']} | {c['report_date']} | {_fmt(c['age_days'], 0)}d{' STALE' if c['stale'] else ''} | {c['flag']} |")
    L += ["", f"**Conclusion:** {fl['conclusion']}", ""]

    br = b["breadth"]
    L += ["## 7 · Breadth & internals",
          f"- % above 50-day: **{_fmt(br.get('pct_above_50'), 0)}%** · above 200-day: **{_fmt(br.get('pct_above_200'), 0)}%** "
          f"· 52-wk highs/lows: {br.get('new_highs', 'n/a')}/{br.get('new_lows', 'n/a')} · universe: {br.get('universe')}",
          f"- SPY 20d {_fmt(br.get('spy_20d'), 1, '%', True)} vs RSP (equal weight) 20d {_fmt(br.get('rsp_20d'), 1, '%', True)}",
          "", f"**Conclusion:** {br['conclusion']}", ""]

    pf = b["portfolio"]
    L += ["## 8 · Portfolio (Levels 5–7)"]
    if pf.get("available"):
        if pf.get("stale"):
            L.append(f"> ⚠ **Ledger last updated {pf['ledger_age_days']} days ago.** Positions below may not reflect your account.")
        L += ["| Position | Close | Stop | Stop status | Invalidation | Check |", "|---|---|---|---|---|---|"]
        for r in pf["positions"]:
            L.append(f"| {r['ticker']} | {_fmt(r['last'])} | {_fmt(r['stop'])} | {r['status']} — {r['note']} | "
                     f"{r['invalidation'][:70]} | **{r['inv_status']}** {r['inv_detail']} |")
        if pf.get("drift"):
            br_ = [d for d in pf["drift"] if d["breach"]]
            L += ["", f"Drift vs `{b['regime'].get('key')}` targets (ledger-value basis): "
                  + (", ".join(f"{d['sleeve']} {d['live']:.1f}% vs {d['target']:.1f}%" for d in br_) if br_ else "all sleeves inside ±20%")]
        if pf.get("authorized_today"):
            L += ["", "**Authorized today:**", *[f"- {x}" for x in pf["authorized_today"]]]
    L += ["", f"**Conclusion:** {pf['conclusion']}", ""]

    sw = b["swing"]
    L += ["## 9 · Swing (Level 4)"]
    if sw.get("available"):
        hg = sw.get("grounds", {})
        L.append(f"- Grounds — long: {', '.join(s['ticker'] for s in hg.get('long', [])) or 'none'} · "
                 f"short: {', '.join(s['ticker'] for s in hg.get('short', [])) or 'none'} · "
                 f"watch (price and money disagree): {', '.join(s['ticker'] for s in hg.get('long_watch', []) + hg.get('short_watch', [])) or 'none'}")
        for c in sw.get("cards", []):
            L.append(f"- **{c['ticker']}** {c['setup']} {c['side']} {c['confluence']} · entry {c['entry']} · stop {c['stop']} "
                     f"({c['stop_pct']}%) · {'ENTRY PERMITTED' if c['entry_permitted'] else 'not permitted — ' + str(c.get('entry_block_reason'))}")
        if sw.get("near_misses"):
            L += ["- Near-misses:", *[f"  - {w['ticker']}: {w['reason'][:170]}" for w in sw["near_misses"]]]
    L += ["", f"**Conclusion:** {sw['conclusion']}", ""]

    nx = b["next48"]
    L += [f"## 10 · Next 48 hours (through {nx['horizon']})"]
    for e in nx["events"]:
        L.append(f"- **{e['event']}** {e['date']} — affects {e['affects']}")
    for s in nx["if_then"]:
        L.append(f"- If/then: {s}")
    L += ["", f"**Conclusion:** {nx['conclusion']}", ""]

    if b.get("alerts"):
        L += ["### Alerts from today's daily log"]
        for a in b["alerts"]:
            L.append(f"- `{a['rule']}`" + (f" — repeat, session {a['sessions']} in a row (no new information)" if a["repeat"] else " — new today"))
        L.append("")

    cc = b["conclusions"]
    L += ["## 11 · Conclusions", f"- **{cc['base_case']}**"]
    if cc["what_would_change"]:
        L += ["- **What would change it:**", *[f"  - {x}" for x in cc["what_would_change"]]]
    L += ["- **Weekend review list:**", *([f"  - {x}" for x in cc["weekend"]] or ["  - nothing queued"])]
    L += ["", f"_Daily rule: {DAILY_RULE}_", ""]

    L += ["## 12 · Data health", "| Input | As of | Age | Status | Note |", "|---|---|---|---|---|"]
    for d in b["data_health"]:
        L.append(f"| {d['input']} | {d['asof'] or '—'} | {'' if d['age_days'] is None else str(d['age_days']) + 'd'} | "
                 f"{'✅' if d['status'] == 'OK' else '⚠'} {d['status']} | {d['note']} |")
    if b.get("errors"):
        L += ["", "Errors this run:", *[f"- {e}" for e in b["errors"]]]
    return "\n".join(L)


def _jsonable(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, (date, datetime, pd.Timestamp)):
        return str(o)
    return str(o)


def write(b: dict) -> dict:
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    mp = SUMMARY_DIR / f"{b['session']}_brief.md"
    jp = STATE_DIR / f"{b['session']}_brief.json"
    mp.write_text(render_md(b), encoding="utf-8")
    jp.write_text(json.dumps(b, default=_jsonable, indent=1), encoding="utf-8")
    return {"md": str(mp), "json": str(jp)}


def run(fred_key: str = "", **kw) -> dict:
    inp = gather(fred_key=fred_key, **kw)
    return build(inp)


# ═══════════════════════════════════════════════════════════════════════════
#  Selftest (offline, synthetic)
# ═══════════════════════════════════════════════════════════════════════════

def selftest() -> dict:
    import tempfile
    from types import SimpleNamespace
    f = []
    rng = np.random.default_rng(3)
    idx = pd.bdate_range(end="2026-09-25", periods=520)

    def walk(v0, sd):
        return pd.Series(v0 + np.cumsum(rng.normal(0, sd, len(idx))), index=idx)
    fred = {"DFII10": walk(2.0, 0.04), "DGS10": walk(4.0, 0.05), "DGS2": walk(3.7, 0.05), "T10YIE": walk(2.3, 0.02),
            "BAMLH0A0HYM2": walk(3.0, 0.03).clip(lower=2.5), "BAMLC0A0CM": walk(0.9, 0.01),
            "DTWEXBGS": walk(120, 0.3), "VIXCLS": walk(16, 0.6).clip(lower=10), "DCOILWTICO": walk(70, 1.0),
            "DGS30": walk(4.6, 0.05)}
    fred["DFII10"].iloc[-1] = fred["DFII10"].iloc[-2] + 0.20        # a 5σ day
    fred["VIXCLS"] = fred["VIXCLS"].iloc[:-2]                        # FRED lags the market
    fetch_fred = lambda sid, key="", start="": fred.get(sid, pd.Series(dtype=float))

    def px(v0, drift=0.0005):
        c = v0 * np.exp(np.cumsum(rng.normal(drift, 0.01, len(idx))))
        return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6}, index=idx)
    tickers = {t for _, a, b in COMPASS for t in a + b} | {"QQQ", "GLD", "TLT", "XOM", "CVX", "NVDA", "AAPL"}
    prices = {t: px(100) for t in tickers}
    prices["TLT"] = px(100, drift=-0.001)
    prices["^VIX"] = px(16, drift=0.0)

    sig = SimpleNamespace(short_real_rate=0.48, long_real_yield=2.85, long_real_mom_3m=0.66, breakeven_10y=2.3,
                          hy_oas=2.8, hy_oas_mom_2w=0.1, spread_2s10s=0.3, spread_2s10s_mom_3m=0.0,
                          dxy_20d_change_pct=1.0, stock_bond_corr_60d=0.48, asof=None,
                          cpi_yoy=3.4, cpi_3m_saar=0.2, cpi_mom_sa=0.4, eff_funds=3.88, ig_oas=0.9, dxy=120)
    import regime_classifier as rc
    reg = rc.classify_regime(sig, fetch_prices=None, cape=40.0, top20_concentration_pct=49.0)
    assessment = {"signals": sig, "regime": reg, "repression": {"score": 3, "band": "Tightening cycle", "hollow": True},
                  "targets": {"VGT": 17.0, "TLT": 2.0, "SGOV": 11.0, "KMLM": 8.0},
                  "macro_flags": {}, "_fetch_prices": None}
    tmp = tempfile.mkdtemp()
    cwd = os.getcwd()
    try:
        os.chdir(tmp)
        os.makedirs("logs/swing"); os.makedirs("data")
        pd.DataFrame([{"et_date": "2026-09-23", "regime": "transition_ambiguous", "short_real_rate": 0.48,
                       "alert_rules": "short_real_band;dfii10_level", "gold_gate": "FAIL"},
                      {"et_date": "2026-09-24", "regime": reg["key"], "short_real_rate": 0.48,
                       "alert_rules": "short_real_band", "gold_gate": "FAIL"},
                      {"et_date": "2026-09-25", "regime": reg["key"], "short_real_rate": 0.48,
                       "alert_rules": "short_real_band;cpi_mixed_signal", "gold_gate": "FAIL"}]).to_csv("logs/daily_log.csv", index=False)
        json.dump({"published_at": "2026-09-25T22:00:00+00:00", "sectors": [
            {"ticker": "XLK", "sector": "Technology", "quadrant": "Leading", "accumulation_score": 50, "rotation_direction": "Strengthening"},
            {"ticker": "XLE", "sector": "Energy", "quadrant": "Improving", "accumulation_score": -40}],
            "constituents": {"XLK": ["NVDA", "AAPL"], "XLE": ["XOM", "CVX"]},
            "flow_divergences": [{"ticker": "XLK", "price_chg_pct": 4.7, "net_flow_pct_aum": 1.5, "verdict": "CONFIRMED UPTREND"},
                                 {"ticker": "TLT", "price_chg_pct": -4, "net_flow_pct_aum": None, "verdict": "UNRELIABLE — new source"}],
            "cot": [{"contract": "GOLD", "sleeve": "GLD", "report_date": "2026-09-22", "age_days": 3, "stale": False,
                     "flag": "noncomm crowded LONG (91th pctile)"}]}, open("data/rotation_summary.json", "w"))
        json.dump({"published_at": "2026-09-25T22:00:00+00:00", "regime": {"key": "transition_ambiguous"}},
                  open("data/markets_summary.json", "w"))
        json.dump({"date": "2026-09-25", "cards": [
            {"ticker": "XLK", "setup": "M0 Rotation", "side": "long", "confluence": "3-of-3", "entry": 196.9, "stop": 190.7,
             "stop_pct": 3.2, "entry_permitted": True, "sector": "XLK"},
            {"ticker": "NVDA", "setup": "M0 Rotation", "side": "long", "confluence": "2-of-3", "entry": 226.9, "stop": 219.1,
             "stop_pct": 3.4, "entry_permitted": True, "sector": "XLK"}],
            "watch": [{"ticker": "XLE", "reason": "M0 Rotation long (2-of-3) demoted — flow does not confirm"}],
            "hunting_grounds": {"long": [{"ticker": "XLK"}], "short": [], "long_watch": [{"ticker": "XLE"}]}},
            open("logs/swing/2026-09-25_brief.json", "w"))
        pd.DataFrame([{"ticker": "TLT", "shares": 100, "entry_price": 120, "stop": 110, "stop_basis": "ATR",
                       "thesis": "", "invalidation": "DFII10 closes back above 2.50%", "sleeve": "TLT",
                       "last_updated": "2026-07-26T00:00:00"},
                      {"ticker": "SGOV", "shares": 100, "entry_price": 100.5, "stop": 100.4, "stop_basis": "",
                       "thesis": "", "invalidation": "", "sleeve": "SGOV", "last_updated": "2026-07-26T00:00:00"},
                      {"ticker": "VGT", "shares": 50, "entry_price": 90, "stop": 80, "stop_basis": "",
                       "thesis": "", "invalidation": "FOMC language changes", "sleeve": "VGT",
                       "last_updated": "2026-07-26T00:00:00"}]).to_csv("data/positions.csv", index=False)
        prices["SGOV"] = px(100.4, 0.0001); prices["VGT"] = px(100)
        os.environ["DATA_DIR"] = "data"
        import importlib, storage_backend, position_ledger
        importlib.reload(storage_backend); importlib.reload(position_ledger)
        now = datetime(2026, 9, 25, 20, 0)
        inp = gather(today_et=now, fetch_fred=fetch_fred, fetch_prices=lambda tks: {t: prices[t] for t in tks if t in prices},
                     assess=lambda: assessment, macro_lookup=lambda d: [
                         {"event": "NFP", "date": "2026-10-02", "days_away": 7, "affects": "rates", "blackout": False}])
        b = build(inp)
        md = render_md(b)
        out = write(b)

        vix = next(r for r in b["scoreboard"]["rows"] if r["name"] == "VIX")
        if vix["asof"] != "2026-09-25" or "yfinance ^VIX" not in (inp.get("fred_src") or {}).get("VIXCLS", ""):
            f.append(f"lagging FRED VIX must be extended with the yfinance close: {vix['asof']} {inp.get('fred_src')}")
        json.dump({"date": "2026-09-26", "cards": [], "watch": [], "hunting_grounds": {}},
                  open("logs/swing/2026-09-26_brief.json", "w"))
        sb_, fn_ = _latest_swing(date(2026, 9, 25), date(2026, 9, 27))
        if fn_ != "2026-09-26_brief.json":
            f.append(f"a Saturday swing run is the Friday session's scan and must be picked: {fn_}")
        os.remove("logs/swing/2026-09-26_brief.json")
        if b["session"] != "2026-09-25":
            f.append(f"session date wrong: {b['session']}")
        dfii = next(r for r in b["scoreboard"]["rows"] if r["name"].startswith("10Y real"))
        if dfii["z1d"] is None or dfii["z1d"] < 3 or dfii not in b["scoreboard"]["movers"]:
            f.append(f"a +20bp DFII10 day must register as a large σ move: {dfii['z1d']}")
        if abs(dfii["d1"] - 0.20) > 1e-6 or dfii["d1_txt"] != "+20bp":
            f.append(f"Δ1d for a rate must be in bp: {dfii['d1_txt']}")
        rg = b["regime"]
        if rg["key"] != reg["key"] or rg["days_in_regime"] != 2 or "Confirmed on two" not in rg["confirm"]:
            f.append(f"days-in-regime/two-close wrong: {rg.get('days_in_regime')} {rg.get('confirm')}")
        if not rg["flips"]:
            f.append(f"nearest flips must be found: {rg.get('flip_error')}")
        else:
            for fl in rg["flips"]:
                s2 = SimpleNamespace(**vars(sig)); setattr(s2, fl["input"], fl["at"]) if fl["input"] in vars(sig) else None
                if fl["input"] in vars(sig):
                    k2 = rc.classify_regime(s2, fetch_prices=None, cape=40.0, top20_concentration_pct=49.0)["key"]
                    if k2 == reg["key"]:
                        f.append(f"flip point for {fl['input']} at {fl['at']} does not change the regime")
            sr = [x for x in rg["flips"] if x["input"] == "short_real_rate"]
            if not sr or abs(sr[0]["at"] - BAND) > 0.02:
                f.append(f"short real flip should sit at the +{BAND} band edge: {sr}")
        if rg["bridge_agrees"] is not False or "republish" not in rg["conclusion"]:
            f.append("bridge disagreement must be named")
        pf = b["portfolio"]
        tlt = next(r for r in pf["positions"] if r["ticker"] == "TLT")
        if tlt["inv_status"] != "FIRED":
            f.append(f"TLT invalidation 'DFII10 above 2.50%' with DFII10 2.85 must FIRE: {tlt}")
        sg = next(r for r in pf["positions"] if r["ticker"] == "SGOV")
        if sg["status"] != "CASH":
            f.append("cash sleeves must be exempt from ATR stops")
        vgt = next(r for r in pf["positions"] if r["ticker"] == "VGT")
        if vgt["inv_status"] != "MANUAL":
            f.append("unrecognised invalidation text must be MANUAL, never guessed")
        if not pf["stale"] or "Update the position ledger" not in b["conclusions"]["weekend"][0]:
            f.append("a 2-month-old ledger must be flagged first on the weekend list")
        if tlt["status"] == "STOP HIT" and not pf["authorized_today"]:
            f.append("a stop hit must be listed as authorized today")
        ro = b["rotation"]
        if ro["grounds"]["long"] != ["XLK"] or ro["grounds"]["price_only"] != ["XLE"]:
            f.append(f"rotation grounds must be flow-signed: {ro['grounds']}")
        if "singular" not in ro["conclusion"]:
            f.append("single confirmed sector must read as singular leadership")
        if len(ro["compass"]) != len(COMPASS) or any(c["r20"] is None for c in ro["compass"]):
            f.append(f"compass incomplete: {[c['name'] for c in ro['compass'] if c['r20'] is None]}")
        fl = b["flow"]
        if [d["ticker"] for d in fl["confirmed"]] != ["XLK"] or fl["unreliable"] != ["TLT"]:
            f.append("UNRELIABLE flow rows must be excluded from the confirmed table")
        sw = b["swing"]
        if len(sw["permitted"]) != 2 or "one sector bet" not in sw["conclusion"]:
            f.append("two permitted cards in one sector must be called one bet")
        al = {a["rule"]: a for a in b["alerts"]}
        if al.get("short_real_band", {}).get("sessions") != 3 or al.get("cpi_mixed_signal", {}).get("repeat"):
            f.append(f"alert repetition counts wrong: {b['alerts']}")
        nx = b["next48"]
        if nx["events"] or not nx["next_event"] or "NFP" not in nx["conclusion"]:
            f.append("no event in window must name the next one")
        if not any(d["input"] == "Position ledger" and d["status"] == "STALE" for d in b["data_health"]):
            f.append("data health must mark the ledger STALE")
        for sec in ("## 1 ·", "## 6 ·", "## 12 ·", "**Conclusion:**"):
            if sec not in md:
                f.append(f"render missing {sec}")
        if not Path(out["md"]).exists() or not Path(out["json"]).exists():
            f.append("files not written")
        # second run next session: quadrant change + counter-clockwise flag
        rot = json.load(open("data/rotation_summary.json"))
        rot["sectors"][0]["quadrant"] = "Improving"          # Leading -> Improving is counter-clockwise
        json.dump(rot, open("data/rotation_summary.json", "w"))
        inp2 = gather(today_et=datetime(2026, 9, 28, 20, 0), fetch_fred=fetch_fred,
                      fetch_prices=lambda tks: {t: prices[t] for t in tks if t in prices},
                      assess=lambda: assessment, macro_lookup=lambda d: [])
        b2 = build(inp2)
        if not b2["rotation"]["ccw"] or "XLK Leading → Improving" not in b2["rotation"]["changes"][0]:
            f.append(f"counter-clockwise move must be flagged: {b2['rotation']['changes']} {b2['rotation']['ccw']}")
        # assessment failure degrades loudly
        def boom():
            raise RuntimeError("FRED down")
        b3 = build(gather(today_et=now, fetch_fred=fetch_fred, fetch_prices=lambda tks: {},
                          assess=boom, macro_lookup=lambda d: []))
        if "failed" not in b3["regime"]["conclusion"] or not any("assessment failed" in e for e in b3["errors"]):
            f.append("a failed assessment must be named, not silently replaced")
        render_md(b3)
    finally:
        os.chdir(cwd)
    return {"ok": not f, "failures": f}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dry", action="store_true", help="print, do not write")
    a = ap.parse_args()
    if a.selftest:
        print(json.dumps(selftest(), indent=2)); sys.exit(0)
    b = run(fred_key=os.environ.get("FRED_API_KEY", ""))
    if a.dry:
        print(render_md(b))
    else:
        print(json.dumps(write(b), indent=2))
        print(render_md(b))
