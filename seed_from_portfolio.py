"""
seed_from_portfolio.py  (v1 — July 2026)
──────────────────────────────────────────────────────────────────────────────
Seeds position_ledger.py from the classifier's own target_weights() output,
so the heat/drift/stop machinery has real starting positions instead of one
manually-typed test ticker.

WHAT THIS SEEDS, AND WHAT IT DELIBERATELY DOES NOT
  This uses target_weights(current_regime) — the FULL MECHANICAL overlay,
  exactly what the code computes with no judgment layered on top.

  It does NOT encode any "staged" or "deferred" position sizing from a past
  review. A staged posture (e.g., holding growth adds back pending a Tier-A
  flow confirmation per Weekly Step 5) is a JUDGMENT CALL made on a specific
  day's evidence — it has no place hardcoded into a module that will be reused
  indefinitely across regimes this specific judgment never saw. Baking a past
  conversation's opinion into code as if it were a system output is exactly
  the class of staleness this whole build has been correcting (see: the
  README weight drift, the false volume-methodology claim). If you're
  deliberately deferring some legs, seed normally, then edit or remove those
  specific positions afterward — the ledger doesn't know about that
  intention, and shouldn't pretend to.

STOPS
  No structural (chart-based) stop exists here — that requires a human to
  look at a chart. Each seeded stop is `entry - ATR_MULTIPLE * ATR(14)`, a
  standard, honest placeholder, explicitly labeled `stop_basis="ATR-placeholder"`
  so it's never mistaken for a real structural stop in the Weekly Step 7
  review. Replace it with a real swing-low/structure stop before trusting
  Daily Step 6's "within 1 ATR" check for anything that matters.

INVALIDATION SENTENCES
  Weekly Step 7 requires one per position, enforced by add_position() itself.
  SLEEVE_INVALIDATIONS below gives each a real, mechanism-based default drawn
  from the actual classifier/checklist logic for that sleeve (not a generic
  placeholder) — but they are GENERIC across regimes, not tied to any one
  day's numbers, specifically so this file doesn't go stale the way a
  snapshot-specific version would.

THIS IS A SIMULATION OF THE MODEL PORTFOLIO, NOT YOUR BROKERAGE ACCOUNT
  Seeded share counts are back-solved from a typed-in equity figure and
  today's price — they represent "if I held exactly the model weights," not
  your real fills, real cost basis, or real share count. The whole reason a
  ledger exists (vs. slider weights) is to measure ACTUAL drift — replace
  seeded rows with your real numbers as you actually execute, or this
  degrades back into the same "drift is zero by construction" problem the
  ledger was built to fix.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

ATR_MULTIPLE = 2.0          # entry - 2×ATR(14) as the placeholder stop
FALLBACK_STOP_PCT = 0.08    # used only if ATR can't be computed (thin history)

# Generic, mechanism-based invalidations — regime-agnostic on purpose (see
# module docstring). Ticker not listed here gets a generic regime-change
# fallback rather than a blank rejection from add_position().
SLEEVE_INVALIDATIONS: dict[str, str] = {
    "GLD":  "the short real policy rate re-crosses negative, or the gold "
            "momentum gate (GLD vs rising 200d MA) flips PASS",
    "SLV":  "the gold gate flips PASS and silver's own trend confirms",
    "RING": "the gold gate flips PASS and miners show an RRG hook from Lagging",
    "XLE":  "the weekly RRG rolls to Weakening, or energy re-spikes on renewed "
            "geopolitical/supply risk",
    "PDBC": "the same trigger as XLE — commodities move together on the "
            "inflation-impulse read",
    "SCHD": "defensives show Weakening on the weekly RRG, or the regime "
            "reverts toward inflationary_repression",
    "XLV":  "the same trigger as SCHD — defensive-equity de-rating",
    "XLU":  "DFII10 momentum flips positive on two closes (removes the rate-"
            "relief case) or defensives roll to Weakening",
    "SGOV": "growth adds confirm on Tier-A flow evidence and capital drains "
            "toward VGT/QQQ, or a liquidity-crisis override arms it as "
            "rebalance ammunition",
    "USFR": "FOMC language kills the near-term hike/cut tail this position "
            "is priced for",
    "TLT":  "DFII10 closes back above 2.50%, reversing the re-arm case",
    "KMLM": "60-day stock/bond correlation confirms below -0.30 (overlay and "
            "live signal converge), or the live kmlm_signal() stance itself rolls",
    "VGT":  "the regime reverts toward inflationary_repression/hard_repression, "
            "or the weekly RRG confirms Weakening with volume",
    "SMH":  "same trigger as VGT — highest-beta growth expression, cut first "
            "on any reversal",
    "QQQ":  "same trigger as VGT — broadest, least concentrated growth sleeve, "
            "cut last on any reversal",
}

DEFAULT_INVALIDATION = ("the current regime classification changes, or the "
                        "sleeve's target weight in target_weights() moves "
                        "outside the ±20% drift band")


def _fetch_prices_and_atr(tickers: list[str]) -> dict[str, dict]:
    """
    One batched OHLCV pull for every ticker being seeded.

    Returns {ticker: {"price": float, "atr": float|None}}. A ticker with a
    failed fetch or too little history for ATR(14) gets atr=None, NOT a
    fabricated number — the caller falls back to FALLBACK_STOP_PCT instead of
    silently sizing a stop off missing data.
    """
    out = {}
    try:
        import yfinance as yf
    except ImportError:
        print("[seed] yfinance unavailable — cannot fetch prices")
        return out

    try:
        raw = yf.download(tickers, period="60d", interval="1d", auto_adjust=True,
                          progress=False, threads=True, timeout=30)
    except Exception as e:
        print(f"[seed] batch download failed: {e}")
        return out

    for tk in tickers:
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                lvl0 = set(raw.columns.get_level_values(0))
                if "Close" in lvl0:
                    df = pd.DataFrame({"High": raw["High"][tk], "Low": raw["Low"][tk],
                                       "Close": raw["Close"][tk]}).dropna()
                else:
                    df = raw[tk][["High", "Low", "Close"]].dropna()
            else:
                df = raw[["High", "Low", "Close"]].dropna()
            if df.empty:
                continue
            price = float(df["Close"].iloc[-1])

            atr_val = None
            if len(df) >= 15:
                h, l, c = df["High"], df["Low"], df["Close"]
                pc = c.shift(1)
                tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
                a = float(tr.rolling(14).mean().iloc[-1])
                atr_val = a if a == a else None   # NaN guard

            out[tk] = {"price": price, "atr": atr_val}
        except Exception as e:
            print(f"[seed] {tk}: {e}")
            continue
    return out


def preview(equity: float, regime_key: str | None = None,
           existing_tickers: list[str] | None = None) -> dict:
    """
    Compute what WOULD be seeded, without writing anything.

    Always call this before seed(). Returns rows for every sleeve with a
    non-zero target weight, plus which ones would be skipped because a
    position with that ticker already exists (unless overwrite is requested
    at seed() time) — so nothing is overwritten by surprise.
    """
    try:
        from regime_classifier import full_assessment, target_weights
    except ImportError as e:
        return {"ok": False, "error": f"regime_classifier not importable: {e}"}

    if regime_key is None:
        try:
            a = full_assessment("")
            regime_key = (a.get("regime") or {}).get("key")
        except Exception as e:
            return {"ok": False, "error": f"Could not determine current regime: {e}"}
    if not regime_key:
        return {"ok": False, "error": "No regime key available — pass one explicitly."}

    try:
        weights = target_weights(regime_key)
    except Exception as e:
        return {"ok": False, "error": f"target_weights('{regime_key}') failed: {e}"}

    tickers = [t for t, w in weights.items() if w and w > 0]
    if not tickers:
        return {"ok": False, "error": f"No positive weights for regime '{regime_key}'."}

    data = _fetch_prices_and_atr(tickers)
    existing = set(t.upper() for t in (existing_tickers or []))

    rows = []
    for tk in tickers:
        w = weights[tk]
        d = data.get(tk)
        row = {"ticker": tk, "target_weight_pct": round(w, 2),
              "already_in_ledger": tk.upper() in existing}
        if not d:
            row.update(price=None, shares=None, stop=None, stop_basis="—",
                       status="NO PRICE DATA — will be skipped")
            rows.append(row)
            continue

        price = d["price"]
        shares = round((equity * w / 100.0) / price, 4)
        if d["atr"]:
            stop = round(price - ATR_MULTIPLE * d["atr"], 2)
            basis = f"ATR-placeholder ({ATR_MULTIPLE}x14-day)"
        else:
            stop = round(price * (1 - FALLBACK_STOP_PCT), 2)
            basis = f"pct-placeholder ({FALLBACK_STOP_PCT:.0%}, ATR unavailable)"

        row.update(price=round(price, 2), shares=shares, stop=stop, stop_basis=basis,
                   invalidation=SLEEVE_INVALIDATIONS.get(tk, DEFAULT_INVALIDATION),
                   status="will OVERWRITE existing" if row["already_in_ledger"]
                          else "will add")
        rows.append(row)

    df = pd.DataFrame(rows)
    return {"ok": True, "regime_key": regime_key, "equity": equity,
            "table": df, "n_priced": int(df["price"].notna().sum()),
            "n_total": len(df),
            "n_conflicts": int(df["already_in_ledger"].sum())}


def seed(equity: float, regime_key: str | None = None,
         overwrite_existing: bool = False) -> dict:
    """
    Actually write the seeded positions. Always preview() first — this
    function does not ask twice.

    Tickers already present in the ledger are SKIPPED unless
    overwrite_existing=True, so re-running this never silently clobbers a
    real position you've since edited by hand.
    """
    from position_ledger import load_positions, add_position

    existing = load_positions()
    existing_tickers = existing["ticker"].tolist() if not existing.empty else []

    pv = preview(equity, regime_key, existing_tickers)
    if not pv["ok"]:
        return pv

    added, skipped, failed = [], [], []
    for _, r in pv["table"].iterrows():
        tk = r["ticker"]
        # BUG FIX: preview() sets price=None for an unpriced row, but pandas
        # silently upcasts that to NaN (a float) the moment the column also
        # holds real float prices elsewhere — so `r.get("price") is None` is
        # ALWAYS False here, and every unpriced row was falling through into
        # add_position() carrying a NaN invalidation, crashing on
        # `invalidation.strip()`. pd.isna() is the correct check for a value
        # pulled from a DataFrame row.
        if pd.isna(r.get("price")):
            failed.append(tk)
            continue
        if r["already_in_ledger"] and not overwrite_existing:
            skipped.append(tk)
            continue
        res = add_position(tk, r["shares"], r["price"], r["stop"],
                           r["invalidation"], stop_basis=r["stop_basis"],
                           sleeve=tk, thesis=f"Seeded from target_weights('{pv['regime_key']}')")
        (added if res["ok"] else failed).append(tk)

    return {"ok": True, "regime_key": pv["regime_key"], "equity": equity,
            "added": added, "skipped_existing": skipped, "failed": failed,
            "message": (f"Seeded {len(added)} position(s) for regime "
                        f"'{pv['regime_key']}'."
                        + (f" Skipped {len(skipped)} already in the ledger "
                           f"(re-run with overwrite to replace them)." if skipped else "")
                        + (f" {len(failed)} failed (no price data): {failed}." if failed else ""))}
