import json, numpy as np, pandas as pd
from model import game_probs
ev=pd.read_parquet('../out/backtest_games.parquet'); ev=ev[ev.xg_h.notna()].copy()
g=pd.read_parquet('../data/games.parquet'); g=g[g.playoff==0].copy()
g['adj']=(g.home_xg_adj+g.away_xg_adj)*3600/g.icetime; g['reg']=g.reg_home+g.reg_away
dates=np.sort(g.date.unique()); cm={}
for d in ev.date.unique():
    i=np.searchsorted(dates,d); w=g[(g.date<d)&(g.date>=dates[max(0,i-80)])]; cm[d]=w.reg.sum()/w.adj.sum()
ev['c']=ev.date.map(cm)
m=pd.read_parquet('../data/missing.parquet').set_index(['gameId','team']).missing_value
ev['Mh']=[m.get((a,b),0.0) for a,b in zip(ev.gameId,ev.home)]
ev['Ma']=[m.get((a,b),0.0) for a,b in zip(ev.gameId,ev.away)]
print('coverage', (ev.Mh!=0).mean().round(3))
C=json.load(open('../out/dist_calib.json')); S=json.load(open('../out/share.json'))
y=ev.home_win.values; tune=ev.season.isin([2021,2022]).values; test=ev.season.isin([2023,2024,2025]).values
def run(k):
    xh=ev.xg_h-k*ev.Mh/2+k*ev.Ma/2; xa=ev.xg_a-k*ev.Ma/2+k*ev.Mh/2
    p=np.array([game_probs(C['scale']*c*S['hshare']*a,C['scale']*c*S['ashare']*b,C['dist'])['p_home'] for a,b,c in zip(xh.clip(lower=.5),xa.clip(lower=.5),ev.c)])
    ll=lambda msk:-np.mean(y[msk]*np.log(p[msk])+(1-y[msk])*np.log(1-p[msk]))
    return ll(tune),ll(test)
for k in [0,0.5,1,1.5,2,3,4]:
    a,b=run(k); print(k,round(a,5),round(b,5),flush=True)
