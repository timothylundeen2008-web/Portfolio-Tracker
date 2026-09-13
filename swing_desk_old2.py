"""
swing_desk.py  (v1 — September 2026)
────────────────────────────────────
The ACTIVE agent. Reads market signals, spots setups across every method in
swing_trading_procedure.md — long AND short, 3-day bursts AND multi-week
trends — scores confluence, and produces trade cards with direction,
reasoning, and an explicit list of what to stay away from and why.

WHAT IT READS
  Level 1  regime + Fed posture + tripwires    <- markets_bridge (published
                                                  by the Markets Dashboard)
  Level 2  sector RRG quadrant + Tier A flow   <- rotation_bridge (Money Flow)
  Level 4  price/volume structure              <- computed here, per ticker

WHAT IT PRODUCES
  For every ticker in the universe: a classification (which setup, if any),
  a confluence score with each leg's evidence, a full trade card, and --
  when it is NOT a setup -- the specific criterion it fails. The avoid list
  is not an afterthought: knowing what NOT to trade is half the edge.

DIRECTION IS SET BY THE REGIME, NOT BY THE CHART
  risk-on regimes           -> long book leads, short book on parabolic only
  transition / term-premium -> both books, half size, 2-of-3 minimum
  growth_scare / liq_crisis -> long book CLOSED, short book ACTIVE
  A clean long setup in a hostile regime is reported as a setup -- and then
  explicitly refused, with the regime named as the reason.

HONEST LIMITS
  * This evaluates any ticker fed to it and scans a defined universe. It is
    NOT a market-wide screener: discovering a fresh Episodic Pivot across
    5,000 listed names needs a pre-market gap feed this does not have.
    Point a screener (ChartMill / TrendSpider / Deepvue) at the EP criteria
    and feed the survivors here for the full evaluation.
  * All sizing here is per swing_trading_procedure.md. Progressive Exposure
    step must be supplied -- this module cannot know your last five trades.
"""

from __future__ import annotations

from typing import Callable, Optional

import numpy as np
import pandas as pd

# ── Method thresholds, straight from the procedure ──────────────────────────
ADR_MIN_PCT = 3.5             # Kullamägi universe filter
DOLLAR_VOL_MIN = 3_000_000    # daily
VCP_MIN_CONTRACTIONS = 3
BREAKOUT_VOL_MULT = 1.5       # breakout bar vs 50d avg
EP_GAP_MIN_PCT = 10.0
PARABOLIC_ADR_ABOVE_10EMA = 5.0
BURST_RANGE_MAX_ADR = 1.5     # tight range for a momentum burst
MAX_STOP_PCT_M1 = 8.0         # Minervini hard cap

REGIME_DIRECTION = {
    "goldilocks":              ("long", 1.0),
    "inflationary_repression": ("long", 1.0),
    "term_premium_repricing":  ("both", 0.5),
    "transition_ambiguous":    ("both", 0.5),
    "neutral":                 ("both", 0.5),
    "hard_repression":         ("both", 0.5),
    "stagflation":             ("both", 0.5),
    "growth_scare":            ("short", 1.0),
    "liquidity_crisis":        ("short", 1.0),
}

PROGRESSIVE_EXPOSURE = {0: 0.0, 1: 0.5, 2: 1.0, 3: 2.0}   # step -> risk %


# ── Indicators ──────────────────────────────────────────────────────────────

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def _adr_pct(df: pd.DataFrame, n: int = 20) -> float:
    """Average daily range as % of close — Kullamägi's volatility filter."""
    rng = (df["High"] / df["Low"] - 1) * 100
    return float(rng.tail(n).mean())


def _rs_rank_proxy(close: pd.Series, bench: Optional[pd.Series]) -> Optional[float]:
    """
    0-100 relative-strength proxy: the stock's 3/6-month return vs the
    benchmark's, mapped onto a percentile-ish scale. A true IBD-style RS
    rank needs the whole market; this is a per-ticker approximation.
    """
    if bench is None or len(close) < 130 or len(bench) < 130:
        return None
    r3 = close.iloc[-1] / close.iloc[-63] - 1
    r6 = close.iloc[-1] / close.iloc[-126] - 1
    b3 = bench.iloc[-1] / bench.iloc[-63] - 1
    b6 = bench.iloc[-1] / bench.iloc[-126] - 1
    excess = 0.6 * (r3 - b3) + 0.4 * (r6 - b6)
    # squash: +30% excess ~ 90, 0 ~ 50, -30% ~ 10
    return float(np.clip(50 + excess * 133, 0, 100))


