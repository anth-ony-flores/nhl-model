# NHL model

Personal, non-commercial NHL game projection model with a live board on GitHub Pages.

**Board:** https://anth-ony-flores.github.io/nhl-model/

## What it does
- Team ratings from opponent-adjusted expected goals (MoneyPuck), plus goalie, finishing, back-to-back, missing-player and home-ice adjustments.
- Moneyline, total and puck-line probabilities for every game, locked at puck drop.
- Live scores, live game stats and DraftKings lines in the page, read straight from ESPN's public scoreboard feed every 30 seconds.
- Nightly tracking of the model against DraftKings' closing line in `tracking/log.csv`.

## Backtest (2023-24 to 2025-26, 3,936 games, walk-forward)
| Model | Log loss |
|---|---|
| This model | 0.6696 |
| Season points % | 0.6884 |
| Always pick home | 0.6899 |

On 2021-23 closing lines (free archive), the market scored 0.6477 vs the model's 0.6528. Beating the market is not yet shown.

## How it runs
`.github/workflows/board.yml` (all times Arizona):
- 6:30 AM: full refresh (downloads MoneyPuck data, rebuilds ratings, player values, metrics, board).
- 8:00 AM to 8:45 PM, every 15 minutes: injuries, goalie overrides, projections; games lock at puck drop.
- 3:00 AM: logs the previous night's results vs DraftKings' close.

Scheduled runs on GitHub can start a few minutes late. Goalie confirmations and written summaries are added by hand (or by Claude) in `out/goalie_overrides_<day>.json` and `out/summaries_<day>.json`.

## Layout
- `src/` model and pipeline (`data.py`, `players.py`, `metrics.py`, `injuries.py`, `board.py`, `export_site.py`, `track.py`); `src/research/` one-off backtests and calibration (run from `src/` with `PYTHONPATH=.`).
- `site/` the Pages board. `out/` model settings and daily outputs. `data/` processed tables (raw files are downloaded each run and not committed). `tracking/` forward results.

## Data credits
- [MoneyPuck.com](https://moneypuck.com): expected goals, shots, player and goalie data (free for non-commercial use with credit).
- NHL public API: schedule, standings, starters.
- ESPN public scoreboard feed (unofficial): live scores, game stats, DraftKings lines.
- ESPN injury feed, Daily Faceoff and team reporters for lineup news.

No team logos are used.
