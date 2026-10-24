"""DraftKings player prop lines (ESPN public feed) vs the prop model.

Usage: python props_lines.py 2026-10-24
Needs out/board_DAY.json (team xG, starting goalies) and out/props_rates_DAY.json (python props.py DAY).
Writes out/props_DAY.json and site/data/props.json.

Markets: shots on goal (Total Shots on Goal), points (Total Points), anytime goal (Anytime Goalscorer),
goalie saves (Total Saves). Only players with a DraftKings line are listed.

Feed: https://sports.core.api.espn.com/v2/sports/hockey/leagues/nhl/events/{id}/competitions/{id}/odds/100/propBets
Each over/under line is two consecutive unlabeled items for the same athlete and market. Side convention,
verified 2026-10-24 against DraftKings' one-sided milestone markets ("X+", always an over) on every pair
where a matching milestone exists: the FIRST item is the over and the SECOND is the under (57 of 59 pairs in
TOR@EDM matched the milestone's current price and the other 2 matched its opening price; e.g. Auston Matthews
points 0.5: first item -250 = "1+ points" -250, second +180). The code re-checks every pair and flags any where the second
item matches it better at both the current and the opening price, and reports those pairs (the order is
never swapped: near pick'em lines can drift apart from the milestone, so the first item is always the over).

Anytime goal is a single "yes" price, so its market probability still includes the vig.
"""
import difflib, json, re, sys, time, unicodedata, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from scipy.stats import poisson

sys.path.insert(0, str(Path(__file__).resolve().parent))
import props as P
from picks import implied, novig, EVEN, STRONG

ROOT = P.ROOT
SITE = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl"
CORE = "https://sports.core.api.espn.com/v2/sports/hockey/leagues/nhl"
AB = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL", "UTAH": "UTA", "WAS": "WSH", "MON": "MTL",
      "NAS": "NSH", "CLB": "CBJ", "CAL": "CGY", "VEG": "VGK", "LV": "VGK"}
ESPN_TEAM = {"LAK": "la", "NJD": "nj", "SJS": "sj", "TBL": "tb", "UTA": "utah"}   # our code -> ESPN roster URL code
MARKETS = {"Total Shots on Goal": "sog", "Total Points": "pts", "Anytime Goalscorer": "goal", "Total Saves": "saves"}
MILESTONE = {"sog": "Shots on Goal Milestones", "pts": "Points Milestones", "saves": "Goalkeeper Saves Milestones"}
CURVE = {"sog": [x + 0.5 for x in range(0, 8)], "pts": [0.5, 1.5, 2.5, 3.5], "goal": [0.5],
         "saves": [x + 0.5 for x in range(14, 42)]}
NICK = {"matthew": "matt", "alexander": "alex", "alexandre": "alex", "nicholas": "nick", "joshua": "josh",
        "zachary": "zach", "mitchell": "mitch", "samuel": "sam", "jacob": "jake", "cameron": "cam",
        "michael": "mike", "daniel": "dan", "christopher": "chris", "joseph": "joe", "anthony": "tony",
        "nikolai": "nikolay", "evgeni": "evgeny", "alexei": "alexey", "aleksei": "alexey", "yegor": "egor",
        "jonathan": "jon", "thomas": "tom", "maxime": "max", "maximilian": "max", "william": "will",
        "benjamin": "ben", "frederick": "fred", "timothy": "tim", "patrick": "pat", "gabriel": "gabe"}


def fix(a):
    return AB.get(a, a)


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                print(f"fetch failed {url}: {e}")
                return None
            time.sleep(1.5 * (i + 1))


def norm(name, drop=False):
    """Lowercase ASCII name key. drop=True deletes accented letters instead of transliterating them, which is
    how MoneyPuck's CSVs store them (e.g. "Alexis Lafrenire", "Tim Sttzle")."""
    s = (name.encode("ascii", "ignore").decode() if drop else
         unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()).lower()
    s = re.sub(r"[.'`]", "", s).replace("-", " ")
    s = re.sub(r"\b(jr|sr|ii|iii)\b", "", s)
    parts = s.split()
    if parts:
        parts[0] = NICK.get(parts[0], parts[0])
    return " ".join(parts)


