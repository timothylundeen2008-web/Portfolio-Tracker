"""
book_risk.py  (v1.1 — November 2026)
────────────────────────────────────
Four readings of the MODEL BOOK that make concentration and speed visible.
All are DISPLAY ONLY: nothing here changes a weight. (fix_status N39-N41, N45)

v1.1 (2026-11-07): risk_by_group(). The first live AI reading (11/06) was
  5.1% of an SMH-over-SPY position: VGT's AI tilt beyond the market is only
  +0.41, and most of its loss came from high market beta (1.15). The excess-
  over-SPY measure therefore understates concentration. risk_by_group()
  answers the direct question: what share of the book's daily variance
  each group carries (Euler risk contribution), next to its share of weight.

1. attribution()   Which sleeves made or lost the book's return over the last
                   5 / 20 sessions and since inception. Uses each session's
                   HELD weights (the prior row's should-hold, exactly as the
                   NAV is marked) and the same dividend-adjusted closes, so
                   the daily contributions add up to the daily book return.
                   Over a window the contributions are summed (arithmetic);
                   the NAV compounds, and the small gap is reported.

2. ai_exposure()   How much of the book is an AI bet, measured from prices,
                   not from hand-typed holdings. Each sleeve's daily return
                   is regressed on the market (SPY) and an AI factor
                   (SMH minus SPY) over 60 sessions:
                       r_i = a + b_mkt * r_SPY + b_ai * (r_SMH - r_SPY)
                   b_ai = 1 for SMH itself. The book's AI exposure is the
                   weight-sum of b_ai: "the book carries X% of an
                   SMH-over-SPY position". The AI share of the book's daily
                   variance is reported too. 2026-11-07: over the month to
                   11/6, VGT/SMH/QQQ (23% of the book) supplied about -3.6 of
                   the book's roughly -4.1% return.
                   Limits are PROPOSED (risk_policy.md): flag at 12% exposure
                   or 40% of variance. Calibrate on a few weeks of readings
                   before treating either as a rule.

3. vol_target()    What a volatility target would do today. Realized 20-session
                   volatility of the book vs a 9% target (the book's own
                   2005-2026 volatility in the hedge lab was 8.8%); scale =
                   target / realized, capped at 1.0 (never levers up) and
                   floored at 0.5 (the breaker's own scale). Risk sleeves are
                   scaled; cash and trend (model_book.RISK_EXEMPT) are not;
                   the freed weight would park in SGOV. NOT APPLIED to the
                   book: the hedge lab must test it first (variant V4).
"""
from __future__ import annotations

import json
import math
from typing import Optional

import numpy as np
import pandas as pd

AI_FACTOR_LONG, AI_FACTOR_MKT = "SMH", "SPY"
AI_LOOKBACK = 60
AI_EXPOSURE_FLAG_PCT = 12.0      # PROPOSED
AI_RISK_SHARE_FLAG_PCT = 40.0    # PROPOSED
GROUP_RISK_FLAG_PCT = 40.0       # PROPOSED: no group above 40% of book risk
RISK_LOOKBACK = 60
VOL_TARGET_PCT = 9.0             # book's long-run vol in the hedge lab: 8.8%
VOL_LOOKBACK = 20
VOL_SCALE_FLOOR, VOL_SCALE_CAP = 0.5, 1.0
RISK_EXEMPT = {"SGOV", "USFR", "BIL", "SHV", "KMLM"}   # = model_book.RISK_EXEMPT
PARK = "SGOV"

BUCKETS = {
    "AI / growth tech": ("VGT", "SMH", "QQQ", "XLK", "SOXX"),
    "Dividend & defensive equity": ("SCHD", "XLV", "XLU", "XLP", "RSP"),
    "Precious metals": ("GLD", "SLV", "RING", "GDX"),
    "Energy & commodities": ("XLE", "PDBC"),
    "Duration": ("TLT", "IEF"),
    "Trend (managed futures)": ("KMLM", "DBMF"),
    "Cash": ("SGOV", "USFR", "BIL", "SHV"),
}


