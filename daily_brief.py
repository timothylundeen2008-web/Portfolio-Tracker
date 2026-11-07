"""
daily_brief.py  (v1.6 — November 2026)
─────────────────────────────────────
v1.6 (2026-11-07, fix_status N12/N37-N41): cross-asset lanes get 20-session
  credit and real-yield momentum (credit WATCH at +30bp/20 sessions; rates
  note shows both horizons). Model section adds book_risk.py readings:
  attribution by sleeve and bucket (5 / 20 sessions / since inception), AI-
  factor exposure (regression on SPY and SMH − SPY, PROPOSED limits 12% /
  40% of variance), and a volatility-target readout (9% target, display
  only, not applied). Scoreboard adds the market-implied policy path
  (2Y − fed funds, 3M bill − fed funds; FRED DFF, DTB3).
v1.5.4 (2026-11-01, fix_status N33): WTI is ONE price series throughout —
  the NYMEX front-month settle — instead of FRED's EIA Cushing spot for the
  history plus futures for the last 1-3 days. On 10/27 the two differed by
  $3.50 (steep backwardation), so the 5-day change spanned two price
  definitions. Now: Yahoo's daily CL=F bars for completed sessions (Yahoo
  overwrites them with the settle), the rebuilt 14:28-14:30 VWAP for the
  latest; the latest daily bar is never used on its own (it can still be a
  last trade) and partial next-day bars are dropped. Front-month expiries
  (NYMEX rule) are named when a change spans a roll. With no futures history
  the series is FRED spot ONLY — futures are never spliced onto spot again.
  The data-health note reports Yahoo daily vs the rebuilt settle on earlier
  sessions (the method check) and FRED spot minus settle (a market spread).
v1.5.3 (2026-11-01, fix_status N29): WTI after FRED's last date is the
  NYMEX settlement, rebuilt from Yahoo 1-minute CL=F bars as the volume-
  weighted price from 2:28 to 2:30pm ET (how NYMEX settles WTI), for sessions
  whose 2:30pm has passed. The daily CL=F "close" it replaces is the last
  trade (to 5pm, and a partial next-day bar after the 6pm reopen): 10/30
  printed 102.95 against a 104.12 settle. With no minute bars, nothing is
  spliced and FRED's own last value shows with its real age. Each run notes
  the rebuilt settle's gap to FRED on days both exist.
v1.5.2 (2026-11-01, N23): the "Event calendar" data-health row reports
  event_calendar.coverage() (OK / WARN 45 days before a typed schedule runs
  out / STALE) instead of a fixed OK, and US elections (computed by the
  calendar) get a pre-committed line in "Next 48 hours".
v1.5.1 (2026-11-01, N32): the top-10 verdict says "Driven by the top 10"
  (was "Carried by", which read oddly for a decline).
v1.5 (2026-11-01): section 7 gains two tables.
  * Breadth trend: % of the constituent proxy above its 50- and 200-day, and
    52-week highs minus lows, today and 5 / 20 / 60 sessions ago, each from
    closes up to that session. A 10-point move in 20 sessions is a trend; a
    falling trend under a rising SPY is flagged as narrowing.
  * Top-10 contribution: SPY's 10 largest holdings (State Street daily file),
    their 1- and 20-day returns and points contributed, with the rest of the
    index's return backed out. Verdict: carried by the top 10 / in line /
    leaders lagging, by their share of the move versus their weight.
v1.4 (2026-11-01): section 6A carries the Flow Map v1.2 verdict as published:
  firm or BORDERLINE (within one typical day of the ±0.25% line), the
  recommended steps for the model portfolio and the swing book, and a regime
  cross-check (does flow confirm, contradict, or say nothing about the
  regime's tilt, taken from swing_desk.REGIME_DIRECTION). A firm flow call is
  logged to signal_outcomes (flow_into_stocks / flow_out_of_stocks) so it is
  scored; borderline days are not signals.
v1.3 (2026-10-31): section 6A "Where the money went". Reads
  flow_map_summary.json (published by Money_Flow publish_to_checklist v1.1):
  20-session net ETF creations minus redemptions by asset class, trusted
  funds only, with the Flow Map's verdict / evidence / rule / what would
  change it. Funds that fail the integrity test are listed as not measured,
  never counted as zero. A missing or stale (>36h) summary is said plainly,
  and is a data-health row.
v1.2 (2026-10-31): section 1A "Market read". Four diagnoses, each printed as
  verdict / evidence (numbers with their dates) / the rule applied / what
  would change it: what moved long yields (10Y split exactly into real +
  breakeven), concentrated or broad (cap vs equal weight vs Nasdaq-100,
  breadth), de-risking or rotation (stocks, gold, Treasuries, VIX, credit),
  and distance to stress (credit and VIX vs the cross-asset lanes' own lines,
  in typical days). Built only from data the brief already gathers.
  Thresholds are named READ_* / LANE_*; the selftest asserts the LANE_* lines
  match cross_asset.py.
v1.1 (2026-10-31): section 4 prints each cross-asset lane's full "why" note.
  v1 cut it at 160 characters, which dropped the rates lane's term-premium
  diagnosis mid-sentence. Selftest now asserts the full note is rendered.

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
try:                                   # v1.6.1: load-time import (the selftest chdirs to a temp folder)
    import book_risk as _book_risk
except Exception:                      # the brief still runs; the model section says what is missing
    _book_risk = None

SUMMARY_DIR = Path("logs/summaries")
STATE_DIR = Path("logs/brief")
DAILY_CSV = Path("logs/daily_log.csv")
SWING_DIR = Path("logs/swing")
ROTATION_FILE = "rotation_summary.json"
MARKETS_FILE = "markets_summary.json"
FLOW_MAP_FILE = "flow_map_summary.json"      # Money_Flow flow_map.SUMMARY_FILE
FLOW_MAP_MAX_AGE_H = 36                      # one missed daily publish is tolerated, two is stale

BAND = 0.25                      # regime_bands.TRANSITION_BAND
CASH_SLEEVES = {"SGOV", "USFR", "BIL", "SHV"}   # ATR stops do not apply to cash
HEAT_CAP_PCT = 15.0
DRIFT_BAND_REL = 0.20
LEDGER_STALE_DAYS = 7
LEDGER_ACTIVE_DAYS = 30          # older than this = not tracking real positions; the model portfolio is the reference

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
EXTRA_FRED = ["DGS30", "DFF", "DTB3"]   # v1.6: DFF/DTB3 for the market-implied policy path (N12)
BENCH_TICKERS = ("SPY", "AGG")   # model-book benchmarks: SPY and a 60/40 (60% SPY / 40% AGG)
FRESHER = {"VIXCLS": "^VIX"}                           # yfinance close splices for lagging FRED series
# v1.5.3 (N29): WTI is spliced from the rebuilt NYMEX settle, never the daily CL=F last trade
OIL_SID, OIL_TICKER = "DCOILWTICO", "CL=F"
SETTLE_START, SETTLE_END = (14, 28), (14, 30)           # NYMEX WTI settlement window, ET (VWAP)
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


def _intraday_default(ticker: str) -> pd.DataFrame:
    import yfinance as yf
    return yf.download(ticker, period="5d", interval="1m", auto_adjust=False, progress=False, prepost=True)


def settle_series(bars: Optional[pd.DataFrame], now_et) -> pd.Series:
    """Daily WTI settlement rebuilt from 1-minute bars: volume-weighted close
    of the bars stamped 14:28 and 14:29 ET (covering 14:28:00-14:30:00), one
    value per session whose 14:30 has passed. Empty when the bars are missing,
    so the caller never falls back to an after-hours last trade."""
    if bars is None or getattr(bars, "empty", True):
        return pd.Series(dtype=float)
    df = bars.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if "Close" not in df.columns:
        return pd.Series(dtype=float)
    idx = pd.DatetimeIndex(df.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx
    df.index = idx.tz_convert("America/New_York")
    now = pd.Timestamp(now_et)
    now = now.tz_localize("America/New_York") if now.tzinfo is None else now.tz_convert("America/New_York")
    t = df.index.hour * 60 + df.index.minute
    lo, hi = SETTLE_START[0] * 60 + SETTLE_START[1], SETTLE_END[0] * 60 + SETTLE_END[1]
    win = df[(t >= lo) & (t < hi)]
    out = {}
    for day, g in win.groupby(win.index.date):
        if now < pd.Timestamp(day).tz_localize("America/New_York") + pd.Timedelta(minutes=hi):
            continue
        c = pd.to_numeric(g["Close"], errors="coerce")
        v = pd.to_numeric(g["Volume"], errors="coerce") if "Volume" in g.columns else pd.Series(np.nan, index=g.index)
        ok = c.notna()
        if not ok.any():
            continue
        vv = v[ok].fillna(0)
        out[pd.Timestamp(day)] = float((c[ok] * vv).sum() / vv.sum()) if vv.sum() > 0 else float(c[ok].mean())
    return pd.Series(out, dtype=float).sort_index()


def cl_expiry(year: int, month: int) -> date:
    """Last trading day of the NYMEX WTI contract for delivery (year, month):
    3 business days before the 25th of the prior month, or 4 if the 25th is
    not a business day. NYSE holidays stand in for CME's (they match on the
    days that matter here)."""
    py, pm = (year, month - 1) if month > 1 else (year - 1, 12)
    d = date(py, pm, 25)
    n = 3 if mt.is_trading_day(d) else 4
    k = 0
    while k < n:
        d -= timedelta(days=1)
        if mt.is_trading_day(d):
            k += 1
    return d


def cl_expiries_between(start: date, end: date) -> list:
    out = []
    y, m = start.year, start.month
    for _ in range(30):
        e = cl_expiry(y, m)
        if start <= e <= end:
            out.append((e, date(y, m, 1).strftime("%b %Y")))
        if e > end:
            break
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return sorted(out)


def wti_settle_series(daily: pd.Series, settle: pd.Series, session: date) -> pd.Series:
    """One series of front-month settles: daily closes for completed sessions
    up to `session`, overridden by the rebuilt settle wherever it exists. The
    latest daily bar is dropped unless a rebuilt settle replaces it."""
    if daily is None or not len(daily):
        return pd.Series(dtype=float)
    d = daily.copy()
    d.index = pd.to_datetime(d.index).normalize()
    d = d[d.index <= pd.Timestamp(session)]
    st_ = settle[settle.index <= pd.Timestamp(session)] if settle is not None and len(settle) else pd.Series(dtype=float)
    if len(d) and d.index[-1] not in st_.index:
        d = d.iloc[:-1]
    out = d.copy()
    for k, v in st_.items():
        out.loc[pd.Timestamp(k)] = v
    return out.sort_index()


def settle_vs_fred(settle: pd.Series, fred: pd.Series) -> Optional[dict]:
    """Gap between the rebuilt settle and FRED's WTI on the days both exist
    (FRED's DCOILWTICO is EIA's Cushing spot, which tracks the settle)."""
    if settle is None or fred is None or not len(settle) or not len(fred):
        return None
    f = fred.copy()
    f.index = pd.to_datetime(f.index).normalize()
    both = pd.concat([settle, f], axis=1, join="inner").dropna()
    if both.empty:
        return None
    d = (both.iloc[:, 0] - both.iloc[:, 1]).abs()
    return {"n": int(len(d)), "max_abs": float(d.max()), "mean_abs": float(d.mean())}


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
           data_dir: Optional[str] = None, fetch_holdings: Optional[Callable] = None,
           fetch_intraday: Optional[Callable] = None) -> dict:
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
            # v9: if FRED fails, the classifier HOLDS the last confirmed regime
            # instead of falling through to `neutral`. Give it the prior
            # session's logged regime explicitly (not today's row).
            prior = None
            try:
                _lg = pd.read_csv(DAILY_CSV) if DAILY_CSV.exists() else pd.DataFrame()
                if not _lg.empty and "regime" in _lg:
                    _lg = _lg[_lg["et_date"].astype(str) < session.isoformat()].sort_values("et_date")
                    _keys = [k for k in _lg["regime"].astype(str) if k in rc.REGIMES]
                    prior = _keys[-1] if _keys else None
            except Exception:
                prior = None
            out = rc.full_assessment(fred_key, fetch_fred=fetch_fred, fetch_prices=memo,
                                     prior_regime=prior, **ckw)
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
    inp["data_dir"] = data_dir
    inp["rotation"] = _read_json_file(ROTATION_FILE, data_dir)
    inp["markets"] = _read_json_file(MARKETS_FILE, data_dir)
    inp["flow_map"] = _read_json_file(FLOW_MAP_FILE, data_dir)
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
    try:
        import regime_classifier as _rc
        sleeves = set(_rc.BASE_WEIGHTS)
    except Exception:
        sleeves = set()
    inp["spy_holdings"], inp["spy_holdings_error"] = [], None
    try:
        inp["spy_holdings"] = (fetch_holdings or _holdings_default)() or []
    except Exception as e:
        inp["spy_holdings_error"] = f"{type(e).__name__}: {str(e)[:120]}"
    tickers = sorted(set(universe) | set(comp) | set(ledger_tk) | {t for _, t in PRICE_SCORE}
                     | set(FRESHER.values()) | sleeves | set(BENCH_TICKERS)
                     | {t for t, _ in inp["spy_holdings"]} | {OIL_TICKER})
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
    # v1.5.4 (N33): WTI = one series of NYMEX front-month settles; never spot and futures mixed
    inp.setdefault("series_label", {})
    try:
        fs = hist.get(OIL_SID, pd.Series(dtype=float))
        daily = _price_close(inp["prices"], OIL_TICKER)
        try:
            st_ = settle_series((fetch_intraday or _intraday_default)(OIL_TICKER), now)
        except Exception:
            st_ = pd.Series(dtype=float)
        ws = wti_settle_series(daily, st_, session)
        if len(ws) >= 260:
            hist[OIL_SID] = ws
            inp["series_label"][OIL_SID] = "WTI (NYMEX front-month settle)"
            dn = daily.copy(); dn.index = pd.to_datetime(dn.index).normalize()
            chk = settle_vs_fred(st_[st_.index < ws.index[-1]], dn) if len(st_) else None   # method check: settled daily bars vs rebuild
            sp = settle_vs_fred(ws, fs)                                         # market spread: spot vs settle
            last_shared = None
            if sp:
                f2 = fs.copy(); f2.index = pd.to_datetime(f2.index).normalize()
                both = pd.concat([ws, f2], axis=1, join="inner").dropna()
                if len(both):
                    last_shared = (both.index[-1].date(), float(both.iloc[-1, 1] - both.iloc[-1, 0]))
            rolls = cl_expiries_between((ws.index[-21] if len(ws) > 21 else ws.index[0]).date(), ws.index[-1].date())
            n_reb = int(st_.index.isin(ws.index).sum()) if len(st_) else 0
            inp["fred_src"][OIL_SID] = (
                f"one series of front-month settles: Yahoo CL=F daily for completed sessions, latest {n_reb} rebuilt "
                f"from 1-min bars (VWAP 14:28–14:30 ET)"
                + (f"; method check — Yahoo daily vs rebuilt on {chk['n']} earlier session(s): max ${chk['max_abs']:.2f}" if chk else "")
                + (f"; FRED spot minus settle on {last_shared[0]}: {last_shared[1]:+.2f} (market spread, not an error)"
                   if last_shared else "")
                + ("; front-month expiry " + ", ".join(f"{e} ({lab} contract)" for e, lab in rolls)
                   + " inside the 20-day window — changes spanning it include the roll" if rolls else "")
                + ("" if n_reb else "; no settlement-window bars today, so the latest session is not shown yet"))
        else:
            inp["series_label"][OIL_SID] = "WTI (FRED DCOILWTICO, EIA Cushing spot)"
            inp["fred_src"][OIL_SID] = ("FRED spot only — futures history unavailable; futures are never spliced onto spot "
                                        "(different prices); lags the market 1–3 sessions")
    except Exception as e:
        inp["series_label"][OIL_SID] = "WTI (FRED DCOILWTICO, EIA Cushing spot)"
        inp["fred_src"][OIL_SID] = f"FRED spot only — futures series failed ({type(e).__name__})"
    missing = [t for t in tickers if t not in inp["prices"]]
    if missing:
        errors.append(f"prices missing for {len(missing)} of {len(tickers)} tickers"
                      + (f" ({', '.join(missing[:8])}{'…' if len(missing) > 8 else ''})"))

    # ── Events ────────────────────────────────────────────────────────────
    try:
        import event_calendar as ec
        inp["events"] = (macro_lookup or (lambda d: ec.upcoming_macro(d, today=now.date())))(10)
        inp["calendar_asof"] = getattr(ec, "CALENDAR_ASOF", None)
        inp["calendar_coverage"] = ec.coverage(now.date()) if hasattr(ec, "coverage") else None
    except Exception as e:
        inp["events"] = []; inp["calendar_asof"] = None; inp["calendar_coverage"] = None
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


TRAIL_1M, TRAIL_3M, TRAIL_12, TRAIL_SKIP = 21, 63, 252, 21


def trailing_returns(close: pd.Series) -> dict:
    """Display-only trailing returns in % from an adjusted-close series.

    1M = last 21 sessions, 3M = last 63, 12-1 = the 12-month return that
    EXCLUDES the most recent month (price 21 sessions ago over price 252
    sessions ago) — the standard momentum construction, because the latest
    month tends to partly reverse. Any window without enough history is None,
    never a shorter-window number under the same label. Nothing here feeds a
    gate, a weight or the circuit breaker."""
    s = close.dropna() if close is not None else pd.Series(dtype=float)
    n = len(s)

    def span(a: int, b: int):
        # return from `a` sessions ago to `b` sessions ago (b=0 → latest)
        if n <= a or float(s.iloc[-1 - a]) <= 0:
            return None
        end = float(s.iloc[-1 - b])
        return round((end / float(s.iloc[-1 - a]) - 1) * 100, 2)
    return {"ret_1m": span(TRAIL_1M, 0), "ret_3m": span(TRAIL_3M, 0),
            "ret_12_1": span(TRAIL_12, TRAIL_SKIP)}


def scoreboard(inp: dict) -> dict:
    rows = []
    for label, sid, unit, kind in FRED_SCORE:
        s = inp["fred"].get(sid, pd.Series(dtype=float))
        rows.append(_score_row(label, s, unit, kind, source=(inp.get("series_label") or {}).get(sid, f"FRED {sid}")))
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
    # v1.6 (N12): market-implied policy path, crude: 2Y and 3-month bill yields minus the
    # effective fed funds rate on the same dates. Positive = the market prices policy HIGHER.
    _fd = inp.get("fred") or {}
    _dff = _fd.get("DFF", pd.Series(dtype=float)).dropna()
    for _lab, _sid in (("Market-implied path: 2Y − fed funds", "DGS2"), ("Market-implied path: 3M bill − fed funds", "DTB3")):
        _y = _fd.get(_sid, pd.Series(dtype=float)).dropna()
        if len(_y) and len(_dff):
            _sp = (_y - _dff.reindex(_y.index, method="ffill")).dropna()
            if len(_sp) > 1:
                _rw = _score_row(_lab, _sp, "%", "rate", source=f"FRED {_sid} − DFF")
                _rw["note"] = ("≈ {:+.1f} × 25bp moves priced{}; includes term premium, so read the direction, "
                               "not the exact count").format(
                    float(_sp.iloc[-1]) / 0.25, " over ~2 years" if _sid == "DGS2" else " over ~3 months")
                rows.append(_rw)
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
    failed = bool(reg.get("data_failure"))
    out.update(key=key, label=reg.get("label"), drivers=reg.get("drivers", []),
               transition_reason=reg.get("transition_reason"),
               source=("HELD — data failure (" + ", ".join(reg.get("missing_inputs") or []) + " missing)")
               if failed else "live (FRED)",
               data_failure=failed, held_from=reg.get("held_from"))
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
    # v7.1: gated rebalance plans. Entry gate evaluated on the 2y closes the
    # brief already fetched (no extra network). Shown for (a) a regime change
    # still being executed and (b) the nearest flip, as a ready contingency.
    out["plans"], out["gates_today"] = [], {}
    try:
        import regime_classifier as rc
        prices = inp.get("prices") or {}
        gate_fp = lambda t, p="2y": _price_close(prices, t)
        out["gates_today"] = {t: rc.entry_gate(t, gate_fp)
                              for t, d in rc.regime_overlay(key, sig).items()
                              if d > 0 and t not in rc.ENTRY_EXEMPT}
        if n <= 2 and prev_key and prev_key != key and prev_key in rc.REGIMES:
            pl = rc.transition_plan(prev_key, key, gate_fp, sig)
            pl["title"] = (f"Rebalance QUEUED: `{prev_key}` → `{key}` — executes only if the next close "
                           "confirms" if n == 1 else
                           f"Rebalance CONFIRMED: `{prev_key}` → `{key}` — execute at the weekend review")
            out["plans"].append(pl)
        # contingencies: the nearest flip, plus any credit escalation in the flip list
        targets_ = []
        for f_ in ok:
            t_ = f_.get("to")
            if t_ in rc.REGIMES and t_ != key and t_ not in targets_ and (
                    not targets_ or t_ in ("credit_stress", "liquidity_crisis", "growth_scare")):
                targets_.append(t_)
        for t_ in targets_[:3]:
            pl = rc.transition_plan(key, t_, gate_fp, sig)
            pl["title"] = f"Contingency — if `{t_}` confirms on two closes"
            out["plans"].append(pl)
    except Exception as e:
        out["plan_error"] = f"{type(e).__name__}: {e}"
    # v7: spread-peak re-entry state (from the assessment, else from the scoreboard history)
    cc = a.get("credit_cycle")
    if not cc or cc.get("state") == "UNAVAILABLE":
        try:
            import regime_classifier as rc
            cc = rc.credit_cycle_state((inp.get("fred") or {}).get("BAMLH0A0HYM2"))
        except Exception:
            cc = cc or None
    out["credit_cycle"] = cc
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
    if failed:
        c = (f"⚠ DATA FAILURE — Level-1 inputs missing ({', '.join(reg.get('missing_inputs') or [])}). "
             + (f"Holding the last confirmed regime `{reg.get('held_from')}`; nothing here is new information "
                "about the market, and no regime change can start today." if reg.get("held_from") else
                "No prior regime on record — the `neutral` read is a placeholder. Do not act on it.")
             + " " + c)
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
    # v1.6 (N37/N38): 20-session momentum for credit and long real yields
    _hy = fred.get("BAMLH0A0HYM2", pd.Series(dtype=float)).dropna()
    _r10 = fred.get("DFII10", pd.Series(dtype=float)).dropna()
    hy20 = _f(_hy.iloc[-1] - _hy.iloc[-21]) if len(_hy) > 20 else None
    r10_20 = _f(_r10.iloc[-1] - _r10.iloc[-21]) if len(_r10) > 20 else None
    d = ca.divergence(hy_oas=g("hy_oas"), hy_mom_2w=g("hy_oas_mom_2w"),
                      hy_mom_20d=hy20, long_real_mom_20d=r10_20,
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
    elif regime_key == "credit_stress":
        fit = st.get("credit") in ("STRESS", "WATCH")
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

def _hours_since(iso: Optional[str], now) -> Optional[float]:
    """Hours from a UTC ISO timestamp to the brief's ET clock (naive = ET)."""
    if not iso:
        return None
    try:
        t = pd.Timestamp(iso)
        if pd.isna(t):
            return None
        t = t.tz_localize("UTC") if t.tzinfo is None else t
        n = pd.Timestamp(now)
        n = n.tz_localize("America/New_York") if n.tzinfo is None else n
        return round((n - t).total_seconds() / 3600.0, 1)
    except Exception:
        return None


