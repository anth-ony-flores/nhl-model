"""Walk-forward backtest. Tune on 2021-22 and 2022-23, test on 2023-24 to 2025-26,
report 2026-27 to date as live. Every prediction uses only games before its date."""
import itertools, json, sys
import numpy as np
import pandas as pd
from pathlib import Path
from model import (team_rows, DayIndex, fit_ratings, shrunk_ratio, xg_pred, game_probs)

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = Path(__file__).resolve().parent.parent / "out"
OUT.mkdir(exist_ok=True)
TUNE, TEST, LIVE = [2021, 2022], [2023, 2024, 2025], [2026]

games = pd.read_parquet(DATA / "games.parquet")
gl = pd.read_parquet(DATA / "goalies.parquet")
rows = team_rows(games)
DI = DayIndex(games.date)
rows["di"] = rows.date.map(DI.of)
gl["di"] = gl.date.map(DI.of)
gl["gsax"] = gl.xga - gl.ga
rows["shoot"] = rows.goals - rows.xg_raw
teams = sorted(set(rows.team) | set(rows.opp))

ev = games[(games.playoff == 0) & (games.season.isin(TUNE + TEST + LIVE))].copy()
ev["di"] = ev.date.map(DI.of)
hr = rows[rows.home == 1].set_index("gameId")[["b2b", "opp_b2b"]]
ev = ev.join(hr, on="gameId")
starters = gl[gl.starter].set_index(["gameId", "team"]).goalie_id
ev["home_g"] = [starters.get((g, t)) for g, t in zip(ev.gameId, ev.home)]
ev["away_g"] = [starters.get((g, t)) for g, t in zip(ev.gameId, ev.away)]
dates = sorted(ev.di.unique())


def rating_preds(p, target="xg60"):
    out = {}
    for d in dates:
        season = int(ev.loc[ev.di == d, "season"].iloc[0])
        out[d] = fit_ratings(rows, teams, d, season, p, target)
    xh, xa = [], []
    for r in ev.itertuples():
        rt = out[r.di]
        if rt is None:
            xh.append(np.nan); xa.append(np.nan); continue
        xh.append(xg_pred(rt, r.home, r.away, r.b2b, r.opp_b2b))
        xa.append(xg_pred(rt, r.away, r.home, r.opp_b2b, r.b2b))
    return np.array(xh), np.array(xa), out