def bucket_of(t: str) -> str:
    for b, members in BUCKETS.items():
        if t in members:
            return b
    return "Other"


def _clean(s) -> pd.Series:
    if s is None:
        return pd.Series(dtype=float)
    s = pd.Series(s).astype(float).dropna()
    if getattr(s.index, "tz", None) is not None:
        s.index = s.index.tz_localize(None)
    s.index = pd.to_datetime(s.index).normalize()
    return s[~s.index.duplicated(keep="last")].sort_index()


def _w(x) -> dict:
    return json.loads(x) if isinstance(x, str) else dict(x or {})


# ── 1. attribution ──────────────────────────────────────────────────────────

def attribution(book: pd.DataFrame, closes: dict, windows=(5, 20, None)) -> dict:
    """{'windows': {label: {'by_ticker': {t: pts}, 'by_bucket': {b: pts},
    'sum_pts', 'nav_pct', 'steps'}}, 'available'}. Points are percentage
    points of book return."""
    out = {"available": False, "windows": {}}
    if book is None or len(book) < 2:
        return out
    b = book.copy()
    b["date"] = pd.to_datetime(b["date"]).dt.normalize()
    b = b.sort_values("date").reset_index(drop=True)
    cl = {t: _clean(s) for t, s in closes.items()}
    steps = []                       # list of (date, {ticker: contribution pts})
    for i in range(1, len(b)):
        d0, d1 = b.loc[i - 1, "date"], b.loc[i, "date"]
        w = _w(b.loc[i - 1, "weights"])
        c = {}
        for t, wt in w.items():
            s = cl.get(t)
            if s is None or s.empty or d0 not in s.index or d1 not in s.index or float(s.loc[d0]) == 0:
                continue
            c[t] = float(wt) * (float(s.loc[d1]) / float(s.loc[d0]) - 1)    # weight in % x return = pts
        steps.append((d1, c))
    if not steps:
        return out
    navs = b["nav"].astype(float).tolist()
    for n in windows:
        sel = steps if n is None else steps[-n:]
        label = "since inception" if n is None else f"{n} sessions"
        tk: dict = {}
        for _, c in sel:
            for t, v in c.items():
                tk[t] = tk.get(t, 0.0) + v
        bk: dict = {}
        for t, v in tk.items():
            bk[bucket_of(t)] = bk.get(bucket_of(t), 0.0) + v
        k = len(sel)
        nav_pct = (navs[-1] / navs[-1 - k] - 1) * 100 if k < len(navs) else None
        out["windows"][label] = {
            "by_ticker": {t: round(v, 3) for t, v in sorted(tk.items(), key=lambda kv: kv[1])},
            "by_bucket": {x: round(v, 3) for x, v in sorted(bk.items(), key=lambda kv: kv[1])},
            "sum_pts": round(sum(tk.values()), 3),
            "nav_pct": round(nav_pct, 3) if nav_pct is not None else None,
            "steps": k, "from": sel[0][0].date().isoformat(), "to": sel[-1][0].date().isoformat()}
    out["available"] = True
    w20 = out["windows"].get("20 sessions") or {}
    if w20.get("by_bucket"):
        worst = min(w20["by_bucket"].items(), key=lambda kv: kv[1])
        best = max(w20["by_bucket"].items(), key=lambda kv: kv[1])
        out["conclusion"] = (f"Last 20 sessions: book {w20['nav_pct']:+.2f}%. Biggest drag {worst[0]} "
                             f"{worst[1]:+.2f} pts; biggest support {best[0]} {best[1]:+.2f} pts.")
    return out


# ── 2. AI-factor exposure ───────────────────────────────────────────────────

