"""
rc_probe.py  (v1.0 — 2026-11-28)
────────────────────────────────
Data probe for the regime classifier replay (strategy plan item 4, fix_status N11). Looks at NO
returns and decides nothing: it reports, for every input the classifier reads, how far back the
history goes and whether it can be had point-in-time. Run once by hand.

Questions it answers:
  1. Full HY / IG OAS history. FRED cut the ICE BofA series to a rolling 3 years in April 2026.
     Does an ALFRED snapshot from before the cut (realtime 2026-03-31, then 2025-12-31) still return
     the full history back to 1996? Sanity checks: HY OAS on 2008-12-15 (~21.8%) and the 2007 low (~2.4%).
  2. Proxy credit spreads with long history (Moody's BAA10Y, AAA10Y), in case 1 fails.
  3. First date of every other FRED input, and the first ALFRED vintage of the revised series
     (growth composite, CPI SA), which says from when a point-in-time replay is possible.
  4. CAPE history from free sources (Yale / Shiller file, a datahub mirror) — also a candidate fix for N95.
  5. First price date of every Balanced sleeve and guard ticker (yfinance).

The FRED key is read from FRED_API_KEY and never printed (every message is scrubbed).
Run:  python rc_probe.py            (Actions)
      python rc_probe.py --selftest (offline)
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

VERSION = "1.0.1"
OUT_DIR, LOG_DIR = Path("data/rc_probe"), Path("logs/rc_probe")
FRED = "https://api.stlouisfed.org/fred"
SERIES = {"DFF": "fed funds (short real rate)", "CPIAUCNS": "CPI NSA (YoY)", "CPIAUCSL": "CPI SA (3m, 1m)",
          "DFII10": "10y real yield", "T10YIE": "10y breakeven", "DGS10": "10y nominal", "DGS2": "2y nominal",
          "DTWEXBGS": "broad dollar (current)", "DTWEXB": "broad dollar (old, discontinued)",
          "BAMLH0A0HYM2": "HY OAS", "BAMLC0A0CM": "IG OAS", "BAA10Y": "Moody's BAA − 10y (proxy)",
          "AAA10Y": "Moody's AAA − 10y (proxy)", "PAYEMS": "payrolls (growth)", "ICSA": "initial claims (growth)",
          "RSAFS": "retail sales (growth)", "UMCSENT": "sentiment (growth)"}
VINTAGE = ["PAYEMS", "ICSA", "RSAFS", "UMCSENT", "CPIAUCSL"]
SNAPSHOTS = ["2026-03-31", "2025-12-31"]
CAPE_URLS = {"yale_shiller_xls": "http://www.econ.yale.edu/~shiller/data/ie_data.xls",
             "datahub_sp500_csv": "https://datahub.io/core/s-and-p-500/r/data.csv"}
TICKERS = ["VGT", "SMH", "QQQ", "GLD", "SLV", "RING", "XLE", "PDBC", "SCHD", "XLV", "XLU", "SGOV", "USFR",
           "TLT", "KMLM", "DBMF", "SCHP", "SPY", "XLY", "XLI", "XLF", "XLP", "BIL", "SHV"]


def _log(m: str) -> None:
    print(f"[rc_probe {datetime.now(timezone.utc):%H:%M:%S}] {m}", flush=True)


def scrub(text: str, secret: str) -> str:
    return str(text).replace(secret, "***") if secret else str(text)


CORE = ("DFF", "CPIAUCNS", "DFII10", "DGS10", "DGS2", "BAMLH0A0HYM2")


class ClientError(Exception):
    """A 4xx reply: the request itself is refused, so it is not retried. Carries FRED's error_message."""


def http_get(url: str) -> bytes:
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research; portfolio-tracker rc_probe)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        msg = ""
        try:
            body = e.read().decode("utf-8", "replace")
            try:
                msg = json.loads(body).get("error_message") or body[:200]
            except Exception:
                msg = body[:200]
        except Exception:
            pass
        if 400 <= e.code < 500:
            raise ClientError(f"HTTP {e.code}: {msg}") from None
        raise RuntimeError(f"HTTP {e.code}: {msg}") from None


