"""The report's HTML pages: index.html (findings grouped by severity) and bugs/<id>.html (one page per finding).

Pages are self-contained (inline CSS and JS, system fonts) so a run folder opens offline from disk.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from .report_text import (
    RETEST_WORDS,
    SEVERITIES,
    SEVERITY_ORDER,
    TYPE_NAMES,
    TYPES,
    environment,
    history_sentence,
    outside,
    performance_rows,
    repro,
    seen_again,
    summary,
    technical_rows,
)


def _e(text) -> str:
    return html.escape(str(text if text is not None else ""))


def _icon(path: str, size: int = 20, filled: bool = False) -> str:
    paint = ('fill="currentColor" stroke="none"' if filled else
             'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"')
    return (f'<svg viewBox="0 0 24 24" width="{size}" height="{size}" aria-hidden="true" focusable="false" {paint}>'
            f'<path d="{path}"/></svg>')


_CLOSE = "M6 6l12 12M18 6L6 18"
_LEFT = "M15 5l-7 7 7 7"
_RIGHT = "M9 5l7 7-7 7"
_BACK = "M19 12H5M11 6l-6 6 6 6"
_PLAY = "M8 5v14l11-7z"
_SEARCH = "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4"
_FILTER = "M4 6h16M7 12h10M10 18h4"
_DOWNLOAD = "M12 4v11M7 10l5 5 5-5M5 20h14"


# --- order -----------------------------------------------------------------------------------

def _id_key(fid: str) -> tuple:
    """B2 before B10: letters, then the number."""
    m = re.fullmatch(r"(\D*)(\d*)(.*)", fid)
    return m.group(1), int(m.group(2) or 0), m.group(3)


def _by_priority(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda f: (f.get("priority") or "P9", _id_key(f["id"])))


def groups(findings: list[dict]) -> list[tuple[str, str, list[dict]]]:
    """In-scope findings as the list shows them: (key, heading, findings) per severity, then the unrated ones."""
    live = [f for f in findings if f["status"] != "Retracted" and not outside(f)]
    result = [(s, s, _by_priority([f for f in live if f.get("severity") == s])) for s in SEVERITIES]
    rest = [f for f in live if f.get("severity") not in SEVERITIES]
    result.append(("unrated", "Not rated", _by_priority([f for f in rest if f["type"] != "observation"])))
    result.append(("observations", "Observations", _by_priority([f for f in rest if f["type"] == "observation"])))
    return [g for g in result if g[2]]


def _outside_order(findings: list[dict]) -> list[dict]:
    return sorted((f for f in findings if f["status"] != "Retracted" and outside(f)),
                  key=lambda f: (SEVERITY_ORDER.get(f.get("severity"), 5), f.get("priority") or "P9",
                                 _id_key(f["id"])))


def _retracted(findings: list[dict]) -> list[dict]:
    return sorted((f for f in findings if f["status"] == "Retracted"), key=lambda f: _id_key(f["id"]))


def page_order(findings: list[dict]) -> list[dict]:
    """The list's order, top to bottom, so Previous/Next on finding pages follow it."""
    return ([f for _, _, items in groups(findings) for f in items]
            + _outside_order(findings) + _retracted(findings))


# --- styles and scripts ----------------------------------------------------------------------

_DARK = """--page:#11151b;--surface:#191e26;--sunk:#212833;--ink:#e6e9ee;--muted:#a3adba;--line:#2b323c;
--field:#6f7a89;--link:#93b4ff;--focus:#93b4ff;--chip:#262d37;--chip-ink:#c9d0da;--bezel:#05070a;
--blocker:#c9a3f2;--blocker-ink:#230a3d;--critical:#ff9b91;--critical-ink:#3d0804;--major:#ffad73;
--major-ink:#3a1600;--minor:#f0d36e;--minor-ink:#2e2300;--trivial:#3a4350;--trivial-ink:#e1e6ec;--trivial-mark:#7d8898;
--unconfirmed:#f5b264;--ok:#6fd49b;--bad:#ff9b91"""