def ai_exposure(weights: dict, closes: dict, lookback: int = AI_LOOKBACK) -> dict:
    out = {"available": False, "rows": [], "lookback": lookback,
           "flag_exposure_pct": AI_EXPOSURE_FLAG_PCT, "flag_risk_share_pct": AI_RISK_SHARE_FLAG_PCT,
           "status": "PROPOSED limits"}
    spy, smh = _clean(closes.get(AI_FACTOR_MKT)), _clean(closes.get(AI_FACTOR_LONG))
    if len(spy) < lookback + 1 or len(smh) < lookback + 1:
        out["conclusion"] = (f"AI exposure unavailable: needs {lookback + 1} closes of SPY and SMH "
                             "(a data gap, not a zero reading).")
        return out
    rets = {}
    for t in set(weights) | {AI_FACTOR_MKT, AI_FACTOR_LONG}:
        s = _clean(closes.get(t))
        if len(s) > lookback:
            rets[t] = s.pct_change()
    R = pd.DataFrame(rets).dropna(subset=[AI_FACTOR_MKT, AI_FACTOR_LONG]).iloc[-lookback:]
    mkt = R[AI_FACTOR_MKT]
    ai = R[AI_FACTOR_LONG] - R[AI_FACTOR_MKT]
    X = np.column_stack([np.ones(len(R)), mkt.values, ai.values])
    tot_ai = tot_mkt = 0.0
    covered = 0.0
    book_r = pd.Series(0.0, index=R.index)
    for t, w in sorted(weights.items(), key=lambda kv: -float(kv[1])):
        w = float(w)
        if w <= 0:
            continue
        if t not in R or R[t].isna().sum() > lookback * 0.1:
            out["rows"].append({"ticker": t, "weight": w, "b_mkt": None, "b_ai": None, "ai_pct": None})
            continue
        y = R[t].fillna(0.0).values
        if t in RISK_EXEMPT and t != "KMLM":
            b = np.array([0.0, 0.0, 0.0])
        else:
            b, *_ = np.linalg.lstsq(X, y, rcond=None)
        ai_pct = w * float(b[2])
        tot_ai += ai_pct
        tot_mkt += w * float(b[1])
        covered += w
        book_r = book_r + (w / 100.0) * pd.Series(y, index=R.index)
        out["rows"].append({"ticker": t, "weight": w, "b_mkt": round(float(b[1]), 2),
                            "b_ai": round(float(b[2]), 2), "ai_pct": round(ai_pct, 2)})
    var_book = float(book_r.var())
    ai_var = (tot_ai / 100.0) ** 2 * float(ai.var())
    share = (ai_var / var_book * 100) if var_book > 0 else None
    direct = sum(float(weights.get(t, 0)) for t in BUCKETS["AI / growth tech"])
    flags = []
    if tot_ai >= AI_EXPOSURE_FLAG_PCT:
        flags.append(f"AI exposure {tot_ai:.1f}% ≥ {AI_EXPOSURE_FLAG_PCT:.0f}% (PROPOSED limit)")
    if share is not None and share >= AI_RISK_SHARE_FLAG_PCT:
        flags.append(f"AI factor {share:.0f}% of book variance ≥ {AI_RISK_SHARE_FLAG_PCT:.0f}% (PROPOSED limit)")
    out.update(available=True, ai_exposure_pct=round(tot_ai, 2), market_beta_pct=round(tot_mkt, 1),
               ai_risk_share_pct=round(share, 1) if share is not None else None,
               direct_growth_pct=round(direct, 1), covered_pct=round(covered, 1),
               asof=R.index[-1].date().isoformat(), flags=flags,
               conclusion=(f"The book carries {tot_ai:.1f}% of an SMH-over-SPY position "
                           f"(direct AI/growth sleeves {direct:.0f}%); the AI factor is "
                           + (f"{share:.0f}%" if share is not None else "n/a")
                           + f" of the book's daily variance over {lookback} sessions; market beta "
                           f"{tot_mkt / 100:.2f}. "
                           + ("⚠ " + "; ".join(flags) + "." if flags else "Within the PROPOSED limits.")))
    return out


# ── 2b. risk contribution by group ──────────────────────────────────────────