FLOW_INTO = ("new_money", "into_stocks")
FLOW_OUT = ("out_of_stocks", "leaving_both")


def regime_tilt(key: Optional[str]) -> Optional[str]:
    """risk-on / risk-off / none, from the swing desk's books-open table:
    long-only regimes lean risk-on, short-only lean risk-off, both = no tilt."""
    try:
        from swing_desk import REGIME_DIRECTION
    except Exception:
        return None
    if not key or key not in REGIME_DIRECTION:
        return None
    return {"long": "risk-on", "short": "risk-off"}.get(REGIME_DIRECTION[key][0], "none")


def flow_regime_check(state: Optional[str], key: Optional[str]) -> str:
    """Does market-wide flow confirm the regime's tilt? Checklist v4 Step 5:
    flow never overrides the regime; a contradiction is logged and watched."""
    tilt = regime_tilt(key)
    if state in (None, "unavailable"):
        return "Flow is unavailable, so Level 2 cannot confirm or contradict the regime (a data gap, not a signal)."
    if state == "borderline":
        return f"Borderline flow neither confirms nor contradicts `{key}`."
    if tilt is None:
        return f"Regime `{key}` has no tilt on record; flow is context only."
    side = "into" if state in FLOW_INTO else "out" if state in FLOW_OUT else None
    move = {"into": "into stocks", "out": "out of stocks"}.get(side)
    if side is None:
        return f"No market-wide flow signal; `{key}` stands on Level 1 alone."
    if tilt == "none":
        return (f"`{key}` has no directional tilt (swing books both ways), so money moving {move} is "
                f"context, not confirmation.")
    agrees = (side == "into") == (tilt == "risk-on")
    return (f"Money moving {move} {'CONFIRMS' if agrees else 'CONTRADICTS'} `{key}`'s {tilt} tilt."
            + ("" if agrees else " Log the contradiction and watch it; flow does not override the regime (Step 5)."))


def flow_map_section(inp: dict, regime_key: Optional[str] = None) -> dict:
    """6A: where the money went, by asset class (Money_Flow flow_map_summary.json).
    Shown as published; this module does not recompute or re-judge it."""
    s = inp.get("flow_map") or {}
    if not s.get("asset_classes") or not (s.get("verdict") or {}).get("verdict"):
        return {"available": False,
                "message": "Flow map summary not published yet — Money_Flow's Daily Poll and Publish writes "
                           f"{FLOW_MAP_FILE}. Without it the brief cannot say where money moved by asset class; "
                           "that blocks the de-risking-versus-rotation call from flows (prices in 1A still apply)."}
    age = _hours_since(s.get("published_at"), inp["now_et"])
    stale = age is None or age > FLOW_MAP_MAX_AGE_H
    v = s["verdict"]
    rows = [{"asset_class": r.get("asset_class"), "flow_usd": _f(r.get("flow_usd")), "pct_aum": _f(r.get("pct_aum")),
             "direction": r.get("direction") or "n/a", "measured": r.get("measured"), "total": r.get("total"),
             "missing": list(r.get("missing") or []), "thin": bool(r.get("thin"))} for r in s["asset_classes"]]
    cov = s.get("coverage") or {}
    return {"available": True, "stale": stale, "age_hours": age, "published_at": s.get("published_at"),
            "data_through": s.get("data_through"), "window": s.get("window"),
            "measured": cov.get("measured"), "total": cov.get("total"), "rows": rows,
            "kind": v.get("kind"), "verdict": v.get("verdict"), "evidence": list(v.get("evidence") or []),
            "rule": v.get("rule", ""), "changes_if": v.get("changes_if", ""),
            "excluded": s.get("excluded") or {},
            "state": v.get("state"), "borderline": v.get("borderline"),
            "sessions_in_state": v.get("sessions_in_state"), "steps": list(v.get("steps") or []),
            "regime_check": flow_regime_check(v.get("state"), regime_key) if v.get("state") else None}


def _usd(x) -> str:
    x = _f(x)
    if x is None:
        return "n/a"
    sign = "+" if x > 0 else ("−" if x < 0 else "")
    a = abs(x)
    return sign + (f"${a / 1e9:.2f}B" if a >= 1e9 else f"${a / 1e6:.0f}M")


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
    try:
        out["trend"] = breadth_trend(prices, uni)
    except Exception as e:
        out["trend"] = {"available": False, "reason": f"{type(e).__name__}: {e}"}
    try:
        out["top10"] = top10_contribution(prices, inp.get("spy_holdings") or [])
    except Exception as e:
        out["top10"] = {"available": False, "reason": f"{type(e).__name__}: {e}"}
    if inp.get("spy_holdings_error") and not out["top10"].get("available"):
        out["top10"]["reason"] = f"SPY holdings file failed: {inp['spy_holdings_error']}"
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


# ── v1.5: top-10 contribution and breadth trend (section 7) ──────────────────
# Top 10: how much of SPY's move came from its 10 largest holdings, and what
# the other ~490 names did. Weights come from State Street's daily SPY
# holdings file (the same file macro_flags reads for top-20 concentration).
# Start-of-window weights are backed out exactly for a buy-and-hold window:
#   w0_i = w_now_i x (1 + R_spy) / (1 + r_i)
# contribution_i = w0_i x r_i (points of SPY return); the rest of the index
# returned (R_spy - sum contributions) / (1 - sum w0).
TOP_N = 10
CONC_TOP_HEAVY = 1.5      # top-10 share of SPY's move / their weight share at or above this = carried by the top 10
CONC_BROAD = 0.67         # at or below this = the top 10 lagged the rest of the index
CONC_MIN_MOVE = 0.5       # % — a SPY move smaller than this is too small to split into shares
TOP_MIN_COVER = 0.90      # share of the top-10 weight that must be priced, or the split is not reported
# Breadth trend: % of the constituent proxy above its 50-day, as a series.
BREADTH_TREND_PTS = 10.0  # pp change over 20 sessions that counts as a trend (~11 names on a 109-name universe)
BREADTH_LOOKBACK = 60     # sessions of history shown
_TICKER_RE = None


def spy_top_holdings(raw: bytes, n: int = TOP_N) -> list:
    """[(yfinance ticker, weight %)] for the n largest SPY holdings, from an
    SSGA daily-holdings workbook. Raises ValueError on an unrecognised layout."""
    import io, re
    grid = pd.read_excel(io.BytesIO(raw), header=None)
    hdr = None
    for i in range(min(len(grid), 40)):
        cells = [str(c).strip().lower() for c in grid.iloc[i].tolist()]
        if "weight" in cells and "ticker" in cells:
            hdr = i
            break
    if hdr is None:
        raise ValueError("no header row with 'Weight' and 'Ticker' in the first 40 rows")
    df = grid.iloc[hdr + 1:].copy()
    df.columns = [str(c).strip().lower() for c in grid.iloc[hdr].tolist()]
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce")
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df = df[df["weight"] > 0]
    if len(df) < 100:
        raise ValueError(f"only {len(df)} weighted holdings parsed — not the full SPY basket")
    if df["weight"].sum() < 1.5:                     # fractions, not percent
        df["weight"] = df["weight"] * 100
    ok = df["ticker"].str.match(r"^[A-Z]{1,5}([.\-/][A-Z]{1,2})?$")
    df = df[ok].sort_values("weight", ascending=False).head(n)
    return [(re.sub(r"[./]", "-", t), round(float(w), 4)) for t, w in zip(df["ticker"], df["weight"])]


def _holdings_default() -> list:
    import macro_flags as _mf
    return spy_top_holdings(_mf._get(_mf.SPY_HOLDINGS_URL).content)


def top10_contribution(prices: dict, holdings: list, windows=(1, 5, 20)) -> dict:
    out = {"available": False, "rows": [], "windows": {}, "holdings_n": len(holdings or [])}
    spy = _price_close(prices, "SPY")
    if not holdings or len(spy) < max(windows) + 1:
        out["reason"] = "SPY holdings unavailable" if not holdings else "SPY price history too short"
        return out
    total_w = sum(w for _, w in holdings)
    closes = {t: _price_close(prices, t) for t, _ in holdings}
    priced = [(t, w) for t, w in holdings if len(closes[t]) > max(windows)]
    out["missing"] = [t for t, _ in holdings if len(closes[t]) <= max(windows)]
    out["cover"] = sum(w for _, w in priced) / total_w if total_w else 0.0
    out["weight_now"] = round(total_w, 2)
    out["asof"] = spy.index[-1].date().isoformat()
    if out["cover"] < TOP_MIN_COVER:
        out["reason"] = (f"only {out['cover']:.0%} of the top-{len(holdings)} weight is priced "
                         f"(missing {', '.join(out['missing'])})")
        return out
    for t, w in priced:
        c = closes[t]
        out["rows"].append({"ticker": t, "weight": w,
                            **{f"r{n}": float(c.iloc[-1] / c.iloc[-1 - n] - 1) * 100 for n in windows}})
    for n in windows:
        R = float(spy.iloc[-1] / spy.iloc[-1 - n] - 1)
        contrib = w0_sum = 0.0
        for row in out["rows"]:
            r = row[f"r{n}"] / 100
            w0 = row["weight"] / 100 * (1 + R) / (1 + r)
            row[f"c{n}"] = w0 * r * 100               # points of SPY return
            contrib += row[f"c{n}"]; w0_sum += w0
        rest = (R * 100 - contrib) / (1 - w0_sum) if w0_sum < 1 else None
        share = contrib / (R * 100) if abs(R * 100) >= CONC_MIN_MOVE else None
        ratio = share / w0_sum if share is not None and w0_sum else None
        out["windows"][n] = {"spy": R * 100, "top_contrib": contrib, "top_w0": w0_sum * 100, "rest": rest,
                             "share": share, "ratio": ratio}
    w = out["windows"][max(windows)]
    n = max(windows)
    rule = (f"Weights: State Street's daily SPY holdings file. Start-of-window weights are backed out for a "
            f"buy-and-hold window (w0 = w_now x (1+R_SPY)/(1+r)); contribution = w0 x r. The top {len(out['rows'])} "
            f"carry the move when their share of SPY's {n}-day return is at least {CONC_TOP_HEAVY}x their weight; "
            f"they lag when it is {CONC_BROAD}x or less. SPY moves under {CONC_MIN_MOVE}% are not split.")
    k = len(out["rows"])
    if w["share"] is None:
        verdict = (f"Over {n} days SPY moved {w['spy']:+.2f}%, too little to split: the top {k} contributed "
                   f"{w['top_contrib']:+.2f} points and the other names returned {w['rest']:+.2f}%")
        kind = "small_move"
    else:
        kind = ("top_heavy" if w["ratio"] >= CONC_TOP_HEAVY else "leaders_lag" if w["ratio"] <= CONC_BROAD
                else "in_line")
        lead = {"top_heavy": f"Driven by the top {k}", "leaders_lag": f"The top {k} lagged",
                "in_line": f"The top {k} moved in line with their weight"}[kind]
        verdict = (f"{lead}: over {n} days SPY {w['spy']:+.2f}%, of which the top {k} ({w['top_w0']:.1f}% of the "
                   f"index) supplied {w['top_contrib']:+.2f} points ({w['share']:.0%} of the move, "
                   f"{w['ratio']:.1f}x their weight); the other names returned {w['rest']:+.2f}%")
        if (w["spy"] > 0) != (w["rest"] > 0):
            verdict += " — the rest of the index moved the OTHER way"
    out.update(available=True, kind=kind, verdict=verdict, rule=rule,
               changes_if=f"The top {k}'s share of the {n}-day move crossing {CONC_TOP_HEAVY}x or {CONC_BROAD}x their weight.")
    out["rows"].sort(key=lambda r: -abs(r[f"c{n}"]))
    return out


