import json, numpy as np, pandas as pd
from model import game_probs, p_over
ev=pd.read_parquet('../out/backtest_games.parquet'); ev=ev[ev.xg_h.notna()].copy()
g=pd.read_parquet('../data/games.parquet'); g=g[g.playoff==0].copy()
g['adj']=(g.home_xg_adj+g.away_xg_adj)*3600/g.icetime; g['reg']=g.reg_home+g.reg_away
dates=np.sort(g.date.unique()); W=80
C=json.load(open('../out/dist_calib.json')); S=json.load(open('../out/share.json'))
cm={}
for d in ev.date.unique():
    i=np.searchsorted(dates,d); w=g[(g.date<d)&(g.date>=dates[max(0,i-W)])]; cm[d]=w.reg.sum()/w.adj.sum()
t=ev[ev.phase=='Test'].copy(); t['c']=t.date.map(cm)
o=[game_probs(C['scale']*r.c*S['hshare']*r.xg_h,C['scale']*r.c*S['ashare']*r.xg_a,C['dist']) for r in t.itertuples()]
tot=(t.final_home+t.final_away).values; mar=(t.final_home-t.final_away).values
rows=[]
def add(name,p,a): rows.append({'market':name,'pred':float(np.mean(p)),'actual':float(np.mean(a)),'n':int(len(a))})
add('Goes to OT/SO',[x['p_tie'] for x in o],t.ot.values)
add('Over 5.5',[p_over(x['total_dist'],5.5)[0] for x in o],tot>5.5)
add('Over 6.5',[p_over(x['total_dist'],6.5)[0] for x in o],tot>6.5)
add('Home -1.5 covers',[x['p_home_m15'] for x in o],mar>=2)
add('Away -1.5 covers',[x['p_away_m15'] for x in o],mar<=-2)
fav=np.array([x['p_home_m15'] if x['p_home']>=.5 else x['p_away_m15'] for x in o]); fw=np.where(np.array([x['p_home'] for x in o])>=.5,mar>=2,mar<=-2)
add('Favorite -1.5 covers',fav,fw)
ph=np.array([x['p_home'] for x in o]); y=t.home_win.values
print(pd.DataFrame(rows).round(4).to_string(), 'LL', -np.mean(y*np.log(ph)+(1-y)*np.log(1-ph)))
json.dump({'W':W,'markets':rows},open('../out/market_calib.json','w'),indent=1)
