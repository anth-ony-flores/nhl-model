import json, numpy as np, pandas as pd
from model import game_probs, p_over
ev=pd.read_parquet('../out/backtest_games.parquet'); P=json.load(open('../out/params.json'))
ev=ev[ev.xg_h.notna()].copy()
tune=ev.season.isin([2021,2022]); test=ev.phase=='Test'
ch=ev.reg_home[tune].mean()/ev.xg_h[tune].mean(); ca=ev.reg_away[tune].mean()/ev.xg_a[tune].mean()
def run(tk,mask):
    o=[]
    for r in ev[mask].itertuples():
        g=game_probs(ch*r.xg_h,ca*r.xg_a,{"tie_k":tk,"ot_s":P['dist']['ot_s']})
        o.append((g['p_tie'],g['p_home'],g['p_home_m15'],g['p_away_m15'],p_over(g['total_dist'],5.5)[0],p_over(g['total_dist'],6.5)[0],g['exp_total']))
    return np.array(o)
y=ev.home_win.values
for tk in [1.0,1.2,1.3,1.35,1.4]:
    o=run(tk,tune); yy=y[tune.values]
    ll=-np.mean(yy*np.log(o[:,1])+(1-yy)*np.log(1-o[:,1]))
    print(tk,'pred tie',o[:,0].mean().round(4),'actual',ev.ot[tune].mean().round(4),'LL',round(ll,5))
print('---')
P['dist']['ot_s']=0.6
for s in [0.6,0.8,1.0]:
    P['dist']['ot_s']=s
    o=run(1.4,tune); yy=y[tune.values]
    print('ot_s',s,'LL',round(-np.mean(yy*np.log(o[:,1])+(1-yy)*np.log(1-o[:,1])),5))
