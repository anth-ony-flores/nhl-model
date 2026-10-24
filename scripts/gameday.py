"""Game-day refresh loop for GitHub Actions.
Refreshes injuries, projections and the site every INTERVAL minutes while any game starts within WINDOW hours;
sleeps otherwise; exits after the last puck drop or before the job time limit.
Each refresh commits, pushes, and dispatches the board workflow in 'publish' mode to redeploy Pages."""
import json, os, subprocess, sys, time, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MST = timezone(timedelta(hours=-7))
INTERVAL = 10 * 60
WINDOW = timedelta(hours=2)
BUDGET = timedelta(minutes=int(os.environ.get("BUDGET_MIN", "340")))


def sh(cmd, cwd=ROOT):
    print("+", cmd, flush=True)
    return subprocess.run(cmd, shell=True, cwd=cwd).returncode


def starts(day):
    req = urllib.request.Request(f"https://api-web.nhle.com/v1/schedule/{day}", headers={"User-Agent": "Mozilla/5.0"})
    js = json.load(urllib.request.urlopen(req, timeout=30))
    games = next((d["games"] for d in js["gameWeek"] if d["date"] == day), [])
    return sorted(datetime.strptime(g["startTimeUTC"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) for g in games)


def refresh(day):
    sh("git pull -q --rebase -X theirs origin main")
    rc = sh(f"python injuries.py {day} && python board.py {day} && python export_site.py {day}", cwd=ROOT / "src")
    if rc != 0:
        print("refresh failed; will retry next cycle", flush=True)
        return
    sh("git add -A out site")
    if subprocess.run("git diff --cached --quiet", shell=True, cwd=ROOT).returncode == 0:
        print("no changes", flush=True)
        return
    sh(f'git commit -q -m "gameday {day} {datetime.now(MST):%H:%M} MST"')
    for _ in range(3):
        if sh("git pull -q --rebase -X theirs origin main && git push -q") == 0:
            break
        time.sleep(5)
    sh("gh workflow run board.yml -f mode=publish")


def main():
    t0 = datetime.now(timezone.utc)
    day = datetime.now(MST).strftime("%Y-%m-%d")
    st = starts(day)
    if not st:
        print("no games today"); return
    last = st[-1]
    print(f"{day}: {len(st)} games, first {st[0]:%H:%M}Z, last {last:%H:%M}Z", flush=True)
    while True:
        now = datetime.now(timezone.utc)
        if now > last + timedelta(minutes=5) or now - t0 > BUDGET:
            print("done", flush=True); return
        upcoming = [s for s in st if s > now - timedelta(minutes=5)]
        if upcoming and upcoming[0] - now <= WINDOW:
            refresh(day)
            time.sleep(INTERVAL)
        else:
            nxt = upcoming[0] - WINDOW if upcoming else last
            wait = max(60, min((nxt - now).total_seconds(), (t0 + BUDGET - now).total_seconds()))
            print(f"next window opens {nxt:%H:%M}Z; sleeping {int(wait // 60)} min", flush=True)
            time.sleep(wait)


if __name__ == "__main__":
    main()