def get_retry(get: Callable, url: str, secret: str, tries: int = 3, pause: float = 5.0) -> bytes:
    last = None
    for i in range(tries):
        try:
            return get(url)
        except ClientError as e:
            raise RuntimeError(scrub(f"refused: {e}", secret)) from None
        except Exception as e:
            last = e
            if i < tries - 1 and pause:
                time.sleep(pause * (i + 1))
    raise RuntimeError(scrub(f"{type(last).__name__}: {last}", secret)) from None


def obs_series(raw: bytes) -> pd.Series:
    j = json.loads(raw.decode("utf-8"))
    if "observations" not in j:
        raise RuntimeError(f"no observations ({j.get('error_message') or list(j)[:4]})")
    o = j["observations"]
    return pd.Series(pd.to_numeric([x["value"] for x in o], errors="coerce"),
                     index=pd.to_datetime([x["date"] for x in o])).dropna()


def describe(s: pd.Series) -> dict:
    if s is None or not len(s):
        return {"ok": False, "n": 0}
    return {"ok": True, "first": str(s.index[0].date()), "last": str(s.index[-1].date()), "n": int(len(s))}


def probe_fred(get: Callable, key: str, pause: float = 5.0) -> dict:
    out = {}
    for sid, what in SERIES.items():
        url = f"{FRED}/series/observations?series_id={sid}&observation_start=1900-01-01&file_type=json&api_key={key}"
        try:
            out[sid] = {"what": what, **describe(obs_series(get_retry(get, url, key, pause=pause)))}
        except Exception as e:
            out[sid] = {"what": what, "ok": False, "error": scrub(e, key)[:200]}
    return out


def probe_snapshots(get: Callable, key: str, pause: float = 5.0) -> dict:
    out = {}
    for sid in ("BAMLH0A0HYM2", "BAMLC0A0CM"):
        out[sid] = {}
        for day in SNAPSHOTS:
            url = (f"{FRED}/series/observations?series_id={sid}&observation_start=1990-01-01&realtime_start={day}"
                   f"&realtime_end={day}&file_type=json&api_key={key}")
            try:
                s = obs_series(get_retry(get, url, key, pause=pause)).sort_index()
                d = describe(s)
                if sid == "BAMLH0A0HYM2" and len(s):
                    near = s[(s.index >= "2008-12-10") & (s.index <= "2008-12-19")]   # within 3 sessions
                    d["on_2008_12_15"] = round(float(near.iloc[(abs(near.index - pd.Timestamp("2008-12-15"))).argmin()]), 2) \
                        if len(near) else None
                    s07 = s[(s.index >= "2007-01-01") & (s.index <= "2007-12-31")]
                    d["min_2007"] = round(float(s07.min()), 2) if len(s07) else None
                    d["full_history"] = bool(s.index[0] <= pd.Timestamp("1997-12-31") and len(s) > 6500
                                             and d["on_2008_12_15"] is not None and 18 <= d["on_2008_12_15"] <= 25
                                             and d["min_2007"] is not None and 1.8 <= d["min_2007"] <= 3.2)
                out[sid][day] = d
            except Exception as e:
                out[sid][day] = {"ok": False, "error": scrub(e, key)[:200]}
    return out


def probe_vintages(get: Callable, key: str, pause: float = 5.0) -> dict:
    out = {}
    for sid in VINTAGE:
        url = f"{FRED}/series/vintagedates?series_id={sid}&file_type=json&limit=10000&api_key={key}"
        try:
            j = json.loads(get_retry(get, url, key, pause=pause).decode("utf-8"))
            v = j.get("vintage_dates") or []
            out[sid] = {"ok": bool(v), "first_vintage": v[0] if v else None, "n_vintages": len(v),
                        "count_reported": j.get("count")}
        except Exception as e:
            out[sid] = {"ok": False, "error": scrub(e, key)[:200]}
    return out