def risk_by_group(weights: dict, closes: dict, lookback: int = RISK_LOOKBACK) -> dict:
    """Share of the book's daily variance carried by each group, over the
    last `lookback` sessions: RC_i = w_i * cov(r_i, r_book) / var(r_book),
    summed by bucket. Contributions add to 100%; a hedge has a negative one.
    Also reports each group's own annualized volatility and its correlation
    with the rest of the book."""
    out = {"available": False, "lookback": lookback, "flag_pct": GROUP_RISK_FLAG_PCT,
           "status": "PROPOSED limit", "groups": [], "tickers": []}
    rets = {}
    for t, w in weights.items():
        if float(w) <= 0:
            continue
        s = _clean(closes.get(t))
        if len(s) > lookback:
            rets[t] = s.pct_change()
    missing = sorted(t for t, w in weights.items() if float(w) > 0 and t not in rets)
    held = sum(float(w) for t, w in weights.items() if float(w) > 0)
    cov_w = sum(float(weights[t]) for t in rets)
    if not rets or held <= 0 or cov_w / held < 0.9:
        out["conclusion"] = (f"Risk by group unavailable: prices cover {cov_w:.0f}% of the book "
                             f"(missing {', '.join(missing) or 'all'}); needs {lookback + 1} closes. "
                             "A data gap, not a zero reading.")
        return out
    R = pd.DataFrame(rets).iloc[-lookback:].fillna(0.0)
    w = pd.Series({t: float(weights[t]) / 100.0 for t in R.columns})
    book = R.mul(w, axis=1).sum(axis=1)
    var_b = float(book.var())
    if var_b <= 0:
        out["conclusion"] = "Risk by group unavailable: zero book variance in the window."
        return out
    rc = {t: float(w[t] * R[t].cov(book) / var_b * 100) for t in R.columns}
    groups: dict = {}
    for t in R.columns:
        g = bucket_of(t)
        groups.setdefault(g, []).append(t)
    rows = []
    for g, ts in groups.items():
        wg = float(w[ts].sum() * 100)
        gr = R[ts].mul(w[ts], axis=1).sum(axis=1)
        rest = book - gr
        vol = float(gr.std() / (wg / 100) * math.sqrt(252) * 100) if wg > 0 else None
        corr = float(gr.corr(rest)) if rest.std() > 0 and gr.std() > 0 else None
        rows.append({"group": g, "weight_pct": round(wg, 1), "risk_pct": round(sum(rc[t] for t in ts), 1),
                     "vol_pct": round(vol, 1) if vol is not None else None,
                     "corr_rest": round(corr, 2) if corr is not None else None,
                     "tickers": sorted(ts, key=lambda t: -rc[t])})
    rows.sort(key=lambda r: -r["risk_pct"])
    top = rows[0]
    flags = [f"{r['group']} carries {r['risk_pct']:.0f}% of book risk ≥ {GROUP_RISK_FLAG_PCT:.0f}% (PROPOSED limit)"
             for r in rows if r["risk_pct"] >= GROUP_RISK_FLAG_PCT]
    book_vol = float(book.std() * math.sqrt(252) * 100)
    out.update(available=True, groups=rows, flags=flags, book_vol_pct=round(book_vol, 1),
               tickers=[{"ticker": t, "weight_pct": round(float(w[t] * 100), 1), "risk_pct": round(rc[t], 1)}
                        for t in sorted(rc, key=lambda t: -rc[t])],
               missing=missing, asof=R.index[-1].date().isoformat(),
               conclusion=(f"{top['group']} is {top['weight_pct']:.0f}% of the book's weight and "
                           f"{top['risk_pct']:.0f}% of its risk over {lookback} sessions "
                           f"(book volatility {book_vol:.1f}%). "
                           + ("⚠ " + "; ".join(flags) + "." if flags else
                              f"No group is above the PROPOSED {GROUP_RISK_FLAG_PCT:.0f}% line.")
                           + " Negative = the group offset book risk.")) 
    return out


# ── 3. volatility target ────────────────────────────────────────────────────

def vol_scale(realized_pct: Optional[float], target_pct: float = VOL_TARGET_PCT) -> Optional[float]:
    if realized_pct is None or not (realized_pct == realized_pct) or realized_pct <= 0:
        return None
    return float(min(VOL_SCALE_CAP, max(VOL_SCALE_FLOOR, target_pct / realized_pct)))


