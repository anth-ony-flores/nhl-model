"""One-off: rebuild morning locks for past days from git history and regrade every tracked game against
DraftKings' opening line. Lock for a game = the earliest committed board snapshot generated before puck drop."""
import json, subprocess, sys
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import track

def git(*a):
    return subprocess.run(["git", *a], capture_output=True, text=True, cwd=ROOT).stdout

log = pd.read_csv(ROOT / "tracking" / "log.csv")
days = sorted(log.date.unique())
for day in days:
    f = f"out/board_{day}.json"
    locks = {}
    lp = ROOT / "out" / f"lock_{day}.json"
    if lp.exists():
        locks = json.load(open(lp))["games"]
    for sha in [x for x in git("log", "--reverse", "--format=%H", "--", f).split() if x]:
        try:
            b = json.loads(git("show", f"{sha}:{f}"))
        except ValueError:
            continue
        gen = pd.Timestamp(b["generated"].replace(" MST", "")).tz_localize("America/Phoenix").tz_convert("UTC")
        for g in b["games"]:
            k = str(g["id"])
            if k in locks or g.get("frozen") or "totals" not in g:
                continue
            if gen < pd.Timestamp(g["start_utc"]):
                locks[k] = {"home": g["home"], "away": g["away"], "locked": b["generated"], "p_home": g["p_home"],
                            "exp_total": g["exp_total"], "totals": g["totals"], "puck_line": g["puck_line"],
                            "home_goalie": (g.get("home_goalie") or {}).get("name"), "away_goalie": (g.get("away_goalie") or {}).get("name"),
                            "backfilled": True}
    json.dump({"day": day, "games": locks, "backfilled_from": "git history of " + f}, open(lp, "w"), indent=1, default=float)
    track.track(day, locks=locks, redo=True)
