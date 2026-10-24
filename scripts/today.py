"""Print the slate date in Arizona time (MST, no DST). Usage: python scripts/today.py [--yesterday]"""
import sys
from datetime import datetime, timedelta, timezone

now = datetime.now(timezone(timedelta(hours=-7)))
if "--yesterday" in sys.argv:
    now -= timedelta(days=1)
print(now.strftime("%Y-%m-%d"))
