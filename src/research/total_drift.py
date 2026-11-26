"""Does a rolling goals correction fix total bias? Walk-forward: factor for each game uses only earlier games.
Historical: backtest_games (fixed-scale model). Live: tracked board games vs final totals."""
import numpy as np, pandas as pd, json, glob
e = pd.read_parquet("out/backtest_games.parquet")
e = e[e.exp_total.notna()].sort_values("date").copy()
e["pred_reg"] = e.exp_total - e.p_tie
e["act_reg"] = e.reg_home + e.reg_away
e["act_tot"] = e.final_home + e.final_away
def run(df, N, K):
    """factor = (sum act_reg over last N prior game-days' games + K*pred) / (sum pred_reg + K*pred) : shrunk ratio."""
    f = np.ones(len(df)); dates = df.date.values; ar = df.act_reg.values; pr = df.pred_reg.values
    cs_a, cs_p = np.concatenate([[0], np.cumsum(ar)]), np.concatenate([[0], np.cumsum(pr)])
    first = np.searchsorted(dates, dates, side="left")   # index of first game on that date (prior games end here)
    for i in range(len(df)):
        j = first[i]; s = max(0, j - N)
        a, p = cs_a[j] - cs_a[s], cs_p[j] - cs_p[s]
        f[i] = (a + K * 6) / (p + K * 6) if N else 1.0
    return f
test = e[e.phase.isin(["Test", "Live"])]
res = []
for N in [0, 200, 400, 800, 1300]:
    for K in [0, 50, 150]:
        if N == 0 and K: continue
        f = run(e, N, K)[e.phase.isin(["Test", "Live"]).values]
        pred_tot = test.pred_reg * f + test.p_tie
        err = pred_tot - test.act_tot
        res.append(dict(N=N, K=K, bias=err.mean(), mae=err.abs().mean(), rmse=np.sqrt((err**2).mean()),
                        bias_2025=err[test.season == 2025].mean(), bias_2026=err[test.season == 2026].mean()))
print(pd.DataFrame(res).round(4).to_string(index=False))
by = test.groupby("season").apply(lambda t: pd.Series({"pred": t.exp_total.mean(), "act": t.act_tot.mean()}))
print(by.round(3))
