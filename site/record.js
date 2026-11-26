/* Model record strip: reads data/record.json written nightly by src/track.py. Hidden when there is no record yet. */
(function () {
  const fmtU = u => u == null ? '' : (u >= 0 ? '+' : '−') + Math.abs(u).toFixed(2) + 'u';
  const wl = r => `${r.w}-${r.l}${r.p ? '-' + r.p : ''}`;
  const pct = r => r.pct == null ? '' : (100 * r.pct).toFixed(1) + '%';
  function card(label, r, units) {
    const cls = r.units == null ? '' : r.units >= 0 ? 'pos' : 'neg';
    const n = r.w + r.l + (r.p || 0);
    const sub = n ? [pct(r), units && r.units != null ? `<span class="${cls}">${fmtU(r.units)}</span>` : ''].filter(Boolean).join(' · ') : 'No picks yet';
    return `<div class="rc"><span class="l">${label}</span><span class="v">${wl(r)}</span><span class="s">${sub}</span></div>`;
  }
  function clvLine(S) {
    const f = (c, lab) => c && c.n ? `${lab}: ${c.avg_pts >= 0 ? '+' : '−'}${Math.abs(c.avg_pts).toFixed(1)} pts avg, ${(100 * c.beat_close_pct).toFixed(0)}% moved toward the pick (${c.n})` : '';
    const all = ['ml', 'pl', 'tot'].map(m => S.clv && S.clv[m]).filter(c => c && c.n);
    const st = ['ml', 'pl', 'tot'].map(m => S.clv_strong && S.clv_strong[m]).filter(c => c && c.n);
    const pool = cs => { const n = cs.reduce((a, c) => a + c.n, 0); return n ? {n, avg_pts: cs.reduce((a, c) => a + c.avg_pts * c.n, 0) / n, beat_close_pct: cs.reduce((a, c) => a + c.beat_close_pct * c.n, 0) / n} : null; };
    const a = pool(all), b = pool(st);
    if (!a) return '';
    return `<p class="rec-n">Line movement after the pick, open to close: ${f(a, 'all picks')}${b ? '; ' + f(b, 'strong picks') : ''}.</p>`;
  }
  async function load() {
    let d;
    try { const res = await fetch('data/record.json', {cache: 'no-store'}); if (!res.ok) return; d = await res.json(); } catch (e) { return; }
    const S = d && d.summary; if (!S || !S.games) return;
    const O = S.open && S.open.games ? S.open : null;
    const P = O || S, R = P.record;
    const el = document.createElement('section'); el.className = 'rec'; el.id = 'record'; el.setAttribute('aria-label', 'Model record');
    const ll = O ? O.logloss : S.logloss;
    const llTxt = ll && ll.games ? (O ? ` Moneyline log loss: model (locked) ${ll.model_lock.toFixed(3)}, DraftKings open ${ll.market_open.toFixed(3)}, close ${ll.market_close.toFixed(3)} (lower is better).`
                                      : ` Moneyline log loss: model ${ll.model.toFixed(3)}, market ${ll.market.toFixed(3)} (lower is better).`) : '';
    const c = S.all_picks;
    el.innerHTML = `<div class="rec-h"><h2>Model record${O ? ': bet at the opening line' : ''}</h2><a href="history.html">Every graded pick</a></div>
      <div class="rec-grid">${card('Straight up', R.su, false)}${card('Moneyline', R.ml, true)}${card('Puck line', R.pl, true)}${card('Total', R.tot, true)}</div>
      ${P.strong_all ? `<div class="rec-h rec-sub"><h3>Strong edge picks (3+ pts)</h3></div>
      <div class="rec-grid">${card('All strong', P.strong_all, true)}${card('Moneyline', P.strong.ml, true)}${card('Puck line', P.strong.pl, true)}${card('Total', P.strong.tot, true)}</div>` : ''}
      ${clvLine(P)}
      <p class="rec-n">${P.games} game${P.games === 1 ? '' : 's'} through ${S.updated}. ${O ? 'Picks come from the morning projection, locked, against DraftKings\' opening prices and are graded at those prices, 1 unit per pick.' : 'Graded at DraftKings closing lines, 1 unit per pick.'}${llTxt}${O && c ? ` For comparison, the latest projection against the closing line: ${c.w}-${c.l}${c.p ? '-' + c.p : ''}, ${fmtU(c.units)}.` : ''}</p>`;
    const hdr = document.querySelector('header');
    if (hdr) hdr.after(el);
  }
  load();
})();
