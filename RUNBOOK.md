# NHL board refresh runbook

Artifact: https://claude.ai/artifact/FvcEUXLMFnzkLuwdVTEz98 (publish from
/tmp/claude-0/-home-claude/58ed3526-a6f4-5979-8934-be137e911832/scratchpad/nhl_board.html, same path keeps the URL).
All times America/Phoenix (MST, UTC-7). Game day: DAY (YYYY-MM-DD).

## Morning run (full)
1. Refresh MoneyPuck data (adds last night's games):
   cd /home/claude/nhl-model/data && curl -sL -o all_teams.csv https://moneypuck.com/moneypuck/playerData/careers/gameByGame/all_teams.csv
   curl -sL -o shots_2026.zip https://peter-tanner.com/moneypuck/downloads/shots_2026.zip && unzip -o -q shots_2026.zip
   curl -sL -o sk_2026.zip https://peter-tanner.com/moneypuck/downloads/seasonPlayersSummary/skaters/2026.zip && unzip -o -q -j sk_2026.zip
   cd /home/claude/nhl-model/src && python3 data.py && python3 players.py
2. News pass (see below), then rebuild and publish.

## Pre-game runs (every 15 min, from 2 h before first puck drop until the last game starts)
1. Goalie check: WebFetch https://www.dailyfaceoff.com/starting-goalies/DAY for confirmed starters,
   plus any team news from the last few hours (WebSearch "<team> starting goalie tonight", injuries).
2. Update out/goalie_overrides_DAY.json: CONFIRMED starters, goalies ruled out by a cited source, or a cited
   "expected" starter when the model's default goalie is injured. board.py freezes started games automatically.
   Format {"TEAM": {"id": NHL player id, "name": "...", "source": "who/when"}}. Goalie ids: data/goalies.parquet.
3. Update out/summaries_DAY.json text where news changed (paraphrase, cite, no em dashes, 3 to 5 sentences).
   Summaries quote model numbers only when they match the new run.
4. cd /home/claude/nhl-model/src && python3 injuries.py DAY && python3 board.py DAY && python3 metrics.py DAY && python3 build_page.py DAY
   cp /home/claude/nhl-model/out/nhl_board.html <scratchpad path above>; publish with Artifact (same file path).
5. Skip games that already started (keep their last pre-game numbers; do not change them).
6. If the current time is before the last game's start, schedule the next run with send_later in 15 minutes.
   After the last game starts: stop, no further runs.

Only message the user (SendUserMessage) when something material changed: a starter flipped, a key injury, or a
win probability moved 3+ points.

## Repo and GitHub Pages (from Oct 24, 2026)
Source of truth is the repo anth-ony-flores/nhl-model at /home/claude/nhl-model. GitHub Actions runs morning,
pre-game (every 15 min) and nightly tracking on its own. Claude's job on game days is only the judgment layer:
goalie overrides and summaries in out/, then
  cd /home/claude/nhl-model && git pull --rebase -X theirs origin main
  (edit out/goalie_overrides_DAY.json and out/summaries_DAY.json)
  cd src && python3 injuries.py DAY && python3 board.py DAY && python3 export_site.py DAY && python3 build_page.py DAY
  cd .. && git add -A out site && git commit -m "news DAY" && git push   (Pages redeploys on push)
  cp out/nhl_board.html to the artifact scratchpad path and publish (keeps the Claude artifact in sync).

## Staggered cadence (from Oct 24, 2026, 12:20 PM MST)
- GitHub: gameday.yml runs at 8:00 AM and 1:45 PM MST and loops, refreshing every 10 min while any game starts
  within 2 h; idle otherwise; stops after the last puck drop. Each refresh dispatches board.yml (publish) to redeploy.
- Claude news checks: every 30 min when the next puck drop is 60 to 120 min away, every 15 min under 60 min,
  otherwise the next check is set for 120 min before the next puck drop. None after the last puck drop.
