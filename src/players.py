"""Player impact and missing-player value per team-game.

Player value = shrunk 5-on-5 relative expected-goal differential per 60 (on-ice minus off-ice),
times the player's typical 5-on-5 minutes per game -> expected-goal differential per game.
Everything is computed pre-game from earlier games only (exponential decay by games played,
partial carry-over between seasons).
Missing value for a team-game = sum of values of "regulars" (dressed in >= 5 of the team's
previous 10 games) who are not in that game's lineup.
"""
import sys
import numpy as np, pandas as pd
from pathlib import Path
from data import fix

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SEASONS = range(2020, 2027)
P = {"hl": 60, "carry": 0.7, "K": 18000.0}  # K = shrinkage in seconds of on-ice 5v5 time (300 min)


def load():
    cols = ["playerId", "name", "gameId", "season", "playerTeam", "gameDate", "position", "situation",
            "icetime", "OnIce_F_xGoals", "OnIce_A_xGoals", "OffIce_F_xGoals", "OffIce_A_xGoals"]
    out = []
    for s in SEASONS:
        d = pd.read_csv(DATA / f"{s}.csv", usecols=cols)
        d = d[d.situation.isin(["5on5", "all"])]
        out.append(d)
    d = pd.concat(out, ignore_index=True)
    d["team"] = d.playerTeam.map(fix)
    return d


def team_toi():
    t = pd.read_csv(DATA / "all_teams.csv", usecols=["team", "gameId", "situation", "iceTime", "season"])
    t = t[(t.situation == "5on5") & (t.season.isin(SEASONS))]
    t["team"] = t.team.map(fix)
    return t.drop_duplicates(["gameId", "team"]).set_index(["gameId", "team"]).iceTime


def build(p=P):
    d = load()
    lineup = d[(d.situation == "all") & (d.icetime > 0)][["playerId", "name", "gameId", "team", "gameDate", "season", "position"]]
    s5 = d[d.situation == "5on5"][["playerId", "gameId", "team", "icetime", "OnIce_F_xGoals", "OnIce_A_xGoals",
                                    "OffIce_F_xGoals", "OffIce_A_xGoals"]]
    tt = team_toi()
    s5 = s5.join(tt.rename("team_toi"), on=["gameId", "team"])
    s5["off_toi"] = (s5.team_toi - s5.icetime).clip(lower=1)
    g = lineup.merge(s5.drop(columns=["team"]), on=["playerId", "gameId"], how="left").fillna(
        {"icetime": 0, "OnIce_F_xGoals": 0, "OnIce_A_xGoals": 0, "OffIce_F_xGoals": 0, "OffIce_A_xGoals": 0, "off_toi": 0})
    g = g.sort_values(["playerId", "gameDate", "gameId"])

    # ---- pre-game player value (sequential per player)
    a = 0.5 ** (1 / p["hl"])
    vals = np.zeros(len(g)); n_arr = np.zeros(len(g))
    pid = g.playerId.values; seas = g.season.values
    X = g[["icetime", "OnIce_F_xGoals", "OnIce_A_xGoals", "off_toi", "OffIce_F_xGoals", "OffIce_A_xGoals"]].values
    acc = np.zeros(6); n = 0.0; last_p = None; last_s = None
    for i in range(len(g)):
        if pid[i] != last_p:
            acc[:] = 0; n = 0.0; last_s = None
        elif seas[i] != last_s:
            acc *= p["carry"]; n *= p["carry"]
        on_t, onf, ona, off_t, offf, offa = acc
        if on_t > 0 and off_t > 0 and n > 0:
            rel = 3600 * ((onf - ona) / on_t - (offf - offa) / off_t)
            rel *= on_t / (on_t + p["K"])
            vals[i] = rel * (on_t / n) / 3600.0   # xG diff per game
        n_arr[i] = n
        acc = acc * a + X[i]; n = n * a + 1
        last_p, last_s = pid[i], seas[i]
    g["value"] = vals
    g["gp_w"] = n_arr
    return g


def missing_table(g):
    """Per team-game: value of regulars absent from the lineup (pre-game info only)."""
    rows = []
    vlast = {}  # latest pre-game value per player (updated as we walk games in date order)
    gg = g.sort_values(["gameDate", "gameId"])
    by_team_game = {k: v for k, v in gg.groupby(["team", "gameId"], sort=False)}
    order = gg[["team", "gameId", "gameDate", "season"]].drop_duplicates(["team", "gameId"]).sort_values(["gameDate", "gameId"])
    hist = {}  # team -> list of sets of playerIds (previous games)
    for r in order.itertuples(index=False):
        cur = by_team_game[(r.team, r.gameId)]
        prev = hist.get(r.team, [])
        if prev and prev[-1][1] != r.season:
            prev = []
        last10 = [s for s, _ in prev[-10:]]
        counts = {}
        for s in last10:
            for pl in s:
                counts[pl] = counts.get(pl, 0) + 1
        regulars = {pl for pl, c in counts.items() if c >= 5}
        dressed = set(cur.playerId)
        missing = regulars - dressed
        mv = sum(vlast.get(pl, 0.0) for pl in missing)
        rows.append({"gameId": r.gameId, "team": r.team, "missing_value": mv, "n_missing": len(missing),
                     "missing": ";".join(sorted(str(x) for x in missing))})
        for pl, v in zip(cur.playerId, cur.value):
            vlast[pl] = v
        prev = prev + [(dressed, r.season)]
        hist[r.team] = prev[-12:]
    return pd.DataFrame(rows)


if __name__ == "__main__":
    g = build()
    g.to_parquet(DATA / "player_games.parquet")
    m = missing_table(g)
    m.to_parquet(DATA / "missing.parquet")
    print(g.value.describe())
    top = g.sort_values("gameDate").groupby("playerId").tail(1).nlargest(12, "value")[["name", "team", "value", "gp_w"]]
    print(top.to_string())
    print(m.missing_value.describe(), (m.n_missing > 0).mean())