_CSS = """
:root{color-scheme:light dark;--page:#f4f6f8;--surface:#fff;--sunk:#eef1f5;--ink:#1b2330;--muted:#536071;
--line:#dde2e8;--field:#8a95a5;--link:#2a55c9;--focus:#2a55c9;--chip:#e9edf2;--chip-ink:#3b4656;--bezel:#1b2330;
--blocker:#5b1a8f;--blocker-ink:#fff;--critical:#b42318;--critical-ink:#fff;--major:#c2410c;--major-ink:#fff;
--minor:#f2c94c;--minor-ink:#3a2c00;--trivial:#dfe4ea;--trivial-ink:#364152;--trivial-mark:#8a95a5;--unconfirmed:#9a4a05;
--ok:#1d7a46;--bad:#b42318}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;DARK}}
:root[data-theme="dark"]{color-scheme:dark;DARK}
:root[data-theme="light"]{color-scheme:light}
*{box-sizing:border-box}
[hidden]{display:none!important}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,
sans-serif;font-variant-numeric:tabular-nums;scrollbar-color:var(--field) var(--page)}
::selection{background:color-mix(in srgb,var(--link) 30%,transparent)}
a{color:var(--link);text-underline-offset:.18em}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
button,input{font:inherit;color:inherit}
input[type=checkbox]{accent-color:var(--link);width:16px;height:16px}
main{max-width:1120px;margin:0 auto;padding:32px 16px 72px}
h1{font-size:28px;line-height:1.2;margin:0 0 6px;letter-spacing:-.01em;overflow-wrap:anywhere;text-wrap:balance}
h2{font-size:18px;line-height:1.3;margin:40px 0 12px}
h3{font-size:15px;margin:20px 0 4px}
.sub{color:var(--muted);margin:0}
.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
kbd{font:12px/1 ui-monospace,SFMono-Regular,Consolas,monospace;padding:3px 6px;border:1px solid var(--line);
border-bottom-width:2px;border-radius:5px;color:var(--muted);background:var(--surface)}
/* pills */
.pill{display:inline-flex;align-items:center;font-size:12px;font-weight:600;line-height:1;padding:5px 9px;
border-radius:999px;white-space:nowrap;background:var(--chip);color:var(--chip-ink)}
.sev-Blocker{background:var(--blocker);color:var(--blocker-ink)}
.sev-Critical{background:var(--critical);color:var(--critical-ink)}
.sev-Major{background:var(--major);color:var(--major-ink)}
.sev-Minor{background:var(--minor);color:var(--minor-ink)}
.sev-Trivial{background:var(--trivial);color:var(--trivial-ink)}
.sev-none{background:var(--chip);color:var(--chip-ink)}
.swatch.sev-Trivial,.spectrum .sev-Trivial,.legend .sev-Trivial{background:var(--trivial-mark)}
.pill.status-Unconfirmed{background:transparent;color:var(--unconfirmed);box-shadow:inset 0 0 0 1.5px currentColor}
.pill.status-Retracted{background:transparent;color:var(--muted);box-shadow:inset 0 0 0 1.5px currentColor}
/* buttons */
.btn{display:inline-flex;align-items:center;gap:8px;min-height:40px;padding:8px 14px;border-radius:8px;
border:1px solid var(--field);background:var(--surface);color:var(--ink);font-size:14px;font-weight:600;
line-height:1.2;text-decoration:none;cursor:pointer}
.btn:hover{background:var(--sunk)}
.btn.primary{background:var(--ink);border-color:var(--ink);color:var(--surface)}
.btn.primary:hover{background:color-mix(in srgb,var(--ink) 84%,var(--surface))}
.linkish{border:0;background:none;padding:4px 0;color:var(--link);text-decoration:underline;
text-underline-offset:.18em;cursor:pointer;font-size:14px}
/* summary */
.lead{max-width:72ch;margin:18px 0 0}
.lead+.lead{margin-top:8px}
.spectrum{display:flex;gap:2px;height:10px;border-radius:5px;overflow:hidden;margin:22px 0 8px;max-width:720px}
.spectrum span{display:block;min-width:6px}
.legend{display:flex;flex-wrap:wrap;gap:4px 16px;color:var(--muted);font-size:13px;margin:0;padding:0;list-style:none}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
/* toolbar */
.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:30px 0 0}
.search{position:relative;flex:1 1 260px;min-width:0}
.search svg{position:absolute;left:11px;top:50%;transform:translateY(-50%);color:var(--muted);pointer-events:none}
.search input{width:100%;min-height:40px;padding:8px 40px 8px 38px;border:1px solid var(--field);border-radius:8px;
background:var(--surface)}
.search input::placeholder{color:var(--muted);opacity:1}
.search kbd{position:absolute;right:10px;top:50%;transform:translateY(-50%);pointer-events:none}
.search input:focus+kbd,.search input:not(:placeholder-shown)+kbd{display:none}
.badge{min-width:20px;height:20px;padding:0 6px;border-radius:999px;background:var(--link);color:var(--surface);
font-size:12px;line-height:20px;text-align:center}
.filters{display:flex;flex-wrap:wrap;gap:16px 32px;margin:10px 0 0;padding:14px 16px 16px;
border:1px solid var(--line);border-radius:10px;background:var(--surface)}
.filters fieldset{border:0;margin:0;padding:0;min-width:0}
.filters legend{font-size:13px;font-weight:600;color:var(--muted);padding:0;margin-bottom:8px}
.facet{display:flex;flex-wrap:wrap;gap:6px}
.chip{display:inline-flex;align-items:center;gap:7px;min-height:36px;padding:6px 12px 6px 10px;
border:1px solid var(--field);border-radius:999px;background:var(--surface);font-size:14px;cursor:pointer}
.chip:hover{background:var(--sunk)}
.chip:has(input:checked){background:var(--sunk);border-color:var(--ink)}
.chip:has(:focus-visible){outline:2px solid var(--focus);outline-offset:2px}
.chip input{margin:0}
.chip input:focus-visible{outline:0}
.n{color:var(--muted);font-weight:500;font-size:.85em}
.filters .note{flex-basis:100%;margin:0;color:var(--muted);font-size:13px}
.status-line{display:flex;flex-wrap:wrap;gap:4px 14px;align-items:center;min-height:28px;margin:8px 0 0;
font-size:14px;color:var(--muted)}
.status-line+.group h2{margin-top:10px}
/* finding rows */
.group h2{display:flex;align-items:center;gap:10px;font-size:16px;margin:28px 0 10px}
.group>.sub{margin:-4px 0 12px;font-size:14px}
.swatch{width:12px;height:12px;border-radius:3px;flex:none}
.rows{list-style:none;margin:0;padding:0;border:1px solid var(--line);border-radius:10px;background:var(--surface);
overflow:hidden}
.rows li:not([hidden])~li{border-top:1px solid var(--line)}
.row{display:grid;grid-template-columns:3rem minmax(0,1fr) fit-content(40%);gap:4px 14px;align-items:start;
padding:14px 16px;color:inherit;text-decoration:none}
.row:hover{background:var(--sunk)}
.row:hover .title{text-decoration:underline;text-underline-offset:.18em}
.row:focus-visible{outline-offset:-3px;border-radius:10px}
.row .id{color:var(--muted);font-size:13px;font-weight:600;padding-top:1px}
.row .title{display:block;font-weight:600;overflow-wrap:anywhere}
.row .sum{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;color:var(--muted);
font-size:14px;margin-top:2px;overflow-wrap:anywhere}
.row .tags{display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end}
.empty{margin:20px 0 0;padding:28px 16px;text-align:center;border:1px dashed var(--field);border-radius:10px;
color:var(--muted)}
.empty p{margin:0 0 6px}
details.more{margin:36px 0 0;border-top:1px solid var(--line);padding-top:14px}
details.more+details.more{margin-top:14px}
details.more>summary{cursor:pointer;font-weight:600;font-size:16px;padding:4px 0}
details.more .rows{margin-top:12px}
details.more>.sub{margin-top:8px}
table{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--line);border-radius:10px;
overflow:hidden;margin-top:12px}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
th{width:220px;color:var(--muted);font-weight:500}
tr:last-child th,tr:last-child td{border-bottom:0}
.res-pass{color:var(--ok)}.res-fail{color:var(--bad)}.res-blocked{color:var(--unconfirmed)}.res-skipped{color:var(--muted)}
ul.plain{padding-left:20px;max-width:72ch;margin:0}
ul.plain li{margin:3px 0}
.help{max-width:72ch}
.help dt{font-weight:600;margin-top:14px}
.help dd{margin:2px 0 0}
/* history */
ol.history{list-style:none;padding:0 0 0 16px;margin:4px 0 0 5px;border-left:2px solid var(--line)}
ol.history li{position:relative;margin:0 0 10px}
ol.history li::before{content:"";position:absolute;left:-23px;top:.45em;width:10px;height:10px;border-radius:50%;
background:var(--surface);box-shadow:inset 0 0 0 2px var(--muted)}
ol.history time{display:block;color:var(--muted);font-size:13px}
/* finding page */
.crumbs{display:flex;justify-content:space-between;align-items:center;gap:4px 16px;flex-wrap:wrap;font-size:14px;
margin:-8px 0 16px}
.crumbs a{display:inline-flex;align-items:center;gap:6px;min-height:40px;text-decoration:none;font-weight:600}
.crumbs a:hover{text-decoration:underline}
.pn{display:flex;align-items:center;gap:16px}
.pn .pos{color:var(--muted)}
.bug-head h1 .fid{color:var(--muted);margin-right:.4em}
.bug-head .tags{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:12px 0 0}
.area{color:var(--muted);font-size:14px;margin-left:4px}
.actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:22px 0 0}
.copy-status{font-size:14px;font-weight:600;margin-left:6px}
.hint{margin:8px 0 0;color:var(--muted);font-size:13px;max-width:72ch}
.callout{margin:22px 0 0;padding:14px 16px;border:1px solid var(--line);border-radius:10px;background:var(--surface);
max-width:72ch}
.callout h2{margin:0 0 4px;font-size:15px}
.callout p{margin:0}
.bug-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,380px);grid-template-areas:"facts evidence";
gap:0 48px;align-items:start}
.facts{grid-area:facts;max-width:72ch;min-width:0}
.evidence-col{grid-area:evidence;min-width:0}
.facts h2,.evidence-col h2{display:flex;align-items:baseline;gap:8px;font-size:16px;margin:30px 0 8px}
.facts p,.facts ul,.facts ol{margin:0;overflow-wrap:anywhere}
.facts ol,.facts ul{padding-left:22px}
.facts li{margin:4px 0}
.facts details{margin-top:30px}
.facts summary{cursor:pointer;font-weight:600;font-size:16px;padding:4px 0}
.evidence{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:18px}
figure{margin:0}
.phone{position:relative;display:block;width:100%;padding:0;border:7px solid var(--bezel);border-radius:22px;
overflow:hidden;background:var(--bezel);cursor:zoom-in}
.phone img,.phone video{display:block;width:100%;height:auto;pointer-events:none}
.phone:focus-visible{outline-offset:3px}
.play{position:absolute;inset:0;margin:auto;width:52px;height:52px;border-radius:50%;background:rgba(10,13,18,.72);
color:#fff;display:grid;place-items:center}
.play svg{margin-left:3px}
figcaption{font-size:13px;color:var(--muted);margin-top:8px;overflow-wrap:anywhere}
.files{list-style:none;padding:0;margin:16px 0 0;font-size:14px}
.files li{margin:4px 0}
/* viewer */
dialog.viewer{border:0;padding:0;margin:0;inset:0;max-width:none;max-height:none;width:100vw;height:100dvh;
background:transparent;color:#fff;overflow:hidden}
dialog.viewer::backdrop{background:rgba(9,12,17,.94)}
.viewer :focus-visible{outline-color:#fff}
.viewer .stage{position:absolute;inset:64px 76px 80px;overflow:auto;display:flex;align-items:center;
justify-content:center;touch-action:pan-y pinch-zoom}
.viewer .stage img,.viewer .stage video{max-width:100%;max-height:100%;object-fit:contain;border-radius:8px}
.viewer .stage img{cursor:zoom-in}
.viewer .stage video{width:100%;height:100%;background:#000}
.viewer .stage.zoomed{display:block;touch-action:auto}
.viewer .stage.zoomed img{max-width:none;max-height:none;cursor:zoom-out}
.viewer .icon{position:absolute;display:grid;place-items:center;width:44px;height:44px;padding:0;border:0;
border-radius:999px;background:rgba(255,255,255,.14);color:#fff;cursor:pointer}
.viewer .icon:hover{background:rgba(255,255,255,.26)}
.viewer .close{top:12px;right:16px}
.viewer .prev,.viewer .next{top:50%;transform:translateY(-50%)}
.viewer .prev{left:16px}.viewer .next{right:16px}
.viewer .bar{position:absolute;left:0;right:0;bottom:0;display:flex;flex-wrap:wrap;gap:6px 18px;justify-content:center;
align-items:center;padding:14px 16px 18px;font-size:14px;color:#d5dce6}
.viewer .cap{color:#fff;font-weight:600;overflow-wrap:anywhere}
.viewer .bar a{color:#cfdcff}
.viewer .zoom{min-height:36px;padding:6px 14px;border:1px solid rgba(255,255,255,.45);border-radius:999px;
background:transparent;color:#fff;cursor:pointer}
.viewer .zoom[aria-pressed=true]{background:#fff;color:#11151b}
@media (max-width:760px){
main{padding-top:20px}
h1{font-size:24px}
th{width:120px}
.search kbd{display:none}
.row{grid-template-columns:2.6rem minmax(0,1fr);padding:14px}
.row .tags{grid-column:2;justify-content:flex-start;margin-top:6px}
.bug-grid{grid-template-columns:minmax(0,1fr);grid-template-areas:"evidence" "facts"}
.evidence{grid-template-columns:none;grid-auto-flow:column;grid-auto-columns:150px;overflow-x:auto;
overscroll-behavior-x:contain;scroll-snap-type:x mandatory;padding:2px 2px 8px}
.evidence figure{scroll-snap-align:start}
.viewer .stage{inset:60px 0 112px}
.viewer .prev,.viewer .next{top:auto;bottom:14px;transform:none}
.viewer .bar{padding:12px 72px 16px}
}
@media (prefers-reduced-motion:no-preference){.row,.btn,.chip{transition:background-color .12s}}
@media print{
body{background:#fff;color:#000}
.toolbar,.filters,.status-line,.actions,.hint,.pn,dialog,.empty{display:none!important}
.row .sum{display:block}
a{color:inherit;text-decoration:none}
main{padding:0;max-width:none}
}
""".replace("DARK", _DARK)