def american_num(o):
    if o is None:
        return None
    s = str(o).upper()
    if s == "EVEN":
        return 100
    try:
        return int(float(s.replace("+", "")))
    except ValueError:
        return None


def fmt_odds(o):
    n = american_num(o)
    return None if n is None else (f"+{n}" if n > 0 else str(n))


# ---------------- model probabilities ----------------
def model_mean(market, x, prm):
    if market == "sog":
        return x["mu_sog"]
    if market == "pts":
        return prm["c_pts"] * (x["mu_g"] + x["mu_a"])
    if market == "goal":
        return x["mu_g"]
    return x["mu_sa"] * x["sv"]


def model_p(market, line, x, prm):
    k = int(np.floor(line)) + 1
    if market == "sog":
        po = float(P.nb_sf(k, x["mu_sog"], prm["r_sog"]))
        if float(line).is_integer():
            pe = float(P.nb_sf(int(line), x["mu_sog"], prm["r_sog"])) - po
            return po / (1 - pe)
        return po
    if market in ("pts", "goal"):
        mu = model_mean(market, x, prm)
        po = float(poisson.sf(k - 1, mu))
        if float(line).is_integer():
            pe = float(poisson.pmf(int(line), mu))
            return po / (1 - pe)
        return po
    po = float(P.saves_sf(k, x["mu_sa"], x["sv"], prm["r_sa"], prm["q_pull"], prm["f_pull"]))
    if float(line).is_integer():
        pe = float(P.saves_sf(int(line), x["mu_sa"], x["sv"], prm["r_sa"], prm["q_pull"], prm["f_pull"])) - po
        return po / (1 - pe)
    return po


# ---------------- ESPN feed ----------------
def athlete_id(item):
    return item["athlete"]["$ref"].split("/athletes/")[1].split("?")[0]


def parse_props(feed):
    """-> {(market, espn_athlete_id): row} plus side-check stats."""
    items = [x for x in (feed or {}).get("items", []) if "athlete" in x]
    by = {}
    for x in items:
        by.setdefault((x["type"]["name"], athlete_id(x)), []).append(x)
    out, checks = {}, {"pairs": 0, "checked": 0, "first_is_over": 0, "mismatch": 0}
    for (t, aid), xs in by.items():
        m = MARKETS.get(t)
        if not m:
            continue
        cur = lambda it: it["odds"]["american"].get("value")
        opn = lambda it: it["odds"]["american"].get("open")
        line = lambda it, k: (it.get(k) or {}).get("target", {}).get("value")
        if m == "goal":
            x = xs[0]
            out[(m, aid)] = {"line": 0.5, "open_line": 0.5, "over": fmt_odds(cur(x)), "over_open": fmt_odds(opn(x)),
                             "under": None, "under_open": None, "updated": x.get("lastUpdated")}
            continue
        if len(xs) < 2:
            continue
        o, u = xs[0], xs[1]
        checks["pairs"] += 1
        L = line(o, "current")
        ms = [z for z in by.get((MILESTONE.get(m), aid), []) if line(z, "current") == (L or 0) + 0.5]
        if ms:
            # audit only: the milestone ("X+") price is always an over. Count the pair as consistent when the
            # first item is closer to it at the current or the opening price (milestones sometimes lag a move).
            checks["checked"] += 1
            def closer(fn):
                mp, po, pu = implied(fn(ms[0])), implied(fn(o)), implied(fn(u))
                return None if None in (mp, po, pu) else abs(po - mp) <= abs(pu - mp)
            c, c0 = closer(cur), closer(opn)
            if c or c0:
                checks["first_is_over"] += 1
            else:
                checks["mismatch"] += 1
                checks.setdefault("mismatches", []).append({"market": m, "espn_id": aid, "line": L, "first": cur(o),
                                                            "second": cur(u), "milestone": cur(ms[0])})
        out[(m, aid)] = {"line": L, "open_line": line(o, "open"), "over": fmt_odds(cur(o)), "over_open": fmt_odds(opn(o)),
                         "under": fmt_odds(cur(u)), "under_open": fmt_odds(opn(u)), "updated": o.get("lastUpdated")}
    return out, checks


