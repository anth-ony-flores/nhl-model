"""Model picks vs DraftKings, one per market per game (straight up, moneyline, puck line, total).
The same rules run in site/live.js so the pick shown on a card is the pick graded here.

Rules (edges are model probability minus the market's vig-free probability):
- Straight up: the model favorite (home when p_home >= 0.5).
- Moneyline: the side with the positive edge.
- Puck line: the -1.5 favorite if the model's cover probability beats the market's, else the +1.5 dog.
- Total: over or under at DraftKings' line. On a whole-number line the model's push chance is removed
  (over / (over + under)) to match the vig-free market, which also excludes pushes.
- No pick when the edge rounds to 0.0 points (|edge| < 0.0005). Strong edge = 3.0 points or more.
Units: 1 unit risked at the closing American odds; a push returns 0.
"""

EVEN = 0.0005
STRONG = 0.03


def num(o):
    if o is None or o == "" or str(o).upper() == "OFF":
        return None
    if str(o).upper() == "EVEN":
        return 100.0
    try:
        return float(str(o).replace("+", ""))
    except ValueError:
        return None


def implied(o):
    n = num(o)
    if n is None:
        return None
    return -n / (-n + 100) if n < 0 else 100 / (n + 100)


def novig(a, b):
    pa, pb = implied(a), implied(b)
    if pa is None or pb is None:
        return None
    return pa / (pa + pb)


def profit(o):
    n = num(o)
    return n / 100 if n > 0 else 100 / -n


def norm_odds(p):
    """ESPN pickcenter entry -> {book, ml:{home,away}, total:{line,over,under}, spread:{home:{line,odds},away:{...}}}.
    Closing values, falling back to open, then to the flat fields. Mirrors normOdds() in site/live.js."""
    if not p:
        return None
    ml = p.get("moneyline") or {}
    def side(d, s, k):
        x = (d.get(s) or {}).get(k) or {}
        return x.get("odds")
    out = {"book": (p.get("provider") or {}).get("name", "DraftKings")}
    out["ml"] = {
        "home": side(ml, "home", "close") or side(ml, "home", "open") or (p.get("homeTeamOdds") or {}).get("moneyLine"),
        "away": side(ml, "away", "close") or side(ml, "away", "open") or (p.get("awayTeamOdds") or {}).get("moneyLine"),
    }
    t = p.get("total") or {}
    oc = (t.get("over") or {}).get("close") or (t.get("over") or {}).get("open") or {}
    uc = (t.get("under") or {}).get("close") or (t.get("under") or {}).get("open") or {}
    line = None
    try:
        line = float(str(oc.get("line", "")).lstrip("ou"))
    except ValueError:
        line = p.get("overUnder")
    out["total"] = {"line": line if line is not None else p.get("overUnder"),
                    "over": oc.get("odds", p.get("overOdds")), "under": uc.get("odds", p.get("underOdds"))}
    ps = p.get("pointSpread") or {}
    hc = (ps.get("home") or {}).get("close") or (ps.get("home") or {}).get("open") or {}
    ac = (ps.get("away") or {}).get("close") or (ps.get("away") or {}).get("open") or {}
    hl = num(hc.get("line")) if hc.get("line") is not None else p.get("spread")
    out["spread"] = {"home": {"line": hl, "odds": hc.get("odds", (p.get("homeTeamOdds") or {}).get("spreadOdds"))},
                     "away": {"line": -hl if hl is not None else None,
                              "odds": ac.get("odds", (p.get("awayTeamOdds") or {}).get("spreadOdds"))}}
    return out


def model_over(g, line):
    """Model over probability at a line, pushes removed. None if the board has no number for that line."""
    if line is None:
        return None
    t = (g.get("totals") or {}).get(f"{float(line):.1f}") or (g.get("totals") or {}).get(str(line))
    if not t:
        return None
    o, u = t["over"], t["under"]
    return o / (o + u) if o + u > 0 else None


