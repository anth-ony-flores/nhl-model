"""Current missing-regular adjustment. Usage: python injuries.py 2026-10-24 -> out/injuries_<day>.json
Pulls ESPN's injury feed, matches players to MoneyPuck ids, and values regulars ruled out."""
import json, sys, unicodedata, urllib.request
import pandas as pd
from pathlib import Path
from data import fix

ROOT = Path(__file__).resolve().parent.parent
ESPN = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries"
APPLY = {"Out", "Injured Reserve"}      # day-to-day is shown but not applied
ESPN_FIX = {"UTAH": "UTA", "UTH": "UTA", "NJ": "NJD", "SJ": "SJS", "TB": "TBL", "LA": "LAK", "WSH": "WSH"}


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in s if ch.isalnum())


def main(day):
    req = urllib.request.Request(ESPN, headers={"User-Agent": "Mozilla/5.0"})
    feed = json.load(urllib.request.urlopen(req, timeout=20))
    g = pd.read_parquet(ROOT / "data/player_games.parquet")
    cur = g[(g.season == 2026) & (g.gameDate < int(day.replace("-", "")))].sort_values(["gameDate", "gameId"])
    latest = g.sort_values(["gameDate", "gameId"]).groupby("playerId").tail(1).set_index("playerId")
    out = {}
    for t, tg in cur.groupby("team"):
        games = tg.drop_duplicates("gameId").gameId.tolist()[-10:]
        cnt = tg[tg.gameId.isin(games)].playerId.value_counts()
        out[t] = {"regulars": set(cnt[cnt >= 5].index), "names": {}}
    names = {}
    for pid, r in latest.iterrows():
        names.setdefault((norm(r["name"]), r["team"]), pid)
        names.setdefault((norm(r["name"]), None), pid)
    res = {}
    for team in feed["injuries"]:
        for x in team["injuries"]:
            a = x["athlete"]
            ab = a.get("team", {}).get("abbreviation", "")
            ab = fix(ESPN_FIX.get(ab, ab))
            pid = names.get((norm(a["displayName"]), ab)) or names.get((norm(a["displayName"]), None))
            if pid is None or ab not in out:
                continue
            reg = pid in out[ab]["regulars"]
            val = float(latest.loc[pid, "value"]) if pid in latest.index else 0.0
            applied = reg and x["status"] in APPLY
            res.setdefault(ab, []).append({"name": a["displayName"], "status": x["status"], "playerId": int(pid),
                                           "position": str(latest.loc[pid, "position"]), "value": round(val, 4),
                                           "regular": bool(reg), "applied": bool(applied),
                                           "note": x.get("shortComment", "")[:200], "date": x.get("date", "")[:10]})
    summary = {t: {"missing_value": round(sum(p["value"] for p in v if p["applied"]), 4), "players": v} for t, v in res.items()}
    json.dump({"day": day, "source": "ESPN injuries feed", "fetched": pd.Timestamp.now(tz="America/Phoenix").strftime("%Y-%m-%d %H:%M"),
               "k": 1.0, "teams": summary}, open(ROOT / "out" / f"injuries_{day}.json", "w"), indent=1)
    for t, v in sorted(summary.items()):
        ap = [f"{p['name']} {p['value']:+.3f}" for p in v["players"] if p["applied"]]
        if ap:
            print(t, round(v["missing_value"], 3), ap)


if __name__ == "__main__":
    main(sys.argv[1])
