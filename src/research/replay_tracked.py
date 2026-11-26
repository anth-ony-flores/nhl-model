"""Replay tracked games with alternative scoring constants. Reconstructs each game's goal rates from the saved board
(xG, finishing, goalie GSAx/xG) so only the constant changes. Grades totals vs DraftKings' closing line."""
import json, glob, sys
import numpy as np, pandas as pd
sys.path.insert(0, "src")
from model import game_probs, p_over
from picks import novig, profit
C = json.load(open("out/dist_calib.json")); S = json.load(open("out/share.json")); P = json.load(open("out/params.json"))
L = pd.read_csv("tracking/log.csv")
B = {}
for f in sorted(glob.glob("out/board_2026-1*.json")):
    b = json.load(open(f)); fin = {r["team"]: r["finishing"] for r in b["ratings"]}
    for g in b["games"]:
        B[f"{b['date']} {g['away']}@{g['home']}"] = (g, b["goals_per_xg"], fin)
def rates(key, mode):
    g, ct, fin = B[key]
    xh, xa = g["xg_home"], g["xg_away"]
    gh, ga = g["home_goalie"]["gsax_per_xg"], g["away_goalie"]["gsax_per_xg"]
    if mode == "old": mh, ma = C["scale"] * ct * S["hshare"], C["scale"] * ct * S["ashare"]
    else: mh, ma = C["scale"] * P["c_home"], C["scale"] * P["c_away"]
    return mh * xh * (1 + fin.get(g["home"], 0)) * (1 - ga), ma * xa * (1 + fin.get(g["away"], 0)) * (1 - gh)
out = []
for r in L.itertuples():
    if r.game not in B or pd.isna(r.dk_total): continue
    act = r.home_score + r.away_score; row = {"game": r.game, "act": act, "line": r.dk_total}
    mk = novig(r.dk_over, r.dk_under)
    for mode in ["old", "new"]:
        lh, la = rates(r.game, mode); pr = game_probs(lh, la, C["dist"])
        o, u = p_over(pr["total_dist"], r.dk_total); po = o / (o + u)
        row[f"tot_{mode}"] = pr["exp_total"]; row[f"po_{mode}"] = po; row[f"ph_{mode}"] = pr["p_home"]
        if act != r.dk_total and mk is not None:
            over = po > mk; edge = (po - mk) if over else (mk - po)
            win = (act > r.dk_total) == over
            row[f"pick_{mode}"] = "O" if over else "U"; row[f"edge_{mode}"] = edge
            row[f"u_{mode}"] = profit(r.dk_over if over else r.dk_under) if win else -1.0
            row[f"w_{mode}"] = win
    row["mk"] = mk; row["y_home"] = int(r.home_score > r.away_score); row["dk_ph"] = r.dk_p_home
    out.append(row)
D = pd.DataFrame(out); D = D[D.mk.notna() & (D.act != D.line)]
y = (D.act > D.line).astype(int)
ll = lambda p, y: float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
print("games", len(D), "actual mean total", D.act.mean().round(3))
for m in ["old", "new"]:
    print(m, "mean proj", D[f"tot_{m}"].mean().round(3), "over-LL", round(ll(D[f"po_{m}"], y), 4),
          "picks O/U", (D[f"pick_{m}"] == "O").sum(), (D[f"pick_{m}"] == "U").sum(),
          "W-L", int(D[f"w_{m}"].sum()), int((~D[f"w_{m}"].astype(bool)).sum()), "units", D[f"u_{m}"].sum().round(2),
          "ML-LL", round(ll(D[f"ph_{m}"], D.y_home), 4))
print("market over-LL", round(ll(D.mk, y), 4))
