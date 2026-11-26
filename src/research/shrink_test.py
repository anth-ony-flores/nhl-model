"""Shrink the model toward DraftKings' close before picking: p* = logistic(w*logit(model) + (1-w)*logit(market)).
Replays the 232 tracked games with the corrected scoring constants. Reports picks, W-L, units, and closing line
value (market move between open and close on the picked side; computable for either side from the log)."""
import json, glob, sys
import numpy as np, pandas as pd
sys.path.insert(0, "src")
from model import game_probs, p_over
from picks import novig, profit
C = json.load(open("out/dist_calib.json")); P = json.load(open("out/params.json"))
L = pd.read_csv("tracking/log.csv")
B = {}
for f in sorted(glob.glob("out/board_2026-1*.json")):
    b = json.load(open(f)); fin = {r["team"]: r["finishing"] for r in b["ratings"]}
    for g in b["games"]:
        B[f"{b['date']} {g['away']}@{g['home']}"] = (g, fin)
lg = lambda p: np.log(p / (1 - p)); ex = lambda z: 1 / (1 + np.exp(-z))
recs = []
for r in L.itertuples():
    if r.game not in B: continue
    g, fin = B[r.game]
    lh = C["scale"] * P["c_home"] * g["xg_home"] * (1 + fin.get(g["home"], 0)) * (1 - g["away_goalie"]["gsax_per_xg"])
    la = C["scale"] * P["c_away"] * g["xg_away"] * (1 + fin.get(g["away"], 0)) * (1 - g["home_goalie"]["gsax_per_xg"])
    pr = game_probs(lh, la, C["dist"]); hs, as_ = r.home_score, r.away_score
    # moneyline: home side
    if pd.notna(r.dk_p_home):
        cl = r.dk_p_home
        op = None
        if pd.notna(r.ml_open_p):   # open vig-free prob of the side picked live; convert to home side
            op = r.ml_open_p if str(r.ml_pick).startswith(r.home) else 1 - r.ml_open_p
        recs.append(dict(mkt="ml", m=pr["p_home"], k=cl, op=op, win_a=hs > as_, oa=r.dk_ml_home, ob=r.dk_ml_away, push=False))
    # total: over side
    if pd.notna(r.dk_total) and pd.notna(r.dk_over):
        o, u = p_over(pr["total_dist"], r.dk_total); mo = o / (o + u); k = novig(r.dk_over, r.dk_under)
        op = None
        if pd.notna(r.tot_open_p):
            op = r.tot_open_p if str(r.tot_pick).startswith("Over") else 1 - r.tot_open_p
        t = hs + as_
        recs.append(dict(mkt="tot", m=mo, k=k, op=op, win_a=t > r.dk_total, oa=r.dk_over, ob=r.dk_under, push=t == r.dk_total))
    # puck line: home side at DK's home line (+/-1.5)
    if pd.notna(r.dk_pl_home_line) and pd.notna(r.dk_pl_home_odds):
        hl = r.dk_pl_home_line
        mh = pr["p_home_m15"] if hl < 0 else 1 - pr["p_away_m15"]
        k = novig(r.dk_pl_home_odds, r.dk_pl_away_odds)
        op = None
        if pd.notna(r.pl_open_p):
            op = r.pl_open_p if str(r.pl_pick).startswith(r.home) else 1 - r.pl_open_p
        recs.append(dict(mkt="pl", m=mh, k=k, op=op, win_a=(hs - as_ + hl) > 0, oa=r.dk_pl_home_odds, ob=r.dk_pl_away_odds, push=False))
D = pd.DataFrame(recs).dropna(subset=["k"])
rows = []
for mk, G in D.groupby("mkt"):
    for w in [1.0, 0.5, 0.35, 0.2]:
        ps = ex(w * lg(G.m.clip(1e-4, 1 - 1e-4)) + (1 - w) * lg(G.k))
        for th in [0.0, 0.01, 0.02, 0.03]:
            side_a = ps > G.k; edge = np.where(side_a, ps - G.k, G.k - ps)
            sel = (edge > max(th, 0.0005)) & ~G.push
            if sel.sum() == 0: continue
            S = G[sel]; sa = side_a[sel]
            win = np.where(sa, S.win_a, ~S.win_a.astype(bool))
            units = [profit(a if s else b) if wv else -1.0 for a, b, s, wv in zip(S.oa, S.ob, sa, win)]
            clv = [((k - op) if s else (op - k)) for k, op, s in zip(S.k, S.op, sa) if op is not None and not pd.isna(op)]
            rows.append(dict(mkt=mk, w=w, min_edge=th, picks=int(sel.sum()), wins=int(win.sum()),
                             units=round(sum(units), 2), roi=round(sum(units) / sel.sum(), 3),
                             clv_pts=round(100 * np.mean(clv), 2) if clv else None,
                             beat_close=round(np.mean(np.array(clv) > 0), 3) if clv else None))
R = pd.DataFrame(rows)
print(R.to_string(index=False))
