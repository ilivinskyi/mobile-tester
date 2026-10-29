"""The dashboard page: one self-contained HTML file (inline CSS and JS, system fonts, no network)."""

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Test session</title>
<style>
:root{--page:#f6f7f9;--surface:#fff;--sunk:#eef1f4;--ink:#16202b;--muted:#5b6878;--line:#dde2e8;--accent:#2457c5;
--ok:#1d7a46;--bad:#b42318;--warn:#9a4a05;--blocker:#7a0f0f;--critical:#b42318;--major:#d9622b;--minor:#e8b230;
--trivial:#8a95a5}
@media (prefers-color-scheme:dark){:root{--page:#11151b;--surface:#191e26;--sunk:#212833;--ink:#e6e9ee;
--muted:#a3adba;--line:#2b323c;--accent:#8fb0ff;--ok:#6fd49b;--bad:#ff9b91;--warn:#f5b264;--blocker:#ff8a8a;
--critical:#ff9b91;--major:#ffad7a;--minor:#f2d06b;--trivial:#a3adba}}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{display:flex;flex-wrap:wrap;gap:12px 24px;align-items:center;justify-content:space-between;padding:16px 24px;
border-bottom:1px solid var(--line);background:var(--surface);position:sticky;top:0;z-index:2}
h1{margin:0;font-size:19px;line-height:1.25}
h2{margin:0 0 10px;font-size:14px;color:var(--muted);font-weight:600}
.meta{color:var(--muted);font-size:13px;margin-top:2px}
.controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.state{font-size:12px;font-weight:700;padding:5px 10px;border-radius:999px;background:var(--sunk)}
.state.running{color:var(--ok)}.state.paused{color:var(--warn)}.state.stopped,.state.ended{color:var(--muted)}
button{font:inherit;font-size:14px;font-weight:600;padding:7px 14px;border-radius:8px;border:1px solid var(--line);
background:var(--surface);color:var(--ink);cursor:pointer}
button:hover{border-color:var(--muted)}button:focus-visible,textarea:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
button.stop{color:var(--bad)}button:disabled{opacity:.45;cursor:default}
.timebox{min-width:180px;font-size:13px;color:var(--muted)}
.bar{height:6px;border-radius:3px;background:var(--sunk);margin-top:4px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--accent);width:0}.bar i.over{background:var(--bad)}
main{display:grid;grid-template-columns:minmax(260px,360px) minmax(0,1fr) minmax(260px,340px);gap:20px;padding:20px 24px;
align-items:start}
section{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.col{display:grid;gap:20px;min-width:0}
.phone{position:relative;border-radius:18px;overflow:hidden;background:#000;line-height:0}
.phone img{width:100%;height:auto;display:block}
.tap{position:absolute;width:26px;height:26px;margin:-13px 0 0 -13px;border-radius:50%;border:3px solid #ff5a36;
box-shadow:0 0 0 3px rgba(255,255,255,.7);pointer-events:none;display:none}
.caption{display:flex;justify-content:space-between;gap:8px;margin-top:8px;font-size:13px;color:var(--muted)}
.caption label{display:flex;gap:6px;align-items:center;cursor:pointer}
.empty{color:var(--muted);font-size:14px}
.latest{white-space:pre-wrap;font-size:14px;max-height:9.5em;overflow:auto}
.tokens{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:10px;font-size:13px;color:var(--muted)}
.tokens b{color:var(--ink);font-weight:600}
ol.timeline{list-style:none;margin:0;padding:0;max-height:60vh;overflow:auto}
.timeline li{display:grid;grid-template-columns:62px 92px minmax(0,1fr);gap:8px;padding:6px 0;border-top:1px solid var(--line);
font-size:14px}
.timeline li:first-child{border-top:0}
.timeline time{color:var(--muted);font-variant-numeric:tabular-nums}
.timeline .what{font-weight:600}.timeline .on{overflow-wrap:anywhere}
.chip{display:inline-block;font-size:11px;font-weight:700;padding:2px 7px;border-radius:999px;margin-left:6px;
background:var(--sunk);color:var(--muted)}
.chip.bad{color:var(--bad)}.chip.warn{color:var(--warn)}
ul.plain{list-style:none;margin:0;padding:0}
.plain li{padding:6px 0;border-top:1px solid var(--line);font-size:14px;display:flex;gap:8px;align-items:baseline}
.plain li:first-child{border-top:0}
.sev{flex:none;width:9px;height:9px;border-radius:50%;background:var(--trivial);transform:translateY(-1px)}
.sev.Blocker{background:var(--blocker)}.sev.Critical{background:var(--critical)}.sev.Major{background:var(--major)}
.sev.Minor{background:var(--minor)}
.fid{font-weight:700;flex:none}.grow{flex:1;min-width:0;overflow-wrap:anywhere}.muted{color:var(--muted);font-size:13px}
a{color:var(--accent)}
textarea{width:100%;min-height:70px;font:inherit;font-size:14px;padding:8px 10px;border-radius:8px;border:1px solid var(--line);
background:var(--page);color:var(--ink);resize:vertical}
.row{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-top:8px}
.banner{margin:20px 24px 0;padding:14px 16px;border-radius:12px;border:1px solid var(--line);background:var(--surface);
display:none;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.banner.show{display:flex}
@media (max-width:1100px){main{grid-template-columns:minmax(240px,320px) minmax(0,1fr)}.col.side{grid-column:1/-1}}
@media (max-width:720px){main{grid-template-columns:1fr;padding:16px}header{padding:14px 16px}.banner{margin:16px 16px 0}
.timeline li{grid-template-columns:58px minmax(0,1fr)}.timeline .on{grid-column:2}}
</style></head><body>
<header>
  <div><h1 id="title">Test session</h1><div class="meta" id="meta"></div></div>
  <div class="controls">
    <div class="timebox"><span id="clock">Not started</span><div class="bar"><i id="bar"></i></div></div>
    <span class="state" id="state" role="status">Connecting</span>
    <button id="pause" type="button">Pause</button>
    <button id="stop" class="stop" type="button">Stop</button>
  </div>
</header>
<div class="banner" id="ended"><span id="ended-text">The session has ended.</span>
  <a id="report-link" href="/run/index.html" target="_blank" rel="noopener">Open the report</a></div>
<main>
  <div class="col">
    <section aria-labelledby="screen-h"><h2 id="screen-h">Screen</h2>
      <div class="phone"><img id="shot" alt="The device screen at the last observation"><span class="tap" id="tap"></span></div>
      <div class="caption"><span id="shot-caption">No observation yet</span>
        <label id="live-label" hidden><input type="checkbox" id="live"> Live</label></div>
    </section>
  </div>
  <div class="col">
    <section aria-labelledby="agent-h"><h2 id="agent-h">Agent</h2>
      <div class="latest" id="latest"><span class="empty">Waiting for the agent's first message.</span></div>
      <div class="tokens" id="tokens"></div>
    </section>
    <section aria-labelledby="timeline-h"><h2 id="timeline-h">Actions</h2>
      <ol class="timeline" id="timeline"><li class="empty">No actions yet.</li></ol></section>
  </div>
  <div class="col side">
    <section aria-labelledby="findings-h"><h2 id="findings-h">Findings</h2><ul class="plain" id="findings"></ul></section>
    <section aria-labelledby="screens-h"><h2 id="screens-h">Screens</h2><ul class="plain" id="screens"></ul></section>
    <section aria-labelledby="note-h"><h2 id="note-h">Note to the agent</h2>
      <textarea id="note" placeholder="For example: also check the Profile screen" aria-labelledby="note-h"></textarea>
      <div class="row"><span class="muted" id="note-status">The agent reads it with its next action.</span>
        <button id="send" type="button">Send</button></div>
      <ul class="plain" id="notes"></ul>
    </section>
  </div>
</main>
<script>
(() => {
  const $ = id => document.getElementById(id);
  let state = null, liveTimer = null;
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const fmt = n => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(n);

  function clock() {
    const s = state && state.session;
    if (!s || !s.started) return;
    const end = s.ended ? new Date(s.ended) : new Date();
    const min = (end - new Date(s.started)) / 60000;
    const box = s.time_box_min;
    $("clock").textContent = box ? `${Math.floor(min)} of ${box} min` : `${Math.floor(min)} min`;
    const bar = $("bar");
    bar.style.width = box ? Math.min(100, min / box * 100) + "%" : "0";
    bar.classList.toggle("over", !!box && min > box);
  }

  function render(next) {
    state = next;
    const s = next.session, ended = !!s.ended, ctl = next.control.state;
    document.title = `${s.title} (test session)`;
    $("title").textContent = s.title;
    $("meta").textContent = [s.mode && `${s.mode} session`, s.device, s.app, s.charter].filter(Boolean).join(", ");
    const shown = ended ? "ended" : ctl;
    $("state").className = "state " + shown;
    $("state").textContent = {running: "Running", paused: "Paused", stopped: "Stop requested", ended: "Ended"}[shown];
    $("pause").textContent = ctl === "paused" ? "Resume" : "Pause";
    $("pause").disabled = $("stop").disabled = ended || ctl === "stopped";
    $("ended").classList.toggle("show", ended);
    $("report-link").hidden = !next.report;
    $("ended-text").textContent = next.report ? "The session has ended." : "The session has ended. The report is being finished.";
    clock();

    const shot = next.screen;
    if (!$("live").checked && shot.observed) $("shot").src = "/screen.png?t=" + shot.observed;
    if (!$("live").checked) $("shot-caption").textContent = shot.observed
      ? `Last observation ${new Date(shot.observed * 1000).toLocaleTimeString()}` + (shot.title ? `, ${shot.title}` : "")
      : "No observation yet";
    $("live-label").hidden = !shot.live || ended;
    const tap = next.actions.find(a => a.point), dot = $("tap");
    if (tap && shot.size) {
      dot.style.left = tap.point[0] / shot.size[0] * 100 + "%";
      dot.style.top = tap.point[1] / shot.size[1] * 100 + "%";
      dot.style.display = "block";
    } else dot.style.display = "none";

    const t = next.tokens;
    if (t.available) {
      if (t.latest) $("latest").textContent = t.latest;
      $("tokens").innerHTML = `<span>${esc(t.agent)}</span><span><b>${t.requests}</b> requests</span>`
        + `<span><b>${fmt(t.input)}</b> in</span><span><b>${fmt(t.output)}</b> out</span>`
        + (t.cost_usd != null ? `<span><b>$${t.cost_usd.toFixed(2)}</b> at API prices</span>` : "");
    } else {
      $("latest").innerHTML = '<span class="empty">Agent messages and tokens show for Claude Code sessions.</span>';
      $("tokens").textContent = "";
    }

    $("timeline").innerHTML = next.actions.length ? next.actions.map(a => {
      const chips = (a.changed === false ? '<span class="chip warn">no change</span>' : "")
        + (a.crash ? '<span class="chip bad">crash</span>' : "")
        + (a.log_issues ? `<span class="chip warn">${plural(a.log_issues, "log issue")}</span>` : "");
      return `<li><time>${esc(a.t)}</time><span class="what">${esc(a.action)}</span>`
        + `<span class="on">${esc(a.target)}${chips}</span></li>`;
    }).join("") : '<li class="empty">No actions yet.</li>';

    const fs = next.findings;
    $("findings-h").textContent = fs.length ? `Findings (${fs.length})` : "Findings";
    $("findings").innerHTML = fs.length ? fs.map(f => {
      const label = esc(f.title), id = esc(f.id);
      const link = next.report ? `<a href="/run/bugs/${encodeURIComponent(f.id)}.html" target="_blank" rel="noopener">${label}</a>` : label;
      return `<li><span class="sev ${esc(f.severity || "")}" aria-hidden="true"></span><span class="fid">${id}</span>`
        + `<span class="grow">${link}${f.status === "Unconfirmed" ? '<span class="chip warn">unconfirmed</span>' : ""}</span></li>`;
    }).join("") : '<li class="empty">Nothing yet.</li>';

    const sc = next.screens;
    $("screens-h").textContent = sc.length ? `Screens (${sc.length})` : "Screens";
    $("screens").innerHTML = sc.length ? sc.map(r => `<li><span class="grow">${esc(r.title)}</span>`
      + `<span class="muted">${r.untried.length ? r.untried.length + " not tried" : "all tried"}</span></li>`).join("")
      + (next.no_change.length ? `<li><span class="grow muted">${plural(next.no_change.length, "tap")} with no visible change</span></li>` : "")
      : '<li class="empty">None observed yet.</li>';

    const notes = next.control.notes;
    $("notes").innerHTML = notes.slice().reverse().map(n => `<li><span class="grow">${esc(n.text)}</span>`
      + `<span class="muted">${n.delivered ? "read" : "waiting"}</span></li>`).join("");
  }

  async function post(body) {
    const r = await fetch("/api/control", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }
  $("pause").onclick = () => post({state: state.control.state === "paused" ? "running" : "paused"}).then(refresh);
  $("stop").onclick = () => { if (confirm("Stop the session? The agent finishes what it is doing and wraps up.")) post({state: "stopped"}).then(refresh); };
  $("send").onclick = () => {
    const text = $("note").value.trim();
    if (!text) { $("note-status").textContent = "Write a note first."; return; }
    post({note: text}).then(() => { $("note").value = ""; $("note-status").textContent = "Sent. The agent reads it with its next action."; refresh(); })
      .catch(e => { $("note-status").textContent = "Not sent: " + e.message; });
  };
  // Live view: fetch a frame off-screen and swap it in only once it has arrived, then ask for the next one,
  // so a slow frame is never cut off by the next request and the picture never goes blank.
  function nextFrame() {
    if (!$("live").checked) return;
    const frame = new Image();
    frame.onload = () => {
      if (!$("live").checked) return;
      $("shot").src = frame.src;
      $("shot-caption").textContent = `Live ${new Date().toLocaleTimeString()}`;
      liveTimer = setTimeout(nextFrame, 1000);
    };
    frame.onerror = () => { liveTimer = setTimeout(nextFrame, 3000); };
    frame.src = "/live.png?t=" + Date.now();
  }
  $("live").onchange = () => {
    clearTimeout(liveTimer);
    $("tap").style.visibility = $("live").checked ? "hidden" : "visible";  // the mark belongs to the observation
    if ($("live").checked) nextFrame();
    else if (state) render(state);
  };

  function refresh() { return fetch("/api/state").then(r => r.json()).then(render).catch(() => {}); }
  function listen() {
    const events = new EventSource("/events");
    events.onmessage = e => render(JSON.parse(e.data));
    events.onerror = () => { $("state").textContent = "Reconnecting"; };
  }
  refresh(); listen(); setInterval(clock, 15000);
})();
</script></body></html>
"""