def roster(team):
    code = ESPN_TEAM.get(team, team).lower()
    r = get(f"{SITE}/teams/{code}/roster")
    out = {}
    for g in (r or {}).get("athletes", []):
        for p in g.get("items", []):
            out[str(p["id"])] = {"name": p.get("fullName") or p.get("displayName"),
                                 "pos": (p.get("position") or {}).get("abbreviation")}
    return out


def match(name, team, pool_team, pool_all):
    """ESPN name + team -> MoneyPuck player. Exact normalized name on the team, then on any team (accents
    transliterated or dropped), then unique last name + first initial on the team, then a close spelling match
    (difflib ratio >= 0.88) on the team."""
    tp = pool_team.get(team, {})
    keys = [norm(name), norm(name, drop=True)]
    for n in keys:
        if n in tp:
            return tp[n]
    for n in keys:
        hits = pool_all.get(n, [])
        if len(hits) == 1:
            return hits[0]
    parts = keys[0].split()
    if len(parts) >= 2:
        c = [v for k, v in tp.items() if k.split()[-1] == parts[-1] and k[0] == parts[0][0]]
        if len(c) == 1:
            return c[0]
    close = difflib.get_close_matches(keys[0], list(tp), n=1, cutoff=0.88)
    return tp[close[0]] if close else None