_INDEX_JS = r"""
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const base = location.pathname.replace(/[^/]*$/, '');
  const store = (k, v) => { try { sessionStorage.setItem(`mt:${base}:${k}`, v); } catch (e) { /* storage off */ } };
  const take = k => {
    try {
      const v = sessionStorage.getItem(`mt:${base}:${k}`);
      sessionStorage.removeItem(`mt:${base}:${k}`);
      return v;
    } catch (e) { return null; }
  };
  const rows = $$('li[data-id]');
  const q = $('#q'), panel = $('#filters'), toggle = $('#filter-toggle'), badge = $('#filter-count'),
        count = $('#count'), empty = $('#empty');
  const boxes = panel ? $$('input[type=checkbox]', panel) : [];
  const open = on => { if (panel) { panel.hidden = !on; toggle.setAttribute('aria-expanded', String(on)); } };

  function apply() {
    const text = q.value.trim().toLowerCase(), on = {};
    for (const b of boxes) if (b.checked) (on[b.name] = on[b.name] || []).push(b.value);
    let shown = 0, total = 0;
    for (const li of rows) {
      const ok = Object.entries(on).every(([k, vals]) => vals.includes(li.dataset[k])) &&
        (!text || li.dataset.text.includes(text));
      li.hidden = !ok;
      if (!li.closest('[data-retracted]')) { total++; if (ok) shown++; }
    }
    for (const sec of $$('[data-section]')) {
      const n = $$('li[data-id]', sec).filter(li => !li.hidden).length;
      sec.hidden = !n;
      const label = $('.n', sec); if (label) label.textContent = n;
    }
    const active = boxes.filter(b => b.checked).length, filtered = active > 0 || text !== '';
    if (badge) { badge.textContent = active; badge.hidden = !active; }
    $$('.reset').forEach(b => { b.hidden = !filtered; });
    empty.hidden = shown > 0 || total === 0;
    count.textContent = filtered ? `Showing ${shown} of ${total} findings` : '';
    const params = new URLSearchParams();
    if (text) params.set('q', q.value.trim());
    for (const [k, v] of Object.entries(on)) params.set(k, v.join(','));
    const hash = params.toString() ? `#${params}` : '';
    try { history.replaceState(null, '', location.pathname + location.search + hash); } catch (e) { /* file: rules */ }
    store('hash', hash);
    store('order', rows.filter(li => !li.hidden).map(li => li.dataset.id).join(' '));
  }

  if (q) {
    const init = new URLSearchParams(location.hash.slice(1));
    q.value = init.get('q') || '';
    for (const b of boxes) b.checked = !!init.get(b.name) && init.get(b.name).split(',').includes(b.value);
    if (boxes.some(b => b.checked)) open(true);
    let timer;
    q.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(apply, 120); });
    if (panel) panel.addEventListener('change', apply);
    if (toggle) toggle.addEventListener('click', () => open(panel.hidden));
    $$('.reset').forEach(b => b.addEventListener('click', () => {
      q.value = ''; boxes.forEach(x => { x.checked = false; }); apply(); q.focus();
    }));
    apply();
  }

  const back = take('return');
  const row = back && rows.find(li => li.dataset.id === back);
  if (row && row.offsetParent) $('a', row).focus();

  document.addEventListener('keydown', e => {
    if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return;
    const typing = e.target.closest && e.target.closest('input, textarea, select, [contenteditable]');
    if (q && e.key === '/' && !typing) { e.preventDefault(); q.focus(); q.select(); return; }
    if (q && e.key === 'Escape' && e.target === q && q.value) { e.preventDefault(); q.value = ''; apply(); return; }
    if (typing || (e.key !== 'j' && e.key !== 'k')) return;
    const links = rows.filter(li => !li.hidden && li.offsetParent).map(li => $('a', li));
    if (!links.length) return;
    const at = links.indexOf(document.activeElement);
    const to = at < 0 ? 0 : Math.max(0, Math.min(links.length - 1, at + (e.key === 'j' ? 1 : -1)));
    links[to].focus(); e.preventDefault();
  });
})();
"""