# ── Method 1: Trend Template + VCP ──────────────────────────────────────────

def trend_template(df: pd.DataFrame, bench: Optional[pd.Series] = None) -> dict:
    """All 8 Minervini criteria, each reported. ALL must pass."""
    c = df["Close"]
    if len(c) < 260:
        return {"passes": False, "criteria": {}, "reason": "need ~1yr of history"}
    ma50, ma150, ma200 = _sma(c, 50), _sma(c, 150), _sma(c, 200)
    px = float(c.iloc[-1])
    lo52, hi52 = float(c.tail(252).min()), float(c.tail(252).max())
    rs = _rs_rank_proxy(c, bench)
    crit = {
        "1 price > 50/150/200 MA":  px > ma50.iloc[-1] and px > ma150.iloc[-1] and px > ma200.iloc[-1],
        "2 150 MA > 200 MA":         ma150.iloc[-1] > ma200.iloc[-1],
        "3 200 MA rising 1mo+":      ma200.iloc[-1] > ma200.iloc[-22],
        "4 50 MA > 150 & 200":       ma50.iloc[-1] > ma150.iloc[-1] > ma200.iloc[-1],
        "5 >=25% above 52w low":     px >= lo52 * 1.25,
        "6 within 25% of 52w high":  px >= hi52 * 0.75,
        "7 RS rank >= 70":           (rs is not None and rs >= 70),
        "8 price > 50 MA":           px > ma50.iloc[-1],
    }
    failed = [k for k, v in crit.items() if not v]
    return {"passes": not failed, "criteria": crit, "failed": failed,
            "rs_rank": None if rs is None else round(rs, 0)}


def detect_vcp(df: pd.DataFrame, lookback: int = 120) -> dict:
    """
    Successive pullbacks CONTRACTING in depth with volume drying up into the
    last one. Returns the contraction sequence and the pivot (high of the
    final contraction).
    """
    d = df.tail(lookback)
    c, v = d["Close"], d["Volume"]
    # swing highs/lows via a simple 5-bar pivot
    highs = c[(c.shift(1) < c) & (c.shift(-1) < c) & (c.shift(2) < c) & (c.shift(-2) < c)]
    lows = c[(c.shift(1) > c) & (c.shift(-1) > c) & (c.shift(2) > c) & (c.shift(-2) > c)]
    if len(highs) < 2 or len(lows) < 2:
        return {"is_vcp": False, "reason": "not enough swing structure"}
    # pair each high with the next low to measure pullback depth
    depths = []
    for t, h in highs.items():
        after = lows[lows.index > t]
        if len(after):
            depths.append((t, float((h - after.iloc[0]) / h * 100)))
    if len(depths) < VCP_MIN_CONTRACTIONS:
        return {"is_vcp": False, "reason": f"only {len(depths)} pullbacks, need {VCP_MIN_CONTRACTIONS}"}
    seq = [round(x[1], 1) for x in depths[-VCP_MIN_CONTRACTIONS:]]
    contracting = all(seq[i] > seq[i + 1] for i in range(len(seq) - 1))
    vol_drying = float(v.tail(10).mean()) < float(v.tail(50).mean()) * 0.8
    pivot = float(c.loc[depths[-1][0]])
    return {"is_vcp": contracting and vol_drying, "sequence": seq,
            "contracting": contracting, "volume_drying": vol_drying,
            "pivot": pivot, "last_contraction_pct": seq[-1],
            "reason": ("VCP" if contracting and vol_drying else
                       "pullbacks not contracting" if not contracting else
                       "volume not drying up")}


# ── Method 2: Breakout / EP / Burst / Parabolic / Failed BO ─────────────────

