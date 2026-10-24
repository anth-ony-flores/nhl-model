"""Nightly tracking: model picks vs DraftKings closing lines (ESPN public feed), graded on final scores.
Usage: python track.py 2026-10-24   (run after that day's games finish; safe to rerun)
- tracking/log.csv: one row per finished game (idempotent by game key)
- tracking/summary.json: record by market, strong-edge subset, last 7 days, moneyline log loss
- site/data/record.json: summary + every graded pick, for the Pages site"""
import csv, json, sys, urllib.request
from datetime import date, timedelta
from pathlib import Path
import numpy as np
from picks import norm_odds, make_picks, grade, novig, STRONG, movement

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tracking" / "log.csv"
AB = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL", "UTAH": "UTA", "WAS": "WSH", "MON": "MTL",
      "NAS": "NSH", "CLB": "CBJ", "CAL": "CGY", "VEG": "VGK", "LV": "VGK"}
ESPN = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl"
MKTS = ["su", "ml", "pl", "tot"]
NAMES = {"su": "Straight up", "ml": "Moneyline", "pl": "Puck line", "tot": "Total"}
FIELDS = (["date", "game", "espn_id", "away", "home", "away_score", "home_score", "final_type",
           "model_p_home", "model_total", "away_goalie", "home_goalie",
           "dk_ml_away", "dk_ml_home", "dk_p_home", "dk_pl_home_line", "dk_pl_home_odds", "dk_pl_away_odds",
           "dk_total", "dk_over", "dk_under"]
          + [f"{m}_{k}" for m in MKTS for k in (["pick", "result"] if m == "su" else ["pick", "odds", "edge", "model_p", "market_p", "result", "units", "open_odds", "open_p", "clv"])])


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fix(a):
    return AB.get(a, a)


def read_log():
    return list(csv.DictReader(open(LOG))) if LOG.exists() else []


