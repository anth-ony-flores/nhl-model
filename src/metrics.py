"""Season-to-date team metrics and league ranks from MoneyPuck team game logs.
Usage: python metrics.py 2026-10-24  -> out/metrics_<day>.json"""
import json, sys
import numpy as np
import pandas as pd
from pathlib import Path
from data import fix

ROOT = Path(__file__).resolve().parent.parent
DATA, OUT = ROOT / "data", ROOT / "out"

# (key, label, group, higher_is_better, decimals, unit)
METRICS = [
    ("xgf_pct_5v5", "Expected goal share", "Even strength (5-on-5)", True, 1, "%"),
    ("cf_pct_5v5", "Shot attempt share", "Even strength (5-on-5)", True, 1, "%"),
    ("xgf60_5v5", "xG for per 60", "Even strength (5-on-5)", True, 2, ""),
    ("xga60_5v5", "xG against per 60", "Even strength (5-on-5)", False, 2, ""),
    ("hdxgf60_5v5", "High-danger xG for per 60", "Shot quality (5-on-5)", True, 2, ""),
    ("hdxga60_5v5", "High-danger xG against per 60", "Shot quality (5-on-5)", False, 2, ""),
    ("rebf60_5v5", "Rebound chances for per 60", "Shot quality (5-on-5)", True, 2, ""),
    ("pp_xgf60", "Power play xG per 60", "Special teams", True, 2, ""),
    ("pp_gf60", "Power play goals per 60", "Special teams", True, 2, ""),
    ("pk_xga60", "Penalty kill xG against per 60", "Special teams", False, 2, ""),
    ("pen_drawn_gp", "Penalties drawn per game", "Special teams", True, 2, ""),
    ("pen_taken_gp", "Penalties taken per game", "Special teams", False, 2, ""),
    ("finish_gp", "Goals above expected per game", "Finishing and goaltending", True, 2, ""),
    ("gsax_gp", "Goals saved above expected per game", "Finishing and goaltending", True, 2, ""),
    ("l10_xgf_pct", "Expected goal share, last 10", "Form", True, 1, "%"),
    ("l10_gd", "Goal differential, last 10", "Form", True, 0, ""),
    ("pace60_5v5", "Shot attempts per 60 (both teams)", "Pace and style", None, 1, ""),
    ("fo_pct", "Faceoff win %", "Pace and style", True, 1, "%"),
    ("cf60f_5v5", "Shot attempts for per 60", "Underlying", True, 1, ""),
    ("cf60a_5v5", "Shot attempts against per 60", "Underlying", False, 1, ""),
    ("l10_xgf_gp", "xG for per game, last 10", "Underlying", True, 2, ""),
    ("l10_xga_gp", "xG against per game, last 10", "Underlying", False, 2, ""),
]


def per60(num, toi):
    return 3600.0 * num / toi if toi > 0 else np.nan


