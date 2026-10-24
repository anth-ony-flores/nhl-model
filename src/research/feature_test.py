"""Do richer stats add predictive value on top of the current model?
Method: for every game, build pre-game team features from earlier games only (exponentially
weighted by games played, carried across seasons), then fit logistic regression of home win on
[current model logit + feature differences] on the tuning seasons (2021-22, 2022-23) and score
log loss on the untouched test seasons (2023-24 to 2025-26)."""
import itertools, json
import numpy as np, pandas as pd
from scipy.optimize import minimize
from pathlib import Path
from data import fix

ROOT = Path(__file__).resolve().parent.parent
cols = ["team", "season", "gameId", "gameDate", "situation", "iceTime", "playoffGame", "home_or_away",
        "xGoalsFor", "xGoalsAgainst", "goalsFor", "goalsAgainst", "shotAttemptsFor", "shotAttemptsAgainst",
        "highDangerxGoalsFor", "highDangerxGoalsAgainst", "penaltiesFor", "penaltiesAgainst"]
df = pd.read_csv(ROOT / "data/all_teams.csv", usecols=cols)
df = df[df.season >= 2020].copy()
df["team"] = df.team.map(fix)
piv = {}
for sit in ["5on5", "5on4", "4on5", "all"]:
    s = df[df.situation == sit].set_index(["gameId", "team"])
    piv[sit] = s
base = piv["all"][["season", "gameDate", "home_or_away", "playoffGame", "penaltiesFor", "penaltiesAgainst"]].copy()
f5, fpp, fpk = piv["5on5"], piv["5on4"], piv["4on5"]
base["x5f"], base["x5a"] = f5.xGoalsFor, f5.xGoalsAgainst
base["c5f"], base["c5a"] = f5.shotAttemptsFor, f5.shotAttemptsAgainst
base["h5f"], base["h5a"] = f5.highDangerxGoalsFor, f5.highDangerxGoalsAgainst
base["ppx"] = fpp.xGoalsFor.reindex(base.index).fillna(0)
base["pkx"] = fpk.xGoalsAgainst.reindex(base.index).fillna(0)
base["xaf"], base["xaa"] = piv["all"].xGoalsFor, piv["all"].xGoalsAgainst
base = base.reset_index().sort_values(["team", "gameDate", "gameId"])

SUMS = ["x5f", "x5a", "c5f", "c5a", "h5f", "h5a", "ppx", "pkx", "penaltiesFor", "penaltiesAgainst"]


def ewm_features(hl_games=25, carry=0.5):
    """Pre-game exponentially weighted sums per team (excludes the current game)."""
    a = 0.5 ** (1 / hl_games)
    out = []
    for team, g in base.groupby("team", sort=False):
        acc = np.zeros(len(SUMS)); n = 0.0; prev_season = None
        last10 = []
        for r in g.itertuples(index=False):
            if prev_season is not None and r.season != prev_season:
                acc *= carry; n *= carry; last10 = []
            rec = {"gameId": r.gameId, "team": team, "n": n}
            for i, k in enumerate(SUMS):
                rec[k] = acc[i]
            l = last10[-10:]
            rec["l10_xshare"] = (sum(x for x, _ in l) / max(1e-9, sum(x + y for x, y in l))) if len(l) >= 5 else np.nan
            out.append(rec)
            acc = acc * a + np.array([getattr(r, k) for k in SUMS], float); n = n * a + 1
            last10.append((r.xaf, r.xaa)); prev_season = r.season
    f = pd.DataFrame(out)
    f["xshare5"] = f.x5f / (f.x5f + f.x5a)
    f["cshare5"] = f.c5f / (f.c5f + f.c5a)
    f["hdshare5"] = f.h5f / (f.h5f + f.h5a)
    f["st_net"] = (f.ppx - f.pkx) / f.n.clip(lower=1e-9)          # special-teams xG diff per game
    f["pen_net"] = (f.penaltiesAgainst - f.penaltiesFor) / f.n.clip(lower=1e-9)  # drawn minus taken per game
    return f


ev = pd.read_parquet(ROOT / "out/backtest_games.parquet")
ev = ev[ev.p_home.notna()].copy()
lg = lambda p: np.log(p / (1 - p))
ev["base"] = lg(ev.p_home.clip(1e-4, 1 - 1e-4))
y = ev.home_win.values
tune = ev.season.isin([2021, 2022]).values
test = ev.season.isin([2023, 2024, 2025]).values
FEATS = ["xshare5", "cshare5", "hdshare5", "st_net", "pen_net", "l10_xshare"]


def ll(p, yy):
    p = np.clip(p, 1e-6, 1 - 1e-6); return float(-np.mean(yy * np.log(p) + (1 - yy) * np.log(1 - p)))


def fit_eval(X):
    X = np.column_stack([np.ones(len(ev)), ev.base.values] + ([X] if X is not None else []))
    ok = ~np.isnan(X).any(axis=1)
    tr, te = tune & ok, test & ok
    f = lambda b: ll(1 / (1 + np.exp(-(X[tr] @ b))), y[tr]) + 1e-4 * np.sum(b[2:] ** 2)
    b = minimize(f, np.r_[0, 1, np.zeros(X.shape[1] - 2)], method="BFGS").x
    p = 1 / (1 + np.exp(-(X @ b)))
    base_p = ev.p_home.values
    return b, ll(p[te], y[te]), ll(base_p[te], y[te]), int(te.sum())


results = []
for hl in [15, 30, 60]:
    F = ewm_features(hl)
    H = F.rename(columns=lambda c: "h_" + c); A = F.rename(columns=lambda c: "a_" + c)
    m = ev.merge(H, left_on=["gameId", "home"], right_on=["h_gameId", "h_team"], how="left") \
          .merge(A, left_on=["gameId", "away"], right_on=["a_gameId", "a_team"], how="left")
    D = {k: (m["h_" + k] - m["a_" + k]).values for k in FEATS}
    # standardize on tuning seasons
    for k in FEATS:
        mu, sd = np.nanmean(D[k][tune]), np.nanstd(D[k][tune])
        D[k] = (D[k] - mu) / sd
    for k in FEATS:
        b, l1, l0, n = fit_eval(D[k])
        results.append({"hl": hl, "feature": k, "coef": round(b[2], 4), "test_ll": l1, "base_ll": l0, "gain": l0 - l1, "n": n})
    b, l1, l0, n = fit_eval(np.column_stack([D[k] for k in FEATS]))
    results.append({"hl": hl, "feature": "ALL", "coef": [round(x, 3) for x in b[2:]], "test_ll": l1, "base_ll": l0, "gain": l0 - l1, "n": n})
    print(f"hl={hl} done", flush=True)

R = pd.DataFrame(results)
pd.set_option("display.width", 200)
print(R.to_string())
R.to_csv(ROOT / "out/feature_test.csv", index=False)
