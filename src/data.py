"""Build clean game-level and goalie-level tables from MoneyPuck downloads.

Data: MoneyPuck.com (free for non-commercial use, credit required).
"""
import pandas as pd
import numpy as np
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
SEASONS = range(2020, 2027)  # season label = starting year (2026 = 2026-27)
CODE_MAP = {"L.A": "LAK", "N.J": "NJD", "S.J": "SJS", "T.B": "TBL", "ARI": "UTA"}


def fix(code):
    return CODE_MAP.get(code, code)


def team_games():
    cols = ["team", "season", "gameId", "opposingTeam", "home_or_away", "gameDate",
            "situation", "iceTime", "playoffGame", "goalsFor", "goalsAgainst",
            "xGoalsFor", "xGoalsAgainst",
            "flurryScoreVenueAdjustedxGoalsFor", "flurryScoreVenueAdjustedxGoalsAgainst"]
    df = pd.read_csv(DATA / "all_teams.csv", usecols=cols)
    df = df[(df.situation == "all") & (df.season.isin(SEASONS))].copy()
    df["team"] = df.team.map(fix)
    df["opposingTeam"] = df.opposingTeam.map(fix)
    df["date"] = pd.to_datetime(df.gameDate.astype(str), format="%Y%m%d")
    df = df.drop_duplicates(["gameId", "team"])
    return df


def shots():
    out = []
    for s in SEASONS:
        c = ["game_id", "season", "isPlayoffGame", "period", "teamCode", "homeTeamCode",
             "awayTeamCode", "isHomeTeam", "goal", "xGoal", "goalieIdForShot",
             "goalieNameForShot", "shotOnEmptyNet", "homeTeamWon", "time"]
        d = pd.read_csv(DATA / f"shots_{s}.csv", usecols=c)
        out.append(d)
    d = pd.concat(out, ignore_index=True)
    for c in ["teamCode", "homeTeamCode", "awayTeamCode"]:
        d[c] = d[c].map(fix)
    # MoneyPuck gameId in all_teams = season*1e6 + game_id
    d["gameId"] = d.season * 1_000_000 + d.game_id
    return d


def build():
    tg = team_games()
    sh = shots()

    # ---- game outcomes from shot data: regulation goals, OT flag, winner
    reg = sh[sh.period <= 3]
    rg = reg.groupby(["gameId", "isHomeTeam"]).goal.sum().unstack(fill_value=0)
    rg.columns = ["reg_away", "reg_home"]
    won = sh.groupby("gameId").homeTeamWon.first()
    po = sh.groupby("gameId").isPlayoffGame.first()
    out = rg.join(won).join(po)

    home = tg[tg.home_or_away == "HOME"].set_index("gameId")
    away = tg[tg.home_or_away == "AWAY"].set_index("gameId")
    g = pd.DataFrame({
        "season": home.season, "date": home.date,
        "home": home.team, "away": home.opposingTeam,
        "home_xg_adj": home.flurryScoreVenueAdjustedxGoalsFor,
        "away_xg_adj": home.flurryScoreVenueAdjustedxGoalsAgainst,
        "home_xg": home.xGoalsFor, "away_xg": home.xGoalsAgainst,
        "home_goals": home.goalsFor, "away_goals": home.goalsAgainst,
        "icetime": home.iceTime, "playoff": home.playoffGame,
    })
    g = g.join(out, how="inner")
    g["ot"] = (g.reg_home == g.reg_away).astype(int)
    g["home_win"] = g.homeTeamWon.astype(int)
    # sportsbook-style final: tied-regulation winner credited +1 (OT goal or SO)
    g["final_home"] = g.reg_home + (g.ot & g.home_win)
    g["final_away"] = g.reg_away + (g.ot & (1 - g.home_win))
    g = g.drop(columns=["homeTeamWon", "isPlayoffGame"]).reset_index().sort_values(["date", "gameId"])

    # ---- goalie game log: starter = goalie facing the team's first shot
    gs = sh[(sh.goalieIdForShot > 0) & (sh.shotOnEmptyNet == 0)].copy()
    gs["def_team"] = np.where(gs.isHomeTeam == 1, gs.awayTeamCode, gs.homeTeamCode)
    gl = gs.groupby(["gameId", "def_team", "goalieIdForShot"]).agg(
        name=("goalieNameForShot", "first"), xga=("xGoal", "sum"), ga=("goal", "sum"),
        first_t=("time", "min"), first_p=("period", "min")).reset_index()
    gl = gl.sort_values(["gameId", "def_team", "first_p", "first_t"])
    gl["starter"] = ~gl.duplicated(["gameId", "def_team"])
    gl = gl.merge(g[["gameId", "date", "season"]], on="gameId", how="inner")
    gl = gl.rename(columns={"goalieIdForShot": "goalie_id", "def_team": "team"})

    g.to_parquet(DATA / "games.parquet")
    gl.to_parquet(DATA / "goalies.parquet")
    return g, gl


if __name__ == "__main__":
    g, gl = build()
    print(g.groupby(["season", "playoff"]).size())
    print("OT rate", g[g.playoff == 0].ot.mean(), "home win", g[g.playoff == 0].home_win.mean())
    # integrity: reg+OT goals vs MoneyPuck goalsFor (all situations, excludes shootout)
    chk = (g.reg_home + g.reg_away) - (g.home_goals + g.away_goals)
    print("games where reg goals > total goals (should be 0):", (chk > 0).sum())
    print("tied after reg but goals differ by >1:", ((g.ot == 1) & ((g.home_goals - g.away_goals).abs() > 1)).sum())
    print("starter rows", gl.starter.sum(), "games*2", len(g) * 2)
    print(g.tail(3).T)
