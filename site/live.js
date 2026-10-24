/* Live layer: scores, DraftKings lines and in-game stats from ESPN's public (unofficial) feed.
   The board renders without it; every failure degrades to a quiet "Live feed unavailable" note. */
const ESPN = 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl';
const AB = {LA:'LAK', NJ:'NJD', SJ:'SJS', TB:'TBL', UTAH:'UTA', UTA:'UTA', WAS:'WSH', MON:'MTL', NAS:'NSH', CLB:'CBJ', CAL:'CGY', VEG:'VGK', LV:'VGK'};
const fixAb = a => AB[a] || a;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const LIVE = {games: {}, cards: {}, feedOk: true, B: null, timer: null};

const toNum = o => { if (o == null || o === '' || o === 'OFF' || o === 'EVEN') return o === 'EVEN' ? 100 : null; const n = parseFloat(String(o).replace('+', '')); return isFinite(n) ? n : null; };
const impl = o => { const n = toNum(o); if (n == null) return null; return n < 0 ? -n / (-n + 100) : 100 / (n + 100); };
const novig = (a, b) => { const pa = impl(a), pb = impl(b); return pa == null || pb == null ? null : pa / (pa + pb); };
const fmtO = o => { const n = toNum(o); return n == null ? '–' : (n > 0 ? '+' + n : String(n)); };
const pp = x => (x >= 0 ? '+' : '−') + Math.abs(100 * x).toFixed(1) + ' pts';
const pc1 = x => (100 * x).toFixed(1) + '%';

function normOdds(o) {
  if (!o || !o.moneyline) return null;
  const pick = (side, k) => (o.moneyline[side] && o.moneyline[side][k] && o.moneyline[side][k].odds) || null;
  const ml = {};
  for (const s of ['home', 'away']) ml[s] = {open: pick(s, 'open'), close: pick(s, 'close'), live: pick(s, 'live')};
  let total = null;
  if (o.total && o.total.over && o.total.under) {
    const oc = o.total.over.close || o.total.over.open || {}, uc = o.total.under.close || o.total.under.open || {};
    const line = parseFloat(String(oc.line || '').replace(/[ou]/, '')) || o.overUnder || null;
    total = {line, over: oc.odds, under: uc.odds};
  }
  let spread = null;
  if (o.pointSpread && o.pointSpread.home && o.pointSpread.away) {
    const hc = o.pointSpread.home.close || o.pointSpread.home.open || {}, ac = o.pointSpread.away.close || o.pointSpread.away.open || {};
    spread = {home: {line: parseFloat(hc.line), odds: hc.odds}, away: {line: parseFloat(ac.line), odds: ac.odds}};
  }
  return {book: (o.provider && o.provider.name) || 'DraftKings', ml, total, spread, raw: o};
}

function keyOf(away, home) { return fixAb(away) + '@' + fixAb(home); }

