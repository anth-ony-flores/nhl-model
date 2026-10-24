"""NHL game model.

1. Team ratings: weighted ridge regression of score/venue/flurry-adjusted xG per 60
   (MoneyPuck) on offense, defense, and back-to-back terms. Only games before the
   prediction date are used (no look-ahead).
2. Finishing and goaltending: shrunk goals-vs-xG residuals (team shooting, goalie
   goals saved above expected per xG faced).
3. Regulation goals ~ independent Poisson, with a tie-inflation factor; tied games go to
   OT/SO with a dampened strength edge. Gives moneyline, total, and puck line.
"""
import numpy as np
import pandas as pd
from scipy.stats import poisson

MAXG = 16


def team_rows(games):
    g = games.copy()
    per60 = 3600.0 / g.icetime
    h = pd.DataFrame({"gameId": g.gameId, "date": g.date, "season": g.season,
                      "team": g.home, "opp": g.away, "home": 1,
                      "xg60": g.home_xg_adj * per60, "g60": g.home_goals * per60,
                      "xg_raw": g.home_xg, "goals": g.home_goals})
    a = pd.DataFrame({"gameId": g.gameId, "date": g.date, "season": g.season,
                      "team": g.away, "opp": g.home, "home": 0,
                      "xg60": g.away_xg_adj * per60, "g60": g.away_goals * per60,
                      "xg_raw": g.away_xg, "goals": g.away_goals})
    r = pd.concat([h, a], ignore_index=True)
    r = add_b2b(r)
    return r


def add_b2b(r, extra_schedule=None):
    """b2b = team also played the previous calendar day."""
    sched = r[["team", "date"]]
    if extra_schedule is not None:
        sched = pd.concat([sched, extra_schedule[["team", "date"]]])
    played = set(zip(sched.team, sched.date))
    r = r.copy()
    r["b2b"] = [(t, d - pd.Timedelta(days=1)) in played for t, d in zip(r.team, r.date)]
    r["opp_b2b"] = [(t, d - pd.Timedelta(days=1)) in played for t, d in zip(r.opp, r.date)]
    r["b2b"] = r.b2b.astype(float)
    r["opp_b2b"] = r.opp_b2b.astype(float)
    return r


class DayIndex:
    """League game-day index so the off-season does not count as elapsed time."""
    def __init__(self, dates):
        u = np.sort(pd.Series(dates).unique())
        self.idx = {pd.Timestamp(d): i for i, d in enumerate(u)}
        self.u = u

    def of(self, d):
        d = pd.Timestamp(d)
        if d in self.idx:
            return self.idx[d]
        return int(np.searchsorted(self.u, np.datetime64(d)))


def weights(rows, D_idx, D_season, p, hl_key="hl", carry_key="carry"):
    age = D_idx - rows.di.values
    w = 0.5 ** (age / p[hl_key])
    w = w * p[carry_key] ** (D_season - rows.season.values)
    return w


def fit_ratings(rows, teams, D_idx, D_season, p, target="xg60"):
    m = (rows.di.values < D_idx) & (D_idx - rows.di.values <= p["lookback"])
    r = rows[m]
    if len(r) < 20:
        return None
    w = weights(r, D_idx, D_season, p)
    T = len(teams)
    ti = {t: i for i, t in enumerate(teams)}
    n = len(r)
    X = np.zeros((n, 3 + 2 * T))
    X[:, 0] = 1.0
    X[:, 1] = r.b2b.values
    X[:, 2] = r.opp_b2b.values
    X[np.arange(n), 3 + r.team.map(ti).values] = 1.0          # offense
    X[np.arange(n), 3 + T + r.opp.map(ti).values] = -1.0      # defense (positive = good)
    y = r[target].values
    sw = np.sqrt(w)
    Xw, yw = X * sw[:, None], y * sw
    lam = p["ridge"]
    pen = np.zeros(3 + 2 * T)
    pen[3:] = lam
    A = Xw.T @ Xw + np.diag(pen)
    b = Xw.T @ yw
    beta = np.linalg.solve(A, b)
    return {"mu": beta[0], "b2b": beta[1], "opp_b2b": beta[2],
            "off": dict(zip(teams, beta[3:3 + T])), "def": dict(zip(teams, beta[3 + T:]))}


def shrunk_ratio(df, key, D_idx, D_season, hl, carry, K, num, den):
    """Weighted (sum num) / (sum den + K) per key, using rows before D_idx."""
    d = df[df.di.values < D_idx]
    if len(d) == 0:
        return {}
    w = 0.5 ** ((D_idx - d.di.values) / hl) * carry ** (D_season - d.season.values)
    nn = pd.Series(d[num].values * w).groupby(d[key].values).sum()
    dd = pd.Series(d[den].values * w).groupby(d[key].values).sum()
    return (nn / (dd + K)).to_dict()


def xg_pred(rt, team, opp, b2b, opp_b2b):
    return max(0.5, rt["mu"] + rt["off"].get(team, 0) - rt["def"].get(opp, 0)
               + rt["b2b"] * b2b + rt["opp_b2b"] * opp_b2b)


def game_probs(lh, la, p):
    """Moneyline, total and puck-line distribution from regulation goal rates."""
    k = np.arange(MAXG)
    ph, pa = poisson.pmf(k, lh), poisson.pmf(k, la)
    M = np.zeros((MAXG + 1, MAXG + 1))
    M[:MAXG, :MAXG] = np.outer(ph, pa)
    n = MAXG + 1
    diff = np.subtract.outer(np.arange(n), np.arange(n))
    # 1) tie inflation: regulation ties exceed the independent-Poisson rate
    tie = np.trace(M)
    tie2 = min(0.45, tie * p["tie_k"])
    off = diff != 0
    M[off] *= (1 - tie2) / M[off].sum()
    M[~off] *= tie2 / tie
    # 2) empty-net conversion: a share of 1-goal regulation leads become 2-goal wins
    q = p.get("en_q", 0.0)
    if q:
        for i in range(n - 1):
            for j in range(n - 1):
                if i - j == 1:
                    mv = M[i, j] * q; M[i, j] -= mv; M[i + 1, j] += mv
                elif j - i == 1:
                    mv = M[i, j] * q; M[i, j] -= mv; M[i, j + 1] += mv
    hw = M[diff > 0].sum()
    aw = M[diff < 0].sum()
    ot_home = 0.5 + p["ot_s"] * (lh / (lh + la) - 0.5)
    p_home = hw + tie2 * ot_home
    mh2 = M[diff >= 2].sum()
    ma2 = M[diff <= -2].sum()
    # final total: regulation total, +1 if tied (OT goal or shootout credit)
    tot = np.add.outer(np.arange(n), np.arange(n))
    final = np.zeros(2 * n + 1)
    np.add.at(final, tot[off], M[off])
    np.add.at(final, tot[~off] + 1, M[~off])
    exp_reg_h = float((M.sum(axis=1) * np.arange(n)).sum())
    exp_reg_a = float((M.sum(axis=0) * np.arange(n)).sum())
    return {"p_home": p_home, "p_tie": tie2, "p_home_reg": hw, "p_away_reg": aw,
            "p_home_m15": mh2, "p_away_m15": ma2, "ot_home": ot_home,
            "exp_reg_h": exp_reg_h, "exp_reg_a": exp_reg_a,
            "exp_total": float((np.arange(len(final)) * final).sum()), "total_dist": final}


def p_over(dist, line):
    k = np.arange(len(dist))
    return float(dist[k > line].sum()), float(dist[k < line].sum())