def universe_filter(df: pd.DataFrame) -> dict:
    adr = _adr_pct(df)
    dvol = float((df["Close"] * df["Volume"]).tail(20).mean())
    c = df["Close"]
    ok = (adr >= ADR_MIN_PCT and dvol >= DOLLAR_VOL_MIN
          and c.iloc[-1] > _sma(c, 20).iloc[-1] and c.iloc[-1] > _sma(c, 50).iloc[-1])
    return {"passes": ok, "adr_pct": round(adr, 2), "dollar_vol": round(dvol),
            "above_20_50": bool(c.iloc[-1] > _sma(c, 20).iloc[-1] > 0 and c.iloc[-1] > _sma(c, 50).iloc[-1])}


def detect_breakout(df: pd.DataFrame) -> dict:
    """Prior big move, then a tight consolidation riding the 10/20 EMA, then a range break on volume."""
    c, v = df["Close"], df["Volume"]
    if len(c) < 80:
        return {"is_setup": False, "reason": "need 80 bars"}
    prior_move = float(c.iloc[-20] / c.iloc[-60] - 1) * 100   # move in the 40d before consolidation
    cons = c.tail(20)
    rng_pct = float((cons.max() / cons.min() - 1) * 100)
    e10, e20 = _ema(c, 10), _ema(c, 20)
    surfing = bool((cons > e20.tail(20)).mean() >= 0.8)
    vol_ratio = float(v.iloc[-1] / v.tail(50).mean())
    broke = bool(c.iloc[-1] > cons.iloc[:-1].max())
    ok = prior_move >= 30 and rng_pct <= 15 and surfing and broke and vol_ratio >= BREAKOUT_VOL_MULT
    return {"is_setup": ok, "prior_move_pct": round(prior_move, 1),
            "range_pct": round(rng_pct, 1), "surfing_20ema": surfing,
            "broke_range": broke, "vol_ratio": round(vol_ratio, 2),
            "pivot": float(cons.iloc[:-1].max()),
            "reason": ("Breakout" if ok else
                       f"prior move {prior_move:.0f}% < 30" if prior_move < 30 else
                       f"range {rng_pct:.0f}% > 15 (not tight)" if rng_pct > 15 else
                       "not surfing 20 EMA" if not surfing else
                       "range not broken yet" if not broke else
                       f"volume {vol_ratio:.1f}x < {BREAKOUT_VOL_MULT}x")}


def detect_episodic_pivot(df: pd.DataFrame, catalyst: Optional[str] = None) -> dict:
    """
    Gap >= 10% on heavy volume, ideally after a sideways/down 3-6 months.
    The CATALYST must be named -- this module cannot read the news; the
    caller supplies it, and without one the setup is capped at 2-of-3.
    """
    c, o, v = df["Close"], df["Open"], df["Volume"]
    if len(c) < 130:
        return {"is_setup": False, "reason": "need 130 bars"}
    gap = float(o.iloc[-1] / c.iloc[-2] - 1) * 100
    vol_ratio = float(v.iloc[-1] / v.tail(50).mean())
    prior = float(c.iloc[-2] / c.iloc[-126] - 1) * 100
    neglected = prior <= 15
    closed_strong = bool(c.iloc[-1] >= o.iloc[-1] and (c.iloc[-1] - df["Low"].iloc[-1]) /
                         max(df["High"].iloc[-1] - df["Low"].iloc[-1], 1e-9) >= 0.6)
    ok = gap >= EP_GAP_MIN_PCT and vol_ratio >= 3.0
    return {"is_setup": ok, "gap_pct": round(gap, 1), "vol_ratio": round(vol_ratio, 1),
            "prior_6m_pct": round(prior, 1), "neglected": neglected,
            "closed_strong": closed_strong, "catalyst": catalyst,
            "orb_high": float(df["High"].iloc[-1]), "day_low": float(df["Low"].iloc[-1]),
            "reason": ("Episodic Pivot" if ok else
                       f"gap {gap:.1f}% < {EP_GAP_MIN_PCT}%" if gap < EP_GAP_MIN_PCT else
                       f"volume {vol_ratio:.1f}x < 3x")}


