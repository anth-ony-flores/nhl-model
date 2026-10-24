"""Walk-forward backtest of the player prop model (src/props.py).

Tune on 2021-22 and 2022-23, test on 2023-24, 2024-25 and 2025-26 (regular season only).
Every projection uses only games before the one being projected. Players are the ones who actually dressed
(MoneyPuck game logs); goalies are the actual starters (out/backtest_games.parquet home_g / away_g).
Team goal factor uses the game model's walk-forward predicted xG/60 (xg_h / xg_a).

Baseline: naive season-to-date average per game (falls back to last season, then position average) with a
Poisson distribution. Historical DraftKings prop prices are not available, so there is no market comparison.

Usage: python research/props_backtest.py [--quick]
Writes out/props_backtest.json and out/props_params.json (tuned parameters)."""
import json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import poisson

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import props as P

ROOT = P.ROOT
TUNE = [2021, 2022]
TEST = [2023, 2024, 2025]
SOG_K = [2, 3, 4]          # P(SOG >= k), i.e. over 1.5 / 2.5 / 3.5
SAVE_LINES = [21.5, 23.5, 25.5, 27.5, 29.5]


def ll(p, y):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6); y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def calib(p, y, bins=(0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0001)):
    d = pd.DataFrame({"p": p, "y": y})
    d["b"] = pd.cut(d.p, bins, right=False)
    t = d.groupby("b", observed=True).agg(n=("y", "size"), pred=("p", "mean"), actual=("y", "mean")).reset_index()
    t = t[t.n >= 30]
    return [{"bin": f"{b.left:.1f}-{min(b.right, 1):.1f}", "n": int(n), "pred": round(pr, 4), "actual": round(a, 4)}
            for b, n, pr, a in t.itertuples(index=False)]


def load():
    t0 = time.time()
    sk = P.load_skaters()
    tm = P.load_teams()
    gg = P.load_goalie_games()
    bg = pd.read_parquet(ROOT / "out" / "backtest_games.parquet")
    print(f"loaded in {time.time() - t0:.0f}s: {len(sk)} skater games, {len(gg)} goalie games")
    return sk, tm, gg, bg


def team_pred(bg):
    h = bg[["gameId", "home", "xg_h"]].rename(columns={"home": "team", "xg_h": "xg_pred"})
    a = bg[["gameId", "away", "xg_a"]].rename(columns={"away": "team", "xg_a": "xg_pred"})
    return pd.concat([h, a])


def naive(sk, col):
    """Season-to-date mean per game before this game; fallback last-season mean, then position mean."""
    g = sk.groupby(["playerId", "season"])[col]
    n = g.cumcount()
    s = g.cumsum() - sk[col]
    std = s / n.replace(0, np.nan)
    last = sk.groupby(["playerId", "season"])[col].mean().rename("last").reset_index()
    last["season"] += 1
    m = sk[["playerId", "season"]].merge(last, on=["playerId", "season"], how="left")["last"].to_numpy()
    pos = sk.groupby("pos")[col].transform("mean")
    out = std.to_numpy()
    out = np.where(np.isnan(out), m, out)
    return np.where(np.isnan(out), pos.to_numpy(), out)


