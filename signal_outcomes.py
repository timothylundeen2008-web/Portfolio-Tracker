"""
signal_outcomes.py  (v1 — July 2026)
──────────────────────────────────────────────────────────────────────────────
DOES THIS FRAMEWORK ACTUALLY WORK?

Every other module in this stack analyzes the present. None of them measure
whether past analysis was correct. After six versions of checklist refinement
the system still cannot answer the only question that ultimately matters, and
that gap has a specific cost:

  Without base rates you cannot distinguish a framework that WORKS and is
  having a normal losing stretch from a framework that DOESN'T work but feels
  rigorous because the process is elaborate.

  Those two states are indistinguishable from the inside, and an elaborate
  process makes the second MORE comfortable, not less likely.

The checklist's own meta-rule — "when the dashboard and your gut disagree, the
dashboard wins" — is only correct if the dashboard has a demonstrated edge.
Right now that is an assumption. This module turns it into a measurement.

HOW IT WORKS
  1. record()   — log a signal the moment it fires, with the price then
  2. evaluate() — later, fetch forward returns at 1/4/12 weeks
  3. base_rates()— hit rate, average magnitude, and expectancy PER SIGNAL TYPE

WHAT TO DO WITH THE OUTPUT
  A signal type with a hit rate near 50% and no magnitude edge is noise, and
  should be dropped from the checklist no matter how sensible its rationale
  sounds. Expect some to fail this test — that is the point. The value is in
  finding out which, rather than carrying all of them forever on the strength
  of their reasoning.

STATISTICAL HONESTY (enforced in the output, not just documented)
  - Under ~20 observations, no hit rate is reported — small samples produce
    confident nonsense and confident nonsense is worse than no number.
  - Benchmark-relative return is reported alongside absolute. A 70% hit rate
    in a bull market where SPY was up 70% of the time is not an edge.
  - Overlapping windows are correlated; treat 30 overlapping observations as
    far fewer independent ones. Flagged in the output.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

STORE = os.environ.get("SIGNAL_LOG", "data/signal_outcomes.csv")
HORIZONS = {"1w": 5, "4w": 21, "12w": 63}     # trading sessions
MIN_SAMPLE = 20                                # below this, no rate is reported

SIGNAL_TYPES = [
    "regime_call",          # classifier named a regime
    "regime_transition",    # regime changed
    "gold_gate_pass",       # gate flipped PASS
    "gold_gate_fail",       # gate flipped FAIL
    "kmlm_increase",        # KMLM stance INCREASE
    "confluence_3of3",      # full-size swing candidate
    "confluence_2of3",      # half-size
    "stealth_flag",         # stealth accumulation flagged
    "flow_divergence",      # price/flow disagreement (Tier A)
    "hy_crisis_override",   # HY OAS tripwire fired
]


# ── Storage ───────────────────────────────────────────────────────────────────

def _load() -> pd.DataFrame:
    if not os.path.exists(STORE):
        return pd.DataFrame(columns=[
            "signal_id", "date", "signal_type", "subject", "direction",
            "price_at_signal", "benchmark_at_signal", "context", "notes"])
    df = pd.read_csv(STORE)
    return df


def _save(df: pd.DataFrame) -> None:
    try:
        os.makedirs(os.path.dirname(STORE) or ".", exist_ok=True)
        df.to_csv(STORE, index=False)
    except Exception as e:
        # Expected on Streamlit Cloud's read-only/ephemeral FS — see GAPS.md G0.
        print(f"[signal_outcomes] write failed: {e}")


def record(signal_type: str, subject: str, direction: str = "long",
           price: float | None = None, benchmark_price: float | None = None,
           context: str = "", notes: str = "",
           when: str | None = None) -> str:
    """
    Log a signal AT THE MOMENT IT FIRES. Recording after the fact — even a few
    days later — contaminates the sample with hindsight and is worse than not
    recording at all.

    subject:   ticker or regime key the signal is about
    direction: 'long' | 'short' | 'neutral' — how the signal says to lean
    """
    if signal_type not in SIGNAL_TYPES:
        print(f"[signal_outcomes] warning: unknown type {signal_type!r}")
    d = when or date.today().isoformat()
    sid = f"{d}_{signal_type}_{subject}".replace(" ", "")
    df = _load()
    df = df[df["signal_id"] != sid] if not df.empty else df   # idempotent
    row = {"signal_id": sid, "date": d, "signal_type": signal_type,
           "subject": subject, "direction": direction,
           "price_at_signal": price, "benchmark_at_signal": benchmark_price,
           "context": context, "notes": notes}
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    _save(df)
    return sid


# ── Evaluation ────────────────────────────────────────────────────────────────

def _fetch_series(tickers: list[str], start: str) -> pd.DataFrame:
    try:
        import yfinance as yf
        raw = yf.download(tickers, start=start, interval="1d",
                          auto_adjust=True, progress=False, threads=True, timeout=40)
        return raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    except Exception as e:
        print(f"[signal_outcomes] fetch failed: {e}")
        return pd.DataFrame()


def evaluate(benchmark: str = "SPY") -> pd.DataFrame:
    """
    Compute forward returns for every logged signal whose horizon has elapsed.

    Returns absolute AND benchmark-relative returns. Relative is the one that
    matters: a signal that "worked" by returning +6% while SPY returned +8%
    identified a laggard, not an opportunity.
    """
    df = _load()
    if df.empty:
        return pd.DataFrame()

    subjects = sorted({s for s in df["subject"].dropna().unique()
                       if isinstance(s, str) and s.isupper() and len(s) <= 5})
    if not subjects:
        return df.assign(**{f"ret_{h}": np.nan for h in HORIZONS})

    earliest = min(df["date"])
    px = _fetch_series(list(set(subjects + [benchmark])), earliest)
    if px.empty:
        return df

    rows = []
    for _, r in df.iterrows():
        out = dict(r)
        sub = r["subject"]
        if sub not in px.columns:
            rows.append(out)
            continue
        s = px[sub].dropna()
        b = px[benchmark].dropna() if benchmark in px.columns else pd.Series(dtype=float)
        try:
            sig_dt = pd.Timestamp(r["date"])
            idx = s.index.searchsorted(sig_dt)
            if idx >= len(s):
                rows.append(out)
                continue
            p0 = float(s.iloc[idx])
            b0 = float(b.iloc[b.index.searchsorted(sig_dt)]) if len(b) else np.nan

            for h, sessions in HORIZONS.items():
                j = idx + sessions
                if j >= len(s):
                    out[f"ret_{h}"] = np.nan
                    out[f"rel_{h}"] = np.nan
                    continue
                ret = (float(s.iloc[j]) / p0 - 1) * 100
                out[f"ret_{h}"] = round(ret, 2)
                if len(b) and not np.isnan(b0):
                    jb = b.index.searchsorted(sig_dt) + sessions
                    if jb < len(b):
                        bret = (float(b.iloc[jb]) / b0 - 1) * 100
                        out[f"rel_{h}"] = round(ret - bret, 2)
        except Exception:
            pass
        rows.append(out)
    return pd.DataFrame(rows)


def base_rates(benchmark: str = "SPY", horizon: str = "4w") -> pd.DataFrame:
    """
    THE OUTPUT THAT MATTERS: per-signal-type hit rate and expectancy.

    Columns:
      n            observations with an elapsed horizon
      hit_rate     % where the RELATIVE return went the signal's way
      avg_rel      mean benchmark-relative return
      med_rel      median (less distorted by one outlier)
      expectancy   avg_rel — the honest per-signal edge estimate
      verdict      plain-language read, with sample-size honesty enforced
    """
    ev = evaluate(benchmark)
    col = f"rel_{horizon}"
    if ev.empty or col not in ev.columns:
        return pd.DataFrame()

    out = []
    for stype, g in ev.groupby("signal_type"):
        g = g[g[col].notna()]
        n = len(g)
        if n == 0:
            continue
        sign = g["direction"].map({"long": 1, "short": -1}).fillna(1)
        adj = g[col] * sign
        hit = float((adj > 0).mean() * 100)
        rec = {"signal_type": stype, "n": n,
               "hit_rate": round(hit, 1) if n >= MIN_SAMPLE else None,
               "avg_rel": round(float(adj.mean()), 2),
               "med_rel": round(float(adj.median()), 2),
               "expectancy": round(float(adj.mean()), 2)}
        if n < MIN_SAMPLE:
            rec["verdict"] = f"INSUFFICIENT — {n}/{MIN_SAMPLE} obs, no rate reported"
        elif hit >= 60 and adj.mean() > 0.5:
            rec["verdict"] = "EDGE — keep and consider sizing up"
        elif hit <= 45 or adj.mean() < -0.5:
            rec["verdict"] = "NEGATIVE — candidate for removal from the checklist"
        else:
            rec["verdict"] = "NOISE — no demonstrated edge; keep logging or drop"
        out.append(rec)

    df = pd.DataFrame(out).sort_values("expectancy", ascending=False)
    return df


def coverage() -> dict:
    """Honest status: how far from being able to say anything at all."""
    df = _load()
    if df.empty:
        return {"signals": 0, "ready": False,
                "message": "No signals logged. Base rates need calendar time to "
                           "accumulate — there is no shortcut and no way to "
                           "backfill this. Start logging today."}
    by_type = df.groupby("signal_type").size().to_dict()
    ready = {k: v for k, v in by_type.items() if v >= MIN_SAMPLE}
    oldest = min(df["date"])
    weeks = (date.today() - datetime.strptime(oldest, "%Y-%m-%d").date()).days / 7
    return {
        "signals": len(df), "by_type": by_type,
        "types_ready": list(ready), "weeks_of_history": round(weeks, 1),
        "ready": bool(ready),
        "message": (f"{len(ready)} signal type(s) have {MIN_SAMPLE}+ observations. "
                    if ready else
                    f"No signal type has {MIN_SAMPLE}+ observations yet. ")
                   + "NOTE: overlapping horizons are correlated — 30 overlapping "
                     "observations are worth far fewer independent ones. Treat "
                     "early readings as directional, not conclusive.",
    }


def auto_record_from_assessment(assessment: dict, prev_regime: str | None = None) -> list[str]:
    """
    Convenience: log the signals a weekly run produces, straight from
    full_assessment(). Call this from the checklist tab's weekly commit so
    recording happens automatically at the moment the signal fires rather
    than depending on discipline.
    """
    ids = []
    regime = (assessment.get("regime") or {}).get("key")
    if regime:
        ids.append(record("regime_call", regime, "neutral",
                          context=f"score={((assessment.get('repression') or {}).get('score'))}"))
        if prev_regime and prev_regime != regime:
            ids.append(record("regime_transition", regime, "neutral",
                              context=f"from {prev_regime}"))
    gate = assessment.get("gold_gate")
    if gate is not None:
        ids.append(record("gold_gate_pass" if gate else "gold_gate_fail",
                          "GLD", "long" if gate else "short"))
    kmlm = (assessment.get("kmlm") or {}).get("stance", "")
    if "INCREASE" in str(kmlm).upper():
        ids.append(record("kmlm_increase", "KMLM", "long", context=str(kmlm)))
    sig = assessment.get("signals") or {}
    hy = sig.get("hy_oas")
    if hy is not None and hy > 5.0:
        ids.append(record("hy_crisis_override", "HYG", "short", context=f"HY OAS {hy}"))
    return ids
