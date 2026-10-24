"""Pull historical NHL closing odds from The Odds API (needs ODDS_API_KEY in ~/nhl/.env).
Usage: python fetch_odds.py --check            (1 request: confirms key, shows quota and cost)
       python fetch_odds.py 2023-10-10 2026-04-20 [--markets h2h,totals,spreads]
One snapshot per distinct start time per day, taken 5 minutes before puck drop = closing line.
Cost per snapshot = 10 credits x markets (one 'us' region). Saves to data/odds_raw.jsonl (resumable)."""
import json, sys, time, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY = dict(l.strip().split("=", 1) for l in open(ROOT / ".env") if "=" in l)["ODDS_API_KEY"]
BASE = "https://api.the-odds-api.com/v4/historical/sports/icehockey_nhl/odds"
NHL = "https://api-web.nhle.com/v1/schedule/"
RAW = ROOT / "data" / "odds_raw.jsonl"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r), dict(r.headers)


def snapshot(ts, markets):
    q = urllib.parse.urlencode({"apiKey": KEY, "regions": "us", "markets": markets, "oddsFormat": "american",
                                "date": ts.strftime("%Y-%m-%dT%H:%M:%SZ")})
    data, h = get(f"{BASE}?{q}")
    return data, {k: h.get(k) for k in ["x-requests-remaining", "x-requests-used", "x-requests-last"]}


def start_times(d0, d1):
    """Distinct regular-season/playoff start times from the NHL schedule, by week."""
    out, d = set(), d0
    while d <= d1:
        js, _ = get(NHL + d.strftime("%Y-%m-%d"))
        for day in js.get("gameWeek", []):
            for g in day["games"]:
                if g.get("gameType") in (2, 3):
                    out.add(g["startTimeUTC"])
        d += timedelta(days=7)
    return sorted(datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) for s in out)


def main():
    if "--check" in sys.argv:
        _, q = snapshot(datetime(2024, 1, 15, 23, 55, tzinfo=timezone.utc), "h2h")
        print("quota:", q); return
    d0 = datetime.strptime(sys.argv[1], "%Y-%m-%d"); d1 = datetime.strptime(sys.argv[2], "%Y-%m-%d")
    markets = sys.argv[sys.argv.index("--markets") + 1] if "--markets" in sys.argv else "h2h,totals,spreads"
    done = set()
    if RAW.exists():
        done = {json.loads(l)["snapshot_for"] for l in open(RAW)}
    times = [t for t in start_times(d0, d1) if t.strftime("%Y-%m-%dT%H:%M:%SZ") not in done]
    n_mk = len(markets.split(","))
    print(f"{len(times)} snapshots to pull, about {10 * n_mk * len(times):,} credits")
    with open(RAW, "a") as f:
        for i, t in enumerate(times):
            data, q = snapshot(t - timedelta(minutes=5), markets)
            f.write(json.dumps({"snapshot_for": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "quota": q, "data": data}) + "\n")
            if i % 50 == 0:
                print(i, q, flush=True)
            if q.get("x-requests-remaining") and float(q["x-requests-remaining"]) < 10 * n_mk:
                print("stopping: quota nearly used", q); break
            time.sleep(0.2)


if __name__ == "__main__":
    main()