def probe_cape(get: Callable, pause: float = 5.0) -> dict:
    out = {}
    for name, url in CAPE_URLS.items():
        try:
            raw = get_retry(get, url, "", pause=pause)
            d = {"ok": False, "bytes": len(raw)}
            if name == "datahub_sp500_csv":
                try:
                    df = pd.read_csv(io.BytesIO(raw))
                    col = next((c for c in df.columns if c.strip().upper() in ("PE10", "CAPE")), None)
                    d["columns"] = list(df.columns)[:12]
                    if col:
                        s = pd.Series(pd.to_numeric(df[col], errors="coerce").to_numpy(),
                                      index=pd.to_datetime(df[df.columns[0]], errors="coerce")).dropna()
                        s = s[s.index.notna()]
                        if len(s) > 100:
                            d.update({"ok": True, "cape": describe(s), "last_value": round(float(s.iloc[-1]), 2)})
                    if not d["ok"]:
                        d["error"] = "no usable PE10/CAPE column"
                except Exception as e:
                    d["error"] = f"not a CSV: {str(e)[:120]}"
            else:
                d["ok"] = raw[:4] == b"\xd0\xcf\x11\xe0" or raw[:2] == b"PK"   # .xls / .xlsx signature
                d["note"] = ("Excel file fetched; parsing left to the replay build" if d["ok"]
                             else f"not an Excel file (starts {raw[:30]!r})")
            out[name] = d
        except Exception as e:
            out[name] = {"ok": False, "error": str(e)[:200]}
    return out


def probe_prices(download: Optional[Callable] = None) -> dict:
    out = {}
    if download is None:
        try:
            import yfinance as yf
        except Exception as e:
            return {"_error": f"yfinance not importable: {e}"}

        def download(t):
            for i in range(3):
                try:
                    df = yf.Ticker(t).history(period="max", auto_adjust=True)
                    if df is not None and len(df):
                        return df["Close"]
                except Exception:
                    pass
                time.sleep(3 * (i + 1))
            return None
    for t in TICKERS:
        try:
            s = download(t)
            s = None if s is None else pd.Series(s).dropna()
            if s is not None and len(s):
                s.index = pd.to_datetime(s.index).tz_localize(None) if getattr(s.index, "tz", None) else pd.to_datetime(s.index)
            out[t] = describe(s)
        except Exception as e:
            out[t] = {"ok": False, "error": str(e)[:200]}
    return out


def failures(r: dict) -> list:
    """Core inputs the probe could not read at all (a failed fetch is not a finding)."""
    bad = [f"FRED {sid}: {r['fred'].get(sid, {}).get('error', 'missing')}" for sid in CORE
           if not r["fred"].get(sid, {}).get("ok")]
    snaps = r["snapshots"].get("BAMLH0A0HYM2", {})
    if snaps and all("error" in d for d in snaps.values()):
        bad.append("every HY OAS snapshot request failed: " + "; ".join(d["error"] for d in snaps.values()))
    if "_error" in r["prices"]:
        bad.append(r["prices"]["_error"])
    elif all(not (isinstance(d, dict) and d.get("ok")) for d in r["prices"].values()):
        bad.append("no ticker prices at all")
    return bad


