"""Export the board for the GitHub Pages site.
Usage: python export_site.py 2026-10-24
Writes site/data/board.json (same merge as build_page.py) and site/index.html
(built from src/template.html; the live layer is site/live.js + site/live.css, so the design stays in one place)."""
import json, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


def merged_board(day):
    """Same inputs and merge logic as build_page.py."""
    data = json.load(open(ROOT / "out" / f"board_{day}.json"))
    sp = ROOT / "out" / f"summaries_{day}.json"
    S = json.load(open(sp)) if sp.exists() else {}
    try:
        req = urllib.request.Request(f"https://api-web.nhle.com/v1/standings/{day}", headers={"User-Agent": "Mozilla/5.0"})
        st = json.load(urllib.request.urlopen(req, timeout=20))["standings"]
        REC = {x["teamAbbrev"]["default"]: f"{x['wins']}-{x['losses']}-{x['otLosses']}" for x in st}
    except Exception:
        REC = {}
    for g in data["games"]:
        k = f"{g['away']}@{g['home']}"
        g["summary"] = S.get(k, {}).get("text")
        g["sources"] = S.get(k, {}).get("sources", [])
        g["home_rec"], g["away_rec"] = REC.get(g["home"], ""), REC.get(g["away"], "")
    rank = {r["team"]: i + 1 for i, r in enumerate(data["ratings"])}
    for g in data["games"]:
        g["home_rank"], g["away_rank"] = rank.get(g["home"]), rank.get(g["away"])
    mp = ROOT / "out" / f"metrics_{day}.json"
    if mp.exists():
        MT = json.load(open(mp))
        playing = {g["home"] for g in data["games"]} | {g["away"] for g in data["games"]}
        data["metrics"] = {"defs": MT["metrics"], "n": MT["n_teams"], "through": MT["data_through"],
                           "teams": {t: v for t, v in MT["teams"].items() if t in playing}}
    for g in data["games"]:
        for side in ("home_goalie", "away_goalie"):
            gg = g.get(side) or {}
            if isinstance(gg.get("basis"), str):
                gg["basis"] = gg["basis"].replace("confirmed: confirmed by", "confirmed by").replace("confirmed: likely:", "likely:").replace("confirmed: expected per", "expected per")
    data["detail_games"] = "ALL"
    return data


HEAD = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        '<meta name="description" content="Personal NHL projection model with live scores">'
        '<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
        'body{margin:0;font-size:14px}img{max-width:100%}[hidden]{display:none!important}</style>')


def build_index():
    tpl = (ROOT / "src" / "template.html").read_text()
    # head: title, fonts, styles; body: markup + scripts
    css_end = tpl.index("</style>")
    head_part = tpl[:css_end] + "</style>\n<link rel=\"stylesheet\" href=\"live.css\">"
    body_part = tpl[css_end + len("</style>"):]
    # drop the inline data block; data now comes from data/board.json
    a = body_part.index('<script id="board"')
    b = body_part.index("</script>", a) + len("</script>")
    body_part = body_part[:a] + body_part[b:]
    s0 = body_part.index("<script>") + len("<script>")
    s1 = body_part.index("</script>", s0)
    main = body_part[s0:s1].replace(
        "const B = JSON.parse(document.getElementById('board').textContent);", "")
    # site-only goalie tag: Confirmed / Likely / Expected from news, else Projected
    main = main.replace(
        "const tag = (g.basis||'').startsWith('confirmed') ? '<span class=\"conf\">adjusted for news</span>' : '<span class=\"proj\">projected</span>';",
        "const bs=(g.basis||''); const tag = bs.startsWith('confirmed') ? '<span class=\"conf\">confirmed</span>' : bs.startsWith('likely') ? '<span class=\"conf\">likely</span>' : bs.startsWith('expected') ? '<span class=\"conf\">expected</span>' : '<span class=\"proj\">projected</span>';")
    script = ("\nfunction renderBoard(B){" + main + "\n}\n" +
              "\nfetch('data/board.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error(r.status);return r.json();})"
              ".then(B=>{renderBoard(B);startLive(B);})"
              ".catch(()=>{document.getElementById('games').innerHTML='<p class=\"note\">Board data could not be loaded. Try reloading the page.</p>';});\n")
    body_part = body_part[:s0 - len("<script>")] + '<script src="live.js"></script>\n<script>' + script + body_part[s1:]
    html = HEAD + head_part.replace('<meta name="claude:viewport-fit-sides" content="cover">\n', "") + "</head><body>" + body_part + "</body></html>"
    (SITE / "index.html").write_text(html)
    return len(html)


if __name__ == "__main__":
    day = sys.argv[1]
    (SITE / "data").mkdir(parents=True, exist_ok=True)
    data = merged_board(day)
    json.dump(data, open(SITE / "data" / "board.json", "w"), default=float)
    n = build_index()
    print("wrote", SITE / "data" / "board.json", "and", SITE / "index.html", n)