def detect_momentum_burst(df: pd.DataFrame) -> dict:
    """Tight 3-10 day range (< 1.5x ADR total) then a range break on the first big bar."""
    c, v = df["Close"], df["Volume"]
    if len(c) < 60:
        return {"is_setup": False, "reason": "need 60 bars"}
    adr = _adr_pct(df)
    for n in (3, 5, 7, 10):
        rng = c.iloc[-n - 1:-1]
        rng_pct = float((rng.max() / rng.min() - 1) * 100)
        if rng_pct <= BURST_RANGE_MAX_ADR * adr:
            broke = bool(c.iloc[-1] > rng.max())
            vol_ratio = float(v.iloc[-1] / v.tail(50).mean())
            if broke and vol_ratio >= BREAKOUT_VOL_MULT:
                return {"is_setup": True, "range_days": n, "range_pct": round(rng_pct, 1),
                        "adr_pct": round(adr, 2), "vol_ratio": round(vol_ratio, 2),
                        "pivot": float(rng.max()), "bar_low": float(df["Low"].iloc[-1]),
                        "reason": f"Momentum burst from {n}-day range"}
    return {"is_setup": False, "reason": "no tight range + break on volume"}


def detect_parabolic_short(df: pd.DataFrame) -> dict:
    """>=3 up days expanding, >=5 ADR above 10 EMA, climax volume, first reversal signal."""
    c, v, h, l = df["Close"], df["Volume"], df["High"], df["Low"]
    if len(c) < 60:
        return {"is_setup": False, "reason": "need 60 bars"}
    # Extension measured against the stock's BASELINE volatility -- ADR over
    # the 30 bars BEFORE the last 10 -- not the expanded ADR of the parabolic
    # run itself. A stock that triples in 10 days also triples its 20-day
    # ADR; measuring extension in those inflated units under-counts exactly
    # the move this detector exists to catch.
    adr = _adr_pct(df.iloc[-40:-10]) if len(df) >= 40 else _adr_pct(df)
    e10 = _ema(c, 10)
    ext_adr = float((c.iloc[-1] / e10.iloc[-1] - 1) * 100 / max(adr, 0.1))
    ups = int((c.diff().tail(5) > 0).sum())
    climax_idx = int(v.tail(10).values.argmax())
    climax_recent = climax_idx >= 7
    rev = bool(c.iloc[-1] < c.iloc[-2]) or bool((h.iloc[-1] - c.iloc[-1]) > 0.5 * (h.iloc[-1] - l.iloc[-1]))
    ok = ext_adr >= PARABOLIC_ADR_ABOVE_10EMA and ups >= 3 and climax_recent and rev
    return {"is_setup": ok, "ext_adr_above_10ema": round(ext_adr, 1), "up_days_of_5": ups,
            "climax_recent": climax_recent, "reversal_signal": rev,
            "climax_high": float(h.tail(3).max()), "climax_low": float(l.iloc[-1]),
            "target_10ema": float(e10.iloc[-1]), "target_20ema": float(_ema(c, 20).iloc[-1]),
            "reason": ("Parabolic short" if ok else
                       f"only {ext_adr:.1f} ADR above 10 EMA (need {PARABOLIC_ADR_ABOVE_10EMA})"
                       if ext_adr < PARABOLIC_ADR_ABOVE_10EMA else
                       "no reversal signal yet" if not rev else "no recent climax bar")}


def detect_failed_breakout(df: pd.DataFrame) -> dict:
    """Pivot broke on volume, then closed back below it within 1-3 days on volume >= breakout bar."""
    c, v = df["Close"], df["Volume"]
    if len(c) < 40:
        return {"is_setup": False, "reason": "need 40 bars"}
    base = c.iloc[-25:-4]
    pivot = float(base.max())
    recent = c.tail(4)
    broke = bool((recent.iloc[:-1] > pivot).any())
    bo_vol = float(v.tail(4).iloc[:-1].max())
    failed = bool(c.iloc[-1] < pivot and broke and v.iloc[-1] >= bo_vol * 0.9)
    return {"is_setup": failed, "pivot": pivot, "failed_high": float(df["High"].tail(4).max()),
            "target_base_low": float(base.min()),
            "reason": "Failed breakout" if failed else "no recent breakout-then-failure"}