_BUG_JS = r"""
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const id = document.body.dataset.id;
  const base = location.pathname.replace(/bugs\/[^/]*$/, '');
  const read = k => { try { return sessionStorage.getItem(`mt:${base}:${k}`); } catch (e) { return null; } };
  const store = (k, v) => { try { sessionStorage.setItem(`mt:${base}:${k}`, v); } catch (e) { /* storage off */ } };

  // Previous/Next follow the list as it was filtered on the index page.
  const back = $('#back'), prev = $('#prev'), next = $('#next'), pos = $('#pos');
  const hash = read('hash') || '', order = (read('order') || '').split(' ').filter(Boolean), at = order.indexOf(id);
  if (at >= 0) {
    const point = (a, other) => {
      a.hidden = !other;
      if (other) { a.href = `${encodeURIComponent(other)}.html`; $('.pid', a).textContent = other; }
    };
    point(prev, order[at - 1]); point(next, order[at + 1]);
    pos.textContent = `${at + 1} of ${order.length}${hash ? ' filtered' : ''}`;
  }
  back.href = `../index.html${hash}`;
  back.addEventListener('click', () => store('return', id));

  // Copy buttons: say what happened, and only when it did.
  const status = $('#copy-status');
  let clear;
  const say = msg => {
    status.textContent = msg; clearTimeout(clear);
    clear = setTimeout(() => { status.textContent = ''; }, 4000);
  };
  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* try the old way */ }
    const t = document.createElement('textarea');
    t.value = text; t.setAttribute('readonly', ''); t.style.cssText = 'position:fixed;opacity:0';
    document.body.appendChild(t); t.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    t.remove(); return ok;
  }
  $$('[data-copy]').forEach(b => b.addEventListener('click', async () => {
    const ok = await copyText(document.getElementById(b.dataset.copy).content.textContent);
    say(ok ? b.dataset.done : "Couldn't copy in this browser. Open the Markdown file and copy from there.");
  }));

  // Evidence viewer.
  const items = $$('button.phone'), dlg = $('#viewer');
  if (dlg && items.length) {
    const img = $('img', dlg), vid = $('video', dlg), stage = $('.stage', dlg), cap = $('.cap', dlg),
          orig = $('.orig', dlg), where = $('.pos', dlg), zoomBtn = $('.zoom', dlg);
    let i = 0, swiped = false;
    const zoom = (on, fx = 0.5, fy = 0.5) => {
      if (img.hidden) return;
      stage.classList.toggle('zoomed', on); zoomBtn.setAttribute('aria-pressed', String(on));
      if (on) {
        stage.scrollLeft = fx * img.scrollWidth - stage.clientWidth / 2;
        stage.scrollTop = fy * img.scrollHeight - stage.clientHeight / 2;
      }
    };
    const show = n => {
      i = (n + items.length) % items.length;
      const it = items[i], video = it.dataset.kind === 'video';
      vid.pause(); stage.classList.remove('zoomed'); zoomBtn.setAttribute('aria-pressed', 'false');
      img.hidden = video; vid.hidden = !video; zoomBtn.hidden = video;
      if (video) { vid.src = it.dataset.full; }
      else { img.src = it.dataset.full; img.alt = it.dataset.caption; vid.removeAttribute('src'); vid.load(); }
      cap.textContent = it.dataset.caption; orig.href = it.dataset.full;
      where.textContent = items.length > 1 ? `${i + 1} of ${items.length}` : '';
    };
    $$('.prev, .next', dlg).forEach(b => { b.hidden = items.length < 2; });
    items.forEach((it, n) => it.addEventListener('click', () => { show(n); dlg.showModal(); }));
    $('.close', dlg).addEventListener('click', () => dlg.close());
    $('.prev', dlg).addEventListener('click', () => show(i - 1));
    $('.next', dlg).addEventListener('click', () => show(i + 1));
    zoomBtn.addEventListener('click', () => zoom(!stage.classList.contains('zoomed')));
    // The browser puts focus back on the opening button after 'close'; move it to the item last shown.
    dlg.addEventListener('close', () => { vid.pause(); setTimeout(() => items[i].focus(), 0); });
    dlg.addEventListener('click', e => { if (e.target === dlg || e.target === stage) dlg.close(); });
    dlg.addEventListener('keydown', e => {
      if (e.target === vid && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) return;
      if (e.key === 'ArrowLeft') show(i - 1);
      else if (e.key === 'ArrowRight') show(i + 1);
      else if (e.key === '+' || e.key === '=') zoom(true);
      else if (e.key === '-' || e.key === '0') zoom(false);
      else return;
      e.preventDefault();
    });
    img.addEventListener('click', e => {
      if (swiped) { swiped = false; return; }
      zoom(!stage.classList.contains('zoomed'), e.offsetX / img.clientWidth, e.offsetY / img.clientHeight);
    });
    let startX = null;
    stage.addEventListener('pointerdown', e => { startX = e.pointerType === 'mouse' ? null : e.clientX; });
    stage.addEventListener('pointerup', e => {
      if (startX === null || stage.classList.contains('zoomed')) return;
      const dx = e.clientX - startX; startX = null;
      if (Math.abs(dx) > 50 && items.length > 1) { swiped = true; show(i + (dx < 0 ? 1 : -1)); }
    });
  }

  document.addEventListener('keydown', e => {
    if (e.ctrlKey || e.metaKey || e.altKey || (dlg && dlg.open)) return;
    if (e.key === 'j' && !next.hidden) location.href = next.href;
    else if (e.key === 'k' && !prev.hidden) location.href = prev.href;
  });
})();
"""