def logloss(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(y, p):
    return float(np.mean((p - y) ** 2))


# ---------- Stage 1: team rating params, scored by xG prediction error on TUNE
per60 = 3600 / ev.icetime
act_h, act_a = ev.home_xg_adj * per60, ev.away_xg_adj * per60
tune_m = ev.season.isin(TUNE).values
best = None
grid1 = list(itertools.product([40, 70, 120, 200], [0.5, 0.8], [1.0, 2.5, 5.0, 10.0]))
for hl, carry, ridge in grid1:
    p = {"hl": hl, "carry": carry, "ridge": ridge, "lookback": 500}
    xh, xa, _ = rating_preds(p)
    mse = np.nanmean(((xh - act_h) ** 2 + (xa - act_a) ** 2)[tune_m])
    print("stage1", hl, carry, ridge, round(mse, 4), flush=True)
    if best is None or mse < best[0]:
        best = (mse, p)
P = best[1]
print("best team params", P)
xh, xa, RT = rating_preds(P)
ev["xg_h"], ev["xg_a"] = xh, xa

# goals-based comparison model (same params, target = actual goals per 60)
gxh, gxa, _ = rating_preds(P, target="g60")
ev["gxg_h"], ev["gxg_a"] = gxh, gxa


# ---------- Stage 2: goalie / shooting shrinkage, scale, tie and OT params (log loss on TUNE)
def ratings_cache(K_g, hl_g, K_s):
    gk, sk = {}, {}
    for d in dates:
        season = int(ev.loc[ev.di == d, "season"].iloc[0])
        gk[d] = shrunk_ratio(gl, "goalie_id", d, season, hl_g, 0.85, K_g, "gsax", "xga")
        sk[d] = shrunk_ratio(rows, "team", d, season, 150, 0.6, K_s, "shoot", "xg_raw") if K_s else {}
    return gk, sk


def components(gk, sk, xcol_h="xg_h", xcol_a="xg_a"):
    bh, ba = [], []
    for r in ev.itertuples():
        g = gk[r.di]; s = sk[r.di]
        gh = g.get(r.home_g, 0.0); ga_ = g.get(r.away_g, 0.0)
        bh.append(getattr(r, xcol_h) * (1 + s.get(r.home, 0.0)) * (1 - ga_))
        ba.append(getattr(r, xcol_a) * (1 + s.get(r.away, 0.0)) * (1 - gh))
    return np.array(bh), np.array(ba)


def predict(bh, ba, prm, mask):
    ch = np.nanmean(ev.reg_home[tune_m]) / np.nanmean(bh[tune_m])
    ca = np.nanmean(ev.reg_away[tune_m]) / np.nanmean(ba[tune_m])
    res = []
    for i in np.where(mask)[0]:
        if np.isnan(bh[i]):
            res.append(None); continue
        res.append(game_probs(ch * bh[i], ca * ba[i], prm))
    return res, ch, ca


y = ev.home_win.values
best2 = None
for K_g, hl_g, K_s in itertools.product([60, 150, 400], [150, 400], [0, 300]):
    gk, sk = ratings_cache(K_g, hl_g, K_s)
    bh, ba = components(gk, sk)
    for tie_k, ot_s in itertools.product([1.0, 1.1, 1.2], [0.3, 0.6]):
        prm = {"tie_k": tie_k, "ot_s": ot_s}
        res, _, _ = predict(bh, ba, prm, tune_m)
        ok = [r is not None for r in res]
        ph = np.array([r["p_home"] for r in res if r is not None])
        ll = logloss(y[tune_m][ok], ph)
        if best2 is None or ll < best2[0]:
            best2 = (ll, K_g, hl_g, K_s, prm)
    print("stage2", K_g, hl_g, K_s, "best so far", round(best2[0], 5), flush=True)
_, K_g, hl_g, K_s, PRM = best2
print("best stage2", best2)
GK, SK = ratings_cache(K_g, hl_g, K_s)
bh, ba = components(GK, SK)
allm = np.ones(len(ev), bool)
res, CH, CA = predict(bh, ba, PRM, allm)
ev["p_home"] = [r["p_home"] if r else np.nan for r in res]
ev["p_tie"] = [r["p_tie"] if r else np.nan for r in res]
ev["exp_total"] = [r["exp_total"] if r else np.nan for r in res]

# xG-only variant (no goalie/shooting) and goals-based variant, same tie/ot params
g0 = {d: {} for d in dates}
bh0, ba0 = components(g0, g0)
r0, _, _ = predict(bh0, ba0, PRM, allm)
ev["p_home_xgonly"] = [r["p_home"] if r else np.nan for r in r0]
bhg, bag = components(g0, g0, "gxg_h", "gxg_a")
rg, _, _ = predict(bhg, bag, PRM, allm)
ev["p_home_goals"] = [r["p_home"] if r else np.nan for r in rg]

# ---------- Baselines
home_rate = y[tune_m].mean()
ev["p_base_home"] = home_rate
# season-to-date points% (2 W, 1 OTL), logistic fit on TUNE
pts = {}
pp = []
for r in ev.sort_values("date").itertuples():
    k = (r.season,)
    def pct(t):
        w, gp = pts.get((r.season, t), (0, 0))
        return (w / (2 * gp)) if gp >= 1 else 0.5
    pp.append((r.Index, pct(r.home) - pct(r.away)))
    hp = 2 if r.home_win else (1 if r.ot else 0)
    ap = 2 if not r.home_win else (1 if r.ot else 0)
    for t, add in [(r.home, hp), (r.away, ap)]:
        w, gp = pts.get((r.season, t), (0, 0))
        pts[(r.season, t)] = (w + add, gp + 1)
ev.loc[[i for i, _ in pp], "pct_diff"] = [v for _, v in pp]
from scipy.optimize import minimize
xt, yt = ev.pct_diff.values[tune_m], y[tune_m]
f = lambda b: logloss(yt, 1 / (1 + np.exp(-(b[0] + b[1] * xt))))
bb = minimize(f, [0.1, 1.0]).x
ev["p_base_pct"] = 1 / (1 + np.exp(-(bb[0] + bb[1] * ev.pct_diff)))

# ---------- Scorecard
def phase(s):
    return "Tune" if s in TUNE else ("Test" if s in TEST else "Live")
ev["phase"] = ev.season.map(phase)
models = {"Model (xG + goalie + finishing)": "p_home", "xG ratings only": "p_home_xgonly",
          "Goals-based ratings": "p_home_goals", "Season points %": "p_base_pct",
          "Home team (constant)": "p_base_home"}
rows_out = []
for grp_name, grp in list(ev.groupby("season")) + [("Test 2023-25", ev[ev.phase == "Test"])]:
    m = grp.p_home.notna()
    gg = grp[m]
    for name, col in models.items():
        rows_out.append({"group": str(grp_name), "model": name, "n": int(len(gg)),
                         "logloss": logloss(gg.home_win.values, gg[col].values),
                         "brier": brier(gg.home_win.values, gg[col].values),
                         "acc": float(((gg[col] > 0.5) == (gg.home_win == 1)).mean())})
sc = pd.DataFrame(rows_out)
print(sc.pivot_table(index="group", columns="model", values="logloss").round(4).to_string())

# calibration (test seasons)
t = ev[(ev.phase == "Test") & ev.p_home.notna()]
bins = pd.cut(t.p_home, [0, .35, .45, .5, .55, .65, 1])
cal = t.groupby(bins, observed=True).agg(n=("home_win", "size"), pred=("p_home", "mean"), actual=("home_win", "mean"))
print(cal)
tot_err = (t.exp_total - (t.final_home + t.final_away))
print("Test totals: mean pred", t.exp_total.mean().round(3), "mean actual", (t.final_home + t.final_away).mean().round(3),
      "MAE", tot_err.abs().mean().round(3), "pred tie", t.p_tie.mean().round(3), "actual OT", t.ot.mean().round(3))

params = {"team": P, "goalie_K": K_g, "goalie_hl": hl_g, "shoot_K": K_s, "dist": PRM,
          "c_home": CH, "c_away": CA, "pct_logit": list(bb), "home_rate": home_rate}
json.dump(params, open(OUT / "params.json", "w"), indent=2, default=float)
sc.to_csv(OUT / "scorecard.csv", index=False)
cal.to_csv(OUT / "calibration.csv")
ev.to_parquet(OUT / "backtest_games.parquet")
print(json.dumps(params, indent=2, default=float))
