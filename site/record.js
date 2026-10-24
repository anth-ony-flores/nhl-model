/* Model record strip: reads data/record.json written nightly by src/track.py. Hidden when there is no record yet. */
(function () {
  const fmtU = u => u == null ? '' : (u >= 0 ? '+' : '−') + Math.abs(u).toFixed(2) + 'u';
  const wl = r => `${r.w}-${r.l}${r.p ? '-' + r.p : ''}`;
  const pct = r => r.pct == null ? '' : (100 * r.pct).toFixed(1) + '%';
  function card(label, r, units) {
    const cls = r.units == null ? '' : r.units >= 0 ? 'pos' : 'neg';
    return `<div class="rc"><span class="l">${label}</span><span class="v">${wl(r)}</span><span class="s">${pct(r)}${units && r.units != null ? ` · <span class="${cls}">${fmtU(r.units)}</span>` : ''}</span></div>`;
  }
  async function load() {
    let d;
    try { const res = await fetch('data/record.json', {cache: 'no-store'}); if (!res.ok) return; d = await res.json(); } catch (e) { return; }
    const S = d && d.summary; if (!S || !S.games) return;
    const R = S.record, ll = S.logloss;
    const el = document.createElement('section'); el.className = 'rec'; el.id = 'record'; el.setAttribute('aria-label', 'Model record');
    el.innerHTML = `<div class="rec-h"><h2>Model record</h2><a href="history.html">Every graded pick</a></div>
      <div class="rec-grid">${card('Straight up', R.su, false)}${card('Moneyline', R.ml, true)}${card('Puck line', R.pl, true)}${card('Total', R.tot, true)}</div>
      <p class="rec-n">${S.games} game${S.games === 1 ? '' : 's'} through ${S.updated}. Graded at DraftKings closing lines, 1 unit per pick.${ll && ll.games ? ` Moneyline log loss: model ${ll.model.toFixed(3)}, market ${ll.market.toFixed(3)} (lower is better).` : ''}</p>`;
    const hdr = document.querySelector('header');
    if (hdr) hdr.after(el);
  }
  load();
})();
