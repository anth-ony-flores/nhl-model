"""Player prop model: shots on goal, points, anytime goal (skaters) and saves (goalies).

All rates are pre-game: built only from games before the one being projected, with exponential decay by
games played, partial carry-over between seasons, and shrinkage toward position averages.

Skaters (per game):
  mu_sog = SOG/60 * projected TOI * (opponent shots-against factor)^b_sog
  mu_g   = goal rate/60 (blend of goals and individual xG) * TOI * (team goal factor)^b_g
  mu_a   = assist rate/60 * TOI * (team goal factor)^b_g
  SOG ~ negative binomial (dispersion r_sog); goals, assists ~ Poisson; points ~ Poisson(c_pts*(mu_g + mu_a)).
  Team goal factor = the board's projected xG/60 for the team in this game / the team's own recent xG/60
  (captures opponent, home ice and back-to-backs).
Goalies:
  shots against ~ negative binomial with mean = opponent SOG-for rate * own team SOG-against factor;
  saves | shots ~ binomial(shots, projected save %), save % shrunk toward league.

Data: MoneyPuck skater and team game logs, shot data (credit MoneyPuck.com).
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import nbinom, poisson, binom
from data import fix

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
SEASONS = list(range(2020, 2027))

# tuned on 2021-22 and 2022-23 (src/research/props_backtest.py); see out/props_params.json
DEFAULT = {"hl": 40, "carry": 0.6, "hl_t": 30, "carry_t": 0.5,
           "K_toi": 3.0, "K_sog": 3.0, "K_g": 8.0, "K_a": 6.0, "w_ixg": 0.6,
           "b_sog": 1.0, "b_g": 1.0, "r_sog": 12.0, "c_pts": 1.0, "c_sog": 1.0, "c_g": 1.0, "c_a": 1.0,
           "K_sv": 1500.0, "r_sa": 40.0, "c_sa": 0.96, "h_env": 40, "h_env_g": 40, "hl_g": 60}

SK_COLS = ["playerId", "name", "gameId", "season", "playerTeam", "opposingTeam", "home_or_away", "gameDate",
           "position", "situation", "icetime", "I_F_shotsOnGoal", "I_F_goals", "I_F_primaryAssists",
           "I_F_secondaryAssists", "I_F_points", "I_F_xGoals"]


def params():
    p = dict(DEFAULT)
    f = ROOT / "out" / "props_params.json"
    if f.exists():
        p.update(json.load(open(f)))
    return p


# ---------------- data ----------------
def load_skaters(src=DATA, seasons=SEASONS, use_cache=True):
    CACHE.mkdir(parents=True, exist_ok=True)
    out = []
    for s in seasons:
        cp = CACHE / f"skaters_{s}.parquet"
        raw = Path(src) / f"{s}.csv"
        if use_cache and cp.exists() and (not raw.exists() or cp.stat().st_mtime >= raw.stat().st_mtime):
            out.append(pd.read_parquet(cp)); continue
        d = pd.read_csv(raw, usecols=SK_COLS)
        d = d[d.situation == "all"].drop(columns="situation")
        d.to_parquet(cp)
        out.append(d)
    d = pd.concat(out, ignore_index=True)
    d["team"] = d.playerTeam.map(fix)
    d["opp"] = d.opposingTeam.map(fix)
    d["home"] = (d.home_or_away == "HOME").astype(int)
    d["date"] = pd.to_datetime(d.gameDate.astype(str), format="%Y%m%d")
    d["pos"] = np.where(d.position == "D", "D", "F")
    d = d.rename(columns={"icetime": "toi", "I_F_shotsOnGoal": "sog", "I_F_goals": "g", "I_F_xGoals": "ixg",
                          "I_F_points": "pts"})
    d["a"] = d.I_F_primaryAssists + d.I_F_secondaryAssists
    d = d[d.toi > 0]
    return d[["playerId", "name", "gameId", "season", "team", "opp", "home", "date", "pos", "toi", "sog", "g", "a",
              "pts", "ixg"]].sort_values(["date", "gameId"]).reset_index(drop=True)


def load_teams(src=DATA, seasons=SEASONS):
    cols = ["team", "season", "gameId", "gameDate", "situation", "iceTime", "playoffGame", "shotsOnGoalFor",
            "shotsOnGoalAgainst", "flurryScoreVenueAdjustedxGoalsFor", "goalsFor"]
    t = pd.read_csv(Path(src) / "all_teams.csv", usecols=cols)
    t = t[(t.situation == "all") & (t.season.isin(seasons))].drop_duplicates(["gameId", "team"]).copy()
    t["team"] = t.team.map(fix)
    t["date"] = pd.to_datetime(t.gameDate.astype(str), format="%Y%m%d")
    t["xgf60"] = t.flurryScoreVenueAdjustedxGoalsFor * 3600 / t.iceTime
    return t[["team", "season", "gameId", "date", "playoffGame", "shotsOnGoalFor", "shotsOnGoalAgainst", "xgf60",
              "goalsFor"]].sort_values(["date", "gameId"]).reset_index(drop=True)


def load_goalie_games(src=DATA, seasons=SEASONS):
    """Per goalie-game: shots on goal faced (excluding empty net), goals against, saves."""
    cp = CACHE / "goalie_sa.parquet"
    out = []
    for s in seasons:
        c = CACHE / f"goalie_sa_{s}.parquet"
        raw = Path(src) / f"shots_{s}.csv"
        if c.exists() and (not raw.exists() or c.stat().st_mtime >= raw.stat().st_mtime):
            out.append(pd.read_parquet(c)); continue
        d = pd.read_csv(raw, usecols=["game_id", "season", "goalieIdForShot", "shotWasOnGoal", "goal",
                                       "shotOnEmptyNet", "isHomeTeam", "homeTeamCode", "awayTeamCode"])
        d = d[(d.goalieIdForShot > 0) & (d.shotOnEmptyNet == 0)]
        d["team"] = np.where(d.isHomeTeam == 1, d.awayTeamCode, d.homeTeamCode)
        g = d.groupby(["game_id", "season", "goalieIdForShot", "team"]).agg(sa=("shotWasOnGoal", "sum"), ga=("goal", "sum")).reset_index()
        g["gameId"] = g.season * 1_000_000 + g.game_id
        g = g.rename(columns={"goalieIdForShot": "goalie_id"}).drop(columns="game_id")
        g["team"] = g.team.map(fix)
        g.to_parquet(c)
        out.append(g)
    g = pd.concat(out, ignore_index=True)
    g["saves"] = g.sa - g.ga
    return g


# ---------------- exponentially weighted pre-game sums (vectorized) ----------------
def ewm_pre(df, key, cols, hl, carry):
    """For each row, sum over that key's EARLIER rows of x * a^(games between) * carry^(seasons between).
    Rows must be sorted by date. Returns DataFrame of pre-game sums (cols + '_n' weight count)."""
    a = 0.5 ** (1.0 / hl)
    idx = df.groupby(key).cumcount().to_numpy().astype(float)
    sea = df.season.to_numpy().astype(float)
    s0 = df.groupby(key).season.transform("min").to_numpy().astype(float)
    ds = sea - s0
    # weight of row j seen from row i: a^(t_i - 1 - t_j) * carry^(s_i - s_j)
    up = a ** (-idx) * carry ** (-ds)          # per-row scale (inverse), bounded for these spans
    down = a ** (idx - 1) * carry ** ds
    out = {}
    g = df[key].to_numpy()
    for c in cols + ["_n"]:
        x = np.ones(len(df)) if c == "_n" else df[c].to_numpy().astype(float)
        cs = pd.Series(x * up).groupby(g).cumsum().to_numpy() - x * up   # exclude current row
        out[c] = cs * down
    return pd.DataFrame(out, index=df.index)


def env_rate(df, num, den, h):
    """League environment before each date: decayed sum(num)/sum(den) over earlier dates (half-life h game-dates).
    Returns an array aligned with df rows. The first date falls back to its own value."""
    d = pd.DataFrame({"date": df.date.to_numpy(), "n": np.asarray(num, float), "d": np.asarray(den, float)})
    day = d.groupby("date")[["n", "d"]].sum().sort_index()
    a = 0.5 ** (1.0 / h)
    k = np.arange(len(day), dtype=float)
    # pre-date sums with weight a^(k_i - 1 - k_j); rescale by chunks to keep the numbers finite
    num_pre = np.zeros(len(day)); den_pre = np.zeros(len(day))
    rn = rd = 0.0
    for i, (x, y) in enumerate(zip(day.n.to_numpy(), day.d.to_numpy())):
        num_pre[i], den_pre[i] = rn, rd
        rn = rn * a + x; rd = rd * a + y
    r = pd.Series(np.where(den_pre > 0, num_pre / np.maximum(den_pre, 1e-9), np.nan), index=day.index)
    own = day.n / day.d.replace(0, np.nan)
    r = r.fillna(own).ffill().bfill()
    return d.date.map(r).to_numpy()


def team_rel(tm, p):
    """Per team-game, pre-game relative shot rates (1.0 = league average at the time) and xG/60 level."""
    tm = tm.copy()
    tm["env_sog"] = env_rate(tm, tm.shotsOnGoalFor, np.ones(len(tm)), p["h_env"])
    tm["rf"] = tm.shotsOnGoalFor / tm.env_sog
    tm["ra"] = tm.shotsOnGoalAgainst / tm.env_sog
    T = ewm_pre(tm, "team", ["rf", "ra", "xgf60"], p["hl_t"], p["carry_t"])
    Kt = 5.0
    tm["rel_f"] = (T.rf + Kt) / (T._n + Kt)
    tm["rel_a"] = (T.ra + Kt) / (T._n + Kt)
    lgx = env_rate(tm, tm.xgf60, np.ones(len(tm)), p["h_env"])
    tm["xgf_base"] = (T.xgf60 + Kt * lgx) / (T._n + Kt)
    return tm


# ---------------- skater features ----------------
def skater_features(sk, tm, p, team_pred=None):
    """sk: skater rows sorted by date (today's rows may be appended with zero stats and toi_hint for projection).
    tm: team game rows. team_pred: optional DataFrame [gameId, team, xg_pred] (model xG/60 for that game).
    Shot rates are normalized by the league shot environment at the time, so a league-wide drop in shot
    volume carries through to projections. Returns sk with toi_proj, mu_sog, mu_g, mu_a."""
    sk = sk.copy()
    env = env_rate(sk, sk.sog, sk.toi / 3600, p["h_env"])
    sk["sogn"] = sk.sog / env
    # goals, xG and assists normalized by the league scoring environment the same way
    hr = sk.toi / 3600
    env_g = env_rate(sk, sk.g, hr, p["h_env"]); env_x = env_rate(sk, sk.ixg, hr, p["h_env"])
    env_a = env_rate(sk, sk.a, hr, p["h_env"])
    sk["gn"] = sk.g / env_g; sk["xn"] = sk.ixg / env_x; sk["an"] = sk.a / env_a
    S = ewm_pre(sk, "playerId", ["toi", "sogn", "gn", "an", "xn"], p["hl"], p["carry"])
    n = S["_n"].clip(lower=0)
    pos_toi = sk.pos.map({"F": 15.5 * 60, "D": 20.5 * 60})
    toi = (S.toi + p["K_toi"] * pos_toi) / (n + p["K_toi"])
    hrs = S.toi / 3600
    # priors (per 60): position averages relative to league, from the first season in the data (2020-21)
    base = sk[sk.season == sk.season.min()]
    tot = base.sog.sum() / (base.toi.sum() / 3600)
    rel = (base.groupby("pos").sog.sum() / (base.groupby("pos").toi.sum() / 3600) / tot).to_dict()
    def prior(col):
        t = base[col].sum() / (base.toi.sum() / 3600)
        return sk.pos.map((base.groupby("pos")[col].sum() / (base.groupby("pos").toi.sum() / 3600) / t).to_dict())
    pr_sog, pr_g, pr_x, pr_a = sk.pos.map(rel), prior("g"), prior("ixg"), prior("a")
    sog60 = env * (S.sogn + p["K_sog"] * pr_sog) / (hrs + p["K_sog"])
    # goal rate: blend of the player's goals and individual xG (each relative to league), times league goal rate
    grel = p["w_ixg"] * (S.xn + p["K_g"] * pr_x) / (hrs + p["K_g"]) + (1 - p["w_ixg"]) * (S.gn + p["K_g"] * pr_g) / (hrs + p["K_g"])
    g60 = env_g * grel
    a60 = env_a * (S.an + p["K_a"] * pr_a) / (hrs + p["K_a"])

    T = team_rel(tm, p)
    opp = T[["gameId", "team", "rel_a"]].rename(columns={"team": "opp", "rel_a": "opp_rel_a"})
    own = T[["gameId", "team", "xgf_base"]]
    sk = sk.merge(opp, on=["gameId", "opp"], how="left").merge(own, on=["gameId", "team"], how="left")
    if team_pred is not None:
        sk = sk.merge(team_pred, on=["gameId", "team"], how="left")
        gf = (sk.xg_pred / sk.xgf_base).clip(0.6, 1.6).fillna(1.0)
    else:
        gf = pd.Series(1.0, index=sk.index)
    sf = sk.opp_rel_a.fillna(1.0).clip(0.75, 1.3)
    t60 = toi.to_numpy() / 3600
    sk["toi_proj"] = toi.to_numpy() / 60
    sk["mu_sog"] = p["c_sog"] * sog60.to_numpy() * t60 * sf.to_numpy() ** p["b_sog"]
    sk["mu_g"] = p["c_g"] * g60.to_numpy() * t60 * gf.to_numpy() ** p["b_g"]
    sk["mu_a"] = p["c_a"] * a60.to_numpy() * t60 * gf.to_numpy() ** p["b_g"]
    sk["n_games"] = n.to_numpy()
    return sk


def goalie_features(gg, tm, p):
    """gg: every goalie appearance (history) plus rows to project; columns goalie_id, team, opp, gameId, season,
    date, sa, saves. Projected shots against = league SOG per team-game at the time x opponent's relative
    shots-for x own team's relative shots-against x c_sa (starter share). Save % = league save % at the time
    plus the goalie's decayed save % above league, shrunk with K_sv shots. Returns gg with mu_sa and sv_proj."""
    gg = gg.sort_values(["date", "gameId"]).reset_index(drop=True)
    p = dict(p, h_env=p["h_env_g"])
    envsv = env_rate(gg, gg.saves, gg.sa, p["h_env"])
    gg["dsv"] = gg.saves - gg.sa * envsv
    G = ewm_pre(gg, "goalie_id", ["sa", "dsv"], p["hl_g"], 0.7)
    T = team_rel(tm, p)
    gg = gg.merge(T[["gameId", "team", "rel_a", "env_sog"]], on=["gameId", "team"], how="left")
    gg = gg.merge(T[["gameId", "team", "rel_f"]].rename(columns={"team": "opp"}), on=["gameId", "opp"], how="left")
    gg["mu_sa"] = p["c_sa"] * gg.env_sog * gg.rel_f * gg.rel_a
    gg["sv_proj"] = envsv + G.dsv.to_numpy() / (G.sa.to_numpy() + p["K_sv"])
    gg["league_sv"] = envsv
    return gg


# ---------------- probabilities ----------------
def nb_sf(k, mu, r):
    """P(X >= k) for negative binomial with mean mu and dispersion r (variance mu + mu^2/r)."""
    mu = np.asarray(mu, float); pr = r / (r + mu)
    return nbinom.sf(np.asarray(k) - 1, r, pr)


def p_over(market, line, row, p):
    """Probability the stat goes OVER `line` (half-point lines; integer lines: strictly over, pushes excluded)."""
    k = int(np.floor(line)) + 1
    if market == "sog":
        po = float(nb_sf(k, row["mu_sog"], p["r_sog"]))
        if float(line).is_integer():
            pe = float(nb_sf(int(line), row["mu_sog"], p["r_sog"]) - po)
            return po / (1 - pe) if pe < 1 else None
        return po
    if market == "pts":
        return float(poisson.sf(k - 1, p["c_pts"] * (row["mu_g"] + row["mu_a"])))
    if market == "goal":
        return float(poisson.sf(k - 1, row["mu_g"]))
    if market == "saves":
        return float(saves_sf(k, row["mu_sa"], row["sv_proj"], p["r_sa"]))
    return None


def saves_sf(k, mu_sa, sv, r):
    """P(saves >= k): shots ~ NB(mu_sa, r), saves | shots ~ Binomial(shots, sv). Vectorized over mu_sa, sv."""
    mu = np.atleast_1d(np.asarray(mu_sa, float))[:, None]
    s = np.atleast_1d(np.asarray(sv, float))[:, None]
    n = np.arange(0, 90)[None, :]
    out = (nbinom.pmf(n, r, r / (r + mu)) * binom.sf(k - 1, n, s)).sum(axis=1)
    return out if np.ndim(mu_sa) else float(out[0])
