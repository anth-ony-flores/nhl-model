"""Compare model vs de-vigged closing moneylines (Sportsbook Reviews archive, 2021-22 and part of 2022-23).
Caveat: these are the seasons the model was tuned on."""
import numpy as np, pandas as pd
M={'Anaheim':'ANA','Arizona':'UTA','Boston':'BOS','Buffalo':'BUF','Calgary':'CGY','Carolina':'CAR','Chicago':'CHI','Colorado':'COL','Columbus':'CBJ','Dallas':'DAL','Detroit':'DET','Edmonton':'EDM','Florida':'FLA','LosAngeles':'LAK','Minnesota':'MIN','Montreal':'MTL','NYIslanders':'NYI','NYRangers':'NYR','Nashville':'NSH','NewJersey':'NJD','Ottawa':'OTT','Philadelphia':'PHI','Pittsburgh':'PIT','SanJose':'SJS','Seattle':'SEA','SeattleKraken':'SEA','St.Louis':'STL','TampaBay':'TBL','Toronto':'TOR','Vancouver':'VAN','Vegas':'VGK','Washington':'WSH','Winnipeg':'WPG'}
def imp(o):
    o=float(o); return 100/(o+100) if o>0 else -o/(-o+100)
out=[]
for s,y0 in [('2021-22',2021),('2022-23',2022)]:
    t=pd.read_html(f'../odds/sbr_{s}.htm')[0]; t.columns=t.iloc[0]; t=t[1:].reset_index(drop=True)
    for i in range(0,len(t)-1,2):
        a,h=t.iloc[i],t.iloc[i+1]
        md=int(a.Date); mo,dy=md//100,md%100; yr=y0 if mo>=9 else y0+1
        try: pa,ph=imp(a.Close),imp(h.Close)
        except: continue
        out.append({'date':pd.Timestamp(yr,mo,dy),'away':M[a.Team.replace(' ','')],'home':M[h.Team.replace(' ','')],'mkt_home':ph/(pa+ph),'vig':pa+ph-1})
o=pd.DataFrame(out)
ev=pd.read_parquet('../out/backtest_games.parquet')
m=ev.merge(o,on=['date','home','away'],how='inner')
print('matched',len(m),'of',len(o))
y=m.home_win.values
ll=lambda p:-np.mean(y*np.log(p)+(1-y)*np.log(1-p))
for c in ['p_home','mkt_home','p_base_pct']: print(c,round(ll(m[c].values),5))
print('avg vig',m.vig.mean().round(4))
# simple betting sim: bet side where model prob exceeds market vig-free prob by >= edge, flat 1 unit at closing odds
def dec(o): o=float(o); return 1+ (o/100 if o>0 else 100/-o)
from scipy.optimize import minimize
lg=lambda p:np.log(p/(1-p))
X1,X2=lg(m.mkt_home.values),lg(m.p_home.values)
f=lambda b:ll(1/(1+np.exp(-(b[0]+b[1]*X1+b[2]*X2))))
r=minimize(f,[0,1,0]); print('blend weights (const, market, model)',r.x.round(3),'LL',round(r.fun,5))
# flat-stake sim at closing odds, model edge >= 3 pts vs vig-free market
pr=[]
