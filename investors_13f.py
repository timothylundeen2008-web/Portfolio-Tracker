"""
investors_13f.py  (v1.0 — 2026-11-23)
──────────────────────────────────────
REFERENCE ONLY, not a signal and not tested. Latest quarterly 13F holdings of two investors Matt
follows (2026-11-23: "add a tab or a reference somewhere that shows the current holdings of Stan
druckenmiller and ray dalio"):

  Duquesne Family Office LLC   (Stanley Druckenmiller)   SEC CIK 1536411
  Bridgewater Associates, LP   (Ray Dalio's firm; Dalio no longer runs it day to day)   SEC CIK 1350694

From SEC EDGAR, using the same polite client as edgar_data (edgar_probe.SEC: contact User-Agent from
the repository secret SEC_CONTACT_EMAIL, never printed; under 10 requests a second).

What a 13F is and is not (shown on the tab):
  * US-listed long equity positions, ETFs and listed options, as of the quarter end;
  * filed up to 45 days AFTER the quarter, so it is 6–20 weeks old when you read it;
  * NO shorts, bonds, futures, currencies or non-US listings. For a macro firm like Bridgewater
    that is a small, possibly misleading slice of the book.

Output: data/investors_13f/summary.json (+ holdings_<cik>_<period>.csv). For each filer: the
latest original 13F-HR and the one before, holdings aggregated by CUSIP + put/call, weights, and
changes (new, exited, added, trimmed by share count). An amendment (13F-HR/A) newer than the latest
original is reported, not merged.

Run:  python investors_13f.py            (Actions, needs secret SEC_CONTACT_EMAIL)
      python investors_13f.py --selftest (offline)
"""
from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

VERSION = "1.0"
FILERS = [
    {"key": "druckenmiller", "cik": 1536411, "name": "Duquesne Family Office LLC", "person": "Stanley Druckenmiller"},
    {"key": "bridgewater", "cik": 1350694, "name": "Bridgewater Associates, LP", "person": "Ray Dalio (founder)"},
]
OUT_DATA = Path("data/investors_13f")
DOLLARS_FROM = "2023-01-03"       # SEC rule: 13F values in dollars from filings on/after this date (before: $ thousands)


