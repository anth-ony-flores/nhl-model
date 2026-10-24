"""Inject a board JSON into the HTML template. Usage: python build_page.py 2026-10-24"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
day = sys.argv[1]
DETAIL = sys.argv[2].split(",") if len(sys.argv) > 2 else "ALL"
data = json.load(open(ROOT / "out" / f"board_{day}.json"))
import urllib.request
sp = ROOT / "out" / f"summaries_{day}.json"
S = json.load(open(sp)) if sp.exists() else {}
try:
    req = urllib.request.Request(f"https://api-web.nhle.com/v1/standings/{day}", headers={"User-Agent": "Mozilla/5.0"})
    st = json.load(urllib.request.urlopen(req, timeout=20))["standings"]
    REC = {x["teamAbbrev"]["default"]: f"{x['wins']}-{x['losses']}-{x['otLosses']}" for x in st}
except Exception:
    REC = {}
for g in data["games"]:
    k = f"{g['away']}@{g['home']}"
    g["summary"] = S.get(k, {}).get("text")
    g["sources"] = S.get(k, {}).get("sources", [])
    g["home_rec"], g["away_rec"] = REC.get(g["home"], ""), REC.get(g["away"], "")
rank = {r["team"]: i + 1 for i, r in enumerate(data["ratings"])}
for g in data["games"]:
    g["home_rank"], g["away_rank"] = rank.get(g["home"]), rank.get(g["away"])
mp = ROOT / "out" / f"metrics_{day}.json"
if mp.exists():
    MT = json.load(open(mp))
    playing = {g["home"] for g in data["games"]} | {g["away"] for g in data["games"]}
    data["metrics"] = {"defs": MT["metrics"], "n": MT["n_teams"], "through": MT["data_through"],
                       "teams": {t: v for t, v in MT["teams"].items() if t in playing}}
data["detail_games"] = DETAIL
tpl = (ROOT / "src" / "template.html").read_text()
html = tpl.replace("/*DATA*/", json.dumps(data, default=float).replace("</", "<\\/"))
(ROOT / "out" / "nhl_board.html").write_text(html)
print("wrote", ROOT / "out" / "nhl_board.html", len(html))