# ── Confluence + sizing + the card ──────────────────────────────────────────

def confluence(rotation_ok: Optional[bool], structure_ok: bool, volume_ok: bool) -> dict:
    """Each leg independently sourced. A leg with no data does NOT pass."""
    legs = {"rotation": bool(rotation_ok), "structure": structure_ok, "volume": volume_ok}
    score = sum(legs.values())
    return {"score": score, "legs": legs,
            "size_mult": {3: 1.0, 2: 0.5}.get(score, 0.0),
            "missing": [k for k, v in legs.items() if not v]}


def size_position(equity: float, entry: float, stop: float, risk_pct: float,
                  regime_mult: float, confl_mult: float, heat_used_pct: float,
                  heat_cap_pct: float = 15.0, max_position_pct: float = 30.0) -> dict:
    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0 or equity <= 0:
        return {"shares": 0, "reason": "invalid entry/stop"}
    eff_risk = risk_pct * regime_mult * confl_mult
    risk_dollars = equity * eff_risk / 100
    shares = int(risk_dollars // risk_per_share)
    notional = shares * entry
    pos_pct = notional / equity * 100
    if pos_pct > max_position_pct:
        shares = int(equity * max_position_pct / 100 // entry)
        notional = shares * entry
        pos_pct = notional / equity * 100
    heat_add = shares * risk_per_share / equity * 100
    blocked = heat_used_pct + heat_add > heat_cap_pct
    return {"shares": 0 if blocked else shares, "notional": round(notional),
            "position_pct": round(pos_pct, 1), "risk_dollars": round(shares * risk_per_share),
            "effective_risk_pct": round(eff_risk, 2), "heat_add_pct": round(heat_add, 2),
            "heat_after_pct": round(heat_used_pct + heat_add, 2),
            "blocked_by_heat": blocked,
            "reason": (f"heat {heat_used_pct + heat_add:.1f}% would exceed {heat_cap_pct}% cap"
                       if blocked else "ok")}


def evaluate(ticker: str, df: pd.DataFrame, regime_key: str, *,
             bench: Optional[pd.Series] = None,
             sector_quadrant: Optional[str] = None, tier_a_confirmed: Optional[bool] = None,
             catalyst: Optional[str] = None, equity: float = 25_000.0,
             pe_step: int = 1, heat_used_pct: float = 0.0,
             earnings_within_48h: bool = False) -> dict:
    """
    The full agent pass for one ticker. Returns a classification, the
    confluence table, a trade card (when tradeable), and -- always -- the
    reason, including the specific criterion that failed when it is NOT one.
    """
    direction, regime_mult = REGIME_DIRECTION.get(regime_key, ("both", 0.5))
    out = {"ticker": ticker, "regime": regime_key, "regime_direction": direction,
           "regime_mult": regime_mult, "setup": None, "side": None, "card": None,
           "avoid_reason": None, "detail": {}}

    uf = universe_filter(df)
    tt = trend_template(df, bench)
    out["detail"]["universe"] = uf
    out["detail"]["trend_template"] = tt

    candidates = []
    # Long side
    if direction in ("long", "both"):
        if tt["passes"]:
            vcp = detect_vcp(df)
            out["detail"]["vcp"] = vcp
            if vcp["is_vcp"]:
                candidates.append(("M1 VCP", "long", vcp["pivot"],
                                   vcp["pivot"] * (1 - min(MAX_STOP_PCT_M1, max(3.0, vcp["last_contraction_pct"] + 1)) / 100),
                                   vcp["reason"]))
        if uf["passes"]:
            bo = detect_breakout(df); out["detail"]["breakout"] = bo
            if bo["is_setup"]:
                candidates.append(("M2 Breakout", "long", float(df["Close"].iloc[-1]),
                                   float(df["Low"].iloc[-1]), bo["reason"]))
            ep = detect_episodic_pivot(df, catalyst); out["detail"]["ep"] = ep
            if ep["is_setup"]:
                candidates.append(("M2 EP", "long", ep["orb_high"], ep["day_low"], ep["reason"]))
            mb = detect_momentum_burst(df); out["detail"]["burst"] = mb
            if mb["is_setup"]:
                candidates.append(("M2c Burst", "long", float(df["Close"].iloc[-1]), mb["bar_low"], mb["reason"]))
    # Short side. Parabolic shorts are an ALL-market setup (Kullamägi's #3):
    # evaluated even in risk-on regimes, at half size. Failed-breakout shorts
    # only where the regime already permits the short book.
    ps = detect_parabolic_short(df); out["detail"]["parabolic"] = ps
    if ps["is_setup"] and not candidates:
        candidates.append(("M2b Parabolic Short", "short", ps["climax_low"], ps["climax_high"], ps["reason"]))
        if direction == "long":
            regime_mult = min(regime_mult, 0.5); out["regime_mult"] = regime_mult
    if direction in ("short", "both"):
        fb = detect_failed_breakout(df); out["detail"]["failed_bo"] = fb
        if fb["is_setup"]:
            candidates.append(("M2b Failed-BO Short", "short", fb["pivot"], fb["failed_high"], fb["reason"]))

    # Long setups in a short-only regime are reported AND refused
    if direction == "short" and uf["passes"]:
        long_probe = detect_breakout(df)
        if not long_probe.get("is_setup"):
            long_probe = detect_momentum_burst(df)
        if long_probe.get("is_setup"):
            out["avoid_reason"] = (f"Clean long breakout, but regime is {regime_key}: the long "
                                   f"book is CLOSED. A Level-4 setup in a hostile Level-1 regime "
                                   f"is a trap. Watchlist it; unlock condition = regime exits "
                                   f"growth_scare/liquidity_crisis.")

    if not candidates:
        if out["avoid_reason"] is None:
            # name the closest miss
            near = []
            if not uf["passes"]:
                near.append(f"universe filter: ADR {uf['adr_pct']}% / $vol {uf['dollar_vol']:,}")
            if not tt["passes"] and tt.get("failed"):
                near.append(f"Trend Template fails: {', '.join(tt['failed'][:3])}")
            for k in ("breakout", "vcp", "ep", "burst", "parabolic"):
                if k in out["detail"] and out["detail"][k].get("reason"):
                    near.append(f"{k}: {out['detail'][k]['reason']}")
            out["avoid_reason"] = "Not a setup. " + " | ".join(near[:4])
        return out

    setup, side, entry, stop, why = candidates[0]
    out["setup"], out["side"] = setup, side

    # Confluence
    rot_ok = (sector_quadrant in ("Improving", "Leading")) if side == "long" else \
             (sector_quadrant in ("Weakening", "Lagging"))
    if tier_a_confirmed:
        rot_ok = rot_ok or (side == "long")
    vol_ok = float(df["Volume"].iloc[-1]) >= BREAKOUT_VOL_MULT * float(df["Volume"].tail(50).mean())
    cf = confluence(rot_ok if sector_quadrant else None, True, vol_ok)
    if setup == "M2 EP" and not catalyst:
        cf["score"] = min(cf["score"], 2); cf["size_mult"] = 0.5
        cf["missing"].append("catalyst not named")
    out["confluence"] = cf

    if earnings_within_48h and setup != "M2 EP":
        out["avoid_reason"] = "Earnings within 48h — no new entry regardless of setup quality."
        return out
    if cf["score"] < 2:
        out["avoid_reason"] = f"Only {cf['score']}-of-3 confluence (missing: {', '.join(cf['missing'])}). Watchlist only."
        return out

    risk_pct = PROGRESSIVE_EXPOSURE.get(pe_step, 0.5)
    sz = size_position(equity, entry, stop, risk_pct, regime_mult, cf["size_mult"], heat_used_pct)
    r = abs(entry - stop)
    tgt = (lambda k: entry + k * r) if side == "long" else (lambda k: entry - k * r)
    trail = {"M1 VCP": "50-day SMA", "M2 Breakout": "10 EMA (aggressive) / 20 EMA (patient)",
             "M2 EP": "10 EMA", "M2c Burst": "exit day 3-5 or first close < 5 EMA — no trail",
             "M2b Parabolic Short": "cover at 10 EMA, then 20 EMA",
             "M2b Failed-BO Short": "cover at base low"}[setup]
    out["card"] = {
        "setup": setup, "side": side, "entry": round(entry, 2), "stop": round(stop, 2),
        "stop_pct": round(r / entry * 100, 2), "risk_per_share": round(r, 2),
        "pe_step": pe_step, "risk_pct": risk_pct, "regime_mult": regime_mult,
        "confluence": f"{cf['score']}-of-3", "size": sz,
        "targets": {"2R": round(tgt(2), 2), "4R": round(tgt(4), 2), "8R": round(tgt(8), 2)},
        "trail": trail,
        "instrument": ("put debit spread 45-90 DTE" if side == "short" and equity < 100_000 else
                       "call debit spread 45-90 DTE" if sz["blocked_by_heat"] or equity < 15_000 else
                       "stock"),
        "invalidated_when": (f"close {'below' if side == 'long' else 'above'} {stop:.2f} "
                             f"(structural), OR regime flips "
                             f"{'hostile' if side == 'long' else 'risk-on'}, OR sector rotates to "
                             f"{'Weakening/Lagging' if side == 'long' else 'Improving/Leading'}"),
        "why": why,
    }
    return out


def scan(universe: list[str], fetch_ohlcv: Callable[[str], pd.DataFrame],
         regime_key: str, **kw) -> dict:
    """Run evaluate() across a universe. Returns tradeable cards + the avoid list."""
    cards, avoid, errors = [], [], []
    for tk in universe:
        try:
            df = fetch_ohlcv(tk)
            if df is None or len(df) < 60:
                errors.append((tk, "insufficient history")); continue
            r = evaluate(tk, df, regime_key, **kw)
            (cards if r["card"] else avoid).append(r)
        except Exception as e:
            errors.append((tk, f"{type(e).__name__}: {e}"))
    cards.sort(key=lambda r: (-r["confluence"]["score"], r["card"]["stop_pct"]))
    return {"regime": regime_key, "direction": REGIME_DIRECTION.get(regime_key, ("both", 0.5))[0],
            "cards": cards, "avoid": avoid, "errors": errors}


# ── Render ──────────────────────────────────────────────────────────────────

def render(st, result: dict):
    d = result["direction"]
    st.markdown(f"### 🎯 Swing Desk — regime `{result['regime']}` → "
                f"**{ {'long':'LONG book leads','short':'SHORT book ACTIVE, long book CLOSED','both':'both books, half size'}[d] }**")
    if not result["cards"]:
        st.info("No tradeable setups in this universe right now. That is a valid, complete answer — "
                "sitting in cash is a position.")
    for r in result["cards"]:
        c = r["card"]; s = c["size"]
        icon = "🟢" if c["side"] == "long" else "🔴"
        with st.expander(f"{icon} {r['ticker']} — {c['setup']} · {c['confluence']} · stop {c['stop_pct']}% · "
                         f"{'BLOCKED: '+s['reason'] if s['blocked_by_heat'] else str(s['shares'])+' sh'}",
                         expanded=(c["confluence"] == "3-of-3")):
            st.markdown(f"**Entry** {c['entry']} · **Stop** {c['stop']} ({c['stop_pct']}%) · "
                        f"**Risk/sh** {c['risk_per_share']} · **Instrument** {c['instrument']}")
            st.markdown(f"**Size** {s['shares']} sh ≈ ${s['notional']:,} ({s['position_pct']}% of equity) · "
                        f"risk ${s['risk_dollars']:,} ({s['effective_risk_pct']}%) · "
                        f"heat after {s['heat_after_pct']}% of 15%")
            st.markdown(f"**Targets** 2R {c['targets']['2R']} · 4R {c['targets']['4R']} · 8R {c['targets']['8R']} "
                        f"(trim 25% each) · **Trail** {c['trail']}")
            st.markdown(f"**Why:** {c['why']} · PE step {c['pe_step']} → {c['risk_pct']}% × regime {c['regime_mult']}")
            legs = r["confluence"]["legs"]
            st.caption("Confluence: " + " · ".join(f"{'✅' if v else '○'} {k}" for k, v in legs.items()))
            st.warning(f"**Invalidated when:** {c['invalidated_when']}")
    if result["avoid"]:
        with st.expander(f"🚫 Stay away ({len(result['avoid'])}) — and why", expanded=False):
            for r in result["avoid"]:
                st.caption(f"**{r['ticker']}** — {r['avoid_reason']}")
    if result["errors"]:
        st.caption("Not evaluated: " + ", ".join(f"{t} ({e})" for t, e in result["errors"][:8]))


# ── Selftest ────────────────────────────────────────────────────────────────

def _synth(kind: str, n: int = 300, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-06-01", periods=n)
    if kind == "breakout":
        base = np.concatenate([np.linspace(50, 80, 240), np.full(59, 80) + rng.normal(0, 0.4, 59), [86]])
        vol = np.concatenate([np.full(299, 1_000_000), [2_500_000]])
    elif kind == "parabolic":
        base = np.concatenate([np.linspace(50, 60, 289), np.geomspace(60, 220, 10), [210]])
        vol = np.concatenate([np.full(295, 1_000_000), np.linspace(1e6, 8e6, 4), [4_000_000]])
    elif kind == "chop":
        base = 50 + rng.normal(0, 1.5, n).cumsum() * 0.1
        vol = np.full(n, 1_000_000)
    else:
        raise ValueError(kind)
    c = pd.Series(base, index=idx)
    df = pd.DataFrame({"Open": c.shift(1).fillna(c), "Close": c,
                       "High": c * 1.02, "Low": c * 0.98, "Volume": vol}, index=idx)
    df["High"] = df[["Open", "Close", "High"]].max(axis=1); df["Low"] = df[["Open", "Close", "Low"]].min(axis=1)
    return df


def selftest() -> dict:
    f = []
    bo = evaluate("BO", _synth("breakout"), "goldilocks", sector_quadrant="Leading", pe_step=2)
    if bo["card"] is None or bo["side"] != "long":
        f.append(f"breakout in goldilocks should produce a long card: {bo.get('avoid_reason')}")
    # same chart in a hostile regime -> refused, with the regime named
    bo_h = evaluate("BO", _synth("breakout"), "growth_scare", sector_quadrant="Leading", pe_step=2)
    if bo_h["card"] is not None or "CLOSED" not in (bo_h["avoid_reason"] or ""):
        f.append("long breakout in growth_scare must be refused with the regime named")
    ps = evaluate("PS", _synth("parabolic"), "growth_scare", sector_quadrant="Weakening", pe_step=2)
    if ps["card"] is None or ps["side"] != "short":
        f.append(f"parabolic in growth_scare should produce a short card: {ps.get('avoid_reason')}")
    ch = evaluate("CH", _synth("chop"), "goldilocks", sector_quadrant="Leading", pe_step=2)
    if ch["card"] is not None or not ch["avoid_reason"] or "Not a setup" not in ch["avoid_reason"]:
        f.append("chop must be 'Not a setup' with a named reason")
    # heat cap blocks
    blk = evaluate("BO", _synth("breakout"), "goldilocks", sector_quadrant="Leading", pe_step=3, heat_used_pct=14.5)
    if blk["card"] and not blk["card"]["size"]["blocked_by_heat"]:
        f.append("15% heat cap not enforced")
    # concentration cap: tight stop cannot exceed 30% position
    sz = size_position(25_000, 100, 99, 2.0, 1.0, 1.0, 0)
    if sz["position_pct"] > 30.01:
        f.append(f"position {sz['position_pct']}% exceeds 30% concentration cap")
    # PE step 0 = no risk
    z = evaluate("BO", _synth("breakout"), "goldilocks", sector_quadrant="Leading", pe_step=0)
    if z["card"] and z["card"]["size"]["shares"] != 0:
        f.append("PE step 0 must size to zero")
    return {"ok": not f, "failures": f}


if __name__ == "__main__":
    import json
    print(json.dumps(selftest(), indent=2))