def _page(title: str, body: str, script: str, body_attrs: str = "") -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{_e(title)}</title>'
            f"<style>{_CSS}</style></head><body{body_attrs}><main>{body}</main><script>{script}</script>"
            f"</body></html>")


# --- shared parts ----------------------------------------------------------------------------

def _sev_class(f: dict) -> str:
    return f"sev-{f['severity']}" if f.get("severity") in SEVERITIES else "sev-none"


def _pills(f: dict, severity: bool = True) -> str:
    pills = []
    if severity and f.get("severity"):
        pills.append(f'<span class="pill {_sev_class(f)}"><span class="vh">Severity </span>{_e(f["severity"])}</span>')
    if f.get("priority"):
        pills.append(f'<span class="pill"><span class="vh">Priority </span>{_e(f["priority"])}</span>')
    if f["type"] != "bug":
        pills.append(f'<span class="pill">{_e(TYPE_NAMES[f["type"]])}</span>')
    if f["status"] != "Confirmed":
        pills.append(f'<span class="pill status-{f["status"]}">{_e(f["status"])}</span>')
    if outside(f):
        pills.append('<span class="pill">Outside scope</span>')
    if seen_again(f):
        pills.append(f'<span class="pill">{_e(f["known_issue"])} seen again</span>')
    elif f.get("known_issue"):
        pills.append(f'<span class="pill">{_e(f["known_issue"])}</span>')
    return "".join(pills)


def _table(rows: list[tuple[str, str]]) -> str:
    return "<table>" + "".join(f"<tr><th>{_e(k)}</th><td>{_e(v)}</td></tr>" for k, v in rows) + "</table>"


# --- index page ------------------------------------------------------------------------------

