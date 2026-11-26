"""NHL official game roster reports -> out/roster_<day>.json. Usage: python roster.py 2026-11-27

Source: https://www.nhl.com/scores/htmlreports/<season>/RO<6-digit game number>.HTM, one per game.
The report has two columns, away team left and home team right. Once the final lineup is filed it
marks the starting lineup in bold (including the starting goalie) and adds a Scratches section.
Before that it can list a provisional roster, so nothing is used until the Scratches section appears.

Per team: lineup_posted, starter (NHL player id + name, bold goalie), dressed goalies, scratches with
MoneyPuck player id, regular flag and on/off value (same definitions as injuries.py), and dressed names.
board.py applies starters as confirmed goalies, scratched regulars as missing, and lifts an injury
adjustment for any player who is dressed. props_lines.py drops scratched players."""
import json, re, sys, urllib.request, unicodedata
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
API = "https://api-web.nhle.com/v1"
RO = "https://www.nhl.com/scores/htmlreports/{season}/RO{num}.HTM"
ROW = re.compile(r'<td align="center"[^>]*class="([^"]*)">([^<]*)</td>\s*<td align="center"[^>]*>([^<]*)</td>\s*'
                 r'<td align="left"[^>]*>([^<]*)</td>')
COL = re.compile(r'<td (?:valign="top"|align="center") width="50%" class="border">')


def get(url, as_json=True):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=30).read()
    return json.loads(raw) if as_json else raw.decode("latin-1")


def norm(s):
    s = re.sub(r"\((C|A)\)", "", s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in s if ch.isalnum())


def rows(block):
    return [{"bold": "bold" in c, "num": n.strip(), "pos": p.strip(), "name": re.sub(r"\s+", " ", re.sub(r"\((C|A)\)", "", nm)).strip().title()}
            for c, n, p, nm in ROW.findall(block)]


def parse(h):
    """-> (away, home) dicts with dressed rows and scratches, or None if the layout is not recognised."""
    i_s, i_c = h.find('id="Scratches"'), h.find("Head Coaches")
    head = h[:i_s if i_s > 0 else i_c]
    cols = COL.split(head)[1:]
    if len(cols) < 2:
        return None
    dressed = [rows(c) for c in cols[-2:]]
    scr = [[], []]
    if i_s > 0:
        sc = COL.split(h[i_s:i_c])[1:]
        if len(sc) >= 2:
            scr = [rows(c) for c in sc[:2]]
    return [{"dressed": dressed[k], "scratches": scr[k]} for k in (0, 1)], i_s > 0


def main(day):
    sched = get(f"{API}/schedule/{day}")
    games = next((d["games"] for d in sched["gameWeek"] if d["date"] == day), [])
    pg = pd.read_parquet(ROOT / "data/player_games.parquet")
    cur = pg[(pg.season == pg.season.max()) & (pg.gameDate < int(day.replace("-", "")))].sort_values(["gameDate", "gameId"])
    latest = pg.sort_values(["gameDate", "gameId"]).groupby("playerId").tail(1).set_index("playerId")
    regulars, by_name = {}, {}
    for t, tg in cur.groupby("team"):
        last10 = tg.drop_duplicates("gameId").gameId.tolist()[-10:]
        cnt = tg[tg.gameId.isin(last10)].playerId.value_counts()
        regulars[t] = set(cnt[cnt >= 5].index)
    for pid, r in latest.iterrows():
        by_name.setdefault((norm(r["name"]), r["team"]), pid)
    out = {}
    for g in games:
        gid = str(g["id"]); season = f"{gid[:4]}{int(gid[:4]) + 1}"
        A, H = g["awayTeam"]["abbrev"], g["homeTeam"]["abbrev"]
        try:
            h = get(RO.format(season=season, num=gid[4:]), as_json=False)
            res = parse(h)
        except Exception as e:  # report not posted yet (404) or unreachable
            res = None
        for k, team in ((0, A), (1, H)):
            rec = {"game_id": int(gid), "opp": H if k == 0 else A, "home": k == 1, "lineup_posted": False,
                   "starter": None, "dressed_goalies": [], "scratches": [], "dressed": []}
            if res:
                sides, posted = res
                s = sides[k]
                rec["lineup_posted"] = bool(posted and (s["scratches"] or any(r["bold"] for r in s["dressed"])))
                if rec["lineup_posted"]:
                    try:
                        gl = {norm(f"{p['firstName']['default']} {p['lastName']['default']}"): (p["id"], f"{p['firstName']['default']} {p['lastName']['default']}")
                              for p in get(f"{API}/roster/{team}/current")["goalies"]}
                    except Exception:
                        gl = {}
                    for r in s["dressed"]:
                        if r["pos"] == "G":
                            gid_, nm = gl.get(norm(r["name"]), (None, r["name"]))
                            rec["dressed_goalies"].append({"id": gid_, "name": nm, "starter": r["bold"]})
                            if r["bold"] and gid_:
                                rec["starter"] = {"id": int(gid_), "name": nm}
                    rec["dressed"] = [r["name"] for r in s["dressed"]]
                    for r in s["scratches"]:
                        pid = by_name.get((norm(r["name"]), team))
                        rec["scratches"].append({"name": str(latest.loc[pid, "name"]) if pid is not None else r["name"], "pos": r["pos"],
                                                 "playerId": int(pid) if pid is not None else None,
                                                 "regular": bool(pid in regulars.get(team, set())) if pid is not None else False,
                                                 "value": round(float(latest.loc[pid, "value"]), 4) if pid is not None else 0.0})
            out[team] = rec
    js = {"day": day, "source": "NHL official game roster reports (nhl.com/scores/htmlreports)",
          "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "teams": out}
    json.dump(js, open(ROOT / "out" / f"roster_{day}.json", "w"), indent=1)
    for t, r in sorted(out.items()):
        if r["lineup_posted"]:
            print(t, "starter:", (r["starter"] or {}).get("name"), "| scratched regulars:",
                  [f"{x['name']} {x['value']:+.3f}" for x in r["scratches"] if x["regular"]])
    print(f"{sum(r['lineup_posted'] for r in out.values())}/{len(out)} teams with a posted lineup")


if __name__ == "__main__":
    main(sys.argv[1])
