#!/usr/bin/env bash
# Download MoneyPuck raw data (free for non-commercial use; credit MoneyPuck.com).
# FULL=1 also pulls past seasons (needed by data.py and players.py).
set -euo pipefail
cd "$(dirname "$0")/../data"
UA="Mozilla/5.0 (personal NHL model)"
curl -sSL -A "$UA" -o all_teams.csv https://moneypuck.com/moneypuck/playerData/careers/gameByGame/all_teams.csv
SEASONS="2026"
if [ "${FULL:-0}" = "1" ]; then SEASONS="2020 2021 2022 2023 2024 2025 2026"; fi
for y in $SEASONS; do
  curl -sSL -A "$UA" -o shots_$y.zip https://peter-tanner.com/moneypuck/downloads/shots_$y.zip
  unzip -o -q -j shots_$y.zip && rm shots_$y.zip
  curl -sSL -A "$UA" -o sk_$y.zip https://peter-tanner.com/moneypuck/downloads/seasonPlayersSummary/skaters/$y.zip
  unzip -o -q -j sk_$y.zip && rm sk_$y.zip
done
ls -la
