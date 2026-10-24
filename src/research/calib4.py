import json, numpy as np, pandas as pd
from model import game_probs, p_over
ev=pd.read_parquet('../out/backtest_games.parquet')
g=pd.read_parquet('../data/games.parquet'); g=g[g.playoff==0].copy()
per60=3600/g.icetime
g['adj']= (g.home_xg_adj+g.away_xg_adj)*per60; g['reg']=g.reg_home+g.reg_away
dates=np.sort(g.date.unique())
ev=ev[ev.xg_h.notna()].copy()
tune=ev.season.isin([2021,2022]).values; test=(ev.phase=='Test').values
C=json.load(open('../out/dist_calib.json')); prm=C['dist']; s=C['scale']
ch0=ev.reg_home[tune].mean()/ev.xg_h[tune].mean(); ca0=ev.reg_away[tune].mean()/ev.xg_a[tune].mean()
hshare=ch0/((ch0+ca0)/2); ashare=ca0/((ch0+ca0)/2)
for W in [80,160,300]:
    cmap={}
    for d in ev.date.unique():
        i=np.searchsorted(dates,d); lo=dates[max(0,i-W)]
        w=g[(g.date<d)&(g.date>=lo)]
        cmap[d]=w.reg.sum()/w.adj.sum()
    ev['c']=ev.date.map(cmap)
    t=ev[test]; o=[game_probs(s*r.c*hshare*r.xg_h,s*r.c*ashare*r.xg_a,prm) for r in t.itertuples()]
    tot=(t.final_home+t.final_away).values; regt=(t.reg_home+t.reg_away).values; mar=(t.final_home-t.final_away).values
    y=t.home_win.values; ph=np.array([x['p_home'] for x in o])
    print(W,'LL',round(-np.mean(y*np.log(ph)+(1-y)*np.log(1-ph)),5),'reg bias',round(np.mean([x['exp_reg_h']+x['exp_reg_a'] for x in o])-regt.mean(),3),
      'o55',round(np.mean([p_over(x['total_dist'],5.5)[0] for x in o])-(tot>5.5).mean(),4),'o65',round(np.mean([p_over(x['total_dist'],6.5)[0] for x in o])-(tot>6.5).mean(),4),
      'h15',round(np.mean([x['p_home_m15'] for x in o])-(mar>=2).mean(),4),'a15',round(np.mean([x['p_away_m15'] for x in o])-(mar<=-2).mean(),4),'tie',round(np.mean([x['p_tie'] for x in o])-t.ot.mean(),4))
    for ss in t.season.unique():
        m=(t.season==ss).values; print('   ',ss,'reg bias',round(np.mean([o[i]['exp_reg_h']+o[i]['exp_reg_a'] for i in np.where(m)[0]])-regt[m].mean(),3))
json.dump({'hshare':hshare,'ashare':ashare},open('../out/share.json','w'))
