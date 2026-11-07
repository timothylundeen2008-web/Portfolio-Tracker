"""
model_vs_spy.py — the model portfolio's REAL track record against SPY and 60/40.

Source of truth is data/model_book.csv (the NAV the circuit breaker, the brief
and the Model Portfolio panel all use). It is NOT the static-weight backtest on
the Overview tab. SPY and AGG come from the same dividend-adjusted closes the
model book itself is marked with, so nothing is double-counted. 60/40 is the
brief's definition: 60% SPY / 40% AGG, rebalanced daily.

Display only - never a rule input.
"""
from __future__ import annotations
import pandas as pd


def build_frame(book: pd.DataFrame, spy: pd.Series, agg: pd.Series | None = None):
    """Return (frame, info). frame columns: Model, SPY, [60/40], all = 100 at the
    book's first date. info: first_live date, stats dict. None if SPY has no bar
    on the first book date (same guard as daily_brief._model_benchmarks)."""
    b = book.assign(date=pd.to_datetime(book["date"]).dt.normalize()).sort_values("date")
    b = b.drop_duplicates("date", keep="last").set_index("date")
    d0 = b.index[0]

    def _clean(s):
        s = pd.Series(s).astype(float).dropna()
        if getattr(s.index, "tz", None) is not None:
            s.index = s.index.tz_localize(None)
        s.index = pd.to_datetime(s.index).normalize()
        return s[~s.index.duplicated(keep="last")]

    spy = _clean(spy)
    if spy.empty or d0 not in spy.index:
        return None, {}
    idx = b.index.intersection(spy.index)
    f = pd.DataFrame(index=idx)
    f["Model"] = b.loc[idx, "nav"] / float(b.loc[d0, "nav"]) * 100
    f["SPY"] = spy.loc[idx] / float(spy.loc[d0]) * 100
    if agg is not None:
        agg = _clean(agg)
        if not agg.empty and d0 in agg.index:
            r = (0.6 * spy.pct_change() + 0.4 * agg.pct_change()).reindex(idx).fillna(0.0)
            f["60/40"] = (1 + r).cumprod() * 100
    live = b.index[b["source"].astype(str).str.lower() == "live"] if "source" in b else []
    first_live = live[0] if len(live) else None

    def _dd(s):
        return float((s / s.cummax() - 1).min() * 100)

    stats = {"since": d0.date().isoformat(), "last": idx[-1].date().isoformat(), "n": len(idx),
             "n_reconstructed": int((b["source"].astype(str).str.lower() != "live").sum()) if "source" in b else 0}
    for c in f.columns:
        stats[c] = {"ret": float(f[c].iloc[-1] - 100), "maxdd": _dd(f[c])}
        if first_live is not None and first_live in f.index:
            base = float(f.loc[first_live, c])
            stats[c]["ret_live"] = float(f[c].iloc[-1] / base * 100 - 100)
    return f, {"first_live": first_live, "stats": stats}