def breadth_trend(prices: dict, universe: list, lookback: int = BREADTH_LOOKBACK) -> dict:
    """% of the constituent proxy above its 50-day and 200-day, and 52-week
    highs minus lows, for each of the last `lookback` sessions. Each session
    uses only closes up to that session."""
    out = {"available": False}
    spy = _price_close(prices, "SPY")
    cols = {t: _price_close(prices, t) for t in universe}
    cols = {t: s for t, s in cols.items() if len(s) >= 50}
    if len(spy) < lookback + 21 or len(cols) < 20:
        out["reason"] = "not enough constituent history"
        return out
    cal = spy.index[-(lookback + 260):]
    px = pd.DataFrame({t: s.reindex(cal) for t, s in cols.items()})
    ma50, ma200 = px.rolling(50, min_periods=50).mean(), px.rolling(200, min_periods=200).mean()
    hi, lo = px.rolling(252, min_periods=252).max(), px.rolling(252, min_periods=252).min()
    has = px.notna()
    p50 = ((px > ma50) & ma50.notna() & has).sum(1) / (ma50.notna() & has).sum(1).replace(0, np.nan) * 100
    p200 = ((px > ma200) & ma200.notna() & has).sum(1) / (ma200.notna() & has).sum(1).replace(0, np.nan) * 100
    hl = ((px >= hi) & hi.notna()).sum(1) - ((px <= lo) & lo.notna()).sum(1)
    hl = hl.where(hi.notna().sum(1) > 0)
    ser = pd.DataFrame({"p50": p50, "p200": p200, "hl": hl}).iloc[-lookback:]
    pts = {}
    for lab, k in (("today", 1), ("5d", 6), ("20d", 21), ("60d", lookback)):
        if len(ser) >= k:
            r = ser.iloc[-k]
            pts[lab] = {"date": ser.index[-k].date().isoformat(),
                        **{c: (None if pd.isna(r[c]) else round(float(r[c]), 1)) for c in ("p50", "p200", "hl")}}
    if pts.get("today", {}).get("p50") is None:
        out["reason"] = "latest session has no 50-day reading"
        return out
    d20 = None if pts.get("20d", {}).get("p50") is None else pts["today"]["p50"] - pts["20d"]["p50"]
    spy20 = float(spy.iloc[-1] / spy.iloc[-21] - 1) * 100
    trend = ("improving" if d20 is not None and d20 >= BREADTH_TREND_PTS else
             "deteriorating" if d20 is not None and d20 <= -BREADTH_TREND_PTS else "flat")
    if trend == "deteriorating" and spy20 > 0:
        verdict = (f"Narrowing: SPY is up {spy20:+.1f}% over 20 sessions while the share of names above their "
                   f"50-day fell {d20:+.0f} points to {pts['today']['p50']:.0f}% — fewer stocks are carrying the index")
    elif trend == "improving" and spy20 < 0:
        verdict = (f"Broadening under a falling index: SPY {spy20:+.1f}% over 20 sessions, yet the share above the "
                   f"50-day rose {d20:+.0f} points to {pts['today']['p50']:.0f}%")
    elif d20 is None:
        verdict = f"Breadth: {pts['today']['p50']:.0f}% above the 50-day; not enough history for a 20-session trend"
    elif trend == "flat":
        verdict = (f"Breadth flat: {pts['today']['p50']:.0f}% above the 50-day, {d20:+.0f} points over 20 sessions "
                   f"(SPY {spy20:+.1f}%)")
    else:
        verdict = (f"Breadth {trend} with the index: {pts['today']['p50']:.0f}% above the 50-day, {d20:+.0f} points "
                   f"over 20 sessions (SPY {spy20:+.1f}%)")
    rule = (f"Share of the {len(cols)}-name constituent proxy closing above its 50-day average, each session from "
            f"closes up to that session. A change of {BREADTH_TREND_PTS:.0f} points or more over 20 sessions "
            f"(about {BREADTH_TREND_PTS / 100 * len(cols):.0f} names) is a trend; a falling trend under a rising SPY is "
            f"narrowing. Proxy, not the full S&P 500.")
    out.update(available=True, points=pts, d20=d20, spy20=spy20, trend=trend, verdict=verdict, rule=rule,
               n=len(cols), series=[{"date": d.date().isoformat(), "p50": None if pd.isna(v) else round(float(v), 1)}
                                    for d, v in ser["p50"].items()])
    return out


# ── Market read (v1.2): verdict / evidence / rule / what would change it ──
# Every verdict below is a rule applied to numbers the brief already holds.
# Thresholds are named here so the rule text printed in the brief and the
# code that applies it cannot drift apart.
READ_RATE_NOISE_BP = 5.0     # a 20-day move in the 10Y smaller than this is noise
READ_RATE_SHARE = 2 / 3      # a component "drives" the move when it supplies at least this share
READ_DAY_MOVE = 0.5          # % — an index day smaller than this is quiet
READ_BIG_DAY = 1.0           # % — a risk-on / risk-off day for the cross-asset read
READ_CONC_GAP = 0.5          # pp — equal-weight vs cap-weight gap that marks a concentrated day
READ_GROWTH_TILT = 1.0       # % — growth-vs-value 20-day move that counts as a tilt
READ_NEAR_DAYS = 3.0         # within this many typical days of a WATCH line = "close" (a move seen a few times a year)
# The cross-asset lanes' own lines (cross_asset.credit_lane / vol_lane); the
# selftest asserts these match, so a change there cannot silently desync here.
LANE_HY_WATCH, LANE_HY_STRESS, LANE_HY_MOM = 3.5, 5.0, 0.5
LANE_HY_MOM_20D = 0.30       # v1.6 (N37): cross_asset.HY_MOM_20D_WATCH
LANE_VIX_WATCH, LANE_VIX_STRESS = 21.0, 30.0


def _ret1(prices: dict, tk: str) -> tuple:
    """(last-session % change, as-of date) from adjusted closes, or (None, None)."""
    s = _price_close(prices, tk)
    if len(s) < 2 or not float(s.iloc[-2]):
        return None, None
    return float(s.iloc[-1] / s.iloc[-2] - 1) * 100, pd.to_datetime(s.index[-1]).date().isoformat()


def _rate_split(fred: dict, n: int) -> Optional[dict]:
    """10Y change over n sessions split into real (DFII10) + breakeven, on the
    two series' common dates, so nominal = real + breakeven exactly."""
    n10, r10 = fred.get("DGS10"), fred.get("DFII10")
    if n10 is None or r10 is None or not len(n10) or not len(r10):
        return None
    c = pd.concat([n10.rename("n"), r10.rename("r")], axis=1).dropna()
    if len(c) <= n:
        return None
    nom = float(c["n"].iloc[-1] - c["n"].iloc[-1 - n])
    real = float(c["r"].iloc[-1] - c["r"].iloc[-1 - n])
    return {"nom_bp": nom * 100, "real_bp": real * 100, "be_bp": (nom - real) * 100,
            "level": float(c["n"].iloc[-1]), "real_level": float(c["r"].iloc[-1]),
            "asof": pd.to_datetime(c.index[-1]).date().isoformat()}


def read_rates(s20: Optional[dict], s1: Optional[dict], growth_r20: Optional[float]) -> dict:
    topic = "What moved long yields"
    rule = (f"Breakeven = 10Y nominal − 10Y real (DFII10) on the same date, so the parts add up exactly. "
            f"A part drives the 20-day move when it supplies at least two-thirds of it; a 20-day move under "
            f"{READ_RATE_NOISE_BP:.0f}bp is noise. (Section 4's rates lane uses 3-month momentum, so the two can "
            f"point different ways over different horizons.)")
    if not s20:
        return {"topic": topic, "verdict": "unavailable — 10Y or DFII10 history missing", "evidence": [],
                "rule": rule, "changes_if": "Restoring the FRED DGS10 and DFII10 series.", "driver": None}
    nom, real, be = s20["nom_bp"], s20["real_bp"], s20["be_bp"]
    ev = [f"10Y {s20['level']:.2f}% (FRED, {s20['asof']}): 20-day {nom:+.0f}bp = real {real:+.0f}bp + breakeven {be:+.0f}bp"]
    if s1:
        ev.append(f"Last FRED session: {s1['nom_bp']:+.0f}bp = real {s1['real_bp']:+.0f}bp + breakeven {s1['be_bp']:+.0f}bp")
    if abs(nom) < READ_RATE_NOISE_BP:
        driver, verdict = None, f"Long yields little changed over 20 days ({nom:+.0f}bp)"
        changes = f"A 20-day move of {READ_RATE_NOISE_BP:.0f}bp or more in either direction."
    else:
        up = nom > 0
        if real / nom >= READ_RATE_SHARE:
            driver = "real"
            verdict = ("Over 20 days, long yields ROSE on real yields, not inflation expectations — a discount-rate squeeze on "
                       "long-duration assets (growth, tech, long bonds)" if up else
                       "Over 20 days, long yields FELL on real yields — discount-rate pressure on long-duration assets is easing")
            changes = "Breakevens supplying two-thirds of the 20-day move would make it an inflation story."
        elif be / nom >= READ_RATE_SHARE:
            driver = "breakeven"
            verdict = ("Over 20 days, long yields ROSE on inflation expectations — favours real assets over long bonds and growth"
                       if up else "Over 20 days, long yields FELL on lower inflation expectations — a disinflation or growth-worry signal")
            changes = "Real yields supplying two-thirds of the 20-day move would make it a discount-rate story."
        else:
            driver = "both"
            verdict = f"Over 20 days, long yields {'ROSE' if up else 'FELL'} on both real yields and inflation expectations"
            changes = "Either part supplying two-thirds of the 20-day move."
        if growth_r20 is not None:
            ev.append(f"Growth vs value (VUG/VTV) {growth_r20:+.1f}% over 20 days")
            if driver == "real" and not up and growth_r20 <= -READ_GROWTH_TILT:
                ev.append("⚠ Growth is lagging value even though real yields fell, so the drag on growth is coming from "
                          "something other than rates (check earnings and company news), not from the discount rate")
            elif driver == "real" and up and growth_r20 <= -READ_GROWTH_TILT:
                ev.append("Consistent: growth lagging value, as rising real yields would predict")
            elif driver == "real" and not up and growth_r20 >= READ_GROWTH_TILT:
                ev.append("Consistent: growth leading value, as falling real yields would predict")
    return {"topic": topic, "verdict": verdict, "evidence": ev, "rule": rule, "changes_if": changes, "driver": driver}


def read_breadth(spy1, rsp1, qqq1, p50, ecw20, asof) -> dict:
    topic = "Concentrated or broad"
    rule = (f"A down day is megacap-led when equal-weight (RSP) beats cap-weight (SPY) by {READ_CONC_GAP}pp or more, "
            f"and broad when most names are below their 50-day. Index days under ±{READ_DAY_MOVE}% are quiet.")
    if spy1 is None or rsp1 is None:
        return {"topic": topic, "verdict": "unavailable — SPY or RSP prices missing", "evidence": [], "rule": rule,
                "changes_if": "Restoring SPY and RSP prices.", "kind": None}
    gap = rsp1 - spy1
    ev = [f"SPY {spy1:+.1f}% · equal-weight RSP {rsp1:+.1f}%"
          + (f" · Nasdaq-100 QQQ {qqq1:+.1f}%" if qqq1 is not None else "") + f" ({asof})"]
    if p50 is not None:
        ev.append(f"{p50:.0f}% of the 109-name proxy universe above its 50-day")
    if ecw20 is not None:
        ev.append(f"Equal vs cap weight over 20 days {ecw20:+.1f}% "
                  f"({'participation broadening' if ecw20 > 1 else 'leadership narrowing' if ecw20 < -1 else 'no clear trend'})")
    if spy1 <= -READ_DAY_MOVE:
        if gap >= READ_CONC_GAP:
            kind, verdict = "megacap_down", "Megacap-led decline: the cap-weighted index fell more than the average stock"
            changes = "Equal-weight falling as much as cap-weight, or under half of names above their 50-day, would make it a broad sell-off."
        elif p50 is not None and p50 < 50:
            kind, verdict = "broad_selloff", "Broad sell-off: the average stock fell with the index and most names are below their 50-day"
            changes = f"Equal-weight holding up by {READ_CONC_GAP}pp or more would narrow it to the megacaps."
        else:
            kind, verdict = "broad_down", "Broad decline, but most names are still above their 50-day"
            changes = "Under half of names above their 50-day would make it a broad sell-off."
    elif spy1 >= READ_DAY_MOVE:
        if -gap >= READ_CONC_GAP:
            kind, verdict = "narrow_up", "Narrow rally: carried by the megacaps, the average stock lagged"
            changes = "Equal-weight keeping pace with cap-weight would make it a broad rally."
        else:
            kind, verdict = "broad_up", "Broad rally: the average stock kept pace with the index"
            changes = f"Equal-weight lagging by {READ_CONC_GAP}pp or more would make it megacap-led."
    else:
        kind, verdict = "quiet", f"Quiet index day ({spy1:+.1f}%)"
        if qqq1 is not None and abs(qqq1 - rsp1) >= 2 * READ_CONC_GAP:
            verdict += f", with a split underneath (Nasdaq-100 {qqq1:+.1f}% vs equal-weight {rsp1:+.1f}%)"
        changes = f"An index move of ±{READ_DAY_MOVE}% or more."
    return {"topic": topic, "verdict": verdict, "evidence": ev, "rule": rule, "changes_if": changes, "kind": kind}


def read_cross(spy1, gld1, tlt1, vix, vix_d, hy, hy_d, hy_asof, asof) -> dict:
    topic = "De-risking or rotation"
    rule = (f"A risk day is an index move of ±{READ_BIG_DAY}% or more. De-risking = stocks AND gold both down "
            f"{READ_BIG_DAY}%+ with long Treasuries up; flight to quality = stocks down, Treasuries up, gold holding; "
            f"stocks and Treasuries down together = a rates or inflation scare.")
    if spy1 is None or tlt1 is None:
        return {"topic": topic, "verdict": "unavailable — SPY or TLT prices missing", "evidence": [], "rule": rule,
                "changes_if": "Restoring SPY and TLT prices.", "kind": None}
    ev = [f"SPY {spy1:+.1f}%" + (f" · gold (GLD) {gld1:+.1f}%" if gld1 is not None else "")
          + f" · long Treasuries (TLT) {tlt1:+.1f}%"
          + (f" · VIX {vix:.1f} ({vix_d:+.1f})" if vix is not None and vix_d is not None else "") + f" ({asof})"]
    if hy is not None:
        ev.append(f"HY OAS {hy:.2f}%" + (f" ({hy_d:+.0f}bp)" if hy_d is not None else "")
                  + f" (FRED print dated {hy_asof}, one session behind prices)")
    g = gld1 if gld1 is not None else 0.0
    if spy1 <= -READ_BIG_DAY:
        if tlt1 > 0 and g <= -READ_BIG_DAY:
            kind, verdict = "liquidity", "Liquidity de-risking: stocks AND gold were sold while Treasuries were bought — investors raising cash"
        elif tlt1 > 0:
            kind, verdict = "flight", "Flight to quality: stocks down, Treasuries up, gold holding"
        else:
            kind, verdict = "rates_scare", "Rates or inflation scare: stocks and long Treasuries fell together"
        changes = "Credit joining (HY OAS widening) would turn this from de-risking into stress; see the next read for the distance."
    elif spy1 >= READ_BIG_DAY:
        kind, verdict = (("risk_on", "Risk-on: stocks bought, long Treasuries sold") if tlt1 < 0
                         else ("relief", "Relief rally: stocks and long Treasuries up together (falling-rate relief)"))
        changes = f"An index day of −{READ_BIG_DAY}% or worse."
    else:
        kind, verdict = "none", f"No cross-asset risk event: the index moved less than ±{READ_BIG_DAY}% ({spy1:+.1f}%)"
        changes = f"An index move of ±{READ_BIG_DAY}% or more."
    return {"topic": topic, "verdict": verdict, "evidence": ev, "rule": rule, "changes_if": changes, "kind": kind}


def _tdays(x: float) -> str:
    return f"about {x:.0f} typical day{'s' if round(x) != 1 else ''}"


