# Ice Ledger NHL Board

A personal NHL projection board: model win probabilities, totals and puck lines for each game, with live scores, in-game stats and DraftKings lines pulled in the browser.

- `index.html` renders the board from `data/board.json`.
- `live.js` / `live.css` add the live layer. It polls ESPN every 30 seconds and falls back quietly if the feed is down.
- `data/board.json` is written by `src/export_site.py` from the model's daily output.

## Data credits

- [MoneyPuck.com](https://moneypuck.com): expected goals, shots and goalie data behind the model. Free for non-commercial use with credit.
- NHL public API (`api-web.nhle.com`): schedule, standings and starting goalies.
- ESPN public scoreboard and game summary feeds: live scores, box scores and DraftKings lines. These feeds are unofficial and undocumented, and they may change without notice.

Personal, non-commercial use. Projections are model estimates, not betting advice.