def team_metrics(df, team):
    d = df[df.team == team]
    s5, pp, pk, al = (d[d.situation == x] for x in ["5on5", "5on4", "4on5", "all"])
    t5 = s5.iceTime.sum()
    gp = al.gameId.nunique()
    l10 = al.sort_values("gameDate").tail(10)
    return {
        "gp": gp,
        "xgf_pct_5v5": 100 * s5.xGoalsFor.sum() / (s5.xGoalsFor.sum() + s5.xGoalsAgainst.sum()),
        "cf_pct_5v5": 100 * s5.shotAttemptsFor.sum() / (s5.shotAttemptsFor.sum() + s5.shotAttemptsAgainst.sum()),
        "xgf60_5v5": per60(s5.xGoalsFor.sum(), t5),
        "xga60_5v5": per60(s5.xGoalsAgainst.sum(), t5),
        "hdxgf60_5v5": per60(s5.highDangerxGoalsFor.sum(), t5),
        "hdxga60_5v5": per60(s5.highDangerxGoalsAgainst.sum(), t5),
        "rebf60_5v5": per60(s5.reboundsFor.sum(), t5),
        "pp_xgf60": per60(pp.xGoalsFor.sum(), pp.iceTime.sum()),
        "pp_gf60": per60(pp.goalsFor.sum(), pp.iceTime.sum()),
        "pk_xga60": per60(pk.xGoalsAgainst.sum(), pk.iceTime.sum()),
        # MoneyPuck dictionary: "penalties" = penalties the player/team received
        "pen_taken_gp": al.penaltiesFor.sum() / gp,
        "pen_drawn_gp": al.penaltiesAgainst.sum() / gp,
        "finish_gp": (al.goalsFor.sum() - al.xGoalsFor.sum()) / gp,
        "gsax_gp": (al.xGoalsAgainst.sum() - al.goalsAgainst.sum()) / gp,
        "l10_xgf_pct": 100 * l10.xGoalsFor.sum() / (l10.xGoalsFor.sum() + l10.xGoalsAgainst.sum()),
        "l10_gd": float(l10.goalsFor.sum() - l10.goalsAgainst.sum()),
        "pace60_5v5": per60(s5.shotAttemptsFor.sum() + s5.shotAttemptsAgainst.sum(), t5),
        "cf60f_5v5": per60(s5.shotAttemptsFor.sum(), t5),
        "cf60a_5v5": per60(s5.shotAttemptsAgainst.sum(), t5),
        "l10_xgf_gp": l10.xGoalsFor.sum() / len(l10),
        "l10_xga_gp": l10.xGoalsAgainst.sum() / len(l10),
        "fo_pct": 100 * al.faceOffsWonFor.sum() / (al.faceOffsWonFor.sum() + al.faceOffsWonAgainst.sum()),
    }


def main(day, season=2026):
    cols = ["team", "season", "gameId", "gameDate", "situation", "iceTime", "playoffGame",
            "xGoalsFor", "xGoalsAgainst", "goalsFor", "goalsAgainst", "shotAttemptsFor",
            "shotAttemptsAgainst", "highDangerxGoalsFor", "highDangerxGoalsAgainst",
            "reboundsFor", "penaltiesFor", "penaltiesAgainst", "faceOffsWonFor", "faceOffsWonAgainst"]
    df = pd.read_csv(DATA / "all_teams.csv", usecols=cols)
    df = df[(df.season == season) & (df.playoffGame == 0)].copy()
    df["team"] = df.team.map(fix)
    df = df[df.gameDate < int(day.replace("-", ""))]
    teams = sorted(df.team.unique())
    M = {t: team_metrics(df, t) for t in teams}
    ranks = {}
    for key, _, _, hib, _, _ in METRICS:
        vals = pd.Series({t: M[t][key] for t in teams})
        asc = False if hib in (True, None) else True
        ranks[key] = vals.rank(ascending=asc, method="min").astype(int).to_dict()
    out = {"day": day, "season": season, "data_through": str(df.gameDate.max()),
           "n_teams": len(teams),
           "metrics": [{"key": k, "label": l, "group": g, "higher_better": h, "dec": dd, "unit": u}
                       for k, l, g, h, dd, u in METRICS],
           "teams": {t: {"values": {k: (None if pd.isna(v) else round(float(v), 4)) for k, v in M[t].items()},
                         "ranks": {k: ranks[k][t] for k in ranks}} for t in teams}}
    json.dump(out, open(OUT / f"metrics_{day}.json", "w"), indent=1)
    # sanity: penalties drawn should track power-play time
    pp_toi = df[df.situation == "5on4"].groupby("team").iceTime.sum()
    drawn = df[df.situation == "all"].groupby("team").penaltiesAgainst.sum()
    taken = df[df.situation == "all"].groupby("team").penaltiesFor.sum()
    print("corr(PP time, penalties drawn)", round(pp_toi.corr(drawn), 3), " corr(PP time, penalties taken)", round(pp_toi.corr(taken), 3))
    for t in ["TOR", "EDM"]:
        print(t, {k: round(v, 2) for k, v in M[t].items()})


if __name__ == "__main__":
    main(sys.argv[1])