def _log(msg: str) -> None:
    print(f"[investors_13f {datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def filings(submissions: dict) -> list:
    """13F-HR and 13F-HR/A rows from an EDGAR submissions JSON ('recent' block), newest first."""
    r = submissions.get("filings", {}).get("recent", {})
    out = []
    for i, form in enumerate(r.get("form", [])):
        if form in ("13F-HR", "13F-HR/A"):
            out.append({"form": form, "accession": r["accessionNumber"][i], "filed": r["filingDate"][i],
                        "period": (r.get("reportDate") or [""] * (i + 1))[i]})
    return sorted(out, key=lambda z: (z["filed"], z["accession"]), reverse=True)


def pick(fs: list) -> tuple:
    """(latest original, the original before it, newer amendments). Originals of distinct periods only."""
    orig = [f for f in fs if f["form"] == "13F-HR"]
    seen, uniq = set(), []
    for f in orig:
        if f["period"] not in seen:
            seen.add(f["period"])
            uniq.append(f)
    latest = uniq[0] if uniq else None
    prev = uniq[1] if len(uniq) > 1 else None
    amends = [f for f in fs if f["form"] == "13F-HR/A" and latest and f["filed"] >= latest["filed"]]
    return latest, prev, amends


def infotable_name(index_json: dict) -> Optional[str]:
    items = index_json.get("directory", {}).get("item", [])
    xmls = [it["name"] for it in items if it.get("name", "").lower().endswith(".xml")
            and it["name"].lower() != "primary_doc.xml"]
    pref = [n for n in xmls if "info" in n.lower() or "13f" in n.lower() or "table" in n.lower()]
    return (pref or xmls or [None])[0]


def _strip(tag: str) -> str:
    return tag.split("}", 1)[-1]


def parse_infotable(xml: bytes, filed: str) -> pd.DataFrame:
    root = ET.fromstring(xml)
    rows = []
    for it in root.iter():
        if _strip(it.tag) != "infoTable":
            continue
        d = {}
        for ch in it.iter():
            t = _strip(ch.tag)
            if ch is not it and ch.text and ch.text.strip():
                d[t] = ch.text.strip()
        rows.append({"issuer": d.get("nameOfIssuer", ""), "class": d.get("titleOfClass", ""),
                     "cusip": d.get("cusip", "").upper(), "value": float(d.get("value", 0) or 0),
                     "shares": float(d.get("sshPrnamt", 0) or 0), "share_type": d.get("sshPrnamtType", ""),
                     "put_call": (d.get("putCall") or "").title()})
    df = pd.DataFrame(rows, columns=["issuer", "class", "cusip", "value", "shares", "share_type", "put_call"])
    if filed < DOLLARS_FROM:
        df["value"] = df["value"] * 1000.0
    return df


def aggregate(df: pd.DataFrame) -> pd.DataFrame:
    """One row per CUSIP + put/call (filers split lines by manager or discretion)."""
    if df.empty:
        return df.assign(weight_pct=[])
    g = (df.groupby(["cusip", "put_call"], as_index=False)
           .agg(issuer=("issuer", "first"), cls=("class", "first"), value=("value", "sum"), shares=("shares", "sum")))
    g = g.rename(columns={"cls": "class"}).sort_values("value", ascending=False).reset_index(drop=True)
    tot = g["value"].sum()
    g["weight_pct"] = (g["value"] / tot * 100).round(2) if tot > 0 else 0.0
    return g


def changes(now: pd.DataFrame, before: Optional[pd.DataFrame]) -> dict:
    if before is None or before.empty:
        return {"new": [], "exited": [], "added": [], "trimmed": []}
    k = lambda d: {(r.cusip, r.put_call): r for r in d.itertuples()}
    a, b = k(now), k(before)
    lab = lambda r: r.issuer + (f" ({r.put_call})" if r.put_call else "")
    new = [{"issuer": lab(r), "weight_pct": r.weight_pct, "value": r.value} for key, r in a.items() if key not in b]
    exited = [{"issuer": lab(r), "prior_weight_pct": r.weight_pct} for key, r in b.items() if key not in a]
    added, trimmed = [], []
    for key, r in a.items():
        if key in b and b[key].shares > 0:
            ch = (r.shares / b[key].shares - 1) * 100
            row = {"issuer": lab(r), "shares_chg_pct": round(ch, 1), "weight_pct": r.weight_pct}
            if ch >= 10:
                added.append(row)
            elif ch <= -10:
                trimmed.append(row)
    srt = lambda xs, f: sorted(xs, key=lambda z: -abs(z[f]))
    return {"new": srt(new, "weight_pct"), "exited": srt(exited, "prior_weight_pct"),
            "added": sorted(added, key=lambda z: -z["weight_pct"]), "trimmed": sorted(trimmed, key=lambda z: -z["weight_pct"])}


def fetch_filer(sec, f: dict) -> dict:
    cik = f["cik"]
    sub = sec.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    if not sub:
        raise RuntimeError(f"no submissions file for {f['name']}")
    fs = filings(json.loads(sub))
    latest, prev, amends = pick(fs)
    if latest is None:
        raise RuntimeError(f"no 13F-HR on file for {f['name']}")

    def table(fl):
        acc = fl["accession"].replace("-", "")
        idx = sec.get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json")
        name = infotable_name(json.loads(idx)) if idx else None
        if not name:
            raise RuntimeError(f"no information table in {fl['accession']}")
        xml = sec.get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{name}")
        if not xml:
            raise RuntimeError(f"information table missing: {fl['accession']}")
        return aggregate(parse_infotable(xml, fl["filed"]))

    now = table(latest)
    before = table(prev) if prev else None
    return {"filer": f, "latest": latest, "previous": prev, "amendments_after": amends, "holdings": now,
            "previous_holdings": before, "changes": changes(now, before)}


def summarise(res: dict, top: int = 25) -> dict:
    h = res["holdings"]
    rows = [{"issuer": r["issuer"], "class": r["class"], "cusip": r["cusip"], "put_call": r["put_call"],
             "value": round(float(r["value"])), "shares": float(r["shares"]), "weight_pct": float(r["weight_pct"])}
            for _i, r in h.head(top).iterrows()]
    top10 = float(h["weight_pct"].head(10).sum()) if len(h) else 0.0
    return {"name": res["filer"]["name"], "person": res["filer"]["person"], "cik": res["filer"]["cik"],
            "period": res["latest"]["period"], "filed": res["latest"]["filed"], "accession": res["latest"]["accession"],
            "previous_period": (res["previous"] or {}).get("period"),
            "amendments_after": [a["accession"] + " filed " + a["filed"] for a in res["amendments_after"]],
            "total_value": round(float(h["value"].sum())), "positions": int(len(h)), "top10_weight_pct": round(top10, 1),
            "options_lines": int((h["put_call"] != "").sum()) if len(h) else 0,
            "top": rows, "changes": {k: v[:15] for k, v in res["changes"].items()},
            "source_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={res['filer']['cik']:010d}&type=13F-HR"}


def main(sec=None, out_data: Path = OUT_DATA) -> int:
    if sec is None:
        import edgar_probe as ep
        try:
            sec = ep.SEC(os.environ.get("SEC_CONTACT_EMAIL", "").strip())
        except ValueError as e:
            print(f"[investors_13f] DATA FAILURE: {e}; nothing written.")
            return 1
    out, raw = {"version": VERSION, "asof": datetime.now(timezone.utc).date().isoformat(), "filers": {}}, {}
    for f in FILERS:
        try:
            _log(f"{f['name']} ...")
            raw[f["key"]] = fetch_filer(sec, f)
            out["filers"][f["key"]] = summarise(raw[f["key"]])
        except Exception as e:
            print(f"[investors_13f] DATA FAILURE: {f['name']}: {type(e).__name__}: {e}; nothing written.")
            return 1
    out_data.mkdir(parents=True, exist_ok=True)
    for k, r in raw.items():
        r["holdings"].to_csv(out_data / f"holdings_{r['filer']['cik']}_{r['latest']['period']}.csv", index=False)
    (out_data / "summary.json").write_text(json.dumps(out, indent=1, default=str))
    for k, s in out["filers"].items():
        print(f"{s['person']} — {s['name']}: period {s['period']} (filed {s['filed']}), {s['positions']} positions, "
              f"${s['total_value'] / 1e9:,.2f}bn, top 10 = {s['top10_weight_pct']}%")
        for r in s["top"][:10]:
            print(f"   {r['weight_pct']:6.2f}%  {r['issuer']} {r['put_call']}")
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def _xml(rows, ns=True):
    n = ' xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable"' if ns else ""
    body = "".join(
        f"<infoTable><nameOfIssuer>{i}</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>{c}</cusip>"
        f"<value>{v}</value><shrsOrPrnAmt><sshPrnamt>{s}</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>"
        + (f"<putCall>{pc}</putCall>" if pc else "") + "<investmentDiscretion>SOLE</investmentDiscretion></infoTable>"
        for i, c, v, s, pc in rows)
    return f'<?xml version="1.0"?><informationTable{n}>{body}</informationTable>'.encode()


def selftest() -> dict:
    import tempfile
    f = []
    x_now = _xml([("NVIDIA CORP", "67066G104", 600, 10, ""), ("NVIDIA CORP", "67066G104", 400, 5, ""),
                  ("ALPHA INC", "000000001", 500, 100, ""), ("SPDR S&amp;P 500", "78462F103", 300, 1, "Put")])
    df = aggregate(parse_infotable(x_now, "2026-11-14"))
    if len(df) != 3 or float(df.loc[df.cusip == "67066G104", "value"].iloc[0]) != 1000:
        f.append("aggregate: lines must merge by CUSIP + put/call")
    if abs(df["weight_pct"].sum() - 100) > 0.05 or df.iloc[0]["issuer"] != "NVIDIA CORP":
        f.append("weights must sum to 100 and sort by value")
    if df.loc[df.cusip == "78462F103", "put_call"].iloc[0] != "Put":
        f.append("put/call kept")
    old = parse_infotable(_xml([("A", "X", 5, 1, "")], ns=False), "2022-11-14")
    if float(old["value"].iloc[0]) != 5000:
        f.append("pre-2023 values are $ thousands")
    x_prev = _xml([("NVIDIA CORP", "67066G104", 800, 20, ""), ("OLD CO", "000000009", 200, 50, "")])
    ch = changes(df, aggregate(parse_infotable(x_prev, "2026-08-14")))
    names = lambda k: [z["issuer"] for z in ch[k]]
    if "ALPHA INC" not in names("new") or "OLD CO" not in names("exited") or "NVIDIA CORP" not in names("trimmed"):
        f.append(f"changes wrong: {ch}")
    subs = {"filings": {"recent": {"form": ["13F-HR/A", "13F-HR", "4", "13F-HR", "13F-HR"],
                                   "accessionNumber": ["a5", "a4", "x", "a2", "a1"],
                                   "filingDate": ["2026-11-20", "2026-11-14", "2026-11-01", "2026-08-14", "2026-05-15"],
                                   "reportDate": ["2026-09-30", "2026-09-30", "", "2026-06-30", "2026-03-31"]}}}
    la, pr, am = pick(filings(subs))
    if la["accession"] != "a4" or pr["accession"] != "a2" or [a["accession"] for a in am] != ["a5"]:
        f.append("pick: latest original, previous original, newer amendments")
    idx = {"directory": {"item": [{"name": "primary_doc.xml"}, {"name": "0001-index.html"}, {"name": "form13f_20260930.xml"}]}}
    if infotable_name(idx) != "form13f_20260930.xml":
        f.append("infotable_name must skip primary_doc.xml")

    class FakeSEC:
        def __init__(self, broken=False):
            self.broken = broken

        def get(self, url):
            if "submissions" in url:
                return json.dumps(subs).encode()
            if url.endswith("index.json"):
                return None if self.broken else json.dumps(idx).encode()
            return x_now if "/a4/" in url else x_prev

    tmp = Path(tempfile.mkdtemp())
    try:
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            rc = main(FakeSEC(), tmp / "d")
        js = json.loads((tmp / "d" / "summary.json").read_text())
        d = js["filers"]["druckenmiller"]
        if rc != 0 or d["period"] != "2026-09-30" or d["positions"] != 3 or d["top"][0]["issuer"] != "NVIDIA CORP":
            f.append(f"main: summary wrong {rc} {d.get('period')} {d.get('positions')}")
        if not d["amendments_after"] or d["top"][0]["class"] != "COM":
            f.append("main: amendment note / class missing")
        with contextlib.redirect_stdout(io.StringIO()):
            rc2 = main(FakeSEC(broken=True), tmp / "e")
        if rc2 != 1 or (tmp / "e").exists():
            f.append("main: a missing table must stop with nothing written")
        with contextlib.redirect_stdout(io.StringIO()):
            os.environ.pop("SEC_CONTACT_EMAIL", None)
            rc3 = main(None, tmp / "g")
        if rc3 != 1 or (tmp / "g").exists():
            f.append("main: no SEC contact must stop with nothing written")
    except Exception as e:
        f.append(f"main crashed: {type(e).__name__}: {e}")
    return {"ok": not f, "failures": f, "version": VERSION}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r_ = selftest()
        print(json.dumps(r_, indent=2))
        sys.exit(0 if r_["ok"] else 1)
    sys.exit(main())
