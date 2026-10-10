/* LeakWatch front-end: hash-routed static app over site/data/*.json */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const app = $("#app");
  const S = { claims: [], leakers: [], meta: {}, byId: {}, byHandle: {}, claimsByHandle: {} };
  const UI = { feedTab: "latest", lab: "all", q: "", showStale: false, minScore: 0, limit: 60,
               lbGroup: "leakers", lbCat: "all", lbSort: "leak_score", lbDir: -1, profFilter: "all" };

  const VERDICT_LABEL = {
    true: "Came true", mostly_true: "Mostly true", partly_true: "Partly true", false: "False",
    pending: "Pending", already_public: "Already public", unverifiable: "Unverifiable", unfalsifiable: "Too vague",
  };
  const CAT_LABEL = { anon_insider: "Anon insider", reverse_engineer: "Code sleuth", journalist: "Journalist",
                      aggregator: "Aggregator", commentator: "Commentator", newcomer: "Newcomer" };
  const RESOLVED = new Set(["true", "mostly_true", "partly_true", "false"]);

  // ---------- utils ----------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtDate = (s) => { if (!s) return ""; const d = new Date(s.length <= 10 ? s + "T00:00:00Z" : s);
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }); };
  const fmtNum = (n) => n == null ? "–" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + "k" : String(n);
  const pct = (x) => x == null ? "–" : Math.round(x * 100) + "%";
  const scoreColor = (s) => {
    // red -> amber -> green
    const t = Math.max(0, Math.min(1, (s - 15) / 70));
    const h = 0 + t * 135;
    return `hsl(${h} 78% ${document.documentElement.dataset.theme === "light" || (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: light)").matches) ? 40 : 58}%)`;
  };
  const ring = (score, size = "", cap = "") => {
    const r = 26, c = 2 * Math.PI * r, v = Math.max(0, Math.min(100, score ?? 0));
    const col = score == null ? "var(--line2)" : scoreColor(v);
    return `<div class="ring ${size}" title="Legitimacy score">
      <svg viewBox="0 0 60 60"><circle cx="30" cy="30" r="${r}" fill="none" stroke="var(--line)" stroke-width="5"/>
      <circle cx="30" cy="30" r="${r}" fill="none" stroke="${col}" stroke-width="5" stroke-linecap="round"
        stroke-dasharray="${(c * v) / 100} ${c}"/></svg>
      <div class="num" style="color:${col}">${score == null ? "–" : Math.round(v)}</div>${cap ? `<div class="cap">${cap}</div>` : ""}</div>`;
  };
  const avatar = (l, cls = "") => {
    const src = l && l.avatar ? l.avatar.replace("_normal.", "_bigger.") : "";
    return src ? `<img class="avatar ${cls}" src="${esc(src)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'">`
               : `<span class="avatar ${cls}"></span>`;
  };
  const dots = (n) => `<span class="dots" title="Specificity ${n}/5">${[1, 2, 3, 4, 5].map((i) => `<i class="${i <= n ? "on" : ""}"></i>`).join("")}</span>`;
  const pill = (v) => `<span class="pill v-${v}">${VERDICT_LABEL[v] || v}</span>`;
  const leakerOf = (c) => S.byHandle[c.handle.toLowerCase()] || { handle: c.handle, name: c.handle, stats: null };
  const credChip = (l) => {
    if (!l || !l.stats || !l.stats.n_resolved) return `<span class="cred">no record</span>`;
    return `<span class="cred" title="Track-record credibility (Bayesian) over ${l.stats.n_resolved} resolved claims">${pct(l.stats.credibility)} · ${l.stats.n_resolved} res.</span>`;
  };
  const dayLabel = (iso) => {
    const d = iso.slice(0, 10), today = new Date().toISOString().slice(0, 10);
    const y = new Date(Date.now() - 864e5).toISOString().slice(0, 10);
    return d === today ? "Today" : d === y ? "Yesterday" : fmtDate(d);
  };
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

  // ---------- data ----------
  async function load() {
    const get = (p) => fetch(p, { cache: "no-cache" }).then((r) => r.json());
    const [claims, leakers, meta] = await Promise.all([get("data/claims.json"), get("data/leakers.json"), get("data/meta.json")]);
    S.claims = claims; S.leakers = leakers; S.meta = meta;
    claims.forEach((c) => { S.byId[c.id] = c; (S.claimsByHandle[c.handle.toLowerCase()] ||= []).push(c); });
    leakers.forEach((l) => { S.byHandle[l.handle.toLowerCase()] = l; (l.aliases || []).forEach((a) => (S.byHandle[a.toLowerCase()] = l)); });
    $("#footMeta").textContent = meta.updated_at ? `Updated ${fmtDate(meta.updated_at)} · ${fmtNum(meta.n_claims)} claims · ${meta.n_leakers} leakers` : "";
  }

  // ---------- feed ----------
  function feedFilter() {
    const q = UI.q.trim().toLowerCase();
    let list = S.claims.filter((c) => {
      if (!UI.showStale && (c.verdict === "already_public")) return false;
      if (UI.lab !== "all" && c.lab !== UI.lab) return false;
      if (UI.feedTab === "pending" && c.verdict !== "pending") return false;
      if (UI.feedTab === "resolved" && !RESOLVED.has(c.verdict)) return false;
      if (UI.feedTab === "top" && !(c.verdict === "pending" && (c.legitimacy?.score ?? 0) >= 55)) return false;
      if (q && !(c.claim.toLowerCase().includes(q) || c.handle.toLowerCase().includes(q) || (c.lab || "").toLowerCase().includes(q))) return false;
      return true;
    });
    if (UI.feedTab === "top") list.sort((a, b) => (b.legitimacy?.score ?? 0) * (b.significance || 3) - (a.legitimacy?.score ?? 0) * (a.significance || 3));
    else list.sort((a, b) => (b.feed_date || b.date).localeCompare(a.feed_date || a.date));
    return list;
  }

  function cardHTML(c) {
    const l = leakerOf(c);
    const score = c.legitimacy?.score;
    const isNew = c.origin === "daily" && c.first_seen && (Date.now() - new Date(c.first_seen)) < 3 * 864e5;
    const likes = (c.tweets || []).reduce((m, t) => Math.max(m, t.likes || 0), 0);
    const resurfaced = c.feed_date && c.feed_date.slice(0, 10) > c.date.slice(0, 10) && c.verdict !== "pending";
    return `<article class="card ${isNew ? "new" : ""}" data-claim="${esc(c.id)}">
      ${ring(score, "", "legit")}
      <div>
        <div class="who">${avatar(l)}<span class="name">${esc(l.name || c.handle)}</span><span class="handle">@${esc(c.handle)}</span>${credChip(l)}${isNew ? `<span class="tag" style="color:var(--accent);border-color:var(--accent)">NEW</span>` : ""}${resurfaced ? `<span class="tag">resolved ${fmtDate(c.feed_date)}</span>` : ""}</div>
        <div class="claim">${esc(c.claim)}</div>
        <div class="meta"><span class="tag lab">${esc(c.lab)}</span><span>${esc((c.topic || "").replace(/_/g, " "))}</span>
          ${dots(c.specificity || 0)}<span>${fmtDate(c.date)}</span>${likes ? `<span>♥ ${fmtNum(likes)}</span>` : ""}
          ${c.origin === "trawl" ? `<span title="Recovered from press/archive coverage (tweet may be deleted)">archived</span>` : ""}</div>
      </div>
      <div class="right">${pill(c.verdict)}</div>
    </article>`;
  }

  function renderFeed() {
    const labs = [...new Set(S.claims.map((c) => c.lab))].sort();
    const m = S.meta;
    const list = feedFilter();
    let html = `<section class="hero"><div>
        <h1>Who actually knows<br>what's <em>coming next?</em></h1>
        <p>Every notable leak claim about AI labs on X, scored against the leaker's track record of hits, misses and how early they were. Re-checked daily.</p>
      </div>
      <div class="stats">
        <div class="stat"><div class="n">${fmtNum(m.n_claims)}</div><div class="l">claims tracked</div></div>
        <div class="stat"><div class="n">${fmtNum(m.n_resolved)}</div><div class="l">resolved</div></div>
        <div class="stat"><div class="n">${fmtNum(m.n_pending)}</div><div class="l">pending</div></div>
      </div></section>
      <div class="controls">
        <div class="seg" id="tabs">${[["latest", "Latest"], ["top", "Most credible pending"], ["pending", "Pending"], ["resolved", "Resolved"]]
          .map(([k, v]) => `<button data-tab="${k}" class="${UI.feedTab === k ? "on" : ""}">${v}</button>`).join("")}</div>
        <select class="select" id="labSel"><option value="all">All labs</option>${labs.map((l) => `<option ${UI.lab === l ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>
        <input class="search" id="q" placeholder="Search claims or @handles" value="${esc(UI.q)}">
        <label class="toggle"><input type="checkbox" id="stale" ${UI.showStale ? "checked" : ""}> show already-public</label>
      </div><div id="feedList"></div>`;
    app.innerHTML = html;
    renderFeedList(list);
    $("#tabs").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; UI.feedTab = b.dataset.tab; UI.limit = 60; renderFeed(); };
    $("#labSel").onchange = (e) => { UI.lab = e.target.value; UI.limit = 60; renderFeedList(feedFilter()); };
    $("#stale").onchange = (e) => { UI.showStale = e.target.checked; renderFeedList(feedFilter()); };
    let t; $("#q").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { UI.q = e.target.value; UI.limit = 60; renderFeedList(feedFilter()); }, 150); };
  }

  function renderFeedList(list) {
    const el = $("#feedList");
    if (!list.length) { el.innerHTML = `<div class="empty">No claims match.</div>`; return; }
    let html = "", last = "";
    const grouped = UI.feedTab !== "top";
    list.slice(0, UI.limit).forEach((c) => {
      const d = (c.feed_date || c.date).slice(0, 10);
      if (grouped && d !== last) { html += `<div class="day">${dayLabel(d)}</div>`; last = d; }
      html += cardHTML(c);
    });
    if (list.length > UI.limit) html += `<button class="more" id="more">Show more (${list.length - UI.limit} left)</button>`;
    el.innerHTML = html;
    const more = $("#more"); if (more) more.onclick = () => { UI.limit += 80; renderFeedList(list); };
  }

  // ---------- claim drawer ----------
  function openClaim(id) {
    const c = S.byId[id]; if (!c) return;
    const l = leakerOf(c);
    const r = c.resolution || {};
    const comps = (c.legitimacy?.components || []).map((x) => `<div class="comp"><span>${esc(x.label)}</span><span class="dv ${x.delta > 0 ? "pos" : x.delta < 0 ? "neg" : ""}">${x.value != null ? x.value : x.delta == null ? "" : (x.delta > 0 ? "+" : "") + x.delta}</span></div>`).join("");
    const tweets = (c.tweets || []).map((t) => `<div class="tweet">${esc(t.text)}<span class="tmeta">${fmtDate(t.created_at)} · ♥ ${fmtNum(t.likes)} · <a href="${esc(t.url)}" target="_blank" rel="noopener">view on X ↗</a></span></div>`).join("")
      || (c.quote ? `<div class="tweet">${esc(c.quote)}</div>` : "");
    const lab = c.lab;
    const past = (S.claimsByHandle[c.handle.toLowerCase()] || []).filter((x) => x.id !== c.id && RESOLVED.has(x.verdict))
      .sort((a, b) => (b.lab === lab) - (a.lab === lab) || b.date.localeCompare(a.date)).slice(0, 6);
    const st = l.stats;
    const labSt = st && st.by_lab && st.by_lab[lab];
    const corro = (c.corroborated_by || []).map((h) => `<a class="link" href="#/leaker/${esc(h)}">@${esc(h)}</a>`).join(", ");
    const lead = c.lead_days;
    $("#drawerBody").innerHTML = `
      <div class="d-top">${ring(c.legitimacy?.score, "lg")}
        <div><div class="who">${avatar(l, "md")}<div><a class="link" href="#/leaker/${esc(l.handle)}" style="color:var(--text)"><b>${esc(l.name || c.handle)}</b></a>
          <div class="note">@${esc(c.handle)} · ${CAT_LABEL[l.category] || "Untracked account"}</div></div></div>
          <div style="margin-top:8px">${pill(c.verdict)}</div></div></div>
      <div class="meta" style="margin-top:0"><span class="tag lab">${esc(c.lab)}</span><span>${esc((c.topic || "").replace(/_/g, " "))}</span>
        <span>specificity ${dots(c.specificity || 0)}</span><span>significance ${c.significance}/5</span><span>claimed ${fmtDate(c.date)}</span>
        ${c.resolve_by ? `<span>resolves by ${fmtDate(c.resolve_by)}</span>` : ""}</div>
      <div class="d-claim">${esc(c.claim)}</div>
      ${tweets ? `<div class="panel"><h3>${c.origin === "trawl" ? "As documented" : "Original post"}</h3>${tweets}
        ${c.origin === "trawl" && c.source_url ? `<div class="note">Recovered from <a class="link" href="${esc(c.source_url)}" target="_blank" rel="noopener">this source ↗</a>${c.deleted ? " — the original tweet appears deleted." : ""}</div>` : ""}</div>` : ""}
      ${RESOLVED.has(c.verdict) || ["already_public", "unverifiable"].includes(c.verdict) ? `<div class="panel"><h3>What happened</h3>
        <div>${esc(r.explanation || "")}</div>
        ${lead != null && lead > 0 && RESOLVED.has(c.verdict) && c.verdict !== "false" ? `<p style="margin:10px 0 0"><b style="color:var(--true)">${plural(lead, "day")} ahead</b> <span class="note">of public confirmation on ${fmtDate(r.public_date)}</span></p>` : r.public_date ? `<p class="note" style="margin:10px 0 0">Publicly confirmed ${fmtDate(r.public_date)}</p>` : ""}
        <div class="ev" style="margin-top:8px">${(r.evidence || []).map((e) => `<a href="${esc(e.url)}" target="_blank" rel="noopener">↗ ${esc(e.title || e.url)}</a>`).join("")}</div>
        <div class="note" style="margin-top:8px">Resolver confidence: ${esc(r.confidence || "–")}${r.vetted ? ` · <span title="${esc(r.vetted.note || "")}">✓ audited${r.vetted.changed_from ? ` (was “${esc(VERDICT_LABEL[r.vetted.changed_from] || r.vetted.changed_from)}”)` : ""}</span>` : ""}</div></div>`
      : c.verdict === "pending" ? `<div class="panel"><h3>Status</h3><div>Not yet resolved. ${c.resolve_by ? `The claim's own deadline is ${fmtDate(c.resolve_by)}; we re-check it as that approaches.` : "Open claims are re-checked regularly."}</div>${r.explanation ? `<p class="note">${esc(r.explanation)}</p>` : ""}</div>` : ""}
      <div class="panel"><h3>Why this legitimacy score</h3>${comps || `<div class="note">No score.</div>`}
        <p class="note" style="margin:10px 0 0">Computed from the leaker's record <i>as it stood when the claim was made</i>, so resolved claims aren't scored with hindsight.</p></div>
      ${corro ? `<div class="panel"><h3>Also claimed by</h3>${corro}</div>` : ""}
      <div class="panel"><h3>@${esc(l.handle || c.handle)}'s track record</h3>
        ${st ? `<div class="kv">
          <div><b>${pct(st.credibility)}</b><span>credibility</span></div>
          <div><b>${st.n_true + st.n_mostly_true}<span style="color:var(--faint)">/${st.n_resolved}</span></b><span>hits / resolved</span></div>
          <div><b>${st.n_false}</b><span>misses</span></div>
          <div><b>${labSt ? pct(labSt.credibility) : "–"}</b><span>on ${esc(lab)} (${labSt ? labSt.n : 0})</span></div>
          <div><b>${st.median_lead_days != null ? st.median_lead_days + "d" : "–"}</b><span>median lead</span></div>
          <div><b>${l.rank ? "#" + l.rank : "–"}</b><span>leaderboard</span></div></div>` : `<div class="note">No track record yet — this account isn't on our tracked list, so the score uses a sceptical prior.</div>`}
        ${past.length ? `<div class="section-title" style="margin-top:16px">Their past claims${labSt ? ` (${esc(lab)} first)` : ""}</div>` +
          past.map((x) => `<div class="minirow" data-claim="${esc(x.id)}"><span class="chip-dot bg-${x.verdict}"></span><span class="mt">${esc(x.claim)}</span><span class="md">${fmtDate(x.date)}</span></div>`).join("") : ""}
        ${l.handle && S.byHandle[(l.handle || "").toLowerCase()] ? `<p style="margin:12px 0 0"><a class="link" href="#/leaker/${esc(l.handle)}">Full profile →</a></p>` : ""}
      </div>`;
    const dr = $("#drawer"); dr.classList.add("open"); dr.setAttribute("aria-hidden", "false");
    $(".drawer-panel").scrollTop = 0;
    const base = (location.hash || "#/").split("?")[0];
    if (location.hash.indexOf("claim=" + encodeURIComponent(id)) < 0) history.replaceState(null, "", base + "?claim=" + encodeURIComponent(id));
  }
  function closeDrawer() {
    const dr = $("#drawer"); dr.classList.remove("open"); dr.setAttribute("aria-hidden", "true");
    if (location.hash.includes("?claim=")) history.replaceState(null, "", location.hash.split("?")[0] || "#/");
  }

  // ---------- leaderboard ----------
  const LB_COLS = [
    ["rank", "#", false], ["handle", "Leaker", false], ["leak_score", "Leak score", true], ["credibility", "Accuracy", true],
    ["hits", "Hits", true], ["n_false", "Misses", true], ["n_pending", "Pending", true], ["median_lead_days", "Lead", true],
    ["impact", "Impact", true], ["record", "Recent record", false],
  ];
  function lbValue(l, k) {
    const s = l.stats;
    if (k === "hits") return s.n_true + s.n_mostly_true;
    if (k === "handle") return l.handle.toLowerCase();
    return s[k] ?? -1;
  }
  function renderLeaderboard() {
    const MIN = S.meta.min_resolved_for_rank || 5;
    const inGroup = (l) => UI.lbGroup === "all" || l.group === UI.lbGroup;
    const cats = ["all", ...new Set(S.leakers.filter(inGroup).map((l) => l.category))];
    if (!cats.includes(UI.lbCat)) UI.lbCat = "all";
    const pool = S.leakers.filter((l) => inGroup(l) && (UI.lbCat === "all" || l.category === UI.lbCat));
    let ranked = pool.filter((l) => l.stats.n_resolved >= MIN && l.rank);
    const unranked = pool.filter((l) => !(l.stats.n_resolved >= MIN && l.rank));
    // rank shown = position by leak score within the current view
    const pos = {}; ranked.slice().sort((a, b) => b.stats.leak_score - a.stats.leak_score).forEach((l, i) => (pos[l.handle] = i + 1));
    if (UI.lbSort === "rank") ranked.sort((a, b) => pos[a.handle] - pos[b.handle]);
    else ranked.sort((a, b) => { const va = lbValue(a, UI.lbSort), vb = lbValue(b, UI.lbSort);
      return (va > vb ? 1 : va < vb ? -1 : 0) * UI.lbDir || (b.stats.leak_score - a.stats.leak_score); });
    const row = (l) => {
      const s = l.stats, r = pos[l.handle];
      const rec = (l.record || []).slice(-24).map((v) => `<i class="bg-${v}" title="${VERDICT_LABEL[v]}"></i>`).join("");
      return `<tr data-leaker="${esc(l.handle)}">
        <td class="rank ${r && r <= 3 ? "top" : ""}">${r || "–"}</td>
        <td><div class="lbwho">${avatar(l, "md")}<div><div class="n1">${esc(l.name)}</div><div class="n2">@${esc(l.handle)} · <span class="catbadge">${CAT_LABEL[l.category] || l.category}</span></div></div></div></td>
        <td class="num"><div class="scorebar"><span class="mono">${s.leak_score.toFixed(0)}</span><span class="bar"><i style="width:${Math.min(100, s.leak_score)}%"></i></span></div></td>
        <td class="num mono" title="Bayesian credibility; raw hit rate ${pct(s.hit_rate_raw)}">${pct(s.credibility)}</td>
        <td class="num mono" style="color:var(--true)">${s.n_true + s.n_mostly_true}</td>
        <td class="num mono" style="color:var(--false)">${s.n_false}</td>
        <td class="num mono" style="color:var(--pending)">${s.n_pending}</td>
        <td class="num mono">${s.median_lead_days != null ? s.median_lead_days + "d" : "–"}</td>
        <td class="num mono">${s.impact.toFixed(1)}</td>
        <td><div class="strip">${rec}</div></td></tr>`;
    };
    const blurb = UI.lbGroup === "journalists"
      ? "Reporters who break AI-lab stories on X. Graded only on independent confirmation — their own article doesn't count as proof. Lead time is measured to official confirmation."
      : UI.lbGroup === "all" ? "Everyone we track, leakers and journalists together."
      : "Anonymous insiders, code sleuths, aggregators and commentators. Ranked by <b>Leak score</b>: accuracy (a Bayesian hit rate, so tiny samples can't top the board) × the volume of significant claims they got right <i>before</i> they were public.";
    app.innerHTML = `<section class="lb-head"><h1>Leaderboard</h1>
      <p>${blurb} Click a column to re-sort, or a row for the full record. ${MIN}+ resolved claims needed to rank.</p></section>
      <div class="controls">
        <div class="seg" id="grp">${[["leakers", "Leakers"], ["journalists", "Journalists"], ["all", "All"]].map(([k, v]) => `<button data-g="${k}" class="${UI.lbGroup === k ? "on" : ""}">${v}</button>`).join("")}</div>
        ${cats.length > 2 ? `<div class="seg" id="cats">${cats.map((c) => `<button data-cat="${c}" class="${UI.lbCat === c ? "on" : ""}">${c === "all" ? "All types" : CAT_LABEL[c] || c}</button>`).join("")}</div>` : ""}
      </div>
      <div class="table-wrap"><table class="lb"><thead><tr>${LB_COLS.map(([k, label, num]) => `<th data-sort="${k}" class="${num ? "num" : ""} ${UI.lbSort === k ? "sorted" : ""}">${label}${UI.lbSort === k ? (UI.lbDir < 0 ? " ↓" : " ↑") : ""}</th>`).join("")}</tr></thead>
      <tbody>${ranked.map(row).join("")}</tbody></table></div>
      ${unranked.length ? `<div class="section-title">Not enough resolved claims yet</div><div class="table-wrap"><table class="lb"><tbody>${unranked.sort((a, b) => b.stats.n_claims - a.stats.n_claims).map(row).join("")}</tbody></table></div>` : ""}`;
    $("#grp").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; UI.lbGroup = b.dataset.g; UI.lbCat = "all"; renderLeaderboard(); };
    const cs = $("#cats"); if (cs) cs.onclick = (e) => { const b = e.target.closest("button"); if (!b) return; UI.lbCat = b.dataset.cat; renderLeaderboard(); };
    app.querySelectorAll("th[data-sort]").forEach((th) => th.onclick = () => {
      const k = th.dataset.sort; if (k === "record") return;
      if (UI.lbSort === k) UI.lbDir *= -1; else { UI.lbSort = k; UI.lbDir = k === "handle" || k === "rank" ? 1 : -1; }
      renderLeaderboard();
    });
  }

  // ---------- profile ----------
  function renderProfile(handle) {
    const l = S.byHandle[handle.toLowerCase()];
    if (!l) { app.innerHTML = `<div class="empty">Unknown leaker @${esc(handle)}. <a class="link" href="#/leaderboard">Back to leaderboard</a></div>`; return; }
    const s = l.stats;
    const claims = (S.claimsByHandle[l.handle.toLowerCase()] || []).slice().sort((a, b) => b.date.localeCompare(a.date));
    const filt = UI.profFilter;
    const shown = claims.filter((c) => filt === "all" ? c.verdict !== "already_public" : filt === "hits" ? ["true", "mostly_true"].includes(c.verdict)
      : filt === "misses" ? c.verdict === "false" : filt === "pending" ? c.verdict === "pending" : filt === "stale" ? c.verdict === "already_public" : true);
    const labs = Object.entries(s.by_lab || {}).sort((a, b) => b[1].n - a[1].n);
    const best = (l.best_hits || []).map((id) => S.byId[id]).filter(Boolean);
    const worst = (l.worst_misses || []).map((id) => S.byId[id]).filter(Boolean);
    const mini = (x) => `<div class="minirow" data-claim="${esc(x.id)}"><span class="chip-dot bg-${x.verdict}"></span><span class="mt">${esc(x.claim)}${x.lead_days > 0 && x.verdict !== "false" ? ` <span class="note">· ${x.lead_days}d early</span>` : ""}</span><span class="md">${fmtDate(x.date)}</span></div>`;
    app.innerHTML = `<section class="prof-head">${avatar(l, "lg")}
        <div style="flex:1;min-width:240px"><h1>${esc(l.name)}</h1>
          <div class="sub">@${esc(l.handle)}${(l.aliases || []).length ? ` (formerly ${l.aliases.map((a) => "@" + esc(a)).join(", ")})` : ""} · <span class="catbadge">${CAT_LABEL[l.category] || l.category}</span> · ${fmtNum(l.followers)} followers ·
            <a class="link" href="https://x.com/${esc(l.handle)}" target="_blank" rel="noopener">X profile ↗</a></div>
          ${l.bio ? `<div class="bio">${esc(l.bio)}</div>` : ""}</div>
        <div style="text-align:center">${ring(s.leak_score, "lg")}<div class="note" style="margin-top:6px">Leak score${l.rank ? ` · #${l.rank} ${l.group === "journalists" ? "journalist" : "leaker"}` : ""}</div></div>
      </section>
      ${l.summary ? `<div class="panel" style="margin-top:6px"><h3>Verdict on this leaker</h3><div>${esc(l.summary)}</div></div>` : ""}
      <div class="kv" style="margin:14px 0 6px">
        <div><b>${pct(s.credibility)}</b><span>credibility (raw ${pct(s.hit_rate_raw)})</span></div>
        <div><b style="color:var(--true)">${s.n_true + s.n_mostly_true}</b><span>hits</span></div>
        <div><b style="color:var(--partly)">${s.n_partly_true}</b><span>partly right</span></div>
        <div><b style="color:var(--false)">${s.n_false}</b><span>misses</span></div>
        <div><b style="color:var(--pending)">${s.n_pending}</b><span>pending</span></div>
        <div><b>${s.median_lead_days != null ? s.median_lead_days + "d" : "–"}</b><span>median lead time</span></div>
        <div><b>${pct(s.stale_rate)}</b><span>already-public rate</span></div>
        <div><b>${pct(s.vague_rate)}</b><span>vague claims</span></div>
      </div>
      <div class="prof-grid">
        <div>
          <div class="section-title">All claims</div>
          <div class="seg" id="pf" style="margin-bottom:12px">${[["all", "All"], ["hits", "Hits"], ["misses", "Misses"], ["pending", "Pending"], ["stale", "Already public"]].map(([k, v]) => `<button data-f="${k}" class="${filt === k ? "on" : ""}">${v}</button>`).join("")}</div>
          <div id="pclaims">${shown.length ? shown.slice(0, 300).map(cardHTML).join("") : `<div class="empty">Nothing here.</div>`}</div>
        </div>
        <div>
          <div class="panel"><h3>Accuracy by lab</h3><div class="labbars">${labs.map(([lab, v]) => `<div class="lr"><span>${esc(lab)}</span><span class="track"><i style="width:${Math.round(v.credibility * 100)}%;background:${scoreColor(v.credibility * 100)}"></i></span><span class="mono note">${pct(v.credibility)} · ${v.n}</span></div>`).join("") || `<div class="note">No resolved claims.</div>`}</div></div>
          ${best.length ? `<div class="panel"><h3>Best calls</h3>${best.map(mini).join("")}</div>` : ""}
          ${worst.length ? `<div class="panel"><h3>Biggest misses</h3>${worst.map(mini).join("")}</div>` : ""}
          <div class="panel"><h3>Record over time</h3><div class="strip" style="flex-wrap:wrap;gap:3px">${(l.record || []).map((v) => `<i class="bg-${v}" title="${VERDICT_LABEL[v]}"></i>`).join("")}</div><p class="note" style="margin:8px 0 0">Resolved claims, oldest → newest.</p></div>
        </div>
      </div>`;
    $("#pf").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; UI.profFilter = b.dataset.f; renderProfile(handle); };
  }

  // ---------- about ----------
  function renderAbout() {
    const m = S.meta, cal = m.calibration || [];
    app.innerHTML = `<article class="prose">
      <h1>How LeakWatch works</h1>
      <p>LeakWatch tracks claims about unreleased AI models and frontier-lab goings-on made on X — release dates, codenames, capabilities, features found in app code, funding rounds, departures — and checks them against what actually happened.</p>
      <h2>1. Collecting claims</h2>
      <p>We follow ${m.n_leakers} accounts with a history of widely-shared leak claims — anonymous "insiders", code sleuths who dig through app builds, journalists who break scoops, and aggregators — <i>deliberately including accounts with poor records</i>. Their full history of high-engagement posts was pulled, plus famous deleted claims recovered from press coverage and forum archives. Every day the pipeline pulls their new posts and also screens wider X for viral leak claims; brand-new accounts only appear if a claim goes viral (and they're scored with a sceptical prior).</p>
      <p>A language model reads each post and extracts only <b>claims of non-public information</b> — commentary, reactions to launches, and relays of already-published reporting are dropped. Each claim gets a <b>specificity</b> (1 = vibes, 5 = exact date/number) and <b>significance</b> (1 = UI tweak, 5 = frontier flagship or industry-shaking event).</p>
      <h2>2. Resolving claims</h2>
      <p>Each claim is graded against a hand-checked timeline of ${m.n_events} official lab events plus live web search: <code>true</code>, <code>mostly true</code>, <code>partly true</code>, <code>false</code>, <code>pending</code>, <code>already public</code> (no credit — the info was out before the tweet), or <code>unverifiable</code>. We also record the date the information became public, which gives the <b>lead time</b>. A report never counts as confirmation of itself: a claim is only <code>true</code> once it's officially confirmed, the event actually happens, or a different outlet independently confirms it. "In talks" stories that never close stay <code>unverifiable</code>. The highest-impact verdicts for every leaker were then independently audited by a second model (Claude); audited verdicts are marked ✓, and changed ones show what they were changed from.</p>
      <h2>Leakers vs journalists</h2>
      <p>Professional reporters (The Information, Bloomberg, The Verge, Reuters…) are ranked on a separate board: their scoops come with institutional sourcing and editors, and they turn out to be far more reliable than anonymous accounts. For a journalist's own scoop, lead time is measured to official confirmation rather than to their article.</p>
      <h2>3. Scores</h2>
      <p><b>Credibility</b> is a Bayesian hit rate: resolved claims are weighted by specificity (and down-weighted when hedged, cryptic or second-hand), starting from a 50/50 prior worth four claims — so three lucky guesses can't beat a long, solid record. True = 1, mostly true = 0.8, partly true = 0.4, false = 0.</p>
      <p><b>No credit for the obvious.</b> Claims whose information was already public when posted — including "hits" posted the same day it became public, which can't be told apart from reacting to the news — count neither for nor against accuracy, but show up in each profile's <i>already-public rate</i>. Exceptions: a code/A-B-test find or a journalist's own scoop, where same-day coverage <i>is</i> the leak (their lead time runs to official confirmation).</p>
      <p><b>Impact</b> sums the significance of correct claims, boosted for lead time (a call made two months early counts more than one made the day before).</p>
      <p><b>Leak score</b> = credibility<sup>1.5</sup> × (1 − e<sup>−impact/${m.impact_k || 8}</sup>) × 100. You need both a good hit rate <i>and</i> a body of significant early calls.</p>
      <p><b>Legitimacy</b> (the ring on each claim) estimates the chance the claim is true. It starts from the leaker's credibility <i>as of the day the claim was made</i> (blended with their lab-specific record when there's enough data), then adjusts for claim type (code/test evidence +10, journalism +6, speculation −15), hedging, vagueness, and corroboration by other tracked leakers.</p>
      <h2>Is the legitimacy score any good?</h2>
      <p>Because historical scores are computed without hindsight, we can check calibration: of claims scored in each band, how many came true (true/mostly = 1, partly = 0.4)?</p>
      ${cal.length ? `<div class="calib">${cal.map((b) => `<div class="col" title="${b.n} claims"><div class="exp" style="bottom:${b.mid}%"></div><div class="barv" style="height:${Math.round(b.rate * 100)}%"></div></div>`).join("")}</div>
      <div class="calib-labels">${cal.map((b) => `<span>${b.lo}–${b.hi}<br>${Math.round(b.rate * 100)}% · n=${b.n}</span>`).join("")}</div>
      <p class="note">Bars: observed hit rate. Dashed line: what a perfectly calibrated score would give.</p>` : ""}
      ${m.audit ? `<h2>How accurate is the grading?</h2>
      <p>${fmtNum(m.n_audited)} of the most score-relevant verdicts were re-checked by an independent auditor model, which corrected many of them. To measure the rest honestly, the auditor also graded a <b>blind random sample of ${m.audit.sample_n}</b> un-audited verdicts: it agreed on the outcome category (hit / partly / miss / excluded) <b>${Math.round(m.audit.bucket_agreement * 100)}%</b> of the time, and on the exact verdict ${Math.round(m.audit.exact_agreement * 100)}% of the time. Treat any single un-audited verdict accordingly — the aggregate scores are much more robust than individual grades.</p>` : ""}
      <h2>Caveats</h2>
      <ul><li>Automated grading makes mistakes; each claim links to its sources so you can check.</li>
      <li>Deleted tweets are only captured when the press or forums documented them.</li>
      <li>"Already public" detection depends on publication dates and may occasionally penalise a genuine scoop that landed the same day as the story.</li>
      <li>Journalists are graded on what they post on X, which usually reflects their outlet's published stories.</li></ul>
      <p class="note">Data updated ${fmtDate(m.updated_at)}. Source code and raw data: <a class="link" href="${esc(m.repo_url || "#")}">GitHub</a>.</p>
    </article>`;
  }

  // ---------- router ----------
  function route() {
    const h = location.hash.replace(/^#/, "") || "/";
    const [path, query] = h.split("?");
    const parts = path.split("/").filter(Boolean);
    document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active",
      (parts[0] || "feed") === a.dataset.nav || (parts[0] === "leaker" && a.dataset.nav === "leaderboard")));
    const key = path;
    if (route.last !== key) {
      route.last = key;
      if (!parts.length) renderFeed();
      else if (parts[0] === "leaderboard") renderLeaderboard();
      else if (parts[0] === "leaker") renderProfile(decodeURIComponent(parts[1] || ""));
      else if (parts[0] === "about") renderAbout();
      else renderFeed();
      window.scrollTo(0, 0);
    }
    const cm = /claim=([^&]+)/.exec(query || "");
    if (cm) openClaim(decodeURIComponent(cm[1])); else closeDrawer();
  }

  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) { closeDrawer(); return; }
    const card = e.target.closest("[data-claim]");
    if (card && !e.target.closest("a")) { openClaim(card.dataset.claim); return; }
    const row = e.target.closest("[data-leaker]");
    if (row) { location.hash = "#/leaker/" + encodeURIComponent(row.dataset.leaker); }
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
  window.addEventListener("hashchange", route);

  // theme
  const themeBtn = $("#themeBtn");
  try { const t = localStorage.getItem("lw-theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
  themeBtn.onclick = () => {
    const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
    const nt = cur === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = nt;
    try { localStorage.setItem("lw-theme", nt); } catch (e) {}
    route.last = null; route();
  };

  load().then(route).catch((e) => { app.innerHTML = `<div class="empty">Couldn't load data: ${esc(e.message)}</div>`; });
})();