# ---------------- build ----------------
def build(day, feeds=None, rosters=None, scoreboard=None):
    """feeds/rosters/scoreboard can be injected for tests."""
    board = json.load(open(ROOT / "out" / f"board_{day}.json"))
    rp = ROOT / "out" / f"props_rates_{day}.json"
    if not rp.exists():
        print(f"no {rp.name}; run python props.py {day} first")
        return None
    R = json.load(open(rp))
    prm = R["params"]
    cfg_p = ROOT / "out" / "props_config.json"
    cfg = json.load(open(cfg_p)) if cfg_p.exists() else {"picks": False}

    sb = scoreboard or get(f"{SITE}/scoreboard?dates={day.replace('-', '')}") or {}
    events = {}
    for e in sb.get("events", []):
        c = e["competitions"][0]
        side = {x["homeAway"]: x for x in c["competitors"]}
        H, A = fix(side["home"]["team"]["abbreviation"]), fix(side["away"]["team"]["abbreviation"])
        events[(A, H)] = {"espn_id": e["id"], "state": c["status"]["type"].get("state"),
                          "detail": c["status"]["type"].get("shortDetail")}
    games = [(g, events.get((g["away"], g["home"]))) for g in board["games"]]

    def fetch_feed(ev):
        i = ev["espn_id"]
        return i, get(f"{CORE}/events/{i}/competitions/{i}/odds/100/propBets?limit=1000")
    if feeds is None:
        with ThreadPoolExecutor(8) as ex:
            feeds = dict(ex.map(fetch_feed, [ev for _, ev in games if ev]))
    teams = sorted({t for g, _ in games for t in (g["home"], g["away"])})
    if rosters is None:
        with ThreadPoolExecutor(8) as ex:
            rosters = dict(zip(teams, ex.map(roster, teams)))

    # MoneyPuck pools
    pool_team, pool_all, sk_by_id = {}, {}, {}
    for s in R["skaters"]:
        sk_by_id[s["id"]] = s
        pool_team.setdefault(s["team"], {})[norm(s["name"])] = s
        pool_all.setdefault(norm(s["name"]), []).append(s)
    g_team, g_all = {}, {}
    for gid, gv in R["goalies"].items():
        if gv.get("name"):
            rec = dict(gv, id=int(gid))
            g_team.setdefault(gv["team"], {})[norm(gv["name"])] = rec
            g_all.setdefault(norm(gv["name"]), []).append(rec)

    # games already under way keep the last pre-game snapshot (lines and projections), like the board's frozen games
    prev_p = ROOT / "out" / f"props_{day}.json"
    prev = {}
    if prev_p.exists():
        try:
            prev = {g["espn_id"]: g for g in json.load(open(prev_p)).get("games", []) if g.get("espn_id")}
        except (ValueError, KeyError):
            prev = {}

    T = R["teams"]
    out_games, unmatched, checks_all = [], [], {"pairs": 0, "checked": 0, "first_is_over": 0, "mismatch": 0, "mismatches": []}
    n_lines = 0
    for g, ev in games:
        H, A = g["home"], g["away"]
        pg = prev.get(ev["espn_id"]) if ev else None
        if ev and ev["state"] in ("in", "post") and pg and (pg.get("frozen") or pg.get("state") == "pre"):
            out_games.append(dict(pg, state=ev["state"], detail=ev["detail"], frozen=True))
            continue
        # team goal factor from the board's projected xG/60 vs the team's recent xG/60
        gf = {}
        for t, xg in ((H, g["xg_home"]), (A, g["xg_away"])):
            base = T.get(t, {}).get("xgf_base")
            gf[t] = float(np.clip(xg / base, 0.6, 1.6)) if base else 1.0
        opp = {H: A, A: H}
        starters = {H: g.get("home_goalie") or {}, A: g.get("away_goalie") or {}}
        markets = {m: [] for m in ("sog", "pts", "goal", "saves")}
        lines, checks = parse_props(feeds.get(ev["espn_id"]) if ev else None)
        for k in checks:
            checks_all[k] += checks[k]
        espn_team = {}
        for t in (H, A):
            for aid, a in rosters.get(t, {}).items():
                espn_team[aid] = (t, a)
        for (m, aid), ln in lines.items():
            n_lines += 1
            if aid not in espn_team:
                unmatched.append({"espn_id": aid, "name": None, "team": None, "market": m, "game": f"{A}@{H}",
                                  "why": "athlete not on either team's ESPN roster"})
                continue
            t, a = espn_team[aid]
            row = {"espn_id": aid, "player": a["name"], "team": t, "opp": opp[t], **ln}
            if m == "saves":
                gm = match(a["name"], t, g_team, g_all)
                st = starters[t]
                if gm is None and st.get("name") and norm(st["name"]) == norm(a["name"]):
                    gm = {"id": st["id"], "sv": R["league_sv"], "name": st["name"]}
                if gm is None:
                    unmatched.append({"espn_id": aid, "name": a["name"], "team": t, "market": m, "game": f"{A}@{H}",
                                      "why": "no MoneyPuck goalie match"})
                    continue
                to, tt = T.get(opp[t], {}), T.get(t, {})
                mu_sa = prm["c_sa"] * tt.get("env_sog", 28.0) * (to.get("rel_f", 1.0) * tt.get("rel_a", 1.0)) ** prm["b_sa"]
                x = {"mu_sa": mu_sa, "sv": gm["sv"]}
                row.update({"player_id": gm["id"], "pos": "G", "starter": bool(st.get("id") == gm["id"]),
                            "starter_basis": st.get("basis") if st.get("id") == gm["id"] else None,
                            "proj_sa": round(mu_sa, 1), "proj_sv": round(gm["sv"], 4)})
            else:
                s = match(a["name"], t, pool_team, pool_all)
                if s is None:
                    unmatched.append({"espn_id": aid, "name": a["name"], "team": t, "market": m, "game": f"{A}@{H}",
                                      "why": "no MoneyPuck skater match (no recent games?)"})
                    continue
                f = gf.get(s["team"] if s["team"] in gf else t, 1.0) ** prm["b_g"]
                x = {"mu_sog": s["mu_sog"], "mu_g": s["mu_g"] * f, "mu_a": s["mu_a"] * f}
                row.update({"player_id": s["id"], "pos": s["pos"], "proj_toi": s["toi"], "games_weight": s["n"]})
            L = row["line"]
            if L is None:
                continue
            mean = model_mean(m, x, prm)
            po = model_p(m, L, x, prm)
            row["mean"] = round(mean, 3 if m != "saves" else 2)
            row["p_over"] = round(po, 4)
            row["curve"] = {str(c): round(model_p(m, c, x, prm), 4) for c in CURVE[m]}
            if m == "goal":
                mo = implied(row["over"])
                row["mkt_over"] = round(mo, 4) if mo is not None else None
                row["vig_included"] = True
                eo = po - mo if mo is not None else None
                eu = None
            else:
                mo = novig(row["over"], row["under"])
                row["mkt_over"] = round(mo, 4) if mo is not None else None
                eo = po - mo if mo is not None else None
                eu = (1 - po) - (1 - mo) if mo is not None else None
            row["edge_over"] = round(eo, 4) if eo is not None else None
            row["edge_under"] = round(eu, 4) if eu is not None else None
            lean, edge = None, None
            if eo is not None and eo >= EVEN and (eu is None or eo >= eu):
                lean, edge = "Over" if m != "goal" else "Yes", eo
            elif eu is not None and eu >= EVEN:
                lean, edge = "Under", eu
            row["lean"] = lean
            row["edge"] = round(edge, 4) if edge is not None else None
            row["strong"] = bool(edge is not None and edge >= STRONG)
            markets[m].append(row)
        for m in markets:
            markets[m].sort(key=lambda r: (r["team"] != A, -(r.get("mean") or 0)))
        out_games.append({"id": g["id"], "espn_id": ev["espn_id"] if ev else None, "away": A, "home": H,
                          "away_name": g.get("away_name"), "home_name": g.get("home_name"),
                          "start_utc": g["start_utc"], "state": ev["state"] if ev else None,
                          "detail": ev["detail"] if ev else None,
                          "frozen": False,
                          "goal_factor": {A: round(gf[A], 3), H: round(gf[H], 3)},
                          "home_goalie": starters[H].get("name"), "away_goalie": starters[A].get("name"),
                          "markets": markets})
    n_un = len(unmatched)
    bt = {}
    bp = ROOT / "out" / "props_backtest.json"
    if bp.exists():
        B = json.load(open(bp))
        lab = [("sog3", "SOG 3+"), ("pts1", "Points 1+"), ("g1", "Goal"), ("sv25.5", "Saves 26+")]
        bt = {"seasons": "2023-24 to 2025-26",
              "rows": [{"label": l, "model": B["markets"][k]["test"]["logloss"], "base": B["markets"][k]["test"]["baseline_logloss"]}
                       for k, l in lab if k in B["markets"] and B["markets"][k]["test"].get("baseline_logloss") is not None]}
    res = {"date": day, "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "data_through": R["data_through"], "picks_enabled": bool(cfg.get("picks", False)),
           "params": {k: prm[k] for k in ("r_sog", "r_sa", "q_pull", "f_pull", "c_pts")},
           "side_check": checks_all, "lines": n_lines, "unmatched": unmatched,
           "unmatched_rate": round(n_un / n_lines, 4) if n_lines else None,
           "strong": STRONG, "backtest": bt, "games": out_games,
           "notes": ["Market probability is DraftKings' vig-free over price; anytime goal is one-sided, so vig is included.",
                     "Edge = model probability minus market probability on the leaned side, in points.",
                     "Projections: MoneyPuck game logs (credit MoneyPuck.com); lines: DraftKings via ESPN."]}
    json.dump(res, open(ROOT / "out" / f"props_{day}.json", "w"), indent=1)
    site = ROOT / "site" / "data"
    site.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(site / "props.json", "w"))
    nrows = sum(len(v) for g in out_games for v in g["markets"].values())
    print(f"props {day}: {nrows} lines modeled, {n_un} of {n_lines} unmatched; side check {checks_all}")
    return res


if __name__ == "__main__":
    build(sys.argv[1])
