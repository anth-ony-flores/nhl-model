import json, itertools, numpy as np, pandas as pd
from model import game_probs, p_over
ev=pd.read_parquet('../out/backtest_games.parquet')
ev=ev[ev.xg_h.notna()].copy()
tune=ev.season.isin([2021,2022]).values; test=(ev.phase=='Test').values
ch=ev.reg_home[tune].mean()/ev.xg_h[tune].mean(); ca=ev.reg_away[tune].mean()/ev.xg_a[tune].mean()
def stats(mask,prm,s):
    t=ev[mask]; o=[game_probs(s*ch*r.xg_h,s*ca*r.xg_a,prm) for r in t.itertuples()]
    y=t.home_win.values; ph=np.array([g['p_home'] for g in o])
    tot=(t.final_home+t.final_away).values; mar=(t.final_home-t.final_away).values
    regt=(t.reg_home+t.reg_away).values
    r={'LL':-np.mean(y*np.log(ph)+(1-y)*np.log(1-ph)),
       'tie':np.mean([g['p_tie'] for g in o])-t.ot.mean(),
       'reg_goals':np.mean([g['exp_reg_h']+g['exp_reg_a'] for g in o])-regt.mean(),
       'o55':np.mean([p_over(g['total_dist'],5.5)[0] for g in o])-(tot>5.5).mean(),
       'o65':np.mean([p_over(g['total_dist'],6.5)[0] for g in o])-(tot>6.5).mean(),
       'h15':np.mean([g['p_home_m15'] for g in o])-(mar>=2).mean(),
       'a15':np.mean([g['p_away_m15'] for g in o])-(mar<=-2).mean()}
    return r
best=None
sub=tune & (np.random.RandomState(0).rand(len(ev))<0.5)
for q,tk in itertools.product([0.15,0.25,0.35,0.45],[1.3,1.45,1.6]):
    prm={'tie_k':tk,'ot_s':1.0,'en_q':q}
    r=stats(sub,prm,1.0); s=1-r['reg_goals']/ (ev.reg_home[sub].mean()+ev.reg_away[sub].mean())
    r=stats(sub,prm,s)
    err=r['tie']**2+r['o55']**2+r['o65']**2+r['h15']**2+r['a15']**2+(r['reg_goals']/6)**2
    print(q,tk,round(s,4),{k:round(v,4) for k,v in r.items()},round(err,5),flush=True)
    if best is None or err<best[0]: best=(err,prm,s)
print('BEST',best)
prm,s=best[1],best[2]
print('TEST new',{k:round(v,4) for k,v in stats(test,prm,s).items()})
print('TEST old',{k:round(v,4) for k,v in stats(test,{'tie_k':1.0,'ot_s':0.6},1.0).items()})
json.dump({'dist':prm,'scale':s},open('../out/dist_calib.json','w'))