def apply_vol_scale(weights: dict, scale: float) -> dict:
    out, freed = {}, 0.0
    for t, w in weights.items():
        w = float(w)
        nw = w if t in RISK_EXEMPT else round(w * scale, 2)
        freed += w - nw
        out[t] = nw
    out[PARK] = round(out.get(PARK, 0.0) + freed, 2)
    return out


def vol_target(book: pd.DataFrame, lookback: int = VOL_LOOKBACK, target_pct: float = VOL_TARGET_PCT) -> dict:
    out = {"available": False, "target_pct": target_pct, "lookback": lookback, "applied": False}
    if book is None or len(book) < lookback + 1:
        out["conclusion"] = f"Volatility target unavailable: needs {lookback + 1} sessions of NAV."
        return out
    nav = pd.Series(book["nav"].astype(float).values)
    r = nav.pct_change().dropna().iloc[-lookback:]
    realized = float(r.std() * math.sqrt(252) * 100)
    sc = vol_scale(realized, target_pct)
    w = _w(book["weights"].iloc[-1])
    scaled = apply_vol_scale(w, sc) if sc is not None else w
    freed = round(scaled.get(PARK, 0) - float(w.get(PARK, 0)), 1)
    out.update(available=True, realized_pct=round(realized, 2), scale=round(sc, 2) if sc else None,
               freed_to_sgov_pct=freed, scaled_weights=scaled,
               conclusion=(f"Book volatility over {lookback} sessions {realized:.1f}% vs a {target_pct:.0f}% target: "
                           + (f"a volatility target would hold risk sleeves at {sc:.2f}× and park {freed:.1f}% "
                              f"in SGOV." if sc is not None and sc < 1 else
                              "a volatility target would make no change (scale 1.00).")
                           + " Display only — not applied until the hedge lab tests it (V4)."))
    return out


# ── selftest ────────────────────────────────────────────────────────────────

