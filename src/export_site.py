"""Export the board for the GitHub Pages site.
Usage: python export_site.py 2026-10-24
Writes site/data/board.json (same merge as build_page.py) and site/index.html
(built from src/template.html; the live layer is site/live.js + site/live.css, so the design stays in one place)."""
import json, sys, urllib.request, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


def ver(name):
    """Content hash so browsers load updated scripts without a hard refresh."""
    return hashlib.md5((SITE / name).read_bytes()).hexdigest()[:8]


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
    head_part = tpl[:css_end] + "</style>\n<link rel=\"stylesheet\" href=\"live.css?v=" + ver("live.css") + "\">"
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
    body_part = body_part[:s0 - len("<script>")] + '<script src="live.js?v=' + ver('live.js') + '"></script>\n<script src="record.js?v=' + ver('record.js') + '"></script>\n<script>' + script + body_part[s1:]
    html = HEAD + head_part.replace('<meta name="claude:viewport-fit-sides" content="cover">\n', "") + "</head><body>" + body_part + "</body></html>"
    (SITE / "index.html").write_text(html)
    return len(html)


HISTORY_BODY = """
<div class="wrap">
  <header>
    <h1>Pick history</h1>
    <div class="sub"><a href="./" style="color:var(--blue)">Back to the board</a><span id="hmeta"></span></div>
  </header>
  <section class="rec" id="hsum" hidden></section>
  <div class="hf" role="group" aria-label="Filter by market" id="hf">
    <button type="button" data-m="all" aria-pressed="true">All</button>
    <button type="button" data-m="su" aria-pressed="false">Straight up</button>
    <button type="button" data-m="ml" aria-pressed="false">Moneyline</button>
    <button type="button" data-m="pl" aria-pressed="false">Puck line</button>
    <button type="button" data-m="tot" aria-pressed="false">Total</button>
  </div>
  <div class="tbl"><table class="ht" id="ht"></table></div>
  <p class="note">One pick per market per game, graded against DraftKings closing lines from ESPN's public feed. 1 unit risked per pick at the closing odds; a push returns 0. Edge is the model's probability minus the market's vig-free probability. Strong edge is 3.0 points or more.</p>
</div>
<style>
.hf{display:flex;flex-wrap:wrap;gap:6px}
.hf button{font:600 .85rem var(--body);border:1px solid var(--line);background:var(--sheet);color:var(--muted);padding:6px 12px;border-radius:2px;cursor:pointer}
.hf button[aria-pressed="true"]{background:var(--ink);color:var(--sheet);border-color:var(--ink)}
.hf button:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
.ht td.res-W{color:var(--good);font-weight:600}.ht td.res-L{color:var(--red);font-weight:600}.ht td.res-P{color:var(--muted)}
.ht td.wrapc{white-space:normal}
</style>
<script>
const NAMES={su:'Straight up',ml:'Moneyline',pl:'Puck line',tot:'Total'};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtO=o=>{if(o==null||o==='')return '';const n=parseFloat(String(o).replace('+',''));return isFinite(n)?(n>0?'+'+n:String(n)):'';};
const fmtU=u=>u==null?'':(u>=0?'+':'\u2212')+Math.abs(u).toFixed(2);
let D=null,M='all';
function draw(){
  const rows=D.picks.filter(p=>M==='all'||p.market===M);
  document.getElementById('ht').innerHTML='<tr><th>Date</th><th>Game</th><th>Market</th><th>Pick</th><th>Odds</th><th>Edge</th><th>Final</th><th>Result</th><th>Units</th></tr>'+
    (rows.length?rows.map(p=>`<tr><td class="mono">${esc(p.date)}</td><td>${esc(p.game)}</td><td>${NAMES[p.market]}</td><td>${esc(p.pick)}</td><td class="mono">${fmtO(p.odds)}</td><td class="mono">${p.edge==null?'':(100*p.edge).toFixed(1)+' pts'}</td><td class="wrapc">${esc(p.final)}</td><td class="res-${esc(p.result)}">${esc(p.result)}</td><td class="mono">${fmtU(p.units)}</td></tr>`).join(''):'<tr><td colspan="9">No graded picks yet.</td></tr>');
}
function sum(S){
  const wl=r=>`${r.w}-${r.l}${r.p?'-'+r.p:''}`, pct=r=>r.pct==null?'':(100*r.pct).toFixed(1)+'%';
  const card=(l,r,u)=>`<div class="rc"><span class="l">${l}</span><span class="v">${wl(r)}</span><span class="s">${pct(r)}${u&&r.units!=null?` \u00b7 <span class="${r.units>=0?'pos':'neg'}">${fmtU(r.units)}u</span>`:''}</span></div>`;
  const st=S.strong||{};
  const el=document.getElementById('hsum');
  el.innerHTML=`<div class="rec-h"><h2>All picks</h2></div><div class="rec-grid">${card('Straight up',S.record.su,false)}${card('Moneyline',S.record.ml,true)}${card('Puck line',S.record.pl,true)}${card('Total',S.record.tot,true)}</div>`+
    (st.ml?`<div class="rec-h"><h2>Strong edge (3+ pts)</h2></div><div class="rec-grid">${card('Moneyline',st.ml,true)}${card('Puck line',st.pl,true)}${card('Total',st.tot,true)}</div>`:'')+
    (S.last7?`<div class="rec-h"><h2>Last 7 days</h2></div><div class="rec-grid">${card('Straight up',S.last7.su,false)}${card('Moneyline',S.last7.ml,true)}${card('Puck line',S.last7.pl,true)}${card('Total',S.last7.tot,true)}</div>`:'');
  el.hidden=false;
  document.getElementById('hmeta').textContent=`${S.games} games through ${S.updated}`;
}
document.getElementById('hf').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;M=b.dataset.m;document.querySelectorAll('#hf button').forEach(x=>x.setAttribute('aria-pressed',x===b));draw();});
fetch('data/record.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw 0;return r.json();}).then(d=>{D=d;if(d.summary&&d.summary.games)sum(d.summary);draw();})
  .catch(()=>{document.getElementById('ht').innerHTML='<tr><td>No graded picks yet. The first results post the morning after game day.</td></tr>';});
</script>
"""


def build_history():
    tpl = (ROOT / "src" / "template.html").read_text()
    head_part = tpl[:tpl.index("</style>")] + "</style>\n<link rel=\"stylesheet\" href=\"live.css?v=" + ver("live.css") + "\">"
    head_part = head_part.replace("<title>Ice Ledger NHL Board</title>", "<title>Ice Ledger Pick History</title>")
    head_part = head_part.replace('<meta name="claude:viewport-fit-sides" content="cover">\n', "")
    html = HEAD + head_part + "</head><body>" + HISTORY_BODY + "</body></html>"
    (SITE / "history.html").write_text(html)


if __name__ == "__main__":
    day = sys.argv[1]
    (SITE / "data").mkdir(parents=True, exist_ok=True)
    data = merged_board(day)
    json.dump(data, open(SITE / "data" / "board.json", "w"), default=float)
    n = build_index()
    build_history()
    print("wrote", SITE / "data" / "board.json", "and", SITE / "index.html", n)