def read_stress(hy, hy_mom, hy_sd, hy_asof, vix, vix_sd, flips, hy_mom20=None) -> dict:
    topic = "Distance to stress"
    rule = (f"Lines are the cross-asset lanes' own thresholds: credit WATCH above {LANE_HY_WATCH:.2f}% HY OAS or a "
            f"2-week widening above +{LANE_HY_MOM * 100:.0f}bp or a 20-session widening of +{LANE_HY_MOM_20D * 100:.0f}bp "
            f"or more, STRESS above {LANE_HY_STRESS:.2f}%; vol WATCH at VIX "
            f"{LANE_VIX_WATCH:.0f}, STRESS at {LANE_VIX_STRESS:.0f}. A typical day is one standard deviation of that "
            f"series' daily change over the past year; within {READ_NEAR_DAYS:.0f} typical days counts as close.")
    ev, states, near = [], {}, []
    if hy is not None:
        if hy > LANE_HY_STRESS:
            states["credit"] = "STRESS"
        elif (hy > LANE_HY_WATCH or (hy_mom or 0) > LANE_HY_MOM
              or (hy_mom20 is not None and hy_mom20 >= LANE_HY_MOM_20D)):
            states["credit"] = "WATCH"
        else:
            states["credit"] = "CALM"
            dist = LANE_HY_WATCH - hy
            days = dist / hy_sd if hy_sd else None
            if days is not None and days <= READ_NEAR_DAYS:
                near.append(("credit", days))
        e = f"Credit: HY OAS {hy:.2f}% (FRED, {hy_asof}) — {states['credit']}"
        if states["credit"] == "CALM":
            e += f"; WATCH above {LANE_HY_WATCH:.2f}% is {(LANE_HY_WATCH - hy) * 100:.0f}bp away"
            if hy_sd:
                e += f" ({_tdays((LANE_HY_WATCH - hy) / hy_sd)})"
        if hy_mom is not None:
            e += f"; 2-week change {hy_mom * 100:+.0f}bp (WATCH above +{LANE_HY_MOM * 100:.0f}bp)"
        if hy_mom20 is not None:
            e += f"; 20-session change {hy_mom20 * 100:+.0f}bp (WATCH at +{LANE_HY_MOM_20D * 100:.0f}bp)"
        ev.append(e)
    if vix is not None:
        if vix >= LANE_VIX_STRESS:
            states["vol"] = "STRESS"
        elif vix >= LANE_VIX_WATCH:
            states["vol"] = "WATCH"
        else:
            states["vol"] = "CALM"
            days = (LANE_VIX_WATCH - vix) / vix_sd if vix_sd else None
            if days is not None and days <= READ_NEAR_DAYS:
                near.append(("vol", days))
        e = f"Vol: VIX {vix:.1f} — {states['vol']}"
        if states["vol"] == "CALM":
            e += f"; WATCH at {LANE_VIX_WATCH:.0f} is {LANE_VIX_WATCH - vix:.1f} points away"
            if vix_sd:
                e += f" ({_tdays((LANE_VIX_WATCH - vix) / vix_sd)})"
        ev.append(e)
    for fl in (flips or [])[:1]:
        td = fl.get("typical_days")
        ev.append(f"Regime: nearest flip is {fl.get('label')} {_fmt(fl.get('now'), 2)} → {_fmt(fl.get('at'), 2)}"
                  f"{fl.get('unit', '')} → `{fl.get('to')}`" + (f" ({_tdays(td)})" if td is not None else ""))
    if not states:
        return {"topic": topic, "verdict": "unavailable — HY OAS and VIX missing", "evidence": ev, "rule": rule,
                "changes_if": "Restoring HY OAS and VIX.", "states": states}
    hot = [k for k, v in states.items() if v == "STRESS"]
    warm = [k for k, v in states.items() if v == "WATCH"]
    if hot:
        verdict = f"STRESS in {', '.join(hot)}"
        changes = "The lane falling back below its STRESS line."
    elif warm:
        verdict = f"WATCH in {', '.join(warm)}: risk is being repriced"
        changes = "The lane falling back inside its CALM range, or credit crossing its STRESS line."
    elif near:
        near.sort(key=lambda x: x[1])
        verdict = "Calm, but close: " + " and ".join(
            f"{k} is {_tdays(d_)}" for k, d_ in near) + \
            f" from {'its' if len(near) == 1 else 'their'} WATCH line{'s' if len(near) > 1 else ''}"
        changes = "Crossing either WATCH line flips that lane's vote, and with it the brief's cross-asset majority."
    else:
        verdict = "Calm, with room: neither credit nor vol is near its WATCH line"
        changes = f"Either line coming within {READ_NEAR_DAYS:.0f} typical days."
    return {"topic": topic, "verdict": verdict, "evidence": ev, "rule": rule, "changes_if": changes, "states": states}


def market_read_section(inp: dict, ctx: dict) -> dict:
    """Four diagnoses from data the brief already holds. ctx carries the
    already-built breadth, rotation (compass) and regime (flips) sections."""
    prices, fred = inp.get("prices") or {}, inp.get("fred") or {}
    spy1, asof = _ret1(prices, "SPY")
    rsp1, _ = _ret1(prices, "RSP")
    qqq1, _ = _ret1(prices, "QQQ")
    gld1, _ = _ret1(prices, "GLD")
    tlt1, _ = _ret1(prices, "TLT")
    comp = {c["name"]: c.get("r20") for c in ((ctx.get("rotation") or {}).get("compass") or [])}
    br = ctx.get("breadth") or {}
    vix_s = fred.get("VIXCLS", pd.Series(dtype=float))
    vix = _f(vix_s.iloc[-1]) if len(vix_s) else None
    vix_d = _f(vix_s.iloc[-1] - vix_s.iloc[-2]) if len(vix_s) > 1 else None
    vix_sd = _f(vix_s.diff().dropna().iloc[-252:].std()) if len(vix_s) > 41 else None
    hy_s = fred.get("BAMLH0A0HYM2", pd.Series(dtype=float))
    hy = _f(hy_s.iloc[-1]) if len(hy_s) else None
    hy_d = _f((hy_s.iloc[-1] - hy_s.iloc[-2]) * 100) if len(hy_s) > 1 else None
    hy_mom = _f(hy_s.iloc[-1] - hy_s.iloc[-11]) if len(hy_s) > 10 else None
    hy_mom20 = _f(hy_s.iloc[-1] - hy_s.iloc[-21]) if len(hy_s) > 20 else None
    hy_sd = _f(hy_s.diff().dropna().iloc[-252:].std()) if len(hy_s) > 41 else None
    hy_asof = pd.to_datetime(hy_s.index[-1]).date().isoformat() if len(hy_s) else None
    s20, s1 = _rate_split(fred, 20), _rate_split(fred, 1)
    items = [read_rates(s20, s1, comp.get("Growth vs value")),
             read_breadth(spy1, rsp1, qqq1, br.get("pct_above_50"), comp.get("Equal vs cap weight"), asof),
             read_cross(spy1, gld1, tlt1, vix, vix_d, hy, hy_d, hy_asof, asof),
             read_stress(hy, hy_mom, hy_sd, hy_asof, vix, vix_sd, (ctx.get("regime") or {}).get("flips"),
                         hy_mom20)]
    fred_asof = s20["asof"] if s20 else hy_asof
    note = (f"Prices as of {asof or 'n/a'}; FRED rates and credit as of {fred_asof or 'n/a'}"
            + (" (FRED runs one session behind prices)." if asof and fred_asof and fred_asof < asof else "."))
    return {"items": items, "dates_note": note, "price_asof": asof, "fred_asof": fred_asof}


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


def _ledger_age(inp: dict) -> Optional[int]:
    led = inp.get("ledger")
    if led is None or led.empty or "last_updated" not in led:
        return None
    lu = pd.to_datetime(led.get("last_updated"), errors="coerce").max()
    return (inp["now_et"].date() - lu.date()).days if pd.notna(lu) else None


def portfolio_section(inp: dict, targets: dict, regime_key: Optional[str], force: bool = False) -> dict:
    """REAL positions vs the model. Only used when the ledger is actively
    maintained (updated within LEDGER_ACTIVE_DAYS); otherwise it would
    describe positions that do not exist, so it stays out of the brief."""
    led = inp.get("ledger")
    if led is None or led.empty:
        return {"available": False, "active": False,
                "conclusion": "No real positions tracked — the model portfolio is the reference."}
    age = _ledger_age(inp)
    if not force and (age is None or age > LEDGER_ACTIVE_DAYS):
        return {"available": False, "active": False, "ledger_age_days": age,
                "conclusion": (f"Ledger last touched {age} days ago — not tracking real positions, so it is not "
                               "used. The model portfolio (section 8) is what you SHOULD hold.")}
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
    return {"available": True, "active": True, "ledger_age_days": ledger_age, "stale": stale, "positions": rows,
            "heat_pct": heat, "drift": drift, "authorized_today": authorized, "weekend": weekend,
            "conclusion": c.strip()}


# ── Model portfolio (what you SHOULD hold) ──────────────────────────────────

def model_section(inp: dict, rg: dict) -> dict:
    """The framework's answer, every session: regime targets after the entry
    gate and the portfolio circuit breaker, tracked as a model book."""
    out = {"available": False, "conclusion": ""}
    try:
        import regime_classifier as rc
        import model_book as mbk
    except Exception as e:
        out["conclusion"] = f"Model book unavailable: {type(e).__name__}: {e}"
        return out
    a = inp.get("assessment") or {}
    key = rg.get("key")
    if not key or key not in rc.REGIMES:
        out["conclusion"] = "No live regime — the model portfolio cannot be computed today."
        return out
    prices = inp.get("prices") or {}
    closes = {t: _price_close(prices, t) for t in prices}

    def weights_fn(reg, d):
        d = pd.Timestamp(d)
        fp = lambda t, p="2y": (closes.get(t, pd.Series(dtype=float))
                                [lambda x: x.index <= d] if t in closes else pd.Series(dtype=float))
        return rc.target_weights(reg if reg in rc.REGIMES else "neutral", fp)

    log = inp.get("daily_log")
    regime_by_date = {}
    if log is not None and not log.empty and "regime" in log:
        lg = log.dropna(subset=["regime"]).sort_values("et_date").drop_duplicates("et_date", keep="last")
        regime_by_date = {r.et_date: r.regime for r in lg.itertuples()
                          if str(r.et_date) <= inp["session"].isoformat()}
    # Today's weights come from the SAME gate evaluation the table shows
    # (the brief's own 2y closes + live signals), so "should hold" and the
    # entry-gate column can never disagree. Fall back to the assessment's
    # targets only when the brief has no prices.
    sig = a.get("signals")
    if closes:
        full_fp = lambda t, p="2y": closes.get(t, pd.Series(dtype=float))
        today_w = rc.target_weights(key, full_fp, sig)
    else:
        today_w = a.get("targets") or None
        if today_w and abs(sum(float(v) for v in today_w.values()) - 100) > 1.0:
            today_w = None
        if today_w is None:
            today_w = rc.target_weights(key, None, sig, gate=False)
    path = Path(inp.get("data_dir") or "data") / "model_book.csv"
    try:
        book = mbk.advance(mbk.load(path), inp["session"], regime_by_date, prices, weights_fn, key, today_w)
    except Exception as e:
        out["conclusion"] = f"Model book failed: {type(e).__name__}: {e}"
        return out
    sm = mbk.summary(book)
    pending = mbk.pending_session(book, inp["session"])
    out["pending"] = pending
    out["benchmarks"] = _model_benchmarks(book, closes)
    gates = rg.get("gates_today") or {}
    try:
        import trend_filter as tf
    except Exception:
        tf = None
    rows = []
    spy_tr = trailing_returns(closes.get("SPY", pd.Series(dtype=float)))
    out["spy_returns"] = spy_tr
    for t, w in sorted(sm["weights"].items(), key=lambda kv: -kv[1]):
        if w < 0.05:
            continue
        tr = trailing_returns(closes.get(t, pd.Series(dtype=float)))
        vs = (round(tr["ret_3m"] - spy_tr["ret_3m"], 2)
              if tr["ret_3m"] is not None and spy_tr["ret_3m"] is not None else None)
        hold = None
        if tf is not None and t not in tf.EXEMPT:
            hold = tf.assess_ticker(closes.get(t, pd.Series(dtype=float)))["state"]
        ch = next((c["change"] for c in sm["changes"] if c["ticker"] == t), 0.0)
        rows.append({"ticker": t, "weight": w, "change": ch,
                     "gate": (gates.get(t) or {}).get("state"),
                     "gate_trigger": (gates.get(t) or {}).get("trigger"),
                     "hold_trend": hold or ("cash" if t in rc.ENTRY_EXEMPT else "—"),
                     "ret_1m": tr["ret_1m"], "ret_3m": tr["ret_3m"], "ret_12_1": tr["ret_12_1"],
                     "vs_spy_3m": vs})
    actions, weekend = [], []
    if sm["breaker"] == "ON" and sm["breaker_changed"]:
        actions.append(f"CIRCUIT BREAKER ON — model drawdown {sm['drawdown_pct']:.1f}% breached "
                       f"{mbk.TRIGGER_DD:.0f}%: risk sleeves halved, freed weight to SGOV (weekday-authorized, like a stop)")
    elif sm["breaker"] == "OFF" and sm["breaker_changed"]:
        weekend.append("Circuit breaker RELEASED — re-risk through the entry gate (gated adds only), not all at once")
    if sm["changes"] and not actions:
        moved = ", ".join(f"{c['ticker']} {c['change']:+.1f}" for c in sm["changes"][:8])
        weekend.append(f"Model portfolio changed today ({moved}) — execute at the weekend review if following it")
    c = (f"You SHOULD hold the `{key}` model above"
         + (" — with the CIRCUIT BREAKER ON (risk sleeves halved)" if sm["breaker"] == "ON" else "")
         + f". Model book {sm['nav']:.2f} ({sm['drawdown_pct']:+.1f}% from peak"
         + (f"; 20d {sm['ret_20d']:+.1f}%" if sm.get("ret_20d") is not None else "") + "). ")
    if sm["warn"] and sm["breaker"] != "ON":
        c += f"⚠ Drawdown past the {mbk.WARN_DD:.0f}% warning line — the breaker trips at {mbk.TRIGGER_DD:.0f}%. "
    if sm["breaker"] == "ON":
        c += (f"Release needs drawdown back above {mbk.RELEASE_DD:.0f}% and SPY above its 50-day on "
              f"{mbk.RELEASE_CLOSES} closes ({sm['release_count']}/{mbk.RELEASE_CLOSES} so far). ")
    blocked = [r["ticker"] for r in rows if r["gate"] in ("BLOCKED", "UNAVAILABLE")]
    if blocked:
        c += f"Adds waiting on the entry gate (parked in SGOV): {', '.join(blocked)}. "
    c += "No change today." if not sm["changes"] else f"{len(sm['changes'])} weight change(s) vs the prior session."
    bm = out.get("benchmarks") or {}
    if bm.get("model_pct") is not None and bm.get("spy_pct") is not None:
        c += (f" Since {bm['since']}: model {bm['model_pct']:+.2f}% vs SPY {bm['spy_pct']:+.2f}%"
              + (f" and 60/40 {bm['sixty_forty_pct']:+.2f}%" if bm.get("sixty_forty_pct") is not None else "")
              + ".")
    if pending:
        c = (f"⏳ Closing prices for {inp['session']} were not published when this ran — the model book stands at "
             f"{sm.get('date')} and books {inp['session']} on the next run (never as a 0% day). " + c)
    if failed_regime := bool(((inp.get("assessment") or {}).get("regime") or {}).get("data_failure")):
        c = "⚠ Regime HELD through a data failure — these weights are yesterday's call, not a new one. " + c
    # v1.6 (N39-N41): attribution, AI-factor exposure, volatility-target readout (display only)
    try:
        _br = _book_risk
        if _br is None:
            raise ImportError("book_risk.py not found next to daily_brief.py")
        out["attribution"] = _br.attribution(book, closes)
        out["ai_exposure"] = _br.ai_exposure(sm["weights"], closes)
        out["vol_target"] = _br.vol_target(book)
        if (out["ai_exposure"] or {}).get("flags"):
            c += " ⚠ " + "; ".join(out["ai_exposure"]["flags"]) + "."
    except Exception as e:
        out["attribution"] = out["ai_exposure"] = out["vol_target"] = {
            "available": False, "conclusion": f"book_risk unavailable: {type(e).__name__}: {e}"}
    out.update(available=True, summary=sm, rows=rows, actions=actions, weekend=weekend,
               conclusion=c.strip(), _book=book, path=str(path), regime_held=failed_regime)
    return out


def _model_benchmarks(book: pd.DataFrame, closes: dict) -> dict:
    """Model NAV vs SPY and a daily-rebalanced 60/40 (SPY/AGG), over the book's
    own dates. Display only — never a rule input."""
    out = {"since": None, "model_pct": None, "spy_pct": None, "sixty_forty_pct": None}
    try:
        if book is None or book.empty:
            return out
        b = book.assign(date=pd.to_datetime(book["date"]).dt.normalize()).sort_values("date")
        d0, d1 = b["date"].iloc[0], b["date"].iloc[-1]
        out["since"] = d0.date().isoformat()
        out["model_pct"] = round((float(b["nav"].iloc[-1]) / float(b["nav"].iloc[0]) - 1) * 100, 2)

        def _s(t):
            s = closes.get(t, pd.Series(dtype=float)).dropna()
            if getattr(s.index, "tz", None) is not None:
                s.index = s.index.tz_localize(None)
            s.index = pd.to_datetime(s.index).normalize()
            return s[(s.index >= d0) & (s.index <= d1)]
        spy, agg = _s("SPY"), _s("AGG")
        if len(spy) > 1 and spy.index[0] == d0:
            out["spy_pct"] = round((float(spy.iloc[-1]) / float(spy.iloc[0]) - 1) * 100, 2)
        if len(spy) > 1 and len(agg) > 1 and spy.index[0] == d0 and agg.index[0] == d0:
            r = (0.6 * spy.pct_change() + 0.4 * agg.pct_change()).dropna()
            out["sixty_forty_pct"] = round((float((1 + r).prod()) - 1) * 100, 2)
    except Exception:
        pass
    return out


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
    if ev == "GDP":
        return ("GDP — a weak print with weak consumer data moves the growth composite toward CONTRACTING "
                "(the growth_scare path needs price confirmation: cyclicals lagging defensives by 3pp+). "
                "A strong print with hot core PCE (same morning) pushes DFII10 up." + lm_txt(+1))
    if ev == "ELECTION":
        return ("Election — results arrive after the close, so the next session can gap through stops; that is why "
                "it is a blackout. It changes no regime input on the day; any effect reaches the regime through "
                "long real yields (the fiscal path), so watch DFII10 over the following sessions." + lm_txt(+1))
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
        add((inp.get("series_label") or {}).get(sid, f"FRED {sid}"), s.index[-1].date().isoformat() if len(s) else None,
            FRED_MAX_AGE.get(sid, 4), note)
    a = inp.get("assessment")
    _reg = (a or {}).get("regime") or {}
    if a and _reg.get("data_failure"):
        out.append({"input": "Regime assessment", "asof": today.isoformat(), "age_days": 0, "status": "FAILED",
                    "note": "core inputs missing — regime HELD from " + str(_reg.get("held_from") or "nothing (placeholder neutral)")})
    else:
        add("Regime assessment", today.isoformat() if a else None, 0, "" if a else "live assessment failed")
    try:
        import fred_client as _fc
        _os_ = _fc.outage_status()
        if _os_["down"] or _os_["consecutive_failures"]:
            out.append({"input": "FRED connection", "asof": None, "age_days": None,
                        "status": "DOWN" if _os_["down"] else "WARN",
                        "note": f"{_os_['consecutive_failures']} consecutive series failed; {_os_['last_error']}"})
    except Exception:
        pass
    rot = inp.get("rotation") or {}
    add("Money Flow bridge", (rot.get("published_at") or "")[:10] or None, 1, ref=wall)
    if inp.get("spy_holdings"):
        out.append({"input": "SPY holdings (top 10)", "asof": today.isoformat(), "age_days": 0, "status": "OK",
                    "note": f"{len(inp['spy_holdings'])} largest weights, State Street daily file"})
    else:
        out.append({"input": "SPY holdings (top 10)", "asof": None, "age_days": None, "status": "MISSING",
                    "note": inp.get("spy_holdings_error") or "not fetched — blocks the top-10 contribution table"})
    fm_ = inp.get("flow_map") or {}
    add("Flow map summary", (fm_.get("published_at") or "")[:10] or None, 1, ref=wall,
        note="" if fm_ else "not published yet (Money_Flow publish v1.1)")
    mk = inp.get("markets") or {}
    add("Markets bridge", (mk.get("published_at") or "")[:10] or None, 1, ref=wall)
    b = inp.get("swing") or {}
    add("Swing brief", b.get("date"), 0 if not b.get("date") or b.get("date") <= today.isoformat() else 9,
        "" if not b.get("date") or b.get("date") <= today.isoformat() else "run after the close — scans this session")
    led = inp.get("ledger")
    lu = pd.to_datetime(led.get("last_updated"), errors="coerce").max() if led is not None and not led.empty else None
    _lage = _ledger_age(inp)
    if _lage is None or _lage > LEDGER_ACTIVE_DAYS:
        out.append({"input": "Position ledger", "asof": lu.date().isoformat() if lu is not None and pd.notna(lu) else None,
                    "age_days": _lage, "status": "UNUSED",
                    "note": "not tracking real positions — the model portfolio (section 8) is the reference"})
    else:
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
        # v1.1: the session's bar must exist for the CALENDAR ticker (SPY), not
        # for whichever ticker happens to be freshest. Before this, one fresh
        # ticker made the row read OK while SPY was a session behind.
        spy = _price_close(px, "SPY")
        ref = spy.index[-1] if len(spy) else None
        lasts = [pd.to_datetime(df.index[-1]).normalize() for df in px.values() if df is not None and not df.empty]
        have = sum(1 for d in lasts if ref is not None and d >= pd.to_datetime(ref).normalize())
        add("Prices (yfinance)", pd.to_datetime(ref).date().isoformat() if ref is not None else None, 0,
            f"SPY calendar; {have}/{len(px)} tickers have that bar"
            + ("" if ref is None or pd.to_datetime(ref).date() >= today else
               " — this session's closes were NOT published when the brief ran"))
    if inp.get("calendar_asof"):
        cov = inp.get("calendar_coverage") or {}
        out.append({"input": "Event calendar", "asof": inp["calendar_asof"], "age_days": None,
                    "status": cov.get("status") or "UNKNOWN",
                    "note": cov.get("note") or "coverage check unavailable (event_calendar older than v1.2)"})
    return out