def selftest() -> dict:
    f = []
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2026-06-01", periods=90)
    spy_r = rng.normal(0, 0.01, len(idx))
    ai_f = rng.normal(0, 0.015, len(idx))
    smh_r = spy_r + ai_f
    vgt_r = spy_r + 0.5 * ai_f + rng.normal(0, 0.0005, len(idx))
    sch_r = 0.7 * spy_r + rng.normal(0, 0.0005, len(idx))
    px = lambda r: pd.Series(100 * np.cumprod(1 + r), index=idx)
    closes = {"SPY": px(spy_r), "SMH": px(smh_r), "VGT": px(vgt_r), "SCHD": px(sch_r),
              "SGOV": pd.Series(np.linspace(100, 101, len(idx)), index=idx)}
    w = {"VGT": 20.0, "SMH": 5.0, "SCHD": 30.0, "SGOV": 45.0}
    a = ai_exposure(w, closes)
    if not a["available"] or abs(a["ai_exposure_pct"] - (20 * 0.5 + 5 * 1.0)) > 1.0:
        f.append(f"AI exposure must recover 20×0.5 + 5×1.0 = 15%: {a.get('ai_exposure_pct')}")
    if not a["flags"]:
        f.append("15% AI exposure must trip the 12% PROPOSED flag")
    if ai_exposure({"SCHD": 50, "SGOV": 50}, closes)["ai_exposure_pct"] > 1.0:
        f.append("a book with no AI sleeve must read ~0%")
    if ai_exposure(w, {"SPY": closes["SPY"].iloc[:20], "SMH": closes["SMH"].iloc[:20]})["available"]:
        f.append("too little history must be unavailable, not zero")
    # attribution: two sessions, weights from the PRIOR row
    d = list(idx[:3])
    book = pd.DataFrame({"date": d, "nav": [100.0, 0, 0],
                         "weights": [json.dumps({"VGT": 50, "SGOV": 50}), json.dumps({"VGT": 20, "SGOV": 80}),
                                     json.dumps({"VGT": 20, "SGOV": 80})]})
    cl2 = {"VGT": pd.Series([100.0, 110.0, 99.0], index=d), "SGOV": pd.Series([100.0, 100.0, 100.0], index=d)}
    book.loc[1, "nav"] = 100 * (1 + 0.5 * 0.10)
    book.loc[2, "nav"] = book.loc[1, "nav"] * (1 + 0.2 * -0.10)
    at = attribution(book, cl2, windows=(1, None))
    if abs(at["windows"]["1 sessions"]["by_ticker"]["VGT"] - (-2.0)) > 1e-9:
        f.append(f"day 2 must use the PRIOR row's 20% weight: {at['windows']['1 sessions']['by_ticker']}")
    if abs(at["windows"]["since inception"]["sum_pts"] - 3.0) > 1e-9:
        f.append("since inception must sum +5 then -2 = +3 pts")
    if at["windows"]["since inception"]["by_bucket"].get("AI / growth tech") is None:
        f.append("VGT must be bucketed as AI / growth tech")
    # vol target
    if vol_scale(18.0) != 0.5 or vol_scale(6.0) != 1.0 or abs(vol_scale(12.0) - 0.75) > 1e-12:
        f.append("vol scale must be target/realized, capped at 1.0 and floored at 0.5")
    sw = apply_vol_scale({"VGT": 20, "KMLM": 5, "SGOV": 10}, 0.5)
    if sw != {"VGT": 10.0, "KMLM": 5, "SGOV": 20.0}:
        f.append(f"scaling must halve risk sleeves, leave trend/cash, park in SGOV: {sw}")
    if abs(sum(sw.values()) - 35) > 1e-9:
        f.append("scaling must preserve total weight")
    bk = pd.DataFrame({"nav": 100 * np.cumprod(1 + rng.normal(0, 0.02, 30)),
                       "weights": [json.dumps({"VGT": 60, "SGOV": 40})] * 30})
    vt = vol_target(bk)
    if not vt["available"] or vt["scale"] is None or vt["scale"] > 0.75 or vt["applied"]:
        f.append(f"a ~32% vol book must scale well below 1 and never be applied: {vt}")
    # risk by group: contributions add to 100; a high-beta group dominates; a hedge is negative
    rng2 = np.random.default_rng(5)
    mkt = rng2.normal(0, 0.01, len(idx))
    cl3 = {"VGT": px(1.6 * mkt + rng2.normal(0, 0.002, len(idx))),
           "SCHD": px(0.6 * mkt + rng2.normal(0, 0.002, len(idx))),
           "TLT": px(-0.4 * mkt + rng2.normal(0, 0.002, len(idx))),
           "SGOV": pd.Series(np.linspace(100, 101, len(idx)), index=idx)}
    rg = risk_by_group({"VGT": 25, "SCHD": 30, "TLT": 15, "SGOV": 30}, cl3)
    if not rg["available"]:
        f.append(f"risk_by_group must be available: {rg.get('conclusion')}")
    else:
        tot = sum(g["risk_pct"] for g in rg["groups"])
        if abs(tot - 100) > 0.5:
            f.append(f"group risk contributions must add to 100%: {tot}")
        top = rg["groups"][0]
        if top["group"] != "AI / growth tech" or top["risk_pct"] <= 25 * 1.5:
            f.append(f"a 1.6-beta growth sleeve at 25% weight must carry far more than its weight in risk: {top}")
        dur = next(g for g in rg["groups"] if g["group"] == "Duration")
        if dur["risk_pct"] >= 0:
            f.append(f"a negatively correlated duration sleeve must have a negative contribution: {dur}")
        if not rg["flags"]:
            f.append("a group above 40% of book risk must be flagged")
    if risk_by_group({"VGT": 50, "XYZ": 50}, {"VGT": cl3["VGT"]})["available"]:
        f.append("half the book unpriced must be unavailable, not a reading")
    return {"ok": not f, "failures": f}


if __name__ == "__main__":
    print(json.dumps(selftest(), indent=2))