def skater_eval(sk, prm, seasons, tp):
    f = P.skater_features(sk, tm_glob, prm, tp)
    f = f[f.season.isin(seasons) & (f.gameId % 1_000_000 // 10_000 == 2)]
    r = prm["r_sog"]
    out = {}
    for k in SOG_K:
        out[f"sog{k}"] = (P.nb_sf(k, f.mu_sog, r), (f.sog >= k).astype(int).to_numpy())
    out["pts1"] = (poisson.sf(0, prm["c_pts"] * (f.mu_g + f.mu_a)), (f.pts >= 1).astype(int).to_numpy())
    out["g1"] = (poisson.sf(0, f.mu_g), (f.g >= 1).astype(int).to_numpy())
    return f, out


def skater_loss(sk, prm, seasons, tp):
    _, o = skater_eval(sk, prm, seasons, tp)
    return {k: ll(*v) for k, v in o.items()}


def goalie_rows(gg, tm, bg):
    """History = every goalie appearance; projected rows = actual starters from the game model's backtest."""
    side = tm[["gameId", "team", "date"]]
    opp = tm[["gameId", "team"]].rename(columns={"team": "opp"})
    gx = gg.merge(side, on=["gameId", "team"], how="inner")
    gx = gx.merge(opp, on="gameId").query("opp != team")
    st = pd.concat([bg[["gameId", "home", "home_g"]].rename(columns={"home": "team", "home_g": "goalie_id"}),
                    bg[["gameId", "away", "away_g"]].rename(columns={"away": "team", "away_g": "goalie_id"})])
    st["starter"] = 1
    gx = gx.merge(st, on=["gameId", "team", "goalie_id"], how="left")
    gx["starter"] = gx.starter.fillna(0).astype(int)
    return gx


def goalie_eval(gx, tm, prm, seasons):
    f = P.goalie_features(gx, tm, prm)
    f = f[f.season.isin(seasons) & (f.starter == 1) & (f.gameId % 1_000_000 // 10_000 == 2)].dropna(subset=["mu_sa"])
    out = {}
    for L in SAVE_LINES:
        k = int(np.floor(L)) + 1
        p = P.saves_sf(k, f.mu_sa.to_numpy(), f.sv_proj.to_numpy(), prm["r_sa"], prm["q_pull"], prm["f_pull"])
        out[f"sv{L}"] = (p, (f.saves >= k).astype(int).to_numpy())
    return f, out


def fit_priors(prm, scale, n_max=15):
    """Prior multipliers so players with little history (pre-game weight < n_max games) are unbiased on average
    in the tune seasons. Without this, call-ups and fringe players are projected like average regulars
    (about 15 to 45% too high in the 2023-26 test before the fix)."""
    grid = np.round(np.arange(0.4, 1.21, 0.05), 2)
    for _ in range(2):
        for k, col, mu in (("pm_toi", "toi", "toi_proj"), ("pm_sog", "sog", "mu_sog"), ("pm_g", "g", "mu_g"), ("pm_a", "a", "mu_a")):
            best = None
            for v in grid:
                q = scale(dict(prm, **{k: float(v)}))
                f = P.skater_features(sk_glob, tm_glob, q, tp_glob)
                f = f[f.season.isin(TUNE) & (f.gameId % 1_000_000 // 10_000 == 2) & (f.n_games < n_max)]
                act = f[col].mean() / 60 if col == "toi" else f[col].mean()
                err = abs(f[mu].mean() / act - 1)
                if best is None or err < best[0]:
                    best = (err, float(v))
            prm = scale(dict(prm, **{k: best[1]}))
    return prm


def tune(sk, gx, tm, tp, quick=False):
    prm = dict(P.DEFAULT)
    grid = {
        "hl": [15, 25, 40, 70, 120], "carry": [0.3, 0.5, 0.7, 0.9, 1.0],
        "K_toi": [0.5, 1, 3, 6], "K_sog": [0.5, 1, 1.5, 3, 6], "K_g": [1, 2, 4, 8, 16], "K_a": [0.5, 1, 2, 3, 6, 12],
        "w_ixg": [0.3, 0.5, 0.7, 0.9], "b_sog": [0.0, 0.5, 1.0, 1.5], "b_g": [0.0, 0.5, 1.0, 1.5],
        "r_sog": [6, 10, 16, 30, 60, 1000], "hl_t": [15, 30, 60], "h_env": [5, 10, 25],
    }
    if quick:
        grid = {k: v for k, v in grid.items() if k in ("hl", "carry", "r_sog")}

    def scale(pr):
        """Moment-match the overall scale on the tune seasons (the bias is stable across seasons once rates are
        normalized by the league environment, about +1.5% SOG and +3% goals/assists before scaling)."""
        q = dict(pr, c_sog=1.0, c_g=1.0, c_a=1.0)
        f = P.skater_features(sk, tm_glob, q, tp)
        f = f[f.season.isin(TUNE) & (f.gameId % 1_000_000 // 10_000 == 2)]
        return dict(pr, c_sog=f.sog.sum() / f.mu_sog.sum(), c_g=f.g.sum() / f.mu_g.sum(), c_a=f.a.sum() / f.mu_a.sum())

    def obj(pr):
        L = skater_loss(sk, scale(pr), TUNE, tp)
        return np.mean([L["sog2"], L["sog3"], L["sog4"]]) + L["pts1"] + L["g1"]

    best = obj(prm)
    for rnd in range(3 if not quick else 1):
        for k, vals in grid.items():
            for v in vals:
                if v == prm[k]:
                    continue
                t = dict(prm, **{k: v}); s = obj(t)
                if s < best - 1e-6:
                    best, prm = s, t
            print(f"round {rnd} {k}={prm[k]} obj={best:.5f}", flush=True)
    prm = scale(prm)
    prm = fit_priors(prm, scale)
    print("scales", {k: round(prm[k], 4) for k in ("c_sog", "c_g", "c_a", "pm_toi", "pm_sog", "pm_g", "pm_a")})
    # goalie params (separate objective)
    gb = None
    ggrid = {"b_sa": [0.25, 0.5, 0.75, 1.0], "K_sv": [250, 500, 1000, 2000, 4000, 8000, 16000], "r_sa": [10, 15, 25, 40, 80],
             "hl_g": [20, 40, 80, 160], "h_env_g": [5, 10, 25]}

    def gscale(pr):
        f = P.goalie_features(gx, tm, dict(pr, c_sa=1.0))
        f = f[f.season.isin(TUNE) & (f.starter == 1) & (f.gameId % 1_000_000 // 10_000 == 2)].dropna(subset=["mu_sa"])
        return dict(pr, c_sa=f.sa.sum() / f.mu_sa.sum())

    def gobj(pr):
        _, o = goalie_eval(gx, tm, gscale(pr), TUNE)
        return np.mean([ll(*v) for v in o.values()])
    # pull rate and shot share when pulled, measured on tune-season starters (share of team SOG against < 0.8)
    st = gx[(gx.starter == 1) & gx.season.isin(TUNE)].merge(tm[["gameId", "team", "shotsOnGoalAgainst"]], on=["gameId", "team"])
    sh = st.sa / st.shotsOnGoalAgainst
    prm.update(q_pull=float((sh < 0.8).mean()), f_pull=float(sh[sh < 0.8].mean()))
    print("pull", round(prm["q_pull"], 4), round(prm["f_pull"], 3))
    gb = gobj(prm)
    for rnd in range(2):
        for k, vals in ggrid.items():
            for v in vals:
                t = dict(prm, **{k: v}); s = gobj(t)
                if s < gb - 1e-7:
                    gb, prm = s, t
    prm = gscale(prm)
    print("goalie", {k: prm[k] for k in list(ggrid) + ["c_sa"]}, round(gb, 5))
    return prm


def main(quick=False):
    global tm_glob, sk_glob, tp_glob
    sk, tm, gg, bg = load()
    tm_glob = tm
    tp = team_pred(bg)
    sk_glob, tp_glob = sk, tp
    gx = goalie_rows(gg, tm, bg)
    t0 = time.time()
    prm = tune(sk, gx, tm, tp, quick)
    print(f"tuned in {time.time() - t0:.0f}s")
    json.dump({k: prm[k] for k in P.DEFAULT}, open(ROOT / "out" / "props_params.json", "w"), indent=1)

    res = {"params": {k: prm[k] for k in P.DEFAULT}, "tune_seasons": ["2021-22", "2022-23"],
           "test_seasons": ["2023-24", "2024-25", "2025-26"], "markets": {},
           "notes": ["Walk-forward: each projection uses only earlier games.",
                     "Actual dressed skaters and actual starting goalies; real prop lines vary by player, so P(SOG>=k) "
                     "is evaluated at fixed thresholds for every dressed skater.",
                     "Baseline = season-to-date per-game average (fallback last season, then position) with Poisson.",
                     "No historical DraftKings prop prices, so this measures calibration and accuracy, not betting ROI.",
                     "Data: MoneyPuck.com game logs and shot data."]}
    for name, seasons in (("tune", TUNE), ("test", TEST)):
        f, o = skater_eval(sk, prm, seasons, tp)
        sub = sk[sk.season.isin(seasons) & (sk.gameId % 1_000_000 // 10_000 == 2)].index
        nb = {c: naive(sk, c)[sub] for c in ("sog", "pts", "g")}
        base = {f"sog{k}": poisson.sf(k - 1, nb["sog"]) for k in SOG_K}
        base["pts1"] = poisson.sf(0, nb["pts"]); base["g1"] = poisson.sf(0, nb["g"])
        gf, go = goalie_eval(gx, tm, prm, seasons)
        gsub = gf  # naive saves: season-to-date saves per start (starter rows)
        o.update(go)
        for k, (p, y) in o.items():
            m = res["markets"].setdefault(k, {})
            e = {"n": int(len(y)), "base_rate": round(float(np.mean(y)), 4), "mean_pred": round(float(np.mean(p)), 4),
                 "logloss": round(ll(p, y), 5), "brier": round(float(np.mean((p - y) ** 2)), 5)}
            if k in base:
                e["baseline_logloss"] = round(ll(base[k], y), 5)
            e["calibration"] = calib(p, y) if name == "test" else None
            m[name] = e
        if name == "test":
            res["test_means"] = {"sog": [round(float(f.mu_sog.mean()), 3), round(float(f.sog.mean()), 3)],
                                 "goals": [round(float(f.mu_g.mean()), 4), round(float(f.g.mean()), 4)],
                                 "points": [round(float((prm['c_pts'] * (f.mu_g + f.mu_a)).mean()), 4), round(float(f.pts.mean()), 4)],
                                 "saves": [round(float((gf.mu_sa * gf.sv_proj).mean()), 2), round(float(gf.saves.mean()), 2)],
                                 "_format": "[mean projected, mean actual] per player-game"}
    # naive saves baseline on test
    gs = gx[gx.starter == 1].sort_values(["date", "gameId"]).copy()
    g = gs.groupby(["goalie_id", "season"]).saves
    stdv = (g.cumsum() - gs.saves) / g.cumcount().replace(0, np.nan)
    gs["nb"] = stdv.fillna(gs.groupby("season").saves.transform("mean"))
    gs = gs[gs.season.isin(TEST) & (gs.gameId % 1_000_000 // 10_000 == 2)]
    gt = P.goalie_features(gx, tm, prm)
    gt = gt[gt.season.isin(TEST) & (gt.starter == 1) & (gt.gameId % 1_000_000 // 10_000 == 2)].dropna(subset=["mu_sa"])
    gs = gs[gs.gameId.isin(gt.gameId)].merge(gt[["gameId", "goalie_id"]], on=["gameId", "goalie_id"])
    gs = gs.set_index(["gameId", "goalie_id"]).loc[list(zip(gt.gameId, gt.goalie_id))]
    for L in SAVE_LINES:
        k = int(np.floor(L)) + 1
        res["markets"][f"sv{L}"]["test"]["baseline_logloss"] = round(ll(poisson.sf(k - 1, gs.nb.to_numpy()), (gs.saves >= k).astype(int).to_numpy()), 5)
    json.dump(res, open(ROOT / "out" / "props_backtest.json", "w"), indent=1)
    print(json.dumps({k: {"test_ll": v["test"]["logloss"], "base": v["test"].get("baseline_logloss"),
                          "rate": v["test"]["base_rate"], "pred": v["test"]["mean_pred"]} for k, v in res["markets"].items()}, indent=1))
    print(res["test_means"])


if __name__ == "__main__":
    main("--quick" in sys.argv)