def verdict(r: dict) -> list:
    """Plain statements of what the replay can and cannot do, from the probe alone."""
    v = []
    snap = r["snapshots"].get("BAMLH0A0HYM2", {})
    full = next((d for d in snap.values() if d.get("full_history")), None)
    if snap and all("error" in d for d in snap.values()):
        v.append("HY OAS full history UNKNOWN: the snapshot requests failed (" +
                 "; ".join(d["error"] for d in snap.values())[:300] + ").")
    elif full:
        v.append(f"HY OAS full history AVAILABLE via an ALFRED snapshot ({full['first']} → {full['last']}, "
                 f"2008-12-15 = {full['on_2008_12_15']}%): the replay can use the classifier's own credit input.")
    else:
        cur = r["fred"].get("BAMLH0A0HYM2", {})
        v.append(f"HY OAS full history NOT available (current series {cur.get('first')} → {cur.get('last')}; "
                 "snapshots failed or truncated): the replay needs a proxy or a file, and every credit threshold "
                 "would have to be restated — weaker evidence.")
    dfii = r["fred"].get("DFII10", {})
    if dfii.get("ok"):
        v.append(f"Earliest possible replay start is set by DFII10 ({dfii['first']}) plus the 63-session momentum "
                 "and the 200-day gates, i.e. about one year later.")
    gs = ("PAYEMS", "ICSA", "RSAFS", "UMCSENT")
    gerr = [s for s in gs if "error" in r["vintages"].get(s, {})]
    gv = [s for s in gs if r["vintages"].get(s, {}).get("ok") and (r["vintages"][s].get("first_vintage") or "9999") <= "2005-01-01"]
    if gerr:
        v.append(f"Growth vintages UNKNOWN for {', '.join(gerr)} (request failed); vintages from 2005 or earlier: "
                 f"{', '.join(gv) or 'none'}.")
    else:
        v.append(f"Growth series with ALFRED vintages from 2005 or earlier: {', '.join(gv) or 'none'} — "
                 + ("a point-in-time growth composite is possible." if len(gv) >= 3 else
                    "the growth composite would be replayed on revised data (flagged)."))
    cape = [k for k, d in r["cape"].items() if d.get("ok")]
    v.append(f"CAPE sources usable: {', '.join(cape) or 'none'}.")
    if "_error" in r["prices"]:
        v.append(f"Sleeve start dates UNKNOWN ({r['prices']['_error']}).")
    else:
        unread = [t for t, d in r["prices"].items() if not (isinstance(d, dict) and d.get("ok"))]
        late = sorted((d["first"], t) for t, d in r["prices"].items() if isinstance(d, dict) and d.get("ok"))
        late = [f"{t} {f}" for f, t in late if f > "2006-01-01"]
        v.append("Sleeves that start after 2006 (need a stand-in or start later): " + (", ".join(late) or "none")
                 + (f". UNREAD (fetch failed): {', '.join(unread)}" if unread else ""))
    return v


def render(r: dict, stamp: str) -> str:
    L = [f"# Regime classifier replay — data probe {VERSION} — {stamp}", "",
         "Looks at no returns and decides nothing. Research, not personalized advice.", "", "## What it means"]
    L += [f"- {x}" for x in r["verdict"]]
    L += ["", "## FRED inputs (current API)", "| Series | What | First | Last | N | Note |", "|---|---|---|---|---|---|"]
    for sid, d in r["fred"].items():
        L.append(f"| {sid} | {d.get('what')} | {d.get('first', '—')} | {d.get('last', '—')} | {d.get('n', 0)} | "
                 f"{d.get('error', '')} |")
    L += ["", "## ALFRED snapshots (before the April 2026 cut)", "| Series | Snapshot | First | Last | N | 2008-12-15 | 2007 low | Full |",
          "|---|---|---|---|---|---|---|---|"]
    for sid, days in r["snapshots"].items():
        for day, d in days.items():
            L.append(f"| {sid} | {day} | {d.get('first', '—')} | {d.get('last', '—')} | {d.get('n', 0)} | "
                     f"{d.get('on_2008_12_15', '—')} | {d.get('min_2007', '—')} | {d.get('full_history', '—')} "
                     f"{d.get('error', '')} |")
    L += ["", "## Point-in-time (ALFRED vintages)", "| Series | First vintage | Vintages | Note |", "|---|---|---|---|"]
    for sid, d in r["vintages"].items():
        L.append(f"| {sid} | {d.get('first_vintage', '—')} | {d.get('n_vintages', 0)} | {d.get('error', '')} |")
    L += ["", "## CAPE sources", "| Source | Reached | Detail |", "|---|---|---|"]
    for k, d in r["cape"].items():
        det = d.get("error") or json.dumps({x: d[x] for x in d if x not in ("ok",)}, default=str)[:300]
        L.append(f"| {k} | {d.get('ok')} | {det} |")
    L += ["", "## Prices (yfinance, first date)", "| Ticker | First | Last | N |", "|---|---|---|---|"]
    for t, d in r["prices"].items():
        if isinstance(d, dict):
            L.append(f"| {t} | {d.get('first', '—')} | {d.get('last', '—')} | {d.get('n', 0)} |")
        else:
            L.append(f"| {t} | {d} | | |")
    L += ["", f"*rc_probe.py {VERSION}*"]
    return "\n".join(L) + "\n"


