/* Player props page: projections vs DraftKings lines. Data: data/props.json (built by src/props_lines.py).
   Odds refresh from ESPN's public DraftKings feed every 5 minutes; the model's probability for a moved line
   comes from the per-player curve in props.json. Side convention matches props_lines.py: the first item of
   each over/under pair is the over (verified against DraftKings' one-sided milestone prices). */
(function () {
  const MK = [["sog", "Shots on goal"], ["pts", "Points"], ["goal", "Anytime goal"], ["saves", "Goalie saves"]];
  const FEED = { "Total Shots on Goal": "sog", "Total Points": "pts", "Anytime Goalscorer": "goal", "Total Saves": "saves" };
  const CORE = "https://sports.core.api.espn.com/v2/sports/hockey/leagues/nhl";
  const EVEN = 0.0005;
  let D = null, M = "sog", TEAM = "all", ST = false, oddsNote = "";

  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = o => { if (o == null || o === "") return null; const s = String(o).toUpperCase(); if (s === "EVEN") return 100; const n = parseFloat(s.replace("+", "")); return isFinite(n) ? n : null; };
  const fmtO = o => { const n = num(o); return n == null ? "" : (n > 0 ? "+" + n : String(n)); };
  const imp = o => { const n = num(o); if (n == null) return null; return n < 0 ? -n / (-n + 100) : 100 / (n + 100); };
  const novig = (a, b) => { const x = imp(a), y = imp(b); return x == null || y == null ? null : x / (x + y); };
  const pct = p => p == null ? "" : (100 * p).toFixed(1) + "%";
  const ln = v => v == null ? "" : (Number.isInteger(v) ? v.toFixed(0) : String(v));
  const STRONG = () => (D && D.strong) || 0.03;

  function score(r, m) {
    r.p_over = r.curve && r.curve[String(r.line)] != null ? r.curve[String(r.line)] : (r.line === r._line0 ? r.p_over : null);
    if (m === "goal") { r.mkt_over = imp(r.over); r.edge_over = r.p_over != null && r.mkt_over != null ? r.p_over - r.mkt_over : null; r.edge_under = null; }
    else {
      r.mkt_over = novig(r.over, r.under);
      r.edge_over = r.p_over != null && r.mkt_over != null ? r.p_over - r.mkt_over : null;
      r.edge_under = r.edge_over == null ? null : -r.edge_over;
    }
    r.lean = null; r.edge = null;
    if (r.edge_over != null && r.edge_over >= EVEN && (r.edge_under == null || r.edge_over >= r.edge_under)) { r.lean = m === "goal" ? "Yes" : "Over"; r.edge = r.edge_over; }
    else if (r.edge_under != null && r.edge_under >= EVEN) { r.lean = "Under"; r.edge = r.edge_under; }
    r.strong = r.edge != null && r.edge >= STRONG();
  }

  function oddsCell(cur, open, line, openLine) {
    if (cur == null) return "";
    const moved = (open != null && fmtO(open) !== fmtO(cur)) || (openLine != null && openLine !== line);
    const o = moved ? `<span class="op">open ${openLine != null && openLine !== line ? ln(openLine) + " " : ""}${esc(fmtO(open))}</span>` : "";
    return `${esc(fmtO(cur))}${o}`;
  }

  function table(g, m, rows) {
    const goal = m === "goal", sv = m === "saves";
    const unit = { sog: "shots on goal", pts: "points", goal: "goals", saves: "saves" }[m];
    const th = (txt, tip, cls) => `<th${cls ? ` class="${cls}"` : ""}><span class="tip" tabindex="0" data-tip="${esc(tip)}">${txt}</span></th>`;
    const head = "<tr>" +
      th("Player", "Only players with a DraftKings line today are listed.") +
      th("Team", "Player's team.", "tm") +
      th("DK line", goal ? "Anytime goal: the player scores at least once (1+)." : `DraftKings' current line. Over means more than this many ${unit}. If the line moved, the opening line shows under the odds.`) +
      th(goal ? "Yes" : "Over", goal ? "DraftKings' current price for the player to score, with the opening price below it." : "DraftKings' current price on the over, with the opening price below it.") +
      (goal ? "" : th("Under", "DraftKings' current price on the under, with the opening price below it.")) +
      th("Proj", `The model's average projected ${unit} for this player in this game.`) +
      th(`Model P(${goal ? "goal" : "over"})`, goal ? "The model's chance the player scores." : "The model's chance the player goes over the line.") +
      th(`Market P(${goal ? "goal" : "over"})`, goal ? "DraftKings' implied chance he scores. Single price, so the bookmaker's margin is still in it and the edge reads low." : "DraftKings' implied chance of the over, with the bookmaker's margin removed.") +
      th("Edge", "Model chance minus market chance on the side the model leans, in percentage points. 3.0 or more is tagged strong.") +
      th("Model lean", "The side and line the model favors, e.g. Under 2.5 shots means the model expects 2 or fewer. A projection, not a pick: prop picks stay off until validated.", "tm") + "</tr>";
    const body = rows.map(r => {
      const lc = r.lean === "Under" ? "un" : r.lean ? "ov" : "no";
      const who = esc(r.player) + (sv && r.starter === false ? ' <span class="op">not the projected starter</span>' : "");
      return `<tr${g.state === "post" ? ' class="done"' : ""}><td>${who}</td><td class="tm">${esc(r.team)}</td><td>${goal ? "1+" : ln(r.line)}</td>` +
        `<td>${oddsCell(r.over, r.over_open, r.line, r.open_line)}</td>${goal ? "" : `<td>${oddsCell(r.under, r.under_open, r.line, r.open_line)}</td>`}` +
        `<td>${r.mean == null ? "" : (sv ? r.mean.toFixed(1) : r.mean.toFixed(2))}</td><td>${pct(r.p_over)}</td>` +
        `<td>${pct(r.mkt_over)}${goal && r.mkt_over != null ? '<span class="op">vig in</span>' : ""}</td>` +
        `<td>${r.edge == null ? "" : (100 * r.edge).toFixed(1) + " pts"}</td>` +
        `<td class="lean ${lc}">${r.lean ? `${r.lean} ${ln(r.line)} ${{ sog: "shots", pts: "pts", goal: "goals", saves: "saves" }[m]}` : "None"}${r.strong ? '<span class="stg">strong</span>' : ""}</td></tr>`;
    }).join("");
    return `<div class="pp-mk"><h3>${MK.find(x => x[0] === m)[1]}</h3><div class="tbl"><table class="ptb">${head}${body}</table></div></div>`;
  }

  function draw() {
    const el = document.getElementById("pp-games");
    const parts = [];
    for (const g of D.games) {
      if (TEAM !== "all" && g.home !== TEAM && g.away !== TEAM) continue;
      const blocks = [];
      for (const [m] of MK) {
        if (M !== "all" && M !== m) continue;
        const rows = (g.markets[m] || []).filter(r => (TEAM === "all" || r.team === TEAM) && (!ST || r.strong));
        if (rows.length) blocks.push(table(g, m, rows));
      }
      if (!blocks.length) continue;
      const t = new Date(g.start_utc);
      const when = g.state === "pre" || !g.state ? t.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) :
        g.state === "in" ? `<span class="live">Live${g.detail ? ": " + esc(g.detail) : ""}</span>` : esc(g.detail || "Final");
      const gl = [g.away_goalie && `${esc(g.away)}: ${esc(g.away_goalie)}`, g.home_goalie && `${esc(g.home)}: ${esc(g.home_goalie)}`].filter(Boolean).join(" · ");
      parts.push(`<section class="pp-game" aria-label="${esc(g.away)} at ${esc(g.home)}"><div class="pp-gh"><h2>${esc(g.away)}<span class="at">at</span>${esc(g.home)}</h2><span class="gm">${when}</span></div>` +
        (gl ? `<div class="pp-gl">Projected goalies: ${gl}</div>` : "") + blocks.join("") + `</section>`);
    }
    el.innerHTML = parts.length ? parts.join("") : `<p class="pp-empty">No DraftKings lines match these filters.</p>`;
    const n = D.games.reduce((a, g) => a + Object.values(g.markets).reduce((b, v) => b + v.length, 0), 0);
    document.getElementById("pp-meta").textContent = `${D.date} · ${n} DraftKings lines · player data through ${D.data_through} · ${oddsNote}`;
  }

  function gate() {
    const el = document.getElementById("pp-gate");
    if (D.picks_enabled) { el.innerHTML = `<b>Picks on</b><span>Leans with an edge of ${(100 * STRONG()).toFixed(0)} points or more are graded in the pick history.</span>`; return; }
    const bt = D.backtest || {};
    const lines = (bt.rows || []).map(r => `${esc(r.label)}: log loss ${r.model.toFixed(3)} vs ${r.base.toFixed(3)} naive`).join("; ");
    el.innerHTML = `<b>Picks start after validation</b><span>These are projections, not picks. No prop picks are made or tracked until the backtest is reviewed.</span>` +
      (lines ? `<span class="op">Backtest ${esc(bt.seasons || "")} (lower is better): ${lines}. No historical DraftKings prop prices were available, so this measures accuracy, not profit.</span>` : "");
  }

  function filters() {
    const teams = [...new Set(D.games.flatMap(g => [g.away, g.home]))].sort();
    const sel = document.getElementById("pp-team");
    sel.innerHTML = `<option value="all">All teams</option>` + teams.map(t => `<option value="${esc(t)}">${esc(t)}</option>`).join("");
    sel.addEventListener("change", () => { TEAM = sel.value; draw(); });
    document.getElementById("pp-mkt").addEventListener("click", e => {
      const b = e.target.closest("button"); if (!b) return;
      M = b.dataset.m; document.querySelectorAll("#pp-mkt button").forEach(x => x.setAttribute("aria-pressed", x === b)); draw();
    });
    const sb = document.getElementById("pp-strong");
    sb.addEventListener("click", () => { ST = !ST; sb.setAttribute("aria-pressed", ST); draw(); });
  }

  // ---- live odds from ESPN (DraftKings) ----
  function parseFeed(feed) {
    const by = {};
    for (const x of (feed && feed.items) || []) {
      if (!x.athlete) continue;
      const aid = x.athlete.$ref.split("/athletes/")[1].split("?")[0];
      (by[x.type.name + "|" + aid] = by[x.type.name + "|" + aid] || []).push(x);
    }
    const out = {};
    const tv = (it, k) => ((it[k] || {}).target || {}).value;
    for (const key in by) {
      const [t, aid] = key.split("|"), m = FEED[t]; if (!m) continue;
      const xs = by[key];
      if (m === "goal") { out[m + "|" + aid] = { line: 0.5, open_line: 0.5, over: xs[0].odds.american.value, over_open: xs[0].odds.american.open, under: null, under_open: null }; continue; }
      if (xs.length < 2) continue;
      const o = xs[0], u = xs[1], L = tv(o, "current");   // first item = over (verified in props_lines.py)
      out[m + "|" + aid] = { line: L, open_line: tv(o, "open"), over: o.odds.american.value, over_open: o.odds.american.open, under: u.odds.american.value, under_open: u.odds.american.open };
    }
    return out;
  }

  async function refresh() {
    // pre-game lines only: once a game starts, DraftKings switches to in-game prices, which the model does not project
    const live = D.games.filter(g => g.espn_id && (!g.state || g.state === "pre"));
    if (!live.length) return;
    let ok = 0;
    await Promise.all(live.map(async g => {
      try {
        const r = await fetch(`${CORE}/events/${g.espn_id}/competitions/${g.espn_id}/odds/100/propBets?limit=1000`, { cache: "no-store" });
        if (!r.ok) throw new Error(r.status);
        const L = parseFeed(await r.json());
        for (const m in g.markets) for (const row of g.markets[m]) {
          const x = L[m + "|" + row.espn_id];
          if (!x) continue;
          Object.assign(row, x); score(row, m);
        }
        ok++;
      } catch (e) { /* keep the server-built odds */ }
    }));
    if (ok) { oddsNote = `odds refreshed ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} from ESPN (DraftKings)`; draw(); }
  }

  // ---- game status from ESPN scoreboard (every 30 s, same feed as the Games tab) ----
  async function status() {
    try {
      const r = await fetch(`https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates=${D.date.replace(/-/g, "")}`, { cache: "no-store" });
      if (!r.ok) return;
      const sb = await r.json(), by = {};
      for (const e of sb.events || []) { const t = e.competitions[0].status.type; by[e.id] = { state: t.state, detail: t.shortDetail }; }
      let ch = false;
      for (const g of D.games) {
        const x = by[g.espn_id];
        if (x && (x.state !== g.state || x.detail !== g.detail)) { g.state = x.state; g.detail = x.detail; ch = true; }
      }
      if (ch) draw();
    } catch (e) { /* keep last known status */ }
  }

  fetch("data/props.json", { cache: "no-store" }).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }).then(d => {
    D = d;
    for (const g of D.games) for (const m in g.markets) for (const r of g.markets[m]) r._line0 = r.line;
    const t = new Date(D.generated);
    oddsNote = `odds as of ${isNaN(t) ? D.generated : t.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
    gate(); filters(); draw();
    status().then(refresh); setInterval(status, 30 * 1000); setInterval(refresh, 5 * 60 * 1000);
  }).catch(() => {
    document.getElementById("pp-games").innerHTML = '<p class="pp-empty">Prop data could not be loaded. Try reloading the page.</p>';
  });
})();