def make_picks(g, o):
    """g: locked board game; o: norm_odds(). Returns a dict of picks (None where no line or no edge)."""
    H, A = g["home"], g["away"]
    P = {"su": {"pick": H if g["p_home"] >= 0.5 else A, "side": "home" if g["p_home"] >= 0.5 else "away"}}
    # moneyline
    mh = novig(o["ml"]["home"], o["ml"]["away"]) if o else None
    P["ml"] = None
    if mh is not None:
        e = g["p_home"] - mh
        if abs(e) >= EVEN:
            s = "home" if e > 0 else "away"
            P["ml"] = {"pick": f"{H if s == 'home' else A} ML", "side": s, "odds": o["ml"][s], "edge": round(abs(e), 4),
                       "market_p": round(mh if s == "home" else 1 - mh, 4), "model_p": round(g["p_home"] if s == "home" else 1 - g["p_home"], 4)}
    # puck line
    P["pl"] = None
    sp = o.get("spread") if o else None
    if sp and sp["home"]["line"] is not None:
        fav_home = sp["home"]["line"] < 0
        fo = sp["home"]["odds"] if fav_home else sp["away"]["odds"]
        do = sp["away"]["odds"] if fav_home else sp["home"]["odds"]
        mf = novig(fo, do)
        mod = g["puck_line"]["home_-1.5"] if fav_home else g["puck_line"]["away_-1.5"]
        if mf is not None:
            e = mod - mf
            if abs(e) >= EVEN:
                fav, dog = (H, A) if fav_home else (A, H)
                take_fav = e > 0
                P["pl"] = {"pick": f"{fav} -1.5" if take_fav else f"{dog} +1.5",
                           "side": ("home" if fav_home else "away") if take_fav else ("away" if fav_home else "home"),
                           "line": -1.5 if take_fav else 1.5, "odds": fo if take_fav else do, "edge": round(abs(e), 4),
                           "market_p": round(mf if take_fav else 1 - mf, 4), "model_p": round(mod if take_fav else 1 - mod, 4)}
    # total
    P["tot"] = None
    t = o.get("total") if o else None
    if t and t["line"] is not None:
        mo = novig(t["over"], t["under"])
        mod = model_over(g, t["line"])
        if mo is not None and mod is not None:
            e = mod - mo
            if abs(e) >= EVEN:
                over = e > 0
                P["tot"] = {"pick": f"{'Over' if over else 'Under'} {float(t['line']):g}", "side": "over" if over else "under",
                            "line": float(t["line"]), "odds": t["over"] if over else t["under"], "edge": round(abs(e), 4),
                            "market_p": round(mo if over else 1 - mo, 4), "model_p": round(mod if over else 1 - mod, 4)}
        elif mo is not None and mod is None:
            P["tot_note"] = f"no model number at {t['line']}"
    return P


def grade(P, hs, as_):
    """Adds result ('W','L','P') and units to each pick given final scores (sportsbook scoring: SO winner +1)."""
    home_won = hs > as_
    su = P["su"]
    su["result"] = "W" if (su["side"] == "home") == home_won else "L"
    if P.get("ml"):
        x = P["ml"]; win = (x["side"] == "home") == home_won
        x["result"] = "W" if win else "L"; x["units"] = round(profit(x["odds"]) if win else -1.0, 3)
    if P.get("pl"):
        x = P["pl"]
        margin = (hs - as_) if x["side"] == "home" else (as_ - hs)
        win = margin + x["line"] > 0
        x["result"] = "W" if win else "L"; x["units"] = round(profit(x["odds"]) if win else -1.0, 3)
    if P.get("tot"):
        x = P["tot"]; tot = hs + as_
        if tot == x["line"]:
            x["result"] = "P"; x["units"] = 0.0
        else:
            win = (tot > x["line"]) == (x["side"] == "over")
            x["result"] = "W" if win else "L"; x["units"] = round(profit(x["odds"]) if win else -1.0, 3)
    return P


def _open(d, side):
    x = ((d or {}).get(side) or {}).get("open") or {}
    return x.get("line"), x.get("odds")


def movement(p, P):
    """Line movement for each pick: vig-free probability of the picked side at DraftKings' open vs close.
    clv > 0 means the market moved toward the pick (closing line value). Only computed when the line
    (puck line / total) did not change between open and close, so the prices are comparable."""
    out = {}
    if not p:
        return out
    x = P.get("ml")
    if x:
        ml = p.get("moneyline") or {}
        _, oh = _open(ml, "home"); _, oa = _open(ml, "away")
        po_home = novig(oh, oa)
        if po_home is not None:
            po = po_home if x["side"] == "home" else 1 - po_home
            out["ml"] = {"open_odds": oh if x["side"] == "home" else oa, "open_p": round(po, 4), "clv": round(x["market_p"] - po, 4)}
    x = P.get("pl")
    if x:
        ps = p.get("pointSpread") or {}
        other = "away" if x["side"] == "home" else "home"
        ls, os_ = _open(ps, x["side"]); _, oo = _open(ps, other)
        if ls is not None and num(ls) == x["line"]:
            po = novig(os_, oo)
            if po is not None:
                out["pl"] = {"open_odds": os_, "open_p": round(po, 4), "clv": round(x["market_p"] - po, 4)}
    x = P.get("tot")
    if x:
        t = p.get("total") or {}
        other = "under" if x["side"] == "over" else "over"
        ls, os_ = _open(t, x["side"]); _, oo = _open(t, other)
        try:
            same = ls is not None and float(str(ls).lstrip("ou")) == x["line"]
        except ValueError:
            same = False
        if same:
            po = novig(os_, oo)
            if po is not None:
                out["tot"] = {"open_odds": os_, "open_p": round(po, 4), "clv": round(x["market_p"] - po, 4)}
    return out
