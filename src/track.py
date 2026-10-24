"""Nightly forward tracking: model vs DraftKings closing line (via ESPN's public feed) vs results.
Usage: python track.py 2026-10-24   (run after that day's games finish)
Appends one row per finished game to tracking/log.csv (idempotent by game) and rewrites tracking/summary.json."""
import csv, json, sys, urllib.request
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tracking" / "log.csv"
AB = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL", "UTAH": "UTA", "WAS": "WSH", "MON": "MTL",
      "NAS": "NSH", "CLB": "CBJ", "CAL": "CGY", "VEG": "VGK", "LV": "VGK"}
ESPN = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl"
FIELDS = ["date", "game", "home", "away", "model_p_home", "model_total", "home_goalie", "away_goalie",
          "dk_ml_home", "dk_ml_away", "dk_p_home", "dk_total", "dk_over", "dk_under",
          "home_score", "away_score", "ot", "home_win", "espn_id"]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def implied(o):
    o = float(o)
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def main(day):
    board = json.load(open(ROOT / "out" / f"board_{day}.json"))
    games = {(g["away"], g["home"]): g for g in board["games"]}
    sb = get(f"{ESPN}/scoreboard?dates={day.replace('-', '')}")
    done = set()
    if LOG.exists():
        done = {r["game"] for r in csv.DictReader(open(LOG))}
    rows = []
    for e in sb.get("events", []):
        c = e["competitions"][0]
        st = c["status"]["type"]
        if not st.get("completed"):
            continue
        side = {x["homeAway"]: x for x in c["competitors"]}
        h = AB.get(side["home"]["team"]["abbreviation"], side["home"]["team"]["abbreviation"])
        a = AB.get(side["away"]["team"]["abbreviation"], side["away"]["team"]["abbreviation"])
        g = games.get((a, h))
        key = f"{day} {a}@{h}"
        if g is None or key in done:
            continue
        hs, as_ = int(side["home"]["score"]), int(side["away"]["score"])
        ot = int(c["status"].get("period", 3) > 3)
        dk = {}
        try:
            pc = get(f"{ESPN}/summary?event={e['id']}").get("pickcenter", [])
            p = next((x for x in pc if "draftkings" in x.get("provider", {}).get("name", "").lower()), pc[0] if pc else None)
            if p:
                ml = p.get("moneyline", {})
                mh = ml.get("home", {}).get("close", {}).get("odds") or p["homeTeamOdds"].get("moneyLine")
                ma = ml.get("away", {}).get("close", {}).get("odds") or p["awayTeamOdds"].get("moneyLine")
                ih, ia = implied(mh), implied(ma)
                dk = {"dk_ml_home": mh, "dk_ml_away": ma, "dk_p_home": round(ih / (ih + ia), 4),
                      "dk_total": p.get("overUnder"), "dk_over": p.get("overOdds"), "dk_under": p.get("underOdds")}
        except Exception:
            pass
        rows.append({"date": day, "game": key, "home": h, "away": a, "model_p_home": g["p_home"],
                     "model_total": g["exp_total"], "home_goalie": (g.get("home_goalie") or {}).get("name"),
                     "away_goalie": (g.get("away_goalie") or {}).get("name"), **dk,
                     "home_score": hs, "away_score": as_, "ot": ot, "home_win": int(hs > as_), "espn_id": e["id"]})
    LOG.parent.mkdir(exist_ok=True)
    new = not LOG.exists()
    with open(LOG, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)
    summarize()
    print(f"logged {len(rows)} games for {day}")


def summarize():
    R = list(csv.DictReader(open(LOG)))
    def ll(p, y):
        p = np.clip(np.array(p, float), 1e-6, 1 - 1e-6); y = np.array(y, float)
        return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    both = [r for r in R if r.get("dk_p_home")]
    y = [int(r["home_win"]) for r in both]
    s = {"games": len(R), "games_with_close": len(both),
         "model_logloss": ll([float(r["model_p_home"]) for r in both], y) if both else None,
         "market_logloss": ll([float(r["dk_p_home"]) for r in both], y) if both else None,
         "model_fav_record": f"{sum((float(r['model_p_home']) > .5) == (r['home_win'] == '1') for r in R)}-"
                             f"{sum((float(r['model_p_home']) > .5) != (r['home_win'] == '1') for r in R)}",
         "note": "Log loss: lower is better. Market = DraftKings closing moneyline with vig removed (ESPN feed)."}
    json.dump(s, open(ROOT / "tracking" / "summary.json", "w"), indent=1)
    print(s)


if __name__ == "__main__":
    main(sys.argv[1])