# ── Signal scorecard (fix_status N4) ───────────────────────────────────────

SWING_CARDS = Path("logs/swing/cards_history.csv")


def signals_section(inp: dict, mdl: dict) -> dict:
    """Derive today's signals (persisted by write()) and score the log so far.
    Derivation is pure; writing happens only in write(), so a dry run or a
    selftest never touches data/signal_outcomes.csv."""
    out = {"available": False, "new": [], "scorecard": {}, "conclusion": ""}
    try:
        import signal_outcomes as so
    except Exception as e:
        out["conclusion"] = f"Signal log unavailable: {type(e).__name__}: {e}"
        return out
    d = inp["session"].isoformat()
    try:
        existing = so._load(str(Path(inp.get("data_dir") or "data") / "signal_outcomes.csv"))
        book = mdl.get("_book")
        try:
            cards = pd.read_csv(SWING_CARDS) if SWING_CARDS.exists() else pd.DataFrame()
        except Exception:
            cards = pd.DataFrame()
        rows = (so.from_daily_log(inp.get("daily_log"), d, book)
                + so.from_swing_cards(cards, d, existing)
                + so.from_rotation(inp.get("rotation") or {}, d, existing)
                + (so.from_flow_map(inp.get("flow_map") or {}, existing,
                                    stale=(_hours_since((inp.get("flow_map") or {}).get("published_at"), inp["now_et"])
                                           or 1e9) > FLOW_MAP_MAX_AGE_H)
                   if hasattr(so, "from_flow_map") else []))
        known = set(existing["signal_id"]) if not existing.empty else set()
        out["new"] = rows
        out["new_today"] = [r for r in rows if r["signal_id"] not in known]
        closes = {t: _price_close(inp.get("prices") or {}, t) for t in (inp.get("prices") or {})}
        fetch = os.environ.get("SIGNAL_FETCH", "1") != "0"
        out["scorecard"] = so.scorecard(closes, str(Path(inp.get("data_dir") or "data") / "signal_outcomes.csv"),
                                        fetch=fetch) if not existing.empty else {"coverage": so.coverage("/nonexistent"), "rates": {}}
        out["available"] = True
    except Exception as e:
        out["conclusion"] = f"Signal scoring failed: {type(e).__name__}: {e}"
        return out
    cov = (out["scorecard"] or {}).get("coverage") or {}
    nt = out["new_today"]
    c = (f"{cov.get('signals', 0)} signals on record" + (f" since {cov['since']}" if cov.get("since") else "")
         + f"; {len(nt)} new this run"
         + (f" ({', '.join(sorted({r['signal_type'] for r in nt}))})" if nt else "") + ". ")
    rates4 = (out["scorecard"].get("rates") or {}).get("4w") or []
    scored = [r for r in rates4 if r.get("n")]
    if not scored:
        c += "Nothing has reached its 4-week horizon yet — no verdicts, by design."
    else:
        c += "4-week scores so far: " + "; ".join(
            f"{r['signal_type']} n={r['n']} avg {r['avg_rel']:+.2f}pp" for r in scored[:5]) + "."
        c += f" Hit rates appear only at {so.MIN_SAMPLE}+ scored signals."
    out["conclusion"] = c
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
    fm = flow_map_section(inp, rg.get("key"))
    br = breadth_section(inp)
    mr = market_read_section(inp, {"breadth": br, "rotation": ro, "regime": rg})
    targets = a.get("targets") or (inp.get("markets") or {}).get("regime_targets") or {}
    pf = portfolio_section(inp, targets, rg.get("key"))
    mdl = model_section(inp, rg)
    sw = swing_section(inp)
    nx = next48_section(inp, rg)
    al = alerts_section(inp)
    sg = signals_section(inp, mdl)
    dh = data_health(inp)
    brief = {"session": inp["session"].isoformat(), "generated_et": mt.fmt_et(inp["now_et"]),
             "scoreboard": sb, "market_read": mr, "regime": rg, "cross_asset": xa, "rotation": ro, "flow": fl,
             "flow_map": fm, "breadth": br, "model": mdl, "portfolio": pf, "swing": sw, "next48": nx, "alerts": al,
             "signals": sg,
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
    # 3 — what the model says to do
    md_ = b.get("model") or {}
    sm = md_.get("summary") or {}
    auth = list(md_.get("actions") or [])
    if pf.get("active"):
        auth += list(pf.get("authorized_today") or [])
    if sm:
        s3 = (f"Model portfolio: `{sm.get('regime')}`"
              + (", CIRCUIT BREAKER ON" if sm.get("breaker") == "ON" else "")
              + f", drawdown {sm.get('drawdown_pct', 0):+.1f}%"
              + (f", {len(sm.get('changes') or [])} weight change(s) today" if sm.get("changes") else ", no change today")
              + ("; this session's closes not yet published (books next run)" if md_.get("pending") else "")
              + ".")
    else:
        s3 = "Model portfolio unavailable."
    if auth:
        s3 += " Authorized today: " + "; ".join(x.split(" —")[0] for x in auth) + "."
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
    weekend = list((b.get("model") or {}).get("weekend") or [])
    if pf.get("active"):
        weekend += list(pf.get("weekend") or [])
    _cc = (rg.get("credit_cycle") or {}).get("state")
    if _cc == "RE_ENTRY":
        weekend.append("HY spread peak CONFIRMED — run the quality-value screen; cyclical/deep value and "
                       "small caps are eligible adds (still need Level 2 flow + Level 4 entry)")
    elif _cc == "RE_ENTRY_PENDING":
        weekend.append("HY spread peak-and-turn on 1 close — confirm on the next close before any cyclical adds")
    if rg.get("days_in_regime") == 2:
        weekend.insert(0, f"Regime `{rg['key']}` confirmed on two closes — execute the gated rebalance plan in "
                          "section 3 (cuts, then hedges, then adds; blocked adds stay parked in SGOV)")
    if pf.get("active") and pf.get("stale"):
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

    mr = b.get("market_read") or {}
    if mr.get("items"):
        L += ["## 1A · Market read — what the data says, and why",
              f"*{mr.get('dates_note', '')} Each verdict is a rule applied to the numbers listed under it.*", ""]
        for it in mr["items"]:
            L.append(f"**{it['topic']}: {it['verdict']}**")
            L += [f"- {e}" for e in it.get("evidence", [])]
            L += [f"- *Rule:* {it['rule']}", f"- *Would change if:* {it['changes_if']}", ""]

    sb = b["scoreboard"]
    L += ["## 2 · Scoreboard", "| Metric | Value | Δ1d | Δ5d | Δ20d | 1-yr pctile | Today in σ | As of |",
          "|---|---|---|---|---|---|---|---|"]
    for r in sb["rows"]:
        L.append(f"| {r['name']} | {_fmt(r['value'], 2)}{r['unit'] if r['unit'] == '%' else ''} | {r['d1_txt']} | {r['d5_txt']} | "
                 f"{r['d20_txt']} | {_fmt(r['pctile_1y'], 0)} | {_fmt(r['z1d'], 1, 'σ', True) if r['z1d'] is not None else 'n/a'} | {r['asof'] or 'n/a'} |")
    _notes = [f"{r['name']}: {r['note']}" for r in sb["rows"] if r.get("note")]
    if _notes:
        L += [""] + [f"_{x}_" for x in _notes]
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
    cc = rg.get("credit_cycle") or {}
    if cc.get("state"):
        det = ""
        if cc.get("peak") is not None:
            det = (f" (6-mo HY high {cc['peak']:.2f}% on {cc.get('peak_date')}, now {cc['current']:.2f}%, "
                   f"2-wk {cc['mom_2w']:+.2f}pp)" if cc.get("mom_2w") is not None else "")
        L.append(f"- Credit cycle: **{cc['state']}**{det} — {cc.get('action', '')}")
    if rg.get("flips"):
        L += ["", "**Nearest flips** (classifier re-run with one input moved, all else held):", "",
              "| Input | Now | Flips at | Move needed | Typical days | Becomes |", "|---|---|---|---|---|---|"]
        for f in rg["flips"]:
            L.append(f"| {f['label']} | {_fmt(f['now'], 2)}{f['unit']} | {_fmt(f['at'], 2)}{f['unit']} | "
                     f"{f['delta']:+.2f}{f['unit']} | {_fmt(f.get('typical_days'), 0) if f.get('typical_days') is not None else (f.get('note') or 'n/a')} | `{f['to']}` |")
    elif rg.get("flip_error"):
        L.append(f"- Nearest flip: {rg['flip_error']}")
    gt = rg.get("gates_today") or {}
    if gt:
        L += ["", "**Entry gate on today's adds** (every add must be above a rising 200-day and its 50-day; "
              "blocked adds park in SGOV, pullbacks go in at half):",
              "- " + " · ".join(f"{t} {g['state']}" for t, g in sorted(gt.items()))]
    for pl in rg.get("plans") or []:
        L += ["", f"**{pl['title']}** — {pl['summary']}", "",
              "| Step | Fund | From → To | Trade now | Pending | Entry gate | Pending until |",
              "|---|---|---|---|---|---|---|"]
        for r in pl["rows"]:
            L.append(f"| {r['step']} | {r['ticker']} | {r['from']:.1f}% → {r['to']:.1f}% | {r['now']:+.1f} | "
                     f"{r['pending']:+.1f} | {r['gate']} | {r['trigger'] or '—'} |")
        L.append("_Model-portfolio weights. Cuts are never gated; an add executes only when its trend "
                 "confirms. The same gate applies to weight returning through the base allocation._")
    if rg.get("plan_error"):
        L.append(f"- ⚠ Rebalance plan unavailable: {rg['plan_error']}")
    if rg.get("guards"):
        L += ["", "Guard inputs:", *[f"- {g}" for g in rg["guards"]]]
    L += ["", f"**Conclusion:** {rg['conclusion']}", ""]

    xa = b["cross_asset"]
    L += ["## 4 · Cross-asset confirmation"]
    if xa.get("available"):
        L += ["| Lane | Vote | Reading | Why |", "|---|---|---|---|"]
        for k, v in xa.get("lanes", {}).items():
            # Full note, never truncated: the "why" is the evidence for the vote.
            # (v1.1, 2026-10-31: a [:160] cut dropped the term-premium diagnosis
            # mid-sentence.) Pipes are escaped so a note cannot break the table.
            note = str(v.get('note', '')).replace("|", "\\|").replace("\n", " ")
            L.append(f"| {k} | {v.get('state')} | {v.get('reading')} | {note} |")
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

    fm = b.get("flow_map") or {}
    L += [f"## 6A · Where the money went (Tier A ETF flows, {fm.get('window') or 20} sessions)"]
    if not fm.get("available"):
        L += [f"*{fm.get('message', 'Flow map summary unavailable.')}*", ""]
    else:
        when = f"published {str(fm.get('published_at') or '')[:16].replace('T', ' ')} UTC"
        L.append(f"*Data through {fm.get('data_through') or 'n/a'} · {when} · {fm.get('measured')} of {fm.get('total')} "
                 f"funds measured (trusted share counts only).*"
                 + (f" **STALE — {_fmt(fm.get('age_hours'), 0)}h old; treat as last known, not today's flows.**"
                    if fm.get("stale") else ""))
        L += ["", "| Asset class | Net flow | % of assets | Direction | Funds measured | Not measured |",
              "|---|---|---|---|---|---|"]
        for r in fm["rows"]:
            L.append(f"| {r['asset_class']} | {_usd(r['flow_usd'])} | {_fmt(r['pct_aum'], 2, '%', True)} | "
                     f"{r['direction']}{' (thin)' if r['thin'] else ''} | "
                     f"{r['measured']} of {r['total']} | {', '.join(r['missing']) or '—'} |")
        if any(r["thin"] for r in fm["rows"]):
            L.append("\n*(thin) = under half the class's funds measured; that row is indicative only.*")
        L += ["", f"**Verdict: {fm['verdict']}**"]
        L += [f"- {str(e).replace(chr(10), ' ')}" for e in fm["evidence"]]
        L += [f"- *Rule:* {fm['rule']}", f"- *Would change if:* {fm['changes_if']}", ""]
        if fm.get("steps"):
            L.append("**What to do with it**" + (" *(stale summary: last known reading, re-check before acting)*"
                                                if fm.get("stale") else ""))
            L += [f"{i}. {x}" for i, x in enumerate(fm["steps"], 1)]
            L.append("")
        if fm.get("regime_check"):
            L += [f"**Regime cross-check:** {fm['regime_check']}", ""]

    br = b["breadth"]
    L += ["## 7 · Breadth & internals",
          f"- % above 50-day: **{_fmt(br.get('pct_above_50'), 0)}%** · above 200-day: **{_fmt(br.get('pct_above_200'), 0)}%** "
          f"· 52-wk highs/lows: {br.get('new_highs', 'n/a')}/{br.get('new_lows', 'n/a')} · universe: {br.get('universe')}",
          f"- SPY 20d {_fmt(br.get('spy_20d'), 1, '%', True)} vs RSP (equal weight) 20d {_fmt(br.get('rsp_20d'), 1, '%', True)}",
          "", f"**Conclusion:** {br['conclusion']}", ""]
    bt = br.get("trend") or {}
    if bt.get("available"):
        pts = bt["points"]
        labs = [(k, h) for k, h in (("today", "Today"), ("5d", "5 sessions ago"), ("20d", "20 sessions ago"),
                                    ("60d", f"{BREADTH_LOOKBACK} sessions ago")) if k in pts]
        L += ["**Breadth trend**", "", "| | " + " | ".join(f"{h} ({pts[k]['date'][5:]})" for k, h in labs) + " |",
              "|---|" + "---|" * len(labs)]
        for c, name, suf in (("p50", "% above 50-day", "%"), ("p200", "% above 200-day", "%"),
                             ("hl", "52-wk highs minus lows", "")):
            L.append(f"| {name} | " + " | ".join(
                "n/a" if pts[k][c] is None else (f"{pts[k][c]:.0f}{suf}" if suf else f"{pts[k][c]:+.0f}") for k, _ in labs) + " |")
        L += ["", f"**{bt['verdict']}**", f"- *Rule:* {bt['rule']}", ""]
    else:
        L += [f"*Breadth trend unavailable: {bt.get('reason', 'no data')}.*", ""]
    tt = br.get("top10") or {}
    if tt.get("available"):
        k = len(tt["rows"])
        L += [f"**Top-{k} contribution** *(SPY holdings weights; prices through {tt['asof']})*", "",
              "| Holding | Weight | 1-day | 20-day | 20-day contribution |", "|---|---|---|---|---|"]
        for r in tt["rows"]:
            L.append(f"| {r['ticker']} | {r['weight']:.2f}% | {r['r1']:+.2f}% | {r['r20']:+.2f}% | {r['c20']:+.2f} pts |")
        w1, w20 = tt["windows"][1], tt["windows"][20]
        L.append(f"| **Top {k} together** | {tt['weight_now']:.1f}% | {w1['top_contrib']:+.2f} pts | | "
                 f"**{w20['top_contrib']:+.2f} pts** |")
        L.append(f"| **Rest of the index** | {100 - tt['weight_now']:.1f}% | {_fmt(w1['rest'], 2, '%', True)} | "
                 f"{_fmt(w20['rest'], 2, '%', True)} | {w20['spy'] - w20['top_contrib']:+.2f} pts |")
        L.append(f"| **SPY** | 100% | {w1['spy']:+.2f}% | {w20['spy']:+.2f}% | {w20['spy']:+.2f} pts |")
        L += ["", f"**{tt['verdict']}**", f"- *Rule:* {tt['rule']}", f"- *Would change if:* {tt['changes_if']}", ""]
    else:
        L += [f"*Top-10 contribution unavailable: {tt.get('reason', 'no data')}.*", ""]

    pf = b["portfolio"]
    md_ = b.get("model") or {}
    L += ["## 8 · Model portfolio — what you SHOULD hold (Levels 5–7)"]
    if md_.get("available"):
        sm = md_["summary"]
        L.append(f"- Regime `{sm['regime']}` · breaker **{sm['breaker']}** · model book {sm['nav']:.2f} "
                 f"({sm['drawdown_pct']:+.1f}% from peak {sm['peak']:.2f})"
                 + (f" · 5d {sm['ret_5d']:+.2f}%" if sm.get("ret_5d") is not None else "")
                 + (f" · 20d {sm['ret_20d']:+.2f}%" if sm.get("ret_20d") is not None else "")
                 + (f" · since inception {sm['since_inception_pct']:+.2f}%" if sm.get("since_inception_pct") is not None else "")
                 + f" · tracked since {sm['since']}"
                 + (f" ({sm['reconstructed_sessions']} sessions reconstructed from the daily log)"
                    if sm.get("reconstructed_sessions") else ""))
        if md_.get("pending"):
            L.append(f"- ⏳ **This session's closes were not published when the brief ran** — the book stands at "
                     f"{sm.get('date')} and books the session on the next run. A day is never booked as 0%.")
        if md_.get("regime_held"):
            L.append("- ⚠ **Regime held through a data failure** — these weights repeat the last confirmed call.")
        _bm = md_.get("benchmarks") or {}
        if _bm.get("model_pct") is not None:
            L.append(f"- Since {_bm['since']}: model **{_bm['model_pct']:+.2f}%** · SPY "
                     + (f"{_bm['spy_pct']:+.2f}%" if _bm.get("spy_pct") is not None else "n/a")
                     + " · 60/40 (SPY/AGG, daily rebalanced) "
                     + (f"{_bm['sixty_forty_pct']:+.2f}%" if _bm.get("sixty_forty_pct") is not None else "n/a")
                     + " _(before costs and taxes)_")
        L += ["", "| Sleeve | Should hold | Change today | Entry gate (adds) | Hold trend (200-day) "
                  "| 1M | 3M (vs SPY) | 12-1 |",
              "|---|---|---|---|---|---|---|---|"]
        _p = lambda v: "—" if v is None else f"{v:+.1f}%"
        for r in md_["rows"]:
            g = r["gate"] or "—"
            if r.get("gate_trigger") and r["gate"] in ("BLOCKED", "PULLBACK", "UNAVAILABLE"):
                g += f" — until {r['gate_trigger']}"
            m3 = _p(r.get("ret_3m")) + ("" if r.get("vs_spy_3m") is None else f" ({r['vs_spy_3m']:+.1f}pp)")
            L.append(f"| {r['ticker']} | {r['weight']:.1f}% | {r['change']:+.1f} | {g} | {r['hold_trend']} "
                     f"| {_p(r.get('ret_1m'))} | {m3} | {_p(r.get('ret_12_1'))} |")
        _s = md_.get("spy_returns") or {}
        L.append(f"_Returns are display-only (dividend-adjusted closes), not a rule input. 1M = 21 sessions, "
                 f"3M = 63, **12-1** = the 12-month return excluding the latest month. SPY: 1M {_p(_s.get('ret_1m'))} · "
                 f"3M {_p(_s.get('ret_3m'))} · 12-1 {_p(_s.get('ret_12_1'))}. “—” = not enough history._")
        # v1.6: where the return came from, AI exposure, volatility target (display only)
        _at = md_.get("attribution") or {}
        if _at.get("available"):
            _wins = _at["windows"]
            _labs = [k for k in ("5 sessions", "20 sessions", "since inception") if k in _wins]
            _bks = sorted({b_ for k in _labs for b_ in _wins[k]["by_bucket"]},
                          key=lambda b_: _wins[_labs[-1]]["by_bucket"].get(b_, 0.0))
            L += ["", "**Where the return came from** (percentage points of book return; held weights × "
                      "each session's return, summed)",
                  "| Bucket | " + " | ".join(_labs) + " |", "|---|" + "---|" * len(_labs)]
            for b_ in _bks:
                L.append(f"| {b_} | " + " | ".join(f"{_wins[k]['by_bucket'].get(b_, 0.0):+.2f}" for k in _labs) + " |")
            L.append("| **Sum** | " + " | ".join(f"**{_wins[k]['sum_pts']:+.2f}**" for k in _labs) + " |")
            L.append("| Book NAV change | " + " | ".join(
                (f"{_wins[k]['nav_pct']:+.2f}%" if _wins[k].get("nav_pct") is not None else "—") for k in _labs) + " |")
            _w20 = _wins.get("20 sessions") or {}
            if _w20.get("by_ticker"):
                _tk = list(_w20["by_ticker"].items())
                L.append("_Largest 20-session drags: " + ", ".join(f"{t} {v:+.2f}" for t, v in _tk[:3])
                         + " · supports: " + ", ".join(f"{t} {v:+.2f}" for t, v in _tk[::-1][:3])
                         + ". The sum differs slightly from the NAV change because the NAV compounds._")
        _ai = md_.get("ai_exposure") or {}
        if _ai.get("conclusion"):
            L += ["", f"**AI exposure** ({_ai.get('lookback', 60)} sessions, vs SPY and SMH − SPY): {_ai['conclusion']}"]
            if _ai.get("available"):
                _r = [r for r in _ai["rows"] if r.get("ai_pct") not in (None, 0)]
                _r = sorted(_r, key=lambda r: -abs(r["ai_pct"]))[:6]
                if _r:
                    L.append("_Largest contributors: " + ", ".join(
                        f"{r['ticker']} {r['weight']:.0f}% × {r['b_ai']:+.2f} = {r['ai_pct']:+.1f}%" for r in _r)
                        + f". Limits {_ai['flag_exposure_pct']:.0f}% exposure / {_ai['flag_risk_share_pct']:.0f}% "
                          "of variance are PROPOSED._")
        _vt = md_.get("vol_target") or {}
        if _vt.get("conclusion"):
            L += ["", f"**Volatility target** (display only): {_vt['conclusion']}"]
        if md_.get("actions"):
            L += ["", "**Authorized today:**", *[f"- {x}" for x in md_["actions"]]]
        L.append("_Model: regime targets → entry gate (blocked adds parked in SGOV) → circuit breaker "
                 "(halve risk sleeves at −8% drawdown). Daily-rebalanced, before costs and taxes._")
    pf = b["portfolio"]
    if pf.get("available"):
        L += ["", "**Your real positions vs the model** (ledger)"]
        if pf.get("stale"):
            L.append(f"> ⚠ **Ledger last updated {pf['ledger_age_days']} days ago.**")
        L += ["| Position | Close | Stop | Stop status | Invalidation | Check |", "|---|---|---|---|---|---|"]
        for r in pf["positions"]:
            L.append(f"| {r['ticker']} | {_fmt(r['last'])} | {_fmt(r['stop'])} | {r['status']} — {r['note']} | "
                     f"{r['invalidation'][:70]} | **{r['inv_status']}** {r['inv_detail']} |")
        if pf.get("drift"):
            br_ = [d for d in pf["drift"] if d["breach"]]
            L += ["", "Drift vs the model (ledger-value basis): "
                  + (", ".join(f"{d['sleeve']} {d['live']:.1f}% vs {d['target']:.1f}%" for d in br_) if br_ else "all sleeves inside ±20%")]
        if pf.get("authorized_today"):
            L += ["", "**Authorized today (real positions):**", *[f"- {x}" for x in pf["authorized_today"]]]
    else:
        L.append(f"- {pf.get('conclusion')}")
    L += ["", f"**Conclusion:** {md_.get('conclusion') or pf.get('conclusion')}", ""]

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

    sg = b.get("signals") or {}
    L += ["## 12 · Signal scorecard — is the framework working?"]
    if sg.get("conclusion"):
        L.append(f"- {sg['conclusion']}")
    for h in ("1w", "4w", "12w"):
        rows_ = [r for r in ((sg.get("scorecard") or {}).get("rates") or {}).get(h, []) if r.get("logged")]
        if not rows_:
            continue
        L += ["", f"**{h} horizon** (signed return vs SPY; portfolio signals vs their benchmark weights)",
              "| Signal | Logged | Scored | Hit rate | Avg | Median | Verdict |", "|---|---|---|---|---|---|---|"]
        for r in rows_:
            _n = lambda v, sfx="pp": "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:+.2f}{sfx}"
            L.append(f"| {r['signal_type']} | {r['logged']} | {r['n']} | "
                     f"{'—' if r.get('hit_rate') is None else str(r['hit_rate']) + '%'} | {_n(r.get('avg_rel'))} | "
                     f"{_n(r.get('med_rel'))} | {r.get('verdict', '')} |")
    L.append("_Signals are logged when they fire (the daily log and swing cards were written at the time, so "
             "replaying them is not hindsight). Weekly portfolio snapshots overlap at 4w/12w — read early numbers "
             "as direction, not proof._")
    L += ["", "## 13 · Data health", "| Input | As of | Age | Status | Note |", "|---|---|---|---|---|"]
    for d in b["data_health"]:
        L.append(f"| {d['input']} | {d['asof'] or '—'} | {'' if d['age_days'] is None else str(d['age_days']) + 'd'} | "
                 f"{'✅' if d['status'] == 'OK' else 'ℹ️' if d['status'] == 'UNUSED' else '⚠'} {d['status']} | {d['note']} |")
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
    sg = b.get("signals") or {}
    if sg.get("new"):
        try:
            import signal_outcomes as so
            n = so.record_rows(sg["new"], str(Path(os.environ.get("DATA_DIR", "data")) / "signal_outcomes.csv"))
            sg["recorded"] = n
        except Exception as e:
            b.setdefault("errors", []).append(f"signals not saved: {e}")
    md_ = b.get("model") or {}
    book = md_.pop("_book", None)
    if book is not None:
        try:
            import model_book as mbk
            mbk.save(book, Path(md_.get("path") or mbk.BOOK_FILE))
        except Exception as e:
            b.setdefault("errors", []).append(f"model book not saved: {e}")
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
            "DFF": walk(3.6, 0.0), "DTB3": walk(3.7, 0.01),
            "BAMLH0A0HYM2": walk(3.0, 0.03).clip(lower=2.5), "BAMLC0A0CM": walk(0.9, 0.01),
            "DTWEXBGS": walk(120, 0.3), "VIXCLS": walk(16, 0.6).clip(lower=10), "DCOILWTICO": walk(70, 1.0),
            "DGS30": walk(4.6, 0.05)}
    fred["DFII10"].iloc[-1] = fred["DFII10"].iloc[-2] + 0.20        # a 5σ day
    fred["VIXCLS"] = fred["VIXCLS"].iloc[:-2]                        # FRED lags the market
    fred["DCOILWTICO"] = fred["DCOILWTICO"].iloc[:-2]                # ... and so does FRED's WTI
    fetch_fred = lambda sid, key="", start="": fred.get(sid, pd.Series(dtype=float))

    def px(v0, drift=0.0005):
        c = v0 * np.exp(np.cumsum(rng.normal(drift, 0.01, len(idx))))
        return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6}, index=idx)
    tickers = {t for _, a, b in COMPASS for t in a + b} | {"QQQ", "GLD", "TLT", "XOM", "CVX", "NVDA", "AAPL"}
    prices = {t: px(100) for t in tickers}
    prices["TLT"] = px(100, drift=-0.001)
    prices["^VIX"] = px(16, drift=0.0)
    prices["CL=F"] = pd.DataFrame({"Open": 69.0, "High": 69.0, "Low": 69.0, "Close": 69.0, "Volume": 1e6}, index=idx)  # after-hours last trade

    sig = SimpleNamespace(short_real_rate=0.48, long_real_yield=2.85, long_real_mom_3m=0.66, breakeven_10y=2.3,
                          hy_oas=2.8, hy_oas_mom_2w=0.1, spread_2s10s=0.3, spread_2s10s_mom_3m=0.0,
                          dxy_20d_change_pct=1.0, stock_bond_corr_60d=0.48, asof=None,
                          cpi_yoy=3.4, cpi_3m_saar=0.2, cpi_mom_sa=0.4, eff_funds=3.88, ig_oas=0.9, dxy=120)
    import regime_classifier as rc
    for _t in rc.BASE_WEIGHTS:           # every sleeve priced, as in production
        prices.setdefault(_t, px(100))
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
        os.environ["SIGNAL_FETCH"] = "0"          # never touch the network in a selftest
        import importlib, storage_backend, position_ledger
        importlib.reload(storage_backend); importlib.reload(position_ledger)
        now = datetime(2026, 9, 25, 20, 0)
        def _mbars(_t):                     # 1-min CL=F bars for the last 3 sessions, around the settle window
            rows_ = []
            for d_ in pd.bdate_range(end="2026-09-25", periods=3):
                for hh, mm, px_, vol in ((14, 27, 70.0, 100), (14, 28, 71.0, 300), (14, 29, 72.0, 100),
                                         (14, 30, 75.0, 100), (16, 59, 69.0, 50)):
                    rows_.append((pd.Timestamp(d_.date()).replace(hour=hh, minute=mm).tz_localize("America/New_York"),
                                  px_, vol))
            return pd.DataFrame({"Close": [r[1] for r in rows_], "Volume": [r[2] for r in rows_]},
                                index=pd.DatetimeIndex([r[0] for r in rows_]))
        inp = gather(today_et=now, fetch_fred=fetch_fred, fetch_holdings=lambda: [("NVDA", 7.5), ("AAPL", 6.8)],
                     fetch_intraday=_mbars, fetch_prices=lambda tks: {t: prices[t] for t in tks if t in prices},
                     assess=lambda: assessment, macro_lookup=lambda d: [
                         {"event": "NFP", "date": "2026-10-02", "days_away": 7, "affects": "rates", "blackout": False}])
        b = build(inp)
        md = render_md(b)
        out = write(b)
        # v1.2: Market read — each rule on hand-set numbers, thresholds vs cross_asset, rendering
        sp = lambda nom, real, lvl=4.98: {"nom_bp": nom, "real_bp": real, "be_bp": nom - real, "level": lvl,
                                          "real_level": 2.6, "asof": "2026-10-29"}
        r_ = read_rates(sp(30, 28), sp(5, 4), None)
        if r_["driver"] != "real" or "ROSE on real yields" not in r_["verdict"]:
            f.append(f"read_rates: +30 = real +28 must be a real-yield rise: {r_['verdict']}")
        if "20-day +30bp = real +28bp + breakeven +2bp" not in r_["evidence"][0]:
            f.append(f"read_rates evidence must show the split that adds up: {r_['evidence'][0]}")
        r_ = read_rates(sp(30, 5), None, None)
        if r_["driver"] != "breakeven" or "inflation expectations" not in r_["verdict"]:
            f.append(f"read_rates: +30 = breakeven +25 must be an inflation rise: {r_['verdict']}")
        r_ = read_rates(sp(-31, -30), None, -11.1)
        if r_["driver"] != "real" or "FELL on real yields" not in r_["verdict"] or \
                not any("something other than rates" in e for e in r_["evidence"]):
            f.append("read_rates: real-yield fall with growth lagging must flag a non-rate drag on growth")
        r_ = read_rates(sp(18, 9), None, None)
        if r_["driver"] != "both":
            f.append(f"read_rates: an even split must read as both: {r_['driver']}")
        if read_rates(sp(3, 3), None, None)["driver"] is not None:
            f.append("read_rates: a move under the noise line must read as little changed")
        b_ = read_breadth(-1.8, -0.8, -3.5, 66.0, 6.0, "2026-10-30")
        if b_["kind"] != "megacap_down":
            f.append(f"read_breadth: SPY −1.8 / RSP −0.8 must be megacap-led: {b_['kind']}")
        for args, want in (((-1.5, -1.6, -1.4, 40.0, -2.0, "d"), "broad_selloff"),
                           ((-1.5, -1.6, -1.4, 70.0, -2.0, "d"), "broad_down"),
                           ((1.0, 0.2, 1.8, 60.0, -1.0, "d"), "narrow_up"),
                           ((1.0, 0.9, 1.1, 60.0, 1.0, "d"), "broad_up"),
                           ((0.1, 0.0, 0.2, 60.0, 0.0, "d"), "quiet")):
            if read_breadth(*args)["kind"] != want:
                f.append(f"read_breadth{args} must be {want}: {read_breadth(*args)['kind']}")
        for args, want in (((-1.8, -3.5, 0.4), "liquidity"), ((-1.5, 0.5, 0.8), "flight"),
                           ((-1.5, 0.0, -1.0), "rates_scare"), ((1.2, 0.3, -0.5), "risk_on"),
                           ((1.2, 0.3, 0.6), "relief"), ((0.3, -0.2, 0.1), "none")):
            got_k = read_cross(*args, 19.4, 2.2, 3.26, 12.0, "2026-10-29", "2026-10-30")["kind"]
            if got_k != want:
                f.append(f"read_cross{args} must be {want}: {got_k}")
        s_ = read_stress(3.26, 0.03, 0.05, "2026-10-29", 19.4, 1.5, [])
        if s_["verdict"] != "Calm, but close: vol is about 1 typical day from its WATCH line":
            f.append(f"read_stress: VIX 19.4 (1.5-pt typical day) is ~1 day from WATCH, HY ~5 is not close: {s_['verdict']}")
        s_ = read_stress(3.40, 0.03, 0.05, "2026-10-29", 19.4, 1.5, [])
        if s_["verdict"] != "Calm, but close: vol is about 1 typical day and credit is about 2 typical days from their WATCH lines":
            f.append(f"read_stress: both lanes close must both be named, nearest first: {s_['verdict']}")
        if not read_stress(2.8, 0.0, 0.05, "d", 14.0, 1.5, [])["verdict"].startswith("Calm, with room"):
            f.append("read_stress: HY 2.8 / VIX 14 must be calm with room")
        if not read_stress(3.6, 0.0, 0.05, "d", 14.0, 1.5, [])["verdict"].startswith("WATCH in credit"):
            f.append("read_stress: HY 3.6 must be WATCH")
        if not read_stress(3.0, 0.0, 0.05, "d", 31.0, 1.5, [])["verdict"].startswith("STRESS in vol"):
            f.append("read_stress: VIX 31 must be STRESS")
        # the lines must be the cross-asset lanes' own lines, so the two cannot disagree
        import cross_asset as _ca
        for hy_, mom_, m20_ in ((3.49, 0.0, None), (3.51, 0.0, None), (3.0, 0.51, None), (3.0, 0.49, None),
                                (5.01, 0.0, None), (4.9, 0.0, None), (3.48, 0.22, 0.33), (3.48, 0.22, 0.29),
                                (3.2, 0.0, 0.30)):
            lane = _ca.credit_lane(hy_, mom_, m20_)["state"]
            mine = read_stress(hy_, mom_, 0.05, "d", None, None, [], m20_)["states"]["credit"]
            if lane != mine:
                f.append(f"credit line out of sync with cross_asset at HY {hy_}, 2wk {mom_}, 20d {m20_}: {mine} vs {lane}")
        if abs(_ca.HY_MOM_20D_WATCH - LANE_HY_MOM_20D) > 1e-12:
            f.append("the 20-session credit line must equal cross_asset.HY_MOM_20D_WATCH")
        for v_ in (20.99, 21.0, 29.99, 30.0, 12.0):
            lane = _ca.vol_lane(v_)["state"]
            mine = read_stress(None, None, None, "d", v_, 1.5, [])["states"]["vol"]
            if lane != mine:
                f.append(f"vol line out of sync with cross_asset at VIX {v_}: {mine} vs {lane}")
        # the section is built and rendered, every item with its evidence, rule and flip condition
        mr_ = b.get("market_read") or {}
        if len(mr_.get("items", [])) != 4 or "## 1A · Market read" not in md:
            f.append("Market read section missing from the brief")
        for it in mr_.get("items", []):
            if f"**{it['topic']}: {it['verdict']}**" not in md or f"*Rule:* {it['rule']}" not in md \
                    or f"*Would change if:* {it['changes_if']}" not in md:
                f.append(f"Market read item not rendered in full: {it['topic']}")
        if "## 1A · Market read" in md and md.index("## 1A · Market read") > md.index("## 2 · Scoreboard"):
            f.append("Market read must sit between the headline and the scoreboard")
        # _rate_split on real series: common dates only, and nominal = real + breakeven exactly
        _d = pd.bdate_range("2026-09-01", periods=30)
        _n10 = pd.Series(np.linspace(4.60, 4.98, 30), index=_d)
        _r10 = pd.Series(np.linspace(2.40, 2.63, 30), index=_d).drop(_d[-1])      # DFII10 one day short
        _sp = _rate_split({"DGS10": _n10, "DFII10": _r10}, 20)
        _c = pd.concat([_n10, _r10], axis=1).dropna()
        _want_nom = (_c.iloc[-1, 0] - _c.iloc[-21, 0]) * 100
        _want_real = (_c.iloc[-1, 1] - _c.iloc[-21, 1]) * 100
        if not _sp or _sp["asof"] != _d[-2].date().isoformat():
            f.append(f"_rate_split must use the last COMMON date: {_sp and _sp['asof']}")
        elif abs(_sp["nom_bp"] - _want_nom) > 1e-9 or abs(_sp["real_bp"] - _want_real) > 1e-9 \
                or abs(_sp["nom_bp"] - _sp["real_bp"] - _sp["be_bp"]) > 1e-9:
            f.append(f"_rate_split must give nominal = real + breakeven on common dates: {_sp}")
        if _rate_split({"DGS10": _n10}, 20) is not None or _rate_split({"DGS10": _n10, "DFII10": _r10}, 40) is not None:
            f.append("_rate_split must return None when a series or enough history is missing")

        # v1.3: 6A Where the money went — missing, fresh, stale, unmeasured funds, placement
        fm0 = b.get("flow_map") or {}
        if fm0.get("available") or "## 6A · Where the money went" not in md or "not published yet" not in md:
            f.append("6A must say plainly that the flow map summary is not published when the file is absent")
        _dh = {r["input"]: r for r in b["data_health"]}
        if (_dh.get("Flow map summary") or {}).get("status") != "MISSING":
            f.append(f"data health must flag a missing flow map summary: {_dh.get('Flow map summary')}")
        _fms = {"published_at": "2026-09-25T22:00:00+00:00", "window": 20, "data_through": "2026-09-25",
                "coverage": {"measured": 4, "total": 6},
                "asset_classes": [
                    {"asset_class": "US equity", "flow_usd": 1.98e9, "aum": 2.1e12, "pct_aum": 0.09, "measured": 2,
                     "total": 3, "missing": ["VGT"], "direction": "flat"},
                    {"asset_class": "Treasuries", "flow_usd": -592e6, "aum": 6.0e10, "pct_aum": -0.98, "measured": 2,
                     "total": 2, "missing": [], "direction": "out"},
                    {"asset_class": "Cash-like", "flow_usd": None, "aum": None, "pct_aum": None, "measured": 0,
                     "total": 1, "missing": ["SGOV"], "direction": "n/a", "thin": False},
                    {"asset_class": "International equity", "flow_usd": 1.28e9, "aum": 2.3e10, "pct_aum": 5.53,
                     "measured": 1, "total": 5, "missing": ["EEM", "EFA", "FXI", "INDA"], "direction": "in", "thin": True}],
                "verdict": {"kind": "stocks_flat", "verdict": "No material net move in stocks: test",
                            "evidence": ["US equity: +$1.98B", "Within stocks: out of SPY"],
                            "rule": "Net 20-session creations minus redemptions (test rule).",
                            "changes_if": "Stock funds net flow of ±0.25% or more of their assets."},
                "excluded": {"VGT": "frozen relay", "SGOV": "frozen relay"}}
        b1 = build(dict(inp, flow_map=_fms))
        md1 = render_md(b1)
        fm1 = b1["flow_map"]
        if not fm1.get("available") or fm1.get("stale") or abs((fm1.get("age_hours") or -1) - 2.0) > 0.01:
            f.append(f"6A fresh summary: available, not stale, 2.0h old expected: {fm1.get('stale')} {fm1.get('age_hours')}")
        for want in ("| US equity | +$1.98B | +0.09% | flat | 2 of 3 | VGT |",
                     "| Treasuries | −$592M | -0.98% | out | 2 of 2 | — |",
                     "| Cash-like | n/a | n/a | n/a | 0 of 1 | SGOV |",
                     "**Verdict: No material net move in stocks: test**", "- Within stocks: out of SPY",
                     "*Rule:* Net 20-session creations minus redemptions (test rule).",
                     "*Would change if:* Stock funds net flow of ±0.25% or more of their assets.",
                     "4 of 6 funds measured",
                     "| International equity | +$1.28B | +5.53% | in (thin) | 1 of 5 | EEM, EFA, FXI, INDA |",
                     "*(thin) = under half the class's funds measured"):
            if want not in md1:
                f.append(f"6A render missing: {want}")
        if "$0" in md1.split("## 6A")[1].split("## 7")[0]:
            f.append("6A must never print an unmeasured bucket as $0")
        if "| US equity | +$1.98B | +0.09% | flat (thin)" in md1:
            f.append("6A must mark only thin rows as thin")
        if "STALE" in md1.split("## 6A")[1].split("## 7")[0]:
            f.append("6A must not flag a 2-hour-old summary as stale")
        if not (md1.index("## 6 · Flow") < md1.index("## 6A · Where the money went") < md1.index("## 7 · Breadth")):
            f.append("6A must sit between section 6 and section 7")
        if ({r["input"]: r for r in b1["data_health"]}.get("Flow map summary") or {}).get("status") != "OK":
            f.append("data health must show a fresh flow map summary as OK")
        b2 = build(dict(inp, flow_map=dict(_fms, published_at="2026-09-24T08:00:00+00:00")))
        if not b2["flow_map"].get("stale") or "STALE — 40h old" not in render_md(b2):
            f.append(f"6A must flag a 40-hour-old summary as stale: {b2['flow_map'].get('age_hours')}")
        if not flow_map_section(dict(inp, flow_map=dict(_fms, published_at=None))).get("stale"):
            f.append("6A summary with no timestamp must be treated as stale")
        if flow_map_section(dict(inp, flow_map=dict(_fms, verdict={}))).get("available"):
            f.append("6A summary without a verdict must not render as available")
        if _usd(-592e6) != "−$592M" or _usd(3.26e9) != "+$3.26B" or _usd(None) != "n/a" or _usd(float("nan")) != "n/a":
            f.append(f"_usd formatting: {_usd(-592e6)} {_usd(3.26e9)} {_usd(None)} {_usd(float('nan'))}")

        # v1.5.3 (N29): WTI after FRED = rebuilt NYMEX settle, never the after-hours last trade
        _st = settle_series(_mbars("CL=F"), datetime(2026, 9, 25, 20, 0))
        if len(_st) != 3 or abs(_st.iloc[-1] - (71.0 * 300 + 72.0 * 100) / 400) > 1e-9:
            f.append(f"settle = volume-weighted close of the 14:28 and 14:29 bars only (71.25), one per session: {_st.to_dict()}")
        if len(settle_series(_mbars("CL=F"), datetime(2026, 9, 25, 14, 29))) != 2:
            f.append("a session whose 14:30 ET has not passed must not produce a settle")
        _utc = _mbars("CL=F"); _utc.index = _utc.index.tz_convert("UTC")
        if not settle_series(_utc, datetime(2026, 9, 25, 20, 0)).equals(_st):
            f.append("bars stamped in UTC must give the same settle (times compared in New York time)")
        if len(settle_series(pd.DataFrame(), datetime(2026, 9, 25, 20, 0))) or len(settle_series(None, datetime(2026, 9, 25, 20))):
            f.append("no bars -> no settle (never a fallback)")
        # v1.5.4 (N33): one series of settles; latest daily bar only via the rebuild; no next-day bar; no spot mixing
        _oil = inp["fred"]["DCOILWTICO"]
        _src = (inp.get("fred_src") or {}).get("DCOILWTICO", "")
        if abs(float(_oil.iloc[-1]) - 71.25) > 1e-9 or _oil.index[-1] != pd.Timestamp("2026-09-25") \
                or abs(float(_oil.iloc[-4]) - 69.0) > 1e-9 or "one series of front-month settles" not in _src:
            f.append(f"WTI must be daily settles (69.00) then the rebuilt settle (71.25) for the last 3 sessions: "
                     f"{_oil.tail(4).round(2).tolist()} | {_src}")
        if float(_oil.iloc[-300:].min()) < 68.99 or len(_oil) < 260:
            f.append("the WTI series must be futures throughout (no FRED spot values mixed in)")
        _sb = next(r for r in b["scoreboard"]["rows"] if r["name"] == "WTI crude")
        if _sb["source"] != "WTI (NYMEX front-month settle)" or \
                "WTI (NYMEX front-month settle)" not in {r["input"] for r in b["data_health"]}:
            f.append(f"scoreboard and data health must name the series as the NYMEX settle: {_sb['source']}")
        if "front-month expiry 2026-09-22 (Oct 2026 contract)" not in _src:
            f.append(f"a roll inside the 20-day window must be named (Oct 2026 contract expired 9/22): {_src}")
        _px2 = dict(prices)
        _cl = prices["CL=F"].copy()                    # two bars after the session (6pm reopen) — tests the cutoff itself
        _cl.loc[pd.Timestamp("2026-09-28")] = _cl.iloc[-1] * 0 + 55.0
        _cl.loc[pd.Timestamp("2026-09-29")] = _cl.iloc[-1] * 0 + 55.0
        _px2["CL=F"] = _cl
        _i3 = gather(today_et=now, fetch_fred=fetch_fred, fetch_holdings=lambda: [], fetch_intraday=_mbars,
                     fetch_prices=lambda tks: {t: _px2[t] for t in tks if t in _px2}, assess=lambda: assessment,
                     macro_lookup=lambda d: [])
        if _i3["fred"]["DCOILWTICO"].index[-1] != pd.Timestamp("2026-09-25") or (_i3["fred"]["DCOILWTICO"] == 55.0).any():
            f.append("a daily bar dated after the session (the 6pm reopen) must be dropped")
        _i2 = gather(today_et=now, fetch_fred=fetch_fred, fetch_holdings=lambda: [], fetch_intraday=lambda t: pd.DataFrame(),
                     fetch_prices=lambda tks: {t: prices[t] for t in tks if t in prices}, assess=lambda: assessment,
                     macro_lookup=lambda d: [])
        if _i2["fred"]["DCOILWTICO"].index[-1] != pd.Timestamp("2026-09-24") or \
                "latest session is not shown yet" not in (_i2.get("fred_src") or {}).get("DCOILWTICO", ""):
            f.append("without settlement bars the latest daily bar (maybe a last trade) must be left out, and say so")
        _px4 = {t: v for t, v in prices.items() if t != "CL=F"}
        _i4 = gather(today_et=now, fetch_fred=fetch_fred, fetch_holdings=lambda: [], fetch_intraday=_mbars,
                     fetch_prices=lambda tks: {t: _px4[t] for t in tks if t in _px4}, assess=lambda: assessment,
                     macro_lookup=lambda d: [])
        if not _i4["fred"]["DCOILWTICO"].equals(fred["DCOILWTICO"]) or \
                not (_i4.get("fred_src") or {}).get("DCOILWTICO", "").startswith("FRED spot only"):
            f.append("with no futures history WTI must be FRED spot only — never a settle spliced onto spot")
        for (y_, m_), want in (((2026, 11), date(2026, 10, 20)), ((2026, 12), date(2026, 11, 20)),
                               ((2026, 10), date(2026, 9, 22)), ((2027, 1), date(2026, 12, 21))):
            if cl_expiry(y_, m_) != want:
                f.append(f"cl_expiry({y_}, {m_}) must be {want} (NYMEX rule): {cl_expiry(y_, m_)}")
        _g = settle_vs_fred(pd.Series([71.0, 72.0], index=pd.to_datetime(["2026-09-24", "2026-09-25"])),
                            pd.Series([70.5, 73.0], index=pd.to_datetime(["2026-09-24", "2026-09-25"])))
        if not _g or _g["n"] != 2 or abs(_g["max_abs"] - 1.0) > 1e-9:
            f.append(f"settle_vs_fred: max gap over shared days: {_g}")

        # v1.5.2 (N23): calendar coverage in data health; elections get a pre-committed line
        _dhc = {r["input"]: r for r in b["data_health"]}.get("Event calendar") or {}
        if _dhc.get("status") not in ("OK", "WARN", "STALE"):
            f.append(f"the Event calendar row must report coverage status, not a fixed OK: {_dhc}")
        _bst = build(dict(inp, calendar_coverage={"status": "STALE", "note": "CPI has no date ahead — add the next year"}))
        _rst = {r["input"]: r for r in _bst["data_health"]}.get("Event calendar") or {}
        if _rst.get("status") != "STALE" or "CPI has no date ahead" not in _rst.get("note", ""):
            f.append(f"a calendar with an expired schedule must show STALE with the reason: {_rst}")
        if "no pre-committed rule" in _if_then("ELECTION", 0.1, {}) or "gap" not in _if_then("ELECTION", 0.1, {}):
            f.append("an election must have its own pre-committed line")
        import event_calendar as _ec
        _el = [e for e in _ec.upcoming_macro(10, today=date(2026, 11, 1)) if e["event"] == "ELECTION"]
        _nx = next48_section(dict(inp, events=_el, now_et=datetime(2026, 11, 1, 20, 0), session=date(2026, 10, 30)),
                             b["regime"])
        if not any(e["event"] == "ELECTION" for e in _nx.get("events", [])) or \
                not any(l.startswith("Election") for l in _nx.get("if_then", [])):
            f.append(f"the 11/3 election must sit inside next-48 on 11/1 with its pre-committed line: {_nx}")

        # v1.5: SPY holdings parser, top-10 contribution maths, breadth trend
        import io as _io
        _rows = [["SPDR S&P 500 ETF Trust", None, None, None], ["Holdings: As of 30-Oct-2026", None, None, None],
                 [None, None, None, None], ["Name", "Ticker", "Identifier", "Weight"],
                 ["US DOLLAR", "CASH_USD", "X", 9.0], ["NVIDIA", "NVDA", "A", 7.9], ["APPLE", "AAPL", "B", 6.9],
                 ["BERKSHIRE B", "BRK.B", "C", 1.7]]
        _rows += [[f"N{i}", f"T{chr(65 + i % 26)}{chr(65 + i // 26 % 26)}", "Z", 0.15] for i in range(500)]
        _buf = _io.BytesIO(); pd.DataFrame(_rows).to_excel(_buf, header=False, index=False)
        _h = spy_top_holdings(_buf.getvalue(), n=3)
        if _h != [("NVDA", 7.9), ("AAPL", 6.9), ("BRK-B", 1.7)]:
            f.append(f"spy_top_holdings: top 3 by weight, cash row excluded, BRK.B -> BRK-B: {_h}")
        _frac = [r if i < 4 else [r[0], r[1], r[2], r[3] / 100] for i, r in enumerate(_rows)]
        _buf2 = _io.BytesIO(); pd.DataFrame(_frac).to_excel(_buf2, header=False, index=False)
        if spy_top_holdings(_buf2.getvalue(), n=1) != [("NVDA", 7.9)]:
            f.append("spy_top_holdings must read weights given as fractions as percent")
        try:
            _bad = _io.BytesIO(); pd.DataFrame([["Name", "Weight"], ["a", 1]]).to_excel(_bad, header=False, index=False)
            spy_top_holdings(_bad.getvalue()); f.append("a holdings file without a Ticker column must raise")
        except ValueError:
            pass
        # contribution: A is 30% of the index at the start, +10% over 20 days; the rest +1% -> SPY +3.7%
        _cal = pd.bdate_range(end="2026-10-30", periods=30)
        _a = pd.Series(np.r_[np.full(9, 100.0), np.linspace(100, 110, 21)], index=_cal)
        _rest = pd.Series(np.r_[np.full(9, 100.0), np.linspace(100, 101, 21)], index=_cal)
        _spy = 100 * (0.3 * _a / 100 + 0.7 * _rest / 100)
        _px = {"SPY": pd.DataFrame({"Close": _spy}), "A": pd.DataFrame({"Close": _a})}
        _wn = 0.3 * 1.10 / 1.037 * 100
        _t = top10_contribution(_px, [("A", _wn)])
        _w = (_t.get("windows") or {}).get(20) or {}
        if not _t.get("available") or abs(_w["top_contrib"] - 3.0) > 1e-6 or abs(_w["rest"] - 1.0) > 1e-6 \
                or abs(_w["top_w0"] - 30.0) > 1e-6 or _t["kind"] != "top_heavy" \
                or abs(_w["ratio"] - (3.0 / 3.7) / 0.30) > 1e-6:
            f.append(f"top10_contribution: A supplies 3.00 pts of SPY +3.70%, the rest +1.00%, start weight 30%, "
                     f"top-heavy (ratio 2.7): {_w} {_t.get('kind')}")
        if not _t.get("verdict", "").startswith("Driven by the top 1"):
            f.append(f"top-heavy verdict must read 'Driven by the top N': {_t.get('verdict')}")
        if top10_contribution(_px, [("A", _wn), ("MISSING", 40.0)]).get("available"):
            f.append("top10_contribution must refuse when under 90% of the top weight is priced")
        _flat = {"SPY": pd.DataFrame({"Close": pd.Series(np.r_[np.full(9, 100.0), np.linspace(100, 100.3, 21)],
                                                         index=_cal)}), "A": _px["A"]}
        if top10_contribution(_flat, [("A", 30.0)]).get("kind") != "small_move":
            f.append("a SPY move under the minimum must not be split into shares")
        # breadth trend: 40 names; 30 trend up throughout, 10 roll over in the last 20 sessions -> narrowing
        _cal2 = pd.bdate_range(end="2026-10-30", periods=400)
        _pxb = {"SPY": pd.DataFrame({"Close": pd.Series(np.linspace(100, 130, 400), index=_cal2)})}
        for i_ in range(40):
            base_ = np.linspace(50, 80, 400)
            if i_ >= 26:          # 14 names fall hard over the last 15 sessions (inside the 20-session window)
                base_[-15:] = np.linspace(base_[-16], base_[-16] * 0.7, 15)
            _pxb[f"U{i_}"] = pd.DataFrame({"Close": pd.Series(base_, index=_cal2)})
        _uni = [f"U{i_}" for i_ in range(40)]
        _bt = breadth_trend(_pxb, _uni)
        if not _bt.get("available") or _bt["trend"] != "deteriorating" or not _bt["verdict"].startswith("Narrowing"):
            f.append(f"breadth_trend: names rolling over under a rising SPY must read narrowing: {_bt.get('verdict')}")
        _gap = dict(_pxb); _gap.update({t: pd.DataFrame({"Close": _pxb[t]["Close"].iloc[:-1]}) for t in _uni})
        if breadth_trend(_gap, _uni).get("available"):
            f.append("breadth_trend must refuse (not crash) when the latest session has no constituent closes")
        _bs = breadth_section({"prices": _pxb, "universe": _uni})
        if _bt.get("available") and abs(_bt["points"]["today"]["p50"] - _bs["pct_above_50"]) > 0.05:
            f.append(f"breadth_trend today must equal section 7's % above 50-day: {_bt['points']['today']['p50']} vs {_bs['pct_above_50']}")
        _early = {t: pd.DataFrame({"Close": d["Close"].iloc[:-21]}) for t, d in _pxb.items()}
        _bt_e = breadth_trend(_early, _uni)
        if _bt.get("available") and _bt_e.get("available") and \
                abs(_bt["points"]["20d"]["p50"] - _bt_e["points"]["today"]["p50"]) > 0.05:
            f.append("breadth_trend must be point in time: the value 20 sessions ago equals a run cut off there")
        # rendering and data health
        sec7 = md.split("## 7 · Breadth")[1].split("## 8")[0]
        if "**Top-2 contribution**" not in sec7 or "| **Rest of the index** |" not in sec7 or "| NVDA |" not in sec7:
            f.append("section 7 must render the top-holdings contribution table")
        if "Breadth trend unavailable" not in sec7:
            f.append("with a 4-name universe the breadth trend must say it is unavailable, and why")
        _dh5 = {r["input"]: r for r in b["data_health"]}
        if (_dh5.get("SPY holdings (top 10)") or {}).get("status") != "OK":
            f.append("data health must show the SPY holdings row")
        _bf = build(dict(inp, spy_holdings=[], spy_holdings_error="ProxyError: blocked"))
        if "SPY holdings file failed: ProxyError" not in render_md(_bf) or \
                {r["input"]: r for r in _bf["data_health"]}["SPY holdings (top 10)"]["status"] != "MISSING":
            f.append("a failed holdings fetch must be named in section 7 and in data health")

        # v1.4: flow verdict state, steps, regime cross-check, scoring hook
        from swing_desk import REGIME_DIRECTION as _RD
        if any(regime_tilt(k_) not in ("risk-on", "risk-off", "none") for k_ in _RD):
            f.append("regime_tilt must classify every swing_desk regime")
        if "Money moving into stocks CONFIRMS" not in flow_regime_check("new_money", "goldilocks") or \
                "money moving out of stocks is context" not in flow_regime_check("out_of_stocks", "neutral"):
            f.append("regime check wording: 'Money moving into stocks' / 'out of stocks'")
        for st_, key_, want in (("new_money", "goldilocks", "CONFIRMS"), ("into_stocks", "growth_scare", "CONTRADICTS"),
                                ("out_of_stocks", "goldilocks", "CONTRADICTS"), ("leaving_both", "liquidity_crisis", "CONFIRMS"),
                                ("new_money", "transition_ambiguous", "context, not confirmation"),
                                ("borderline", "goldilocks", "neither confirms nor contradicts"),
                                ("stocks_flat", "goldilocks", "No market-wide flow signal"),
                                ("unavailable", "goldilocks", "a data gap, not a signal")):
            if want not in flow_regime_check(st_, key_):
                f.append(f"flow_regime_check({st_}, {key_}) must say '{want}': {flow_regime_check(st_, key_)}")
        _v12 = dict(_fms["verdict"], state="borderline", borderline=True, sessions_in_state=3, prev_state="borderline",
                    steps=["Model portfolio: treat Level 2 as unconfirmed.", "Resolves when the stock reading closes above +0.71%."],
                    record={"date": "2026-09-25", "stocks_pct": 0.21, "margin_days": 0.1})
        b3 = build(dict(inp, flow_map=dict(_fms, verdict=_v12)))
        md3 = render_md(b3)
        sec3 = md3.split("## 6A")[1].split("## 7")[0]
        if "**What to do with it**" not in sec3 or "1. Model portfolio: treat Level 2 as unconfirmed." not in sec3 \
                or "2. Resolves when the stock reading closes above +0.71%." not in sec3:
            f.append("6A must render the recommended steps, numbered, in order")
        if "**Regime cross-check:** Borderline flow neither confirms nor contradicts" not in sec3:
            f.append(f"6A must render the regime cross-check: {b3['flow_map'].get('regime_check')}")
        if "What to do with it" in md1.split("## 6A")[1].split("## 7")[0]:
            f.append("a v1.1 summary (no steps) must render without a steps block")
        if any(r["signal_type"].startswith("flow_") for r in b3["signals"].get("new", [])):
            f.append("a borderline flow verdict must never become a scored signal")
        _firm = dict(_v12, state="new_money", borderline=False, prev_state="borderline")
        b4 = build(dict(inp, flow_map=dict(_fms, verdict=_firm)))
        fs4 = [r for r in b4["signals"].get("new", []) if r["signal_type"] == "flow_into_stocks"]
        if len(fs4) != 1 or fs4[0]["date"] != "2026-09-28":
            f.append(f"a fresh firm new_money must log one flow_into_stocks dated the next session: {fs4}")
        b5 = build(dict(inp, flow_map=dict(_fms, verdict=_firm, published_at="2026-09-23T22:00:00+00:00")))
        if any(r["signal_type"].startswith("flow_") for r in b5["signals"].get("new", [])):
            f.append("a stale flow summary must never be logged as a signal")
        if "CONFIRMS" in (b4["flow_map"].get("regime_check") or "") and regime_tilt(b4["regime"].get("key")) != "risk-on":
            f.append("regime cross-check must use the brief's own regime key")

        # v1.1: every cross-asset "why" must reach the markdown in full (v1 cut at 160 chars)
        for _lane, _v in (b["cross_asset"].get("lanes") or {}).items():
            _note = str(_v.get("note", "")).replace("|", "\\|").replace("\n", " ")
            if _note and _note not in md:
                f.append(f"cross-asset {_lane} note truncated or missing in the markdown ({len(_note)} chars)")
        if not b["regime"].get("plans") or "Contingency" not in md or "Pending until" not in md:
            f.append(f"regime section must carry the gated contingency plan: {b['regime'].get('plan_error')}")
        if "Credit cycle:" not in md or not (b["regime"].get("credit_cycle") or {}).get("state"):
            f.append("regime section must carry the credit-cycle (spread-peak re-entry) line")

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
        if b["portfolio"].get("active") or any("ledger" in w.lower() for w in b["conclusions"]["weekend"]):
            f.append("a 2-month-old ledger must be UNUSED: never in the weekend list or authorized items")
        if "Authorized today: TLT" in " ".join(b["headline"]):
            f.append("stale-ledger stop hits must not reach the headline")
        mdl = b["model"]
        if not mdl.get("available") or not mdl["rows"] or "SHOULD" not in md:
            f.append(f"model portfolio section missing: {mdl.get('conclusion')}")
        elif abs(sum(r["weight"] for r in mdl["rows"]) - 100) > 1.0:
            f.append(f"model weights must sum to ~100: {sum(r['weight'] for r in mdl['rows'])}")
        for r_ in mdl.get("rows") or []:
            if r_["gate"] in ("BLOCKED", "UNAVAILABLE") and r_["change"] > 0.05:
                f.append(f"{r_['ticker']} shows a BLOCKED add yet the model weight rose {r_['change']:+.1f}")
        # Trailing returns: exact windows, and no mislabeled short-history numbers.
        _ix = pd.bdate_range(end="2026-09-25", periods=300)
        _ps = pd.Series(np.arange(300, dtype=float) + 100.0, index=_ix)   # 100 … 399
        _tr = trailing_returns(_ps)
        _ok = (abs(_tr["ret_1m"] - (399 / 378 - 1) * 100) < 0.01            # 21 sessions back
               and abs(_tr["ret_3m"] - (399 / 336 - 1) * 100) < 0.01        # 63 sessions back
               and abs(_tr["ret_12_1"] - (378 / 147 - 1) * 100) < 0.01)     # t-21 over t-252, latest month excluded
        if not _ok:
            f.append(f"trailing returns wrong on a known ramp: {_tr}")
        _sh = trailing_returns(_ps.iloc[-100:])
        if _sh["ret_12_1"] is not None or _sh["ret_3m"] is None:
            f.append(f"12-1 needs 253 sessions and must be None on 100 bars; 3M must still resolve: {_sh}")
        if any(v is not None for v in trailing_returns(pd.Series(dtype=float)).values()):
            f.append("empty history must give no trailing returns")
        if "12-1" not in md or "3M (vs SPY)" not in md:
            f.append("section 8 must carry the 1M / 3M (vs SPY) / 12-1 columns")
        if not any(r_.get("ret_3m") is not None for r_ in mdl.get("rows") or []):
            f.append("model rows must carry trailing returns when 2y prices are present")
        if not Path("data/model_book.csv").exists():
            f.append("model book must be persisted by write()")
        if not any(d["input"] == "Position ledger" and d["status"] == "UNUSED" for d in b["data_health"]):
            f.append("data health must mark an old ledger UNUSED, not STALE")
        pf = portfolio_section(inp, b["targets"], b["regime"].get("key"), force=True)
        tlt = next(r for r in pf["positions"] if r["ticker"] == "TLT")
        if tlt["inv_status"] != "FIRED":
            f.append(f"TLT invalidation 'DFII10 above 2.50%' with DFII10 2.85 must FIRE: {tlt}")
        sg = next(r for r in pf["positions"] if r["ticker"] == "SGOV")
        if sg["status"] != "CASH":
            f.append("cash sleeves must be exempt from ATR stops")
        vgt = next(r for r in pf["positions"] if r["ticker"] == "VGT")
        if vgt["inv_status"] != "MANUAL":
            f.append("unrecognised invalidation text must be MANUAL, never guessed")
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
        for sec in ("## 1 ·", "## 6 ·", "## 12 ·", "## 13 ·", "**Conclusion:**"):
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

        # ── v1.1 bulletproofing ──────────────────────────────────────────
        # (a) session closes not published yet (prices end 9/25, session 9/28):
        #     model book must read PENDING, prices row must say so, and the
        #     session must not be booked
        if not b2["model"].get("pending"):
            f.append("a session without closes must leave the model book PENDING")
        _pxrow = next((r for r in b2["data_health"] if r["input"] == "Prices (yfinance)"), {})
        if _pxrow.get("status") != "STALE" or "NOT published" not in (_pxrow.get("note") or ""):
            f.append(f"prices health must flag the missing session bar: {_pxrow}")
        if "not published" not in render_md(b2):
            f.append("the brief must say the session's closes were not published")
        _bk = b2["model"].get("_book")
        if _bk is not None and str(_bk["date"].max()) >= "2026-09-28":
            f.append("the model book must not book a session with no closing bar")
        # (b) FRED outage: the assessment HOLDS the prior regime and every
        #     section says so
        _h = rc.input_health(SimpleNamespace(short_real_rate=None, long_real_mom_3m=None, hy_oas=None))
        held = dict(assessment, regime=rc.held_regime(_h, "transition_ambiguous"))
        b4 = build(gather(today_et=now, fetch_fred=fetch_fred,
                          fetch_prices=lambda tks: {t: prices[t] for t in tks if t in prices},
                          assess=lambda: held, macro_lookup=lambda d: []))
        if "HELD" not in str(b4["regime"].get("source")) or "DATA FAILURE" not in b4["regime"]["conclusion"]:
            f.append(f"a held regime must be labelled in the regime section: {b4['regime'].get('source')}")
        if not any(r["input"] == "Regime assessment" and r["status"] == "FAILED" for r in b4["data_health"]):
            f.append("data health must show the regime assessment as FAILED during an outage")
        if not b4["model"].get("regime_held"):
            f.append("the model section must say its weights are a held call")
        render_md(b4)
        # (d) signal log: derived in build, persisted only by write(), idempotent
        if not b["signals"].get("available"):
            f.append(f"signals section must build: {b['signals'].get('conclusion')}")
        if "## 12 · Signal scorecard" not in md or "## 13 · Data health" not in md:
            f.append("the brief must render the signal scorecard before data health")
        if not os.path.exists("data/signal_outcomes.csv"):
            f.append("write() must persist data/signal_outcomes.csv")
        else:
            _n0 = len(pd.read_csv("data/signal_outcomes.csv"))
            write(build(inp))
            if len(pd.read_csv("data/signal_outcomes.csv")) != _n0:
                f.append("re-running the same session must not duplicate signals")
        # (c) benchmarks present when SPY and AGG are priced
        prices["AGG"] = px(100, 0.0001)
        b5 = build(gather(today_et=now, fetch_fred=fetch_fred,
                          fetch_prices=lambda tks: {t: prices[t] for t in tks if t in prices},
                          assess=lambda: assessment, macro_lookup=lambda d: []))
        _bm = b5["model"].get("benchmarks") or {}
        if _bm.get("spy_pct") is None or _bm.get("sixty_forty_pct") is None:
            f.append(f"model benchmarks (SPY, 60/40) must be computed when priced: {_bm}")
        # (e) v1.6: attribution, AI exposure, vol target, market-implied path
        m5 = b5["model"]
        if "attribution" not in m5 or "ai_exposure" not in m5 or "vol_target" not in m5:
            f.append("the model section must carry attribution, ai_exposure and vol_target")
        elif m5["vol_target"].get("applied"):
            f.append("the volatility target must never be applied to the book (display only)")
        _at = m5.get("attribution") or {}
        if _at.get("available"):
            _si = _at["windows"].get("since inception") or {}
            if _si.get("nav_pct") is None or abs(_si["sum_pts"] - _si["nav_pct"]) > max(0.5, abs(_si["nav_pct"]) * 0.2):
                f.append(f"attribution must add up to about the NAV change: {_si.get('sum_pts')} vs {_si.get('nav_pct')}")
        _names = [r["name"] for r in b5["scoreboard"]["rows"]]
        if not any(n_.startswith("Market-implied path: 2Y") for n_ in _names):
            f.append("the scoreboard must show the market-implied path (2Y − fed funds)")
        md5 = render_md(b5)
        if _at.get("available") and "Where the return came from" not in md5:
            f.append("the brief must render the attribution table")
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