def write_log(rows):
    LOG.parent.mkdir(exist_ok=True)
    rows = sorted(rows, key=lambda r: (r["date"], r["game"]))
    with open(LOG, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def track(day, board=None, scoreboard=None, summaries=None):
    """board/scoreboard/summaries can be injected for tests; otherwise read from disk and ESPN."""
    board = board or json.load(open(ROOT / "out" / f"board_{day}.json"))
    games = {(g["away"], g["home"]): g for g in board["games"]}
    sb = scoreboard or get(f"{ESPN}/scoreboard?dates={day.replace('-', '')}")
    existing = {r["game"]: r for r in read_log()}
    added = 0
    for e in sb.get("events", []):
        c = e["competitions"][0]
        if not c["status"]["type"].get("completed"):
            continue
        side = {x["homeAway"]: x for x in c["competitors"]}
        H, A = fix(side["home"]["team"]["abbreviation"]), fix(side["away"]["team"]["abbreviation"])
        g = games.get((A, H))
        key = f"{day} {A}@{H}"
        if g is None or key in existing:
            continue
        hs, as_ = int(side["home"]["score"]), int(side["away"]["score"])
        detail = c["status"]["type"].get("detail", "")
        ftype = "SO" if "SO" in detail else ("OT" if "OT" in detail else "REG")
        s = (summaries or {}).get(e["id"]) or get(f"{ESPN}/summary?event={e['id']}")
        pc = s.get("pickcenter") or []
        p = next((x for x in pc if "draftkings" in (x.get("provider") or {}).get("name", "").lower()), pc[0] if pc else None)
        o = norm_odds(p)
        P = grade(make_picks(g, o) if o else {"su": make_picks(g, None)["su"], "ml": None, "pl": None, "tot": None}, hs, as_)
        r = {"date": day, "game": key, "espn_id": e["id"], "away": A, "home": H, "away_score": as_, "home_score": hs,
             "final_type": ftype, "model_p_home": g["p_home"], "model_total": g["exp_total"],
             "away_goalie": (g.get("away_goalie") or {}).get("name"), "home_goalie": (g.get("home_goalie") or {}).get("name"),
             "su_pick": P["su"]["pick"], "su_result": P["su"]["result"]}
        if o:
            r.update({"dk_ml_away": o["ml"]["away"], "dk_ml_home": o["ml"]["home"],
                      "dk_p_home": round(novig(o["ml"]["home"], o["ml"]["away"]), 4) if novig(o["ml"]["home"], o["ml"]["away"]) is not None else "",
                      "dk_pl_home_line": o["spread"]["home"]["line"], "dk_pl_home_odds": o["spread"]["home"]["odds"],
                      "dk_pl_away_odds": o["spread"]["away"]["odds"], "dk_total": o["total"]["line"],
                      "dk_over": o["total"]["over"], "dk_under": o["total"]["under"]})
        MV = movement(p, P) if o else {}
        for m in ("ml", "pl", "tot"):
            x = P.get(m)
            if x:
                for k in ("pick", "odds", "edge", "model_p", "market_p", "result", "units"):
                    r[f"{m}_{k}"] = x[k]
                for k, v in MV.get(m, {}).items():
                    r[f"{m}_{k}"] = v
        existing[key] = r
        added += 1
    write_log(list(existing.values()))
    summary = summarize(list(existing.values()))
    print(f"{day}: logged {added} new games, {len(existing)} total")
    return summary


def rec(rows, m, strong=False):
    W = L = Pu = 0; units = 0.0
    for r in rows:
        if not r.get(f"{m}_result"):
            continue
        if strong and float(r.get(f"{m}_edge") or 0) < STRONG:
            continue
        res = r[f"{m}_result"]
        W += res == "W"; L += res == "L"; Pu += res == "P"
        if m != "su":
            units += float(r.get(f"{m}_units") or 0)
    n = W + L + Pu
    out = {"w": W, "l": L, "p": Pu, "pct": round(W / (W + L), 4) if W + L else None}
    if m != "su":
        out.update({"units": round(units, 2), "roi": round(units / n, 4) if n else None})
    return out


def rec_all(rows, strong=False):
    """Combined record across moneyline, puck line and total (optionally strong-edge picks only)."""
    parts = [rec(rows, m, strong=strong) for m in ("ml", "pl", "tot")]
    W = sum(x["w"] for x in parts); L = sum(x["l"] for x in parts); Pu = sum(x["p"] for x in parts)
    u = round(sum(x["units"] for x in parts), 2); n = W + L + Pu
    return {"w": W, "l": L, "p": Pu, "pct": round(W / (W + L), 4) if W + L else None, "units": u,
            "roi": round(u / n, 4) if n else None}


def clv_stats(rows, m, strong=False):
    """Closing line value: how the market moved on the picked side between DraftKings' open and close."""
    v = [float(r[f"{m}_clv"]) for r in rows if r.get(f"{m}_clv") not in (None, "")
         and (not strong or float(r.get(f"{m}_edge") or 0) >= STRONG)]
    if not v:
        return {"n": 0, "avg_pts": None, "beat_close_pct": None}
    return {"n": len(v), "avg_pts": round(100 * sum(v) / len(v), 2),
            "beat_close_pct": round(sum(x > 0 for x in v) / len(v), 4)}


def summarize(rows):
    rows = sorted(rows, key=lambda r: (r["date"], r["game"]))
    last = max((r["date"] for r in rows), default=None)
    recent = [r for r in rows if last and r["date"] >= (date.fromisoformat(last) - timedelta(days=6)).isoformat()]
    both = [r for r in rows if r.get("dk_p_home") not in (None, "")]
    def ll(ps, ys):
        p = np.clip(np.array(ps, float), 1e-6, 1 - 1e-6); y = np.array(ys, float)
        return round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4)
    ys = [int(int(r["home_score"]) > int(r["away_score"])) for r in both]
    S = {"updated": last, "games": len(rows),
         "record": {m: rec(rows, m) for m in MKTS},
         "strong": {m: rec(rows, m, strong=True) for m in ("ml", "pl", "tot")},
         "last7": {m: rec(recent, m) for m in MKTS},
         "logloss": {"games": len(both),
                     "model": ll([float(r["model_p_home"]) for r in both], ys) if both else None,
                     "market": ll([float(r["dk_p_home"]) for r in both], ys) if both else None},
         "rules": "One pick per market per game. Graded against DraftKings closing lines from ESPN's public feed; "
                  "1 unit risked per pick at the closing odds. Strong edge = 3.0 points or more.",
         "clv": {m: clv_stats(rows, m) for m in ("ml", "pl", "tot")},
         "clv_strong": {m: clv_stats(rows, m, strong=True) for m in ("ml", "pl", "tot")},
         "all_picks": rec_all(rows), "strong_all": rec_all(rows, strong=True),
         "names": NAMES}
    (ROOT / "tracking").mkdir(exist_ok=True)
    json.dump(S, open(ROOT / "tracking" / "summary.json", "w"), indent=1)
    picks = []
    for r in reversed(rows):
        for m in MKTS:
            if not r.get(f"{m}_pick"):
                continue
            picks.append({"date": r["date"], "game": f"{r['away']} at {r['home']}",
                          "final": f"{r['away']} {r['away_score']}, {r['home']} {r['home_score']}" + ("" if r["final_type"] == "REG" else f" ({r['final_type']})"),
                          "market": m, "pick": r[f"{m}_pick"], "odds": r.get(f"{m}_odds") or None,
                          "edge": float(r[f"{m}_edge"]) if r.get(f"{m}_edge") else None,
                          "strong": bool(r.get(f"{m}_edge")) and float(r[f"{m}_edge"]) >= STRONG,
                          "result": r[f"{m}_result"], "units": float(r[f"{m}_units"]) if r.get(f"{m}_units") not in (None, "") else None,
                          "open_odds": r.get(f"{m}_open_odds") or None,
                          "clv": float(r[f"{m}_clv"]) if r.get(f"{m}_clv") not in (None, "") else None})
    site = ROOT / "site" / "data"
    site.mkdir(parents=True, exist_ok=True)
    json.dump({"summary": S, "picks": picks}, open(site / "record.json", "w"))
    return S


if __name__ == "__main__":
    track(sys.argv[1])
