"""Projections for an upcoming date. Usage: python board.py 2026-10-24"""
import json, sys, urllib.request
import numpy as np
import pandas as pd
from pathlib import Path
from model import (team_rows, DayIndex, fit_ratings, shrunk_ratio, xg_pred, game_probs, p_over)

ROOT = Path(__file__).resolve().parent.parent
DATA, OUT = ROOT / "data", ROOT / "out"
API = "https://api-web.nhle.com/v1"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (personal NHL model)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def american(p):
    if p <= 0 or p >= 1:
        return None
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def main(day):
    D = pd.Timestamp(day)
    prev = (D - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    P = json.load(open(OUT / "params.json"))
    C = json.load(open(OUT / "dist_calib.json")); S = json.load(open(OUT / "share.json"))
    P["dist"] = C["dist"]
    games = pd.read_parquet(DATA / "games.parquet")
    gl = pd.read_parquet(DATA / "goalies.parquet")
    data_through = games.date.max()

    sched = get(f"{API}/schedule/{day}")
    todays = next((d["games"] for d in sched["gameWeek"] if d["date"] == day), [])
    ydays = get(f"{API}/score/{prev}")["games"]

    # yesterday's teams and starters (may not be in MoneyPuck yet)
    played_prev, y_start = set(), {}
    for g in ydays:
        for side in ["homeTeam", "awayTeam"]:
            played_prev.add(g[side]["abbrev"])
        try:
            bx = get(f"{API}/gamecenter/{g['id']}/boxscore")["playerByGameStats"]
            for side in ["homeTeam", "awayTeam"]:
                for gg in bx[side]["goalies"]:
                    if gg.get("starter"):
                        y_start[g[side]["abbrev"]] = gg["playerId"]
        except Exception:
            pass

    rows = team_rows(games)
    DI = DayIndex(list(games.date) + [D])
    rows["di"] = rows.date.map(DI.of)
    gl["di"] = gl.date.map(DI.of)
    gl["gsax"] = gl.xga - gl.ga
    rows["shoot"] = rows.goals - rows.xg_raw
    teams = sorted(set(rows.team) | set(rows.opp))
    d_idx, season = DI.of(D), 2026 if D.month >= 9 else D.year - 1
    rt = fit_ratings(rows, teams, d_idx, season, P["team"])
    GK = shrunk_ratio(gl, "goalie_id", d_idx, season, P["goalie_hl"], 0.85, P["goalie_K"], "gsax", "xga")
    SK = shrunk_ratio(rows, "team", d_idx, season, 150, 0.6, P["shoot_K"], "shoot", "xg_raw") if P["shoot_K"] else {}

    # rolling goals-per-xG scale over the last 80 game days (tracks league scoring)
    rs = games[games.playoff == 0].copy()
    rs["adj"] = (rs.home_xg_adj + rs.away_xg_adj) * 3600 / rs.icetime
    ud = np.sort(rs.date.unique())
    win = rs[rs.date >= ud[max(0, len(ud) - 80)]]
    c_t = (win.reg_home + win.reg_away).sum() / win.adj.sum()
    cur = gl[(gl.season == season) & gl.starter].sort_values("date")
    names = gl.drop_duplicates("goalie_id").set_index("goalie_id").name.to_dict()

    ov_path = OUT / f"goalie_overrides_{day}.json"
    OV = json.load(open(ov_path)) if ov_path.exists() else {}

    def proj_goalie(team):
        tg = cur[cur.team == team].tail(10)
        if team in OV:
            g = OV[team]
            names.setdefault(g["id"], g["name"])
            return int(g["id"]), f"confirmed: {g['source']}", []
        if tg.empty:
            return None, "no starts this season", []
        order = tg.goalie_id.value_counts().index.tolist()
        pick, why = order[0], "most starts in last 10"
        if team in played_prev and y_start.get(team) == pick and len(order) > 1:
            pick, why = order[1], "back-to-back: rotated from yesterday's starter"
        alts = [{"id": int(g), "name": names.get(g, str(g)), "gsax_per_xg": round(GK.get(g, 0.0), 4)} for g in order]
        return int(pick), why, alts

    ip = OUT / f"injuries_{day}.json"
    IJ = json.load(open(ip)) if ip.exists() else {"teams": {}, "k": 0.0}
    INJ, INJK = IJ["teams"], IJ.get("k", 1.0)
    out_games = []
    for g in todays:
        h, a = g["homeTeam"]["abbrev"], g["awayTeam"]["abbrev"]
        hb, ab = float(h in played_prev), float(a in played_prev)
        hg, hwhy, halts = proj_goalie(h)
        ag, awhy, aalts = proj_goalie(a)
        xh = xg_pred(rt, h, a, hb, ab)
        xa = xg_pred(rt, a, h, ab, hb)
        Mh = INJ.get(h, {}).get("missing_value", 0.0); Ma = INJ.get(a, {}).get("missing_value", 0.0)
        xh = max(0.5, xh - INJK * Mh / 2 + INJK * Ma / 2)
        xa = max(0.5, xa - INJK * Ma / 2 + INJK * Mh / 2)
        lh = C["scale"] * c_t * S["hshare"] * xh * (1 + SK.get(h, 0)) * (1 - GK.get(ag, 0))
        la = C["scale"] * c_t * S["ashare"] * xa * (1 + SK.get(a, 0)) * (1 - GK.get(hg, 0))
        pr = game_probs(lh, la, P["dist"])
        tot = {}
        for line in [4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5]:
            o, u = p_over(pr["total_dist"], line)
            tot[str(line)] = {"over": round(o, 4), "under": round(u, 4)}
        ph = pr["p_home"]
        exp_h = pr["exp_reg_h"] + pr["p_tie"] * pr["ot_home"]
        exp_a = pr["exp_reg_a"] + pr["p_tie"] * (1 - pr["ot_home"])
        out_games.append({
            "id": g["id"], "start_utc": g["startTimeUTC"], "venue": g.get("venue", {}).get("default"),
            "home": h, "away": a,
            "home_name": g["homeTeam"].get("commonName", {}).get("default", h),
            "away_name": g["awayTeam"].get("commonName", {}).get("default", a),
            "home_b2b": bool(hb), "away_b2b": bool(ab),
            "home_goalie": {"id": hg, "name": names.get(hg), "basis": hwhy, "gsax_per_xg": round(GK.get(hg, 0), 4), "options": halts},
            "away_goalie": {"id": ag, "name": names.get(ag), "basis": awhy, "gsax_per_xg": round(GK.get(ag, 0), 4), "options": aalts},
            "inj_home": INJ.get(h, {}).get("players", []), "inj_away": INJ.get(a, {}).get("players", []),
            "inj_adj_home": round(INJ.get(h, {}).get("missing_value", 0.0), 3), "inj_adj_away": round(INJ.get(a, {}).get("missing_value", 0.0), 3),
            "xg_home": round(xh, 3), "xg_away": round(xa, 3),
            "proj_home": round(exp_h, 2), "proj_away": round(exp_a, 2),
            "p_home": round(ph, 4), "p_away": round(1 - ph, 4), "p_ot": round(pr["p_tie"], 4),
            "fair_ml_home": american(ph), "fair_ml_away": american(1 - ph),
            "exp_total": round(pr["exp_total"], 2), "totals": tot,
            "puck_line": {"home_-1.5": round(pr["p_home_m15"], 4), "away_+1.5": round(1 - pr["p_home_m15"], 4),
                          "away_-1.5": round(pr["p_away_m15"], 4), "home_+1.5": round(1 - pr["p_away_m15"], 4)},
        })

    rat = [{"team": t, "off": round(rt["mu"] + rt["off"][t], 3), "def": round(rt["mu"] - rt["def"][t], 3),
            "net": round(rt["off"][t] + rt["def"][t], 3), "finishing": round(SK.get(t, 0), 4)}
           for t in teams if t in set(rows[rows.season == season].team)]
    rat.sort(key=lambda r: -r["net"])
    sc = pd.read_csv(OUT / "scorecard.csv")
    cal = pd.read_csv(OUT / "calibration.csv")
    mc = json.load(open(OUT / "market_calib.json"))
    board = {"date": day, "data_through": data_through.strftime("%Y-%m-%d"),
             "generated": pd.Timestamp.now(tz="America/Phoenix").strftime("%Y-%m-%d %H:%M MST"),
             "league_xg60": round(rt["mu"], 3), "b2b_effect": {"own_xg": round(rt["b2b"], 3), "opp_xg": round(rt["opp_b2b"], 3)},
             "games": out_games, "ratings": rat, "scorecard": sc.to_dict("records"),
             "calibration": cal.to_dict("records"), "market_calibration": mc["markets"],
             "goals_per_xg": round(c_t, 4), "params": P}
    # freeze games already started at their last pre-game numbers
    prev_p = OUT / f"board_{day}.json"
    if prev_p.exists():
        prev = {g["id"]: g for g in json.load(open(prev_p))["games"]}
        now = pd.Timestamp.now(tz="UTC")
        for i, g in enumerate(board["games"]):
            if pd.Timestamp(g["start_utc"]) <= now and g["id"] in prev:
                frozen = prev[g["id"]]; frozen["frozen"] = True
                board["games"][i] = frozen
    json.dump(board, open(OUT / f"board_{day}.json", "w"), indent=1, default=float)
    for g in out_games:
        print(f"{g['away']:>3} @ {g['home']:<3}  {g['proj_away']:.2f}-{g['proj_home']:.2f}  pH {g['p_home']:.3f}  ML {g['fair_ml_home']}  tot {g['exp_total']}  "
              f"G {g['away_goalie']['name']} / {g['home_goalie']['name']}  b2b {g['away_b2b']}/{g['home_b2b']}")


if __name__ == "__main__":
    main(sys.argv[1])