def run(get: Callable = http_get, key: Optional[str] = None, download: Optional[Callable] = None,
        pause: float = 5.0) -> dict:
    key = os.environ.get("FRED_API_KEY", "").strip() if key is None else key
    if not key:
        raise RuntimeError("FRED_API_KEY is not set: the probe needs the FRED API (ALFRED snapshots and vintages)")
    _log("FRED series ..."); fred = probe_fred(get, key, pause)
    _log("ALFRED snapshots ..."); snaps = probe_snapshots(get, key, pause)
    _log("ALFRED vintages ..."); vint = probe_vintages(get, key, pause)
    _log("CAPE sources ..."); cape = probe_cape(get, pause)
    _log("prices ..."); px = probe_prices(download)
    r = {"version": VERSION, "fred": fred, "snapshots": snaps, "vintages": vint, "cape": cape, "prices": px}
    r["verdict"] = verdict(r)
    r["failures"] = failures(r)
    return r


def write(r: dict, stamp: str, key: str = "") -> str:
    md = render(r, stamp)
    js = json.dumps(r, indent=1, default=str)
    if key and (key in md or key in js):
        raise RuntimeError("refusing to write: the FRED key appears in the output")
    OUT_DIR.mkdir(parents=True, exist_ok=True); LOG_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "summary.json").write_text(js)
    (LOG_DIR / "latest.md").write_text(md)
    (LOG_DIR / f"{stamp}.md").write_text(md)
    return md


def main(**kw) -> int:
    key = os.environ.get("FRED_API_KEY", "").strip() if "key" not in kw else kw.pop("key")
    try:
        r = run(key=key, **kw)
        stamp = datetime.now(timezone.utc).date().isoformat()
        if r["failures"]:
            print(scrub(render(r, stamp), key))
            print("[rc_probe] DATA FAILURE — core inputs could not be read, nothing written:\n- "
                  + scrub("\n- ".join(r["failures"]), key))
            return 1
        print(write(r, stamp, key))
    except Exception as e:
        print(f"[rc_probe] FAILED: {scrub(f'{type(e).__name__}: {e}', key)}")
        return 1
    return 0


