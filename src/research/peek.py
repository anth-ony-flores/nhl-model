import pandas as pd
df=pd.read_csv('data/all_teams.csv',usecols=['team','season','gameId','opposingTeam','home_or_away','gameDate','situation','xGoalsFor','xGoalsAgainst','goalsFor','goalsAgainst','iceTime','flurryScoreVenueAdjustedxGoalsFor','flurryScoreVenueAdjustedxGoalsAgainst','playoffGame'] if True else None)
print(df.situation.value_counts())
print(df.groupby('season').gameId.nunique())
print(df[df.season>=2021].team.nunique(), sorted(df[df.season>=2025].team.unique()))
print(df.gameDate.max(), df.columns.tolist())
print(df[(df.season==2026)].playoffGame.value_counts())
