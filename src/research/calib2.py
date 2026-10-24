import json, numpy as np, pandas as pd
from model import game_probs, p_over
ev=pd.read_parquet('../out/backtest_games.parquet'); P=json.load(open('../out/params.json'))
ev=ev[ev.xg_h.notna()].copy()
tune=ev.season.isin([2021,2022]); test=(ev.phase=='Test')
ch=ev.reg_home[tune].mean()/ev.xg_h[tune].mean(); ca=ev.reg_away[tune].mean()/ev.xg_a[tune].mean()
t=ev[test].copy()
for name,prm in [('old',{"tie_k":1.0,"ot_s":0.6}),('new',{"tie_k":1.4,"ot_s":1.0})]:
    o=[game_probs(ch*r.xg_h,ca*r.xg_a,prm) for r in t.itertuples()]
    ph=np.array([g['p_home'] for g in o]); y=t.home_win.values
    tot=(t.final_home+t.final_away).values; mar=(t.final_home-t.final_away).values
    o55=np.array([p_over(g['total_dist'],5.5)[0] for g in o]); o65=np.array([p_over(g['total_dist'],6.5)[0] for g in o])
    h15=np.array([g['p_home_m15'] for g in o]); a15=np.array([g['p_away_m15'] for g in o])
    print(name,'ML LL',round(-np.mean(y*np.log(ph)+(1-y)*np.log(1-ph)),5),'tie',round(np.mean([g['p_tie'] for g in o]),4),'actual OT',round(t.ot.mean(),4))
    print('  over5.5 pred',o55.mean().round(4),'act',(tot>5.5).mean().round(4),' over6.5 pred',o65.mean().round(4),'act',(tot>6.5).mean().round(4))
    print('  home-1.5 pred',h15.mean().round(4),'act',(mar>=2).mean().round(4),' away-1.5 pred',a15.mean().round(4),'act',(mar<=-2).mean().round(4))
    # puck line calibration for favorite -1.5
    fav=np.where(ph>=0.5,h15,a15); favwin2=np.where(ph>=0.5,mar>=2,mar<=-2)
    b=pd.cut(fav,[0,.25,.3,.35,.4,1]); print(pd.DataFrame({'p':fav,'a':favwin2}).groupby(b,observed=True).agg(n=('p','size'),pred=('p','mean'),act=('a','mean')).round(3).to_string())