def _row(f: dict, severity: bool = False) -> str:
    fid = _e(f["id"])
    rid = f"r-{fid}"
    text = " ".join(str(f.get(k, "")) for k in ("id", "title", "summary", "actual", "area", "known_issue")).casefold()
    return (f'<li data-id="{fid}" data-type="{_e(f["type"])}" data-sev="{_e(f.get("severity") or "none")}" '
            f'data-status="{_e(f["status"])}" data-text="{_e(text)}">'
            f'<a class="row" href="bugs/{fid}.html" aria-labelledby="{rid}-id {rid}-t" '
            f'aria-describedby="{rid}-s {rid}-g"><span class="id" id="{rid}-id">{fid}</span>'
            f'<span class="main"><span class="title" id="{rid}-t">{_e(f["title"])}</span>'
            f'<span class="sum" id="{rid}-s">{_e(summary(f))}</span></span>'
            f'<span class="tags" id="{rid}-g">{_pills(f, severity)}</span></a></li>')


def _facet(name: str, legend: str, findings: list[dict], key: str, values, label) -> str:
    counts = {v: sum(1 for f in findings if (f.get(key) or "none") == v) for v in values}
    present = [v for v in values if counts[v]]
    if len(present) < 2:
        return ""
    chips = "".join(f'<label class="chip"><input type="checkbox" name="{name}" value="{_e(v)}">{_e(label(v))}'
                    f'<span class="n">{counts[v]}</span></label>' for v in present)
    return f'<fieldset><legend>{_e(legend)}</legend><div class="facet">{chips}</div></fieldset>'


def _toolbar(findings: list[dict], csv: bool) -> str:
    live = [f for f in findings if f["status"] != "Retracted"]
    facets = (_facet("type", "Type", live, "type", TYPES, lambda v: TYPE_NAMES[v])
              + _facet("sev", "Severity", live, "severity", (*SEVERITIES, "none"),
                       lambda v: "No severity" if v == "none" else v)
              + _facet("status", "Status", live, "status", ("Confirmed", "Unconfirmed"), str))
    filter_button = (f'<button type="button" class="btn" id="filter-toggle" aria-expanded="false" '
                     f'aria-controls="filters">{_icon(_FILTER, 18)}Filters'
                     f'<span class="badge" id="filter-count" hidden></span></button>') if facets else ""
    csv_link = (f'<a class="btn" href="findings.csv" download>{_icon(_DOWNLOAD, 18)}CSV for Jira import</a>'
                if csv else "")
    panel = (f'<div class="filters" id="filters" hidden>{facets}'
             f'<p class="note">Nothing ticked in a group means all of it is shown.</p></div>') if facets else ""
    return (f'<div class="toolbar"><div class="search" role="search">{_icon(_SEARCH, 18)}'
            f'<input type="search" id="q" placeholder="Search findings" aria-label="Search findings" '
            f'aria-keyshortcuts="/" autocomplete="off" spellcheck="false"><kbd aria-hidden="true">/</kbd></div>'
            f'{filter_button}{csv_link}</div>{panel}'
            f'<div class="status-line"><span id="count" role="status"></span>'
            f'<button type="button" class="linkish reset" hidden>Reset filters</button></div>')


def _spectrum(counted: list[dict]) -> str:
    by_sev = [(s, sum(1 for f in counted if f.get("severity") == s)) for s in SEVERITIES]
    by_sev = [(s, n) for s, n in by_sev if n]
    if not by_sev:
        return ""
    segments = "".join(f'<span class="sev-{s}" style="flex:{n}"></span>' for s, n in by_sev)
    legend = "".join(f'<li><i class="sev-{s}"></i>{n} {s.lower()}</li>' for s, n in by_sev)
    return (f'<div class="spectrum" aria-hidden="true">{segments}</div>'
            f'<ul class="legend"><li>Confirmed findings by severity:</li>{legend}</ul>')


def _lead(session: dict, counted: list[dict], unconfirmed: int, outside_count: int) -> str:
    def plural(n: int, word: str) -> str:
        return f"{n} {word}{'s' if n != 1 else ''}"
    bugs = sum(1 for f in counted if f["type"] == "bug")
    a11y = sum(1 for f in counted if f["type"] == "accessibility")
    obs = sum(1 for f in counted if f["type"] == "observation")
    text = f"{plural(bugs, 'bug')}, {plural(a11y, 'accessibility issue')} and {plural(obs, 'observation')}"
    extra = []
    if again := sum(1 for f in counted if seen_again(f)):
        extra.append(f"{again} {'is a known issue' if again == 1 else 'are known issues'} seen again")
    if unconfirmed:
        extra.append(f"{unconfirmed} still need{'s' if unconfirmed == 1 else ''} a manual reproduction")
    if outside_count:
        extra.append(f"{outside_count} more noticed outside the scope")
    text += (f"; {', '.join(extra)}" if extra else "") + "."
    session_summary = f'<p class="lead">{_e(session["summary"])}</p>' if session.get("summary") else ""
    return f'<p class="lead"><strong>{_e(text[0].upper() + text[1:])}</strong></p>{session_summary}'


def _test_result_row(r: dict) -> str:
    case = _e(r["case"]) + (f" / step {_e(r['step'])}" if r.get("step") else "")
    word = RETEST_WORDS[r["result"]] if r.get("issue") else r["result"].capitalize()
    cell = f'<b class="res-{_e(r["result"])}">{_e(word)}</b>'
    if r.get("finding"):
        fid = _e(r["finding"])
        cell += f' - <a href="bugs/{fid}.html">{fid}</a>'
    if r.get("note"):
        cell += f" - {_e(r['note'])}"
    return f"<tr><th>{case}</th><td>{cell}</td></tr>"


_HELP = """<details class="more"><summary>How to read and use this report</summary><dl class="help">
<dt>Severity</dt><dd>How bad it is for a user. Blocker: the app or a core journey can't be used.
Critical: a main flow is broken with no workaround. Major: broken or misleading, with a workaround.
Minor: limited impact. Trivial: cosmetic.</dd>
<dt>Priority</dt><dd>The tester's suggestion, from P1 (fix before release) to P4 (backlog). The team decides.</dd>
<dt>Status</dt><dd>Confirmed: reproduced by a person, or reliably by automation for minor issues.
Unconfirmed: reproduced only by automation so far; try it by hand before filing.
Retracted: checked and found not to be a problem; kept so you can see what was ruled out.</dd>
<dt>Filing in Jira</dt><dd>Open a finding, paste Copy title into Summary and Copy for Jira into Description,
then attach the files listed under Evidence.
To file everything at once, import the CSV with Jira's CSV import and map Summary, Description, Issue Type,
Priority and Labels; attach evidence afterwards.</dd>
<dt>Keyboard</dt><dd><kbd>/</kbd> searches, <kbd>j</kbd> and <kbd>k</kbd> move between findings, Enter opens one.
On a finding page <kbd>j</kbd> and <kbd>k</kbd> go to the next and previous finding.
In the viewer the arrow keys switch evidence, <kbd>+</kbd> and <kbd>-</kbd> zoom, Esc closes.</dd>
</dl></details>"""