def selftest() -> dict:
    import tempfile
    f, KEY, viol = [], "SECRETKEY123", []
    idx = pd.bdate_range("1996-12-31", "2026-11-25")

    def obs(dates, vals):
        return json.dumps({"observations": [{"date": str(d.date()), "value": str(v)} for d, v in zip(dates, vals)]}).encode()

    def hy_full(d):
        return 21.82 if d == pd.Timestamp("2008-12-15") else (2.41 if d.year == 2007 else 4.0)

    def fake_get(url):
        if "stlouisfed" in url and KEY not in url:
            viol.append(url)
        if "vintagedates" in url:
            return json.dumps({"vintage_dates": ["1999-06-04", "2000-01-07"], "count": 2}).encode()
        if "series_id=BAMLH0A0HYM2" in url and "realtime_start=2026-03-31" in url:
            return obs(idx[::-1], [hy_full(d) for d in idx[::-1]])          # unsorted on purpose
        if "series_id=BAMLH0A0HYM2" in url and "realtime_start=2025-12-31" in url:
            raise ClientError("HTTP 400: Bad Request.  The series does not exist in ALFRED but may exist in FRED.")
        if "series_id=BAMLH0A0HYM2" in url or "series_id=BAMLC0A0CM" in url:
            return obs(idx[-750:], [3.0] * 750)
        if "series_id=DFII10" in url:
            return obs(idx[idx >= "2003-01-02"], [1.0] * int((idx >= "2003-01-02").sum()))
        if "series_id=" in url:
            return obs(idx[:50], [1.0] * 50)
        if "datahub" in url:
            rows = "\n".join(f"{d.date()},100,{20 + (k % 10)}" for k, d in enumerate(pd.date_range("1881-01-01", "2023-09-01", freq="MS")))
            return ("Date,SP500,PE10\n1871-01-01,4.44,\n" + rows + "\n").encode()
        raise OSError("refused")
    tz = pd.bdate_range("2004-01-02", "2026-11-25", tz="America/New_York")
    px = {t: pd.Series(1.0, index=pd.bdate_range("2004-01-02" if t != "SGOV" else "2020-05-28", "2026-11-25"))
          for t in TICKERS}
    px["SPY"] = pd.Series(1.0, index=tz)                                    # tz-aware, as yfinance returns
    r = run(get=fake_get, key=KEY, download=lambda t: px[t], pause=0)
    if viol:
        f.append(f"every FRED request must carry the key ({len(viol)} did not)")
    h = r["snapshots"]["BAMLH0A0HYM2"]["2026-03-31"]
    if not h.get("full_history") or h.get("min_2007") != 2.41 or h.get("on_2008_12_15") != 21.82:
        f.append(f"a full snapshot (unsorted reply) must be recognised ({h})")
    e = r["snapshots"]["BAMLH0A0HYM2"]["2025-12-31"]
    if e.get("ok") is not False or KEY in json.dumps(e) or "does not exist in ALFRED" not in e.get("error", ""):
        f.append(f"a refused snapshot must keep FRED's message, key scrubbed ({e})")
    if not r["verdict"][0].startswith("HY OAS full history AVAILABLE"):
        f.append("verdict must say the full history is available")
    if r["prices"]["SPY"].get("first") != "2004-01-02":
        f.append("tz-aware prices")
    if "SGOV 2020-05-28" not in r["verdict"][-1] or "UNREAD" in r["verdict"][-1]:
        f.append("late sleeves must be listed")
    if r["cape"]["datahub_sp500_csv"].get("last_value") != 20 + ((len(pd.date_range("1881-01-01", "2023-09-01", freq="MS")) - 1) % 10) \
            or r["cape"]["yale_shiller_xls"].get("ok"):
        f.append(f"CAPE: parse the mirror; report the refused source ({r['cape']})")
    if r["failures"]:
        f.append(f"a clean run has no failures ({r['failures']})")
    # http_get keeps FRED's error_message from a 400 reply (urllib raises before the body is read)
    import urllib.error
    import urllib.request
    old_open = urllib.request.urlopen

    def raise_400(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {},
                                     io.BytesIO(b'{"error_code":400,"error_message":"Bad Request.  The series does not exist in ALFRED."}'))
    try:
        urllib.request.urlopen = raise_400
        try:
            http_get("https://api.stlouisfed.org/fred/x?api_key=" + KEY)
            f.append("http_get must raise on a 400")
        except ClientError as ce:
            if "does not exist in ALFRED" not in str(ce) or KEY in str(ce):
                f.append(f"http_get must keep FRED's error_message without the key ({ce})")
        except Exception as ce:
            f.append(f"a 400 must raise ClientError, not {type(ce).__name__}")
    finally:
        urllib.request.urlopen = old_open
    # a refused 4xx is not retried
    calls = []

    def once(url):
        calls.append(url)
        raise ClientError("HTTP 400: Bad Request")
    try:
        get_retry(once, "u", "", tries=3, pause=0)
    except RuntimeError:
        pass
    if len(calls) != 1:
        f.append("4xx replies must not be retried")
    # snapshots that are truncated, or full-looking with gaps, must NOT count as full
    gap = idx[(idx <= "2000-12-31") | (idx >= "2023-01-01")].append(pd.DatetimeIndex(["2008-12-12"])).sort_values()

    def snap_get(dates):
        def g(url):
            if "BAMLH0A0HYM2" in url and "realtime_start" in url:
                return obs(dates, [hy_full(d) if d != pd.Timestamp("2008-12-12") else 21.0 for d in dates])
            return fake_get(url)
        return g
    for lab, dates in (("3-year", idx[-750:]), ("gapped", gap)):
        r2 = run(get=snap_get(dates), key=KEY, download=lambda t: px[t], pause=0)
        if any(d.get("full_history") for d in r2["snapshots"]["BAMLH0A0HYM2"].values()) or \
                not r2["verdict"][0].startswith("HY OAS full history NOT available"):
            f.append(f"a {lab} snapshot must not count as full history")
    # an HTML page is not a CAPE source
    def html_get(url):
        if "yale" in url or "datahub" in url:
            return b"<html>Moved</html>"
        return fake_get(url)
    r3 = run(get=html_get, key=KEY, download=lambda t: px[t], pause=0)
    if any(d.get("ok") for d in r3["cape"].values()) or "usable: none" not in " ".join(r3["verdict"]):
        f.append("an HTML reply must not count as a CAPE source")
    # everything refused (bad key): a data failure, exit 1, nothing written, no false findings
    def deny(url):
        if "stlouisfed" in url:
            raise ClientError("HTTP 400: Bad Request.  The value for variable api_key is not registered.")
        return fake_get(url)
    r4 = run(get=deny, key=KEY, download=lambda t: px[t], pause=0)
    if not r4["failures"] or not r4["verdict"][0].startswith("HY OAS full history UNKNOWN") or \
            "UNKNOWN" not in " ".join(r4["verdict"]):
        f.append("a refused FRED must read as UNKNOWN / failure, not as a finding")
    r5 = run(get=fake_get, key=KEY, download=lambda t: None, pause=0)
    if not r5["failures"] or "9999" in " ".join(r5["verdict"]):
        f.append("no prices at all must be a failure, never a late-start list")
    # no key -> refuse; outputs never contain the key; main exit codes
    try:
        run(get=fake_get, key="", download=lambda t: px[t], pause=0)
        f.append("no key must stop the probe")
    except RuntimeError:
        pass
    cwd = os.getcwd()
    tmp = tempfile.mkdtemp()
    try:
        os.chdir(tmp)
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc_bad = main(get=deny, key=KEY, download=lambda t: px[t], pause=0)
        if rc_bad != 1 or Path("data/rc_probe").exists() or KEY in buf.getvalue():
            f.append("a data failure must exit 1, write nothing, and print no key")
        with contextlib.redirect_stdout(io.StringIO()):
            rc_ok = main(get=fake_get, key=KEY, download=lambda t: px[t], pause=0)
        if rc_ok != 0 or KEY in Path("data/rc_probe/summary.json").read_text() or KEY in Path("logs/rc_probe/latest.md").read_text():
            f.append("a clean run must exit 0 and never write the key")
        bad = dict(r); bad["note"] = KEY
        try:
            write(bad, "2026-11-28", KEY)
            f.append("write must refuse output that contains the key")
        except RuntimeError:
            pass
    finally:
        os.chdir(cwd)
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        out = selftest()
        print(json.dumps(out, indent=2))
        sys.exit(0 if out["ok"] else 1)
    sys.exit(main())