async function getJSON(url) {
  const r = await fetch(url, {cache: 'no-store'});
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

/* ---------- card scaffolding ---------- */
function scaffold(B) {
  const cards = [...document.querySelectorAll('#games article.game')];
  B.games.forEach((g, i) => {
    const el = cards[i]; if (!el) return;
    const k = g.away + '@' + g.home;
    el.dataset.k = k;
    const mid = el.querySelector('.mid');
    const lv = document.createElement('div'); lv.className = 'lv'; lv.setAttribute('aria-live', 'polite');
    lv.innerHTML = '<span class="lv-st">Scheduled</span>';
    mid.prepend(lv);
    const dk = document.createElement('div'); dk.className = 'dk'; dk.innerHTML = '<span class="nm">Market line loading…</span>';
    el.querySelector('.mkts').after(dk);
    const det = document.createElement('details'); det.className = 'mx lg';
    det.innerHTML = '<summary><span class="xt">Live game</span><span class="xh">Goalies, team stats, top skaters, last plays</span><span class="chev" aria-hidden="true"></span></summary><div class="lgbody"><p class="mxnote">Opens at puck drop.</p></div>';
    det.addEventListener('toggle', () => { if (det.open) refreshPanel(k, true); });
    dk.after(det);
    LIVE.cards[k] = {el, g, lv, dk, det, body: det.querySelector('.lgbody'), summary: null, sumAt: 0};
  });
  const hdr = document.querySelector('header');
  const t = document.createElement('div'); t.id = 'tally'; t.className = 'tally'; hdr.appendChild(t);
  const st = document.createElement('div'); st.id = 'livestat'; st.className = 'livestat'; hdr.appendChild(st);
}

/* ---------- scoreboard ---------- */
async function pollScoreboard() {
  if (document.hidden && LIVE.feedOk && Object.keys(LIVE.games).length) return;
  const d = LIVE.B.date.replace(/-/g, '');
  try {
    const sb = await getJSON(`${ESPN}/scoreboard?dates=${d}`);
    LIVE.feedOk = true;
    for (const e of sb.events || []) {
      const c = e.competitions[0];
      const h = c.competitors.find(x => x.homeAway === 'home'), a = c.competitors.find(x => x.homeAway === 'away');
      const k = keyOf(a.team.abbreviation, h.team.abbreviation);
      if (!LIVE.cards[k]) continue;
      const prev = LIVE.games[k] || {};
      const odds = normOdds((c.odds || [])[0]) || prev.odds || null;
      LIVE.games[k] = {
        id: e.id, state: c.status.type.state, completed: c.status.type.completed,
        detail: c.status.type.detail, short: c.status.type.shortDetail, period: c.status.period,
        hs: +h.score, as: +a.score, hWin: h.winner, aWin: a.winner, odds,
        closeOdds: prev.closeOdds || null, closeTried: prev.closeTried || 0
      };
    }
    stamp('Live scores updated ' + new Date().toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit', second: '2-digit', timeZone: 'America/Phoenix'}) + ' MST');
  } catch (err) {
    LIVE.feedOk = false;
    stamp('Live feed unavailable. Projections below are unaffected.');
  }
  await fillMissingOdds();
  render();
}

/* odds vanish from the scoreboard once a game starts: take them from the game summary */
async function fillMissingOdds() {
  const now = Date.now();
  const jobs = [];
  for (const [k, G] of Object.entries(LIVE.games)) {
    const needClose = G.state !== 'pre' && (!G.closeOdds || (G.state === 'in' && now - G.closeTried > 300000));
    if (!needClose || now - G.closeTried < 15000) continue;
    G.closeTried = now;
    jobs.push(getJSON(`${ESPN}/summary?event=${G.id}`).then(s => {
      const o = normOdds((s.pickcenter || [])[0]); if (o) { G.closeOdds = o; G.odds = o; }
      LIVE.cards[k].summary = s; LIVE.cards[k].sumAt = Date.now();
    }).catch(() => {}));
  }
  await Promise.all(jobs);
}

function stamp(txt) { const s = document.getElementById('livestat'); if (s) s.textContent = txt; }

/* ---------- rendering ---------- */
function statusHTML(G, g) {
  if (!G) return LIVE.feedOk ? '<span class="lv-st">Scheduled</span>' : '<span class="lv-st muted">Live feed unavailable</span>';
  if (G.state === 'pre') return '<span class="lv-st">Scheduled</span>';
  const sc = `<span class="lv-sc">${esc(g.away)} ${G.as}<span class="dash">–</span>${G.hs} ${esc(g.home)}</span>`;
  if (G.state === 'in') return `<span class="lv-dot" aria-hidden="true"></span><span class="lv-st live">Live · ${esc(G.short)}</span>${sc}`;
  const suf = /OT/i.test(G.detail) ? ' (OT)' : /SO/i.test(G.detail) ? ' (SO)' : '';
  return `<span class="lv-st final">Final${suf}</span>${sc}`;
}

/* Model picks: same rules as src/picks.py, so the pick shown here is the pick graded nightly.
   Edge = model probability minus the market's vig-free probability; no pick when it rounds to 0.0 points. */
const EVEN = 0.0005, STRONG = 0.03;
function modelOver(g, line) {
  const t = g.totals && (g.totals[Number(line).toFixed(1)] || g.totals[String(line)]);
  return t && t.over + t.under > 0 ? t.over / (t.over + t.under) : null;
}
function makePicks(g, o) {
  const H = g.home, A = g.away, P = {ml: null, pl: null, tot: null};
  if (!o) return P;
  const mh = novig(o.ml.home.close || o.ml.home.open, o.ml.away.close || o.ml.away.open);
  if (mh != null) {
    const e = g.p_home - mh;
    if (Math.abs(e) >= EVEN) { const home = e > 0; P.ml = {pick: (home ? H : A) + ' ML', edge: Math.abs(e), mkt: home ? mh : 1 - mh, mod: home ? g.p_home : 1 - g.p_home}; }
  }
  if (o.spread && isFinite(o.spread.home.line)) {
    const favHome = o.spread.home.line < 0;
    const fo = favHome ? o.spread.home.odds : o.spread.away.odds, dO = favHome ? o.spread.away.odds : o.spread.home.odds;
    const mf = novig(fo, dO), mod = favHome ? g.puck_line['home_-1.5'] : g.puck_line['away_-1.5'];
    const fav = favHome ? H : A, dog = favHome ? A : H;
    if (mf != null) { const e = mod - mf; if (Math.abs(e) >= EVEN) P.pl = {pick: e > 0 ? fav + ' -1.5' : dog + ' +1.5', edge: Math.abs(e), mkt: e > 0 ? mf : 1 - mf, mod: e > 0 ? mod : 1 - mod, fav, dog, fo, dO, mf, modFav: mod}; else P.pl = {pick: null, fav, dog, fo, dO, mf, modFav: mod}; }
  }
  if (o.total && o.total.line != null) {
    const mo = novig(o.total.over, o.total.under), mod = modelOver(g, o.total.line);
    P.totInfo = {mo, mod};
    if (mo != null && mod != null) { const e = mod - mo; if (Math.abs(e) >= EVEN) P.tot = {pick: (e > 0 ? 'Over ' : 'Under ') + Number(o.total.line), edge: Math.abs(e)}; }
  }
  P.mh = mh;
  return P;
}
const pickTxt = x => x && x.pick ? `<span class="pk${x.edge >= STRONG ? ' strong' : ''}">Model pick: ${esc(x.pick)}, ${pp(x.edge)}</span>` : '<span class="nm">No pick (edge rounds to 0.0)</span>';

function marketHTML(g, G) {
  const o = G && (G.closeOdds || G.odds);
  if (!o) return `<span class="nm">${LIVE.feedOk ? 'No market line posted yet' : 'Live feed unavailable'}</span>`;
  const ml = o.ml, P = makePicks(g, o), mh = P.mh;
  const rows = [];
  if (mh != null) {
    const liveTxt = G && G.state === 'in' && ml.home.live ? ` · live ${fmtO(ml.away.live)}/${fmtO(ml.home.live)}` : '';
    rows.push(`<div class="dkr"><span class="dkl">Moneyline</span><span>${esc(g.away)} ${fmtO(ml.away.close || ml.away.open)} / ${esc(g.home)} ${fmtO(ml.home.close || ml.home.open)} <span class="nm">(open ${fmtO(ml.away.open)}/${fmtO(ml.home.open)}${liveTxt})</span></span><span>Market ${esc(g.home)} ${pc1(mh)} · Model ${pc1(g.p_home)}</span>${pickTxt(P.ml)}</div>`);
  }
  if (o.total && o.total.line != null) {
    const {mo, mod} = P.totInfo;
    rows.push(`<div class="dkr"><span class="dkl">Total ${o.total.line}</span><span>Over ${fmtO(o.total.over)} / Under ${fmtO(o.total.under)}</span><span>${mo != null ? 'Market over ' + pc1(mo) : ''}${mod != null ? ' · Model ' + pc1(mod) : ' · Model line not computed'}</span>${mod != null ? pickTxt(P.tot) : '<span class="nm">No pick at this line</span>'}</div>`);
  }
  if (P.pl) {
    const x = P.pl;
    rows.push(`<div class="dkr"><span class="dkl">Puck line</span><span>${esc(x.fav)} −1.5 ${fmtO(x.fo)} / ${esc(x.dog)} +1.5 ${fmtO(x.dO)}</span><span>${x.mf != null ? 'Market ' + esc(x.fav) + ' covers ' + pc1(x.mf) : ''} · Model ${pc1(x.modFav)}</span>${pickTxt(x)}</div>`);
  }
  const pre = !(G && G.state !== 'pre');
  return `<div class="dkh"><span class="dl">${esc(o.book)} vs model</span><span class="nm">Market % has the vig removed. ${pre ? 'Current line; picks are graded at the closing line.' : 'Closing line; these are the graded picks.'}</span></div>` + rows.join('');
}


/* ---------- line movement: DraftKings open vs close vs live, from the picked side ---------- */
LIVE.mvOpen = {};
function px(raw, mkt, side, k) {
  const m = raw && raw[mkt] && raw[mkt][side] && raw[mkt][side][k];
  if (!m || m.odds == null) return null;
  return {line: m.line != null ? String(m.line).replace(/^[ou]/, '') : null, odds: m.odds};
}
function cell(a, b) {
  if (!a) return '<td class="nm">–</td>';
  const p = b ? novig(a.odds, b.odds) : null;
  return `<td class="mono">${a.line != null ? esc(a.line) + ' ' : ''}${fmtO(a.odds)}${p != null ? ' <span class="nm">' + pc1(p) + '</span>' : ''}</td>`;
}
function moveCell(o, c, oo, co, label) {
  if (!o || !c || !oo || !co) return '<td class="nm">–</td>';
  if (o.line != null && c.line != null && o.line !== c.line) return `<td class="nm">line moved ${esc(o.line)} to ${esc(c.line)}</td>`;
  const d = novig(c.odds, co.odds) - novig(o.odds, oo.odds);
  if (!isFinite(d)) return '<td class="nm">–</td>';
  if (Math.abs(d) < 0.0005) return '<td class="nm">no move</td>';
  return `<td class="mono ${d > 0 ? 'mv-up' : 'mv-dn'}">${pp(d)}${label ? ' <span class="nm">' + label(d) + '</span>' : ''}</td>`;
}
function movementHTML(g, G, k) {
  const o = G && (G.closeOdds || G.odds);
  if (!o || !o.raw) return '';
  const raw = o.raw, P = makePicks(g, o), started = G.state !== 'pre';
  const rows = [];
  const add = (name, mkt, side, other, sideLbl, picked) => {
    const op = px(raw, mkt, side, 'open'), cl = px(raw, mkt, side, 'close'), lv = px(raw, mkt, side, 'live');
    const oo = px(raw, mkt, other, 'open'), co = px(raw, mkt, other, 'close'), lo = px(raw, mkt, other, 'live');
    if (!op && !cl) return;
    const lab = picked ? (d => d > 0 ? 'toward pick' : 'against pick') : null;
    rows.push(`<tr><td>${name}</td><td>${esc(sideLbl)}${picked ? ' <span class="pk">pick</span>' : ''}</td>${cell(op, oo)}${cell(cl, co)}${started ? cell(lv, lo) : ''}${moveCell(op, cl, oo, co, lab)}</tr>`);
  };
  const H = g.home, A = g.away;
  { const s = P.ml ? (P.ml.pick.startsWith(H + ' ') ? 'home' : 'away') : 'home';
    add('Moneyline', 'moneyline', s, s === 'home' ? 'away' : 'home', (s === 'home' ? H : A) + ' ML', !!P.ml); }
  if (P.pl || o.spread) {
    let s;
    if (P.pl && P.pl.pick) { const takeFav = P.pl.pick.endsWith('-1.5'); const favHome = o.spread.home.line < 0; s = (takeFav === favHome) ? 'home' : 'away'; }
    else s = o.spread && o.spread.home.line < 0 ? 'home' : 'away';
    const ln = px(raw, 'pointSpread', s, 'close') || px(raw, 'pointSpread', s, 'open');
    add('Puck line', 'pointSpread', s, s === 'home' ? 'away' : 'home', (s === 'home' ? H : A) + ' ' + (ln && ln.line ? ln.line : ''), !!(P.pl && P.pl.pick));
  }
  { const s = P.tot && P.tot.pick.startsWith('Under') ? 'under' : 'over';
    add('Total', 'total', s, s === 'over' ? 'under' : 'over', s === 'over' ? 'Over' : 'Under', !!P.tot); }
  if (!rows.length) return '';
  const open = LIVE.mvOpen[k] ? ' open' : '';
  return `<details class="mx mv" data-k="${esc(k)}"${open}><summary><span class="xt">Line movement</span><span class="xh">${esc(o.book)} open vs ${started ? 'close vs live' : 'now'}</span><span class="chev" aria-hidden="true"></span></summary>
    <div class="tbl"><table class="mvt"><tr><th>Market</th><th>Side</th><th>Open</th><th>${started ? 'Close' : 'Now'}</th>${started ? '<th>Live</th>' : ''}<th>${started ? 'Open to close' : 'Move so far'}</th></tr>${rows.join('')}</table></div>
    <p class="mxnote">Percentages have the vig removed, shown for the side listed. A move toward the model's pick before puck drop is a good sign the model saw something the market later agreed with.${started ? ' Live prices reflect the score and clock, so they are not a fair comparison to the pre-game line.' : ''}</p></details>`;
}
document.addEventListener('toggle', e => { const d = e.target; if (d.matches && d.matches('details.mv')) LIVE.mvOpen[d.dataset.k] = d.open; }, true);

function render() {
  for (const [k, C] of Object.entries(LIVE.cards)) {
    const G = LIVE.games[k];
    C.lv.innerHTML = statusHTML(G, C.g);
    C.el.classList.toggle('is-live', !!G && G.state === 'in');
    C.el.classList.toggle('is-final', !!G && G.state === 'post');
    C.dk.innerHTML = marketHTML(C.g, G) + movementHTML(C.g, G, k);
    if (C.det.open) refreshPanel(k, false);
  }
  tally();
}

/* ---------- live game panel ---------- */
async function refreshPanel(k, force) {
  const C = LIVE.cards[k], G = LIVE.games[k];
  if (!G) { C.body.innerHTML = `<p class="mxnote">${LIVE.feedOk ? 'Waiting for the live feed.' : 'Live feed unavailable.'}</p>`; return; }
  if (G.state === 'pre') { C.body.innerHTML = '<p class="mxnote">Live stats appear here at puck drop.</p>'; return; }
  const stale = Date.now() - C.sumAt > 25000;
  if (force || (G.state === 'in' && stale) || !C.summary) {
    try { C.summary = await getJSON(`${ESPN}/summary?event=${G.id}`); C.sumAt = Date.now(); }
    catch (e) { if (!C.summary) { C.body.innerHTML = '<p class="mxnote">Live feed unavailable.</p>'; return; } }
  }
  C.body.innerHTML = panelHTML(C.g, G, C.summary);
}

function teamSide(s, abbr) {
  const b = s.boxscore || {};
  const T = (b.teams || []).find(t => fixAb(t.team.abbreviation) === abbr);
  const P = (b.players || []).find(t => fixAb(t.team.abbreviation) === abbr);
  return {T, P};
}
function statOf(T, name) { const x = T && T.statistics.find(s => s.name === name); return x ? x.displayValue : '–'; }
function groupRows(P, name) {
  const grp = P && P.statistics.find(s => s.name === name); if (!grp) return [];
  const L = grp.labels || [];
  return (grp.athletes || []).map(a => { const r = {name: a.athlete.shortName || a.athlete.displayName}; L.forEach((l, i) => r[l] = a.stats[i]); return r; });
}

function panelHTML(g, G, s) {
  if (!s) return '<p class="mxnote">Live feed unavailable.</p>';
  const A = g.away, H = g.home, sa = teamSide(s, A), sh = teamSide(s, H);
  const goal = side => groupRows(side.P, 'goalies').filter(r => r.TOI && r.TOI !== '0:00');
  const grows = [...goal(sa).map(r => [A, r]), ...goal(sh).map(r => [H, r])];
  const gtab = grows.length ? `<table class="lt"><tr><th>Goalie</th><th>SA</th><th>SV</th><th>SV%</th><th>GA</th><th>TOI</th></tr>${grows.map(([t, r]) => `<tr><td><span class="tg ${t === A ? 'a' : 'h'}">${esc(t)}</span> ${esc(r.name)}</td><td>${esc(r.SA)}</td><td>${esc(r.SV)}</td><td>${esc(r['SV%'])}</td><td>${esc(r.GA)}</td><td>${esc(r.TOI)}</td></tr>`).join('')}</table>` : '<p class="mxnote">No goalie stats yet.</p>';
  const TS = [['Shots', 'shotsTotal'], ['Hits', 'hits'], ['Blocked shots', 'blockedShots'], ['Power play', 'pp'], ['Faceoff %', 'faceoffPercent']];
  const tv = (T, n) => n === 'pp' ? `${statOf(T, 'powerPlayGoals')}/${statOf(T, 'powerPlayOpportunities')}` : statOf(T, n);
  const ttab = `<table class="lt ts"><tr><th class="a">${esc(A)}</th><th>Team stats</th><th class="h">${esc(H)}</th></tr>${TS.map(([l, n]) => `<tr><td>${esc(tv(sa.T, n))}</td><td class="c">${l}</td><td>${esc(tv(sh.T, n))}</td></tr>`).join('')}</table>`;
  const sk = side => [...groupRows(side.P, 'forwards'), ...groupRows(side.P, 'defenses')];
  const all = [...sk(sa).map(r => [A, r]), ...sk(sh).map(r => [H, r])].map(([t, r]) => ({t, r, pts: (+r.G || 0) + (+r.A || 0), sog: +(r.S ?? r.SOG) || 0}));
  all.sort((x, y) => y.pts - x.pts || y.sog - x.sog);
  const top = all.slice(0, 8);
  const stab = top.length ? `<table class="lt"><tr><th>Skater</th><th>G</th><th>A</th><th>SOG</th><th>TOI</th></tr>${top.map(x => `<tr><td><span class="tg ${x.t === A ? 'a' : 'h'}">${esc(x.t)}</span> ${esc(x.r.name)}</td><td>${esc(x.r.G)}</td><td>${esc(x.r.A)}</td><td>${esc(x.r.S ?? x.r.SOG)}</td><td>${esc(x.r.TOI)}</td></tr>`).join('')}</table>` : '';
  const plays = [...(s.plays || [])].sort((x, y) => (+x.sequenceNumber || 0) - (+y.sequenceNumber || 0)).slice(-5).reverse();
  /* ESPN play clocks count up (time elapsed); show time remaining to match the game clock */
  const left = p => {
    const per = p.period && p.period.number, el = p.clock && p.clock.displayValue;
    const m = /^(\d+):(\d{2})$/.exec(el || ''); const len = per >= 5 ? 0 : per === 4 ? 300 : 1200;
    if (!m || !len) return el || '';
    const r = Math.max(0, len - (+m[1] * 60 + +m[2]));
    return `${Math.floor(r / 60)}:${String(r % 60).padStart(2, '0')}`;
  };
  const ptab = plays.length ? `<ol class="plays">${plays.map(p => `<li class="${p.scoringPlay ? 'goal' : ''}"><span class="pt">${esc(p.period && p.period.displayValue)} ${esc(left(p))}</span> ${esc(p.text)}</li>`).join('')}</ol>` : '';
  let res = '';
  if (G.state === 'post') {
    const hw = G.hWin != null ? G.hWin : G.hs > G.as;
    const c = G.closeOdds && novig(G.closeOdds.ml.home.close, G.closeOdds.ml.away.close);
    const suf = /OT/i.test(G.detail) ? ' in overtime' : /SO/i.test(G.detail) ? ' in a shootout' : '';
    res = `<div class="res"><b>Final${suf}: ${esc(A)} ${G.as}, ${esc(H)} ${G.hs}.</b> Locked projection: ${esc(A)} ${g.proj_away.toFixed(2)}, ${esc(H)} ${g.proj_home.toFixed(2)}, ${esc(H)} ${pc1(g.p_home)} to win${c != null ? `; ${esc(G.closeOdds.book)} close had ${esc(H)} at ${pc1(c)}` : ''}. The model's pick ${(g.p_home >= 0.5) === hw ? 'won' : 'lost'}.</div>`;
  }
  return `${res}<div class="lgrid"><div class="lcol"><div class="sh">Goalies</div>${gtab}<div class="sh">Team stats</div>${ttab}</div><div class="lcol"><div class="sh">Top skaters (points, then shots)</div>${stab}<div class="sh">Last 5 plays</div>${ptab}</div></div><p class="mxnote">${G.state === 'in' ? 'Updates every 30 seconds while this panel is open.' : 'Final box score.'} Source: ESPN public feed.</p>`;
}

/* ---------- nightly tally ---------- */
function tally() {
  const el = document.getElementById('tally'); if (!el) return;
  let n = 0, w = 0, llM = 0, llK = 0, nK = 0, closer = 0;
  for (const [k, G] of Object.entries(LIVE.games)) {
    if (G.state !== 'post') continue;
    const g = LIVE.cards[k].g, hw = (G.hWin != null ? G.hWin : G.hs > G.as) ? 1 : 0;
    n++; if ((g.p_home >= 0.5 ? 1 : 0) === hw) w++;
    const c = G.closeOdds && novig(G.closeOdds.ml.home.close, G.closeOdds.ml.away.close);
    if (c != null) {
      const lm = -Math.log(hw ? g.p_home : 1 - g.p_home), lk = -Math.log(hw ? c : 1 - c);
      llM += lm; llK += lk; nK++; if (lm < lk) closer++;
    }
  }
  if (!n) { el.innerHTML = '<span class="nm">Tonight\'s scorecard appears as games go final.</span>'; return; }
  el.innerHTML = `<span><b>Tonight:</b> model favorite ${w}-${n - w}</span>` + (nK ? `<span>Log loss model ${(llM / nK).toFixed(3)} vs DraftKings close ${(llK / nK).toFixed(3)} (${nK} game${nK > 1 ? 's' : ''}, lower is better)</span><span>Model closer to the result in ${closer} of ${nK}</span>` : '');
}

function startLive(B) {
  LIVE.B = B;
  try { scaffold(B); } catch (e) { return; }
  pollScoreboard();
  LIVE.timer = setInterval(() => {
    const vals = Object.values(LIVE.games);
    if (vals.length && vals.length === Object.keys(LIVE.cards).length && vals.every(G => G.state === 'post' && G.closeOdds)) { render(); clearInterval(LIVE.timer); stamp('All games final.'); return; }
    pollScoreboard();
  }, 30000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) pollScoreboard(); });
}