def render_index(session: dict, findings: list[dict], csv: bool = False) -> str:
    in_scope = [f for f in findings if f["status"] != "Retracted" and not outside(f)]
    noticed = _outside_order(findings)
    retracted = _retracted(findings)
    body = [f'<header><h1>{_e(session.get("title"))}</h1><p class="sub">{_e(session.get("subtitle", ""))}</p>'
            f'</header>',
            _lead(session, in_scope, sum(1 for f in in_scope if f["status"] == "Unconfirmed"), len(noticed)),
            _spectrum([f for f in in_scope if f["status"] == "Confirmed"])]
    if findings:
        body.append(_toolbar(findings, csv))
    for key, heading, items in groups(findings):
        swatch = f'<span class="swatch sev-{key}" aria-hidden="true"></span>' if key in SEVERITIES else ""
        body.append(f'<section class="group" data-section><h2>{swatch}{_e(heading)}'
                    f'<span class="n">{len(items)}</span></h2>'
                    f'<ul class="rows">{"".join(_row(f) for f in items)}</ul></section>')
    if not in_scope:
        body.append('<p class="lead">No findings in scope.</p>')
    if noticed:
        body.append(f'<section class="group" data-section><h2>Noticed outside the scope'
                    f'<span class="n">{len(noticed)}</span></h2>'
                    f'<p class="sub">Seen in passing on other screens or features; not counted above. '
                    f'Triage separately.</p>'
                    f'<ul class="rows">{"".join(_row(f, severity=True) for f in noticed)}</ul></section>')
    if findings:
        body.append('<div class="empty" id="empty" hidden><p>No findings match the search and filters.</p>'
                    '<button type="button" class="linkish reset">Reset filters</button></div>')
    if retracted:
        body.append(f'<details class="more" data-section data-retracted><summary>Retracted '
                    f'<span class="n">{len(retracted)}</span></summary>'
                    f'<p class="sub">Checked during the session and found not to be problems.</p>'
                    f'<ul class="rows">{"".join(_row(f, severity=True) for f in retracted)}</ul></details>')
    if session.get("test_results"):
        rows = "".join(_test_result_row(r) for r in session["test_results"])
        heading = "Retest results" if session.get("mode") == "retest" else "Test results"
        body.append(f"<h2>{heading}</h2><table>{rows}</table>")
    if perf := performance_rows(session.get("performance") or {}):
        body.append(f"<h2>Performance</h2>{_table(perf)}")
    if logs := session.get("log_summary"):
        rows = "".join(f'<tr><th>{_e(g["count"])}x {_e(g["kind"])}</th><td><b>{_e(g["tag"])}</b>: {_e(g["text"])}'
                       f'<br><span class="sub">first at {_e(g["first"])}</span></td></tr>' for g in logs)
        body.append('<h2>App log</h2><p class="sub">Errors and warnings the app logged during the session, '
                    f'grouped. Not every one is a bug; findings link the ones that are.</p><table>{rows}</table>')
    for key, heading in (("worked_well", "Worked well"), ("coverage", "Covered"), ("not_covered", "Not covered")):
        if session.get(key):
            items = "".join(f"<li>{_e(i)}</li>" for i in session[key])
            body.append(f'<h2>{heading}</h2><ul class="plain">{items}</ul>')
    evidence = session.get("evidence") or {}
    links = " ".join(f'<a href="{_e(p)}">{_e(k.replace("_", " "))}</a>' for k, p in evidence.items())
    body.append(f'<details class="more"><summary>Session details</summary>{_table(environment(session))}'
                + (f'<p class="sub" style="margin-top:10px">Session evidence: {links}</p>' if links else "")
                + "</details>")
    if tech := technical_rows(session.get("technical") or {}):
        body.append('<h2>Technical data</h2><p class="sub">How this report was produced, for tracking the testing '
                    f'skill over time. Every run adds a row to telemetry.csv in the reports folder.</p>{_table(tech)}')
    body.append(_HELP)
    return _page(session.get("title", "Test report"), "".join(body), _INDEX_JS)


# --- finding pages ---------------------------------------------------------------------------

def _evidence_html(f: dict) -> str:
    media, files = [], []
    for ev in f.get("evidence", []):
        path = _e("../" + ev["path"])
        cap = _e(ev.get("caption") or Path(ev["path"]).name)
        if ev["type"] == "screenshot":
            media.append(f'<figure><button type="button" class="phone" data-kind="image" data-full="{path}" '
                         f'data-caption="{cap}" aria-label="Enlarge screenshot: {cap}"><img src="{path}" alt="">'
                         f'</button><figcaption>{cap}</figcaption></figure>')
        elif ev["type"] == "video":
            media.append(f'<figure><button type="button" class="phone" data-kind="video" data-full="{path}" '
                         f'data-caption="{cap}" aria-label="Play video: {cap}">'
                         f'<video src="{path}#t=0.1" preload="metadata" muted playsinline tabindex="-1" '
                         f'aria-hidden="true"></video><span class="play">{_icon(_PLAY, 26, filled=True)}</span>'
                         f'</button><figcaption>{cap}</figcaption></figure>')
        else:
            files.append(f'<li><a href="{path}">{cap}</a> <span class="sub">({_e(ev["type"])})</span></li>')
    count = len(media) + len(files)
    head = f'<h2>Evidence{f"<span class=n>{count}</span>" if count else ""}</h2>'
    if not count:
        return head + '<p class="sub">No evidence attached.</p>'
    grid = f'<div class="evidence">{"".join(media)}</div>' if media else ""
    listing = f'<ul class="files">{"".join(files)}</ul>' if files else ""
    return head + grid + listing


_VIEWER = (f'<dialog class="viewer" id="viewer" aria-label="Evidence viewer">'
           f'<button type="button" class="icon close" aria-label="Close viewer">{_icon(_CLOSE, 22)}</button>'
           f'<div class="stage"><img hidden alt=""><video hidden controls playsinline></video></div>'
           f'<button type="button" class="icon prev" aria-label="Previous">{_icon(_LEFT, 24)}</button>'
           f'<button type="button" class="icon next" aria-label="Next">{_icon(_RIGHT, 24)}</button>'
           f'<div class="bar"><span class="pos"></span><span class="cap"></span>'
           f'<button type="button" class="zoom" aria-pressed="false">Actual size</button>'
           f'<a class="orig" target="_blank" rel="noopener">Open original</a></div></dialog>')


def _nav(prev_f: dict | None, next_f: dict | None, position: int, total: int) -> str:
    def link(rel: str, other: dict | None, label: str) -> str:
        href = f' href="{_e(other["id"])}.html"' if other else " hidden"
        pid = f'<span class="pid">{_e(other["id"]) if other else ""}</span>'
        inner = (f"{_icon(_LEFT, 18)}{label} {pid}" if rel == "prev" else f"{label} {pid}{_icon(_RIGHT, 18)}")
        return f'<a id="{rel}" rel="{rel}"{href}>{inner}</a>'
    return (f'<nav class="crumbs" aria-label="Findings"><a id="back" href="../index.html">{_icon(_BACK, 18)}'
            f'All findings</a><span class="pn">{link("prev", prev_f, "Previous")}'
            f'<span class="pos" id="pos">{position} of {total}</span>{link("next", next_f, "Next")}</span></nav>')


def _actions(f: dict, copies: dict[str, str]) -> str:
    templates = "".join(f'<template id="copy-{k}">{_e(v)}</template>' for k, v in copies.items())
    return (f'<div class="actions">'
            f'<button type="button" class="btn primary" data-copy="copy-md" '
            f'data-done="Copied the description. Paste it into the Jira Description field.">Copy for Jira</button>'
            f'<button type="button" class="btn" data-copy="copy-title" '
            f'data-done="Copied the title. Paste it into the Jira Summary field.">Copy title</button>'
            f'<button type="button" class="btn" data-copy="copy-wiki" '
            f'data-done="Copied as wiki markup, for Jira Server and Data Center.">Copy wiki markup</button>'
            f'<a class="btn" href="{_e(f["id"])}.md">Markdown file</a>'
            f'<span class="copy-status" id="copy-status" role="status"></span></div>'
            f'<p class="hint">Title goes into Summary, the description into Description. '
            f'Use wiki markup for Jira Server and Data Center.</p>{templates}')


def render_bug_page(session: dict, f: dict, prev_f: dict | None, next_f: dict | None, position: int, total: int,
                    copies: dict[str, str] | None) -> str:
    """copies: {"title", "md", "wiki"} texts for the copy buttons, or None when the finding isn't fileable."""
    area = f'<span class="area">{_e(f["area"])}</span>' if f.get("area") else ""
    head = (f'<header class="bug-head"><h1><span class="fid">{_e(f["id"])}</span>{_e(f["title"])}</h1>'
            f'<p class="tags">{_pills(f)}{area}</p>{_actions(f, copies) if copies else ""}</header>')
    callout = ""
    if f["status"] == "Retracted":
        callout = f'<section class="callout"><h2>Why it was retracted</h2><p>{_e(f.get("notes"))}</p></section>'
    elif f["status"] == "Unconfirmed":
        callout = ('<section class="callout"><h2>Needs a manual reproduction</h2><p>So far only automation reproduced '
                   f'this ({_e(repro(f))}). Try it by hand before filing.</p></section>')
    facts = []

    def block(heading: str, content: str) -> None:
        facts.append(f"<h2>{_e(heading)}</h2>{content}")

    if f.get("summary"):
        block("Summary", f"<p>{_e(f['summary'])}</p>")
    if f.get("preconditions"):
        block("Preconditions", "<ul>" + "".join(f"<li>{_e(p)}</li>" for p in f["preconditions"]) + "</ul>")
    if f.get("steps"):
        block("Steps to reproduce", "<ol>" + "".join(f"<li>{_e(s)}</li>" for s in f["steps"]) + "</ol>")
    if f.get("expected"):
        block("Expected", f"<p>{_e(f['expected'])}</p>")
    if f.get("actual"):
        block("Actual" if f["type"] != "observation" else "What was seen", f"<p>{_e(f['actual'])}</p>")
    if repro(f):
        block("Reproducibility", f"<p>{_e(repro(f))}</p>")
    if f.get("notes") and f["status"] != "Retracted":
        block("Notes", f"<p>{_e(f['notes'])}</p>")
    if f.get("known_issue"):
        text = ("Known issue, found again in this session." if seen_again(f)
                else "First found in this session and added to the app's known issues.")
        block(f"Known issue {f['known_issue']}", f"<p>{_e(text)}</p>")
    if f.get("history"):
        items = "".join(f'<li><time datetime="{_e(h["time"])}">{_e(h["time"][:16].replace("T", " "))}</time>'
                        f'{_e(history_sentence(h))}</li>' for h in f["history"])
        block("History", f'<ol class="history">{items}</ol>')
    jira = f.get("jira") or {}
    if jira.get("key"):
        link = f'<a href="{_e(jira["url"])}">{_e(jira["key"])}</a>' if jira.get("url") else _e(jira["key"])
        block("Jira", f"<p>{link}</p>")
    facts.append(f"<details><summary>Environment</summary>{_table(environment(session))}</details>")
    body = (f'{_nav(prev_f, next_f, position, total)}{head}{callout}'
            f'<div class="bug-grid"><section class="evidence-col">{_evidence_html(f)}</section>'
            f'<article class="facts">{"".join(facts)}</article></div>{_VIEWER}')
    return _page(f"{f['id']} {f['title']}", body, _BUG_JS, f' data-id="{_e(f["id"])}"')
