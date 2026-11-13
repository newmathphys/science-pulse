from __future__ import annotations

import html
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List

from .config import Config
from .graph import build_links, pagerank, poincare_layout, top_by_pagerank
from .models import DOMAIN_LABELS, Post
from .storage import Storage
from .text import keywords, truncate

LOGGER = logging.getLogger(__name__)

CSS = """
:root {
  --paper: #FAF8F4;
  --paper-2: #FFFFFF;
  --paper-3: #F3F0EA;
  --ink: #111827;
  --ink-2: #4B5563;
  --rule: #D6D1C7;
  --math: #1E3A8A;
  --cs: #065F46;
  --physics: #9F1239;
  --serif: Georgia, 'Charter', 'Source Serif 4', 'Times New Roman', serif;
  --mono: 'JetBrains Mono', Menlo, ui-monospace, monospace;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--paper); color: var(--ink);
  font-family: var(--serif); line-height: 1.66; font-size: 17px;
}
a { color: var(--math); text-decoration: none; border-bottom: 1px solid rgba(30,58,138,.28); }
a:hover { border-bottom-color: var(--math); }
.mono { font-family: var(--mono); }
.wrap { width: min(1120px, calc(100% - 40px)); margin: 0 auto; }
header { padding: 30px 0 0; }
.brand { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
.brand h1 { margin: 0; font-size: clamp(24px, 3.6vw, 38px); letter-spacing: -0.01em; font-weight: 700; }
.brand span { color: var(--ink-2); font-family: var(--mono); font-size: 11px; letter-spacing: .14em; text-transform: uppercase; }
.stats { display: flex; gap: 20px; flex-wrap: wrap; color: var(--ink-2); font-size: 13px; margin-top: 8px; font-family: var(--mono); }
nav.tabs { display: flex; gap: 24px; flex-wrap: wrap; padding: 16px 0; margin-top: 14px; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); font-size: 15px; }
nav.tabs a { border: 0; color: var(--ink-2); }
nav.tabs a:hover, nav.tabs a.active { color: var(--ink); font-weight: 700; }
.passport { display: flex; gap: 26px; flex-wrap: wrap; margin: 22px 0 8px; padding: 16px 20px; background: var(--paper-3); border: 1px solid var(--rule); border-radius: 4px; font-family: var(--mono); font-size: 13px; color: var(--ink-2); }
.passport b { color: var(--ink); }
.spec { list-style: none; margin: 8px 0 0; padding: 0; font-family: var(--mono); font-size: 13px; }
.spec li { display: grid; grid-template-columns: 16ch 1fr; gap: 10px; padding: 5px 0; border-top: 1px solid var(--rule); color: var(--ink-2); }
.spec li b { color: var(--ink); font-weight: 600; }
.toolbar { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin: 20px 0; }
input[type=search] { flex: 1 1 260px; background: var(--paper-2); border: 1px solid var(--rule); color: var(--ink); border-radius: 4px; padding: 11px 14px; font-size: 15px; font-family: var(--serif); }
button.filter { background: var(--paper-2); border: 1px solid var(--rule); color: var(--ink-2); padding: 9px 14px; border-radius: 999px; cursor: pointer; font-size: 14px; font-family: var(--serif); }
button.filter.active { background: var(--ink); border-color: var(--ink); color: var(--paper); font-weight: 700; }
.step { margin: 34px 0; }
.step-head { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; border-bottom: 2px solid var(--ink); padding-bottom: 8px; }
.step-head .roman { font-family: var(--mono); font-size: 12px; letter-spacing: .14em; color: var(--ink-2); }
.step-head h2 { margin: 0; font-size: clamp(18px, 2.4vw, 24px); }
.step-row { display: grid; grid-template-columns: repeat(auto-fill, minmax(272px, 1fr)); gap: 18px; margin-top: 18px; }
.node { background: var(--paper-2); border: 1px solid var(--rule); border-radius: 4px; overflow: hidden; display: flex; flex-direction: column; }
.node.published { border-color: var(--ink); }
.node.staged { border-color: var(--math); border-style: dashed; }
.node.locked { background: var(--paper-3); border-style: dashed; }
.node img { width: 100%; aspect-ratio: 1/1; object-fit: cover; border-bottom: 1px solid var(--rule); }
.node .nbody { padding: 14px 16px 16px; display: flex; flex-direction: column; gap: 8px; flex: 1; }
.node .sec { font-family: var(--mono); font-size: 12px; color: var(--ink-2); letter-spacing: .06em; }
.node h3 { margin: 0; font-size: 17px; line-height: 1.35; }
.node .sci { color: var(--ink-2); font-size: 14px; }
.node .era { color: var(--ink-2); font-size: 13px; font-style: italic; }
.node .fx { background: var(--paper-3); border-left: 3px solid var(--rule); padding: 6px 10px; font-size: 14px; overflow-x: auto; }
.stamp { display: inline-block; font-family: var(--mono); font-size: 10.5px; letter-spacing: .1em; text-transform: uppercase; padding: 3px 8px; border-radius: 3px; }
.stamp.ok { background: var(--cs); color: #fff; }
.stamp.next { background: var(--math); color: #fff; }
.stamp.lock { background: transparent; color: var(--ink-2); border: 1px solid var(--rule); }
.badge { display: inline-flex; align-items: center; gap: 6px; font-family: var(--mono); font-size: 11px; letter-spacing: .1em; text-transform: uppercase; color: var(--math); }
.badge.cs { color: var(--cs); }
.badge.physics { color: var(--physics); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 18px; padding-bottom: 40px; }
.card { background: var(--paper-2); border: 1px solid var(--rule); border-radius: 4px; overflow: hidden; display: flex; flex-direction: column; }
.card img { width: 100%; aspect-ratio: 1/1; object-fit: cover; }
.card .body { padding: 14px 16px 18px; display: flex; flex-direction: column; gap: 8px; flex: 1; }
.card h2 { font-size: 18px; line-height: 1.3; margin: 0; }
.card p { margin: 0; color: var(--ink-2); font-size: 14px; }
.meta { color: var(--ink-2); font-size: 12px; margin-top: auto; font-family: var(--mono); }
article { padding: 30px 0 60px; }
article h1 { font-size: clamp(24px, 4vw, 40px); line-height: 1.2; margin: 8px 0 14px; }
.lead { color: var(--ink-2); font-size: 18px; }
.formula { background: var(--paper-3); border: 1px solid var(--rule); border-left: 4px solid var(--ink); border-radius: 4px; padding: 16px 18px; margin: 22px 0; overflow-x: auto; }
pre { background: var(--paper-3); border: 1px solid var(--rule); border-radius: 4px; padding: 16px; overflow-x: auto; color: var(--ink); font-size: 13px; font-family: var(--mono); }
.article-card { width: min(560px, 100%); border: 1px solid var(--rule); border-radius: 4px; }
.article-body { font-size: 17px; max-width: 760px; }
.article-body p { margin: 0 0 14px; }
.tags { display: flex; gap: 8px; flex-wrap: wrap; margin: 14px 0 24px; }
.tags span { border: 1px solid var(--rule); color: var(--ink-2); border-radius: 999px; padding: 3px 10px; font-size: 12px; font-family: var(--mono); }
.sandbox { background: var(--paper-2); border: 1px solid var(--rule); border-radius: 4px; padding: 18px; margin: 26px 0; }
.sandbox canvas { width: 100%; background: var(--paper-3); border: 1px solid var(--rule); border-radius: 4px; }
.sandbox .ctl { display: flex; gap: 18px; flex-wrap: wrap; align-items: center; margin-top: 12px; font-family: var(--mono); font-size: 13px; }
.sandbox input[type=range] { width: 170px; }
.sandbox input[type=number] { width: 90px; border: 1px solid var(--rule); padding: 5px 8px; font-family: var(--mono); }
.sandbox output { font-weight: 700; color: var(--ink); }
.atlas { margin: 26px 0; }
.atlas canvas { width: 100%; height: auto; background: var(--paper-3); border: 1px solid var(--rule); border-radius: 4px; cursor: grab; }
.depth-nav { display: flex; gap: 8px; flex-wrap: wrap; margin: 18px 0 12px; }
.depth-btn { background: var(--paper-2); border: 1px solid var(--rule); color: var(--ink-2); border-radius: 4px; padding: 8px 12px; cursor: pointer; font-family: var(--mono); font-size: 12px; }
.depth-btn.active { background: var(--ink); border-color: var(--ink); color: var(--paper); }
.depth { display: none; }
.depth.visible { display: block; }
.depth > h2 { font-size: 16px; font-family: var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--ink-2); margin: 4px 0 12px; }
.anatomy { margin: 22px 0; padding: 18px 20px; background: var(--paper-2); border: 1px solid var(--rule); border-left: 4px solid var(--accent); }
.anatomy h2 { font-family: var(--mono); font-size: 14px; letter-spacing: .06em; text-transform: uppercase; color: var(--ink-2); margin: 0 0 12px; }
.anatomy ol { margin: 0; padding-left: 22px; }
.anatomy li { margin: 0 0 10px; color: var(--ink-2); }
.anatomy li b { color: var(--ink); }
.anatomy .legend { font-family: var(--mono); font-size: 13px; line-height: 1.55; }
.journal { display: grid; grid-template-columns: 230px minmax(0, 1fr) 220px; gap: 28px; align-items: start; margin-top: 18px; }
.journal .side { font-size: 14px; }
.journal .side h2 { font-size: 13px; margin: 0 0 8px; font-family: var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--ink-2); }
.journal .side ul { list-style: none; padding: 0; margin: 0 0 18px; }
.journal .side li { margin: 0 0 6px; color: var(--ink-2); }
.journal .side li b { color: var(--ink); }
.journal .main { min-width: 0; }
@media (max-width: 980px) { .journal { grid-template-columns: 1fr; } }
details.flash { background: var(--paper-2); border: 1px solid var(--rule); border-radius: 4px; padding: 12px 16px; margin: 10px 0; }
details.flash summary { cursor: pointer; font-weight: 700; }
footer { border-top: 1px solid var(--rule); color: var(--ink-2); padding: 22px 0 40px; font-size: 13px; }
.two { display: grid; grid-template-columns: 1.1fr .9fr; gap: 22px; align-items: start; }
@media (max-width: 820px) { .two { grid-template-columns: 1fr; } }
.empty { color: var(--ink-2); padding: 40px 0; }
.mini-actions { display: flex; gap: 10px; flex-wrap: wrap; margin: 18px 0; }
.mini-action { background: var(--paper-2); border: 1px solid var(--ink); color: var(--ink); border-radius: 4px; padding: 10px 16px; cursor: pointer; font-size: 15px; font-weight: 600; font-family: var(--serif); }
.mini-action:disabled { opacity: .5; cursor: not-allowed; border-color: var(--rule); color: var(--ink-2); }
.mini-log { font-family: var(--mono); color: var(--ink-2); font-size: 13px; white-space: pre-wrap; }
.panel-box { background: var(--paper-3); border: 1px solid var(--rule); border-radius: 4px; padding: 16px 18px; margin: 14px 0; }
"""

CSS += """
.branch-panel { background: var(--paper-3); border: 1px solid var(--rule); border-radius: 6px; padding: 16px 20px; margin: 22px 0; }
.branch-panel h2 { margin: 0 0 10px; font-size: 18px; }
.branch-row { display: grid; grid-template-columns: 12ch 1fr 8ch; gap: 12px; align-items: center; font-family: var(--mono); font-size: 12px; margin: 8px 0; }
.branch-bar { height: 8px; background: var(--paper-2); border: 1px solid var(--rule); border-radius: 999px; overflow: hidden; }
.branch-bar span { display: block; height: 100%; background: var(--math); }
.branch-bar.cs span { background: var(--cs); }
.branch-bar.physics span { background: var(--physics); }
.branch-next { margin-top: 12px; font-size: 14px; }
.branch-next a { margin-right: 14px; }
.mastered { background: var(--cs); color: #fff; border-color: var(--cs); }
.badges { display: flex; gap: 8px; flex-wrap: wrap; margin: 14px 0; }
.badges details { background: var(--paper-2); border: 1px solid var(--rule); border-radius: 4px; padding: 6px 10px; }
.badges summary { cursor: pointer; font-family: var(--mono); font-size: 12px; letter-spacing: .06em; }
.badges pre { max-height: 260px; overflow: auto; font-size: 13px; }
.fork-copy { background: var(--paper-3); }
"""

INDEX_JS = """
const cards = Array.from(document.querySelectorAll('.card, .node'));
const search = document.getElementById('search');
const filters = Array.from(document.querySelectorAll('button.filter'));
let active = 'all';
function apply() {
  const q = (search.value || '').trim().toLowerCase();
  cards.forEach(card => {
    const domain = card.dataset.domain;
    const haystack = (card.dataset.search || '').toLowerCase();
    const ok = (active === 'all' || domain === active) && (!q || haystack.includes(q));
    card.style.display = ok ? '' : 'none';
  });
  document.querySelectorAll('.step').forEach(section => {
    const shown = Array.from(section.querySelectorAll('.card, .node'))
      .some(el => el.style.display !== 'none');
    section.style.display = shown ? '' : 'none';
  });
}
if (search) search.addEventListener('input', apply);
filters.forEach(button => button.addEventListener('click', () => {
  filters.forEach(item => item.classList.remove('active'));
  button.classList.add('active');
  active = button.dataset.domain;
  apply();
}));
"""


def _e(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _json_for_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


# Маркетинговые эмодзи несовместимы со стилем mokujiro.com: чистим даже старый
# кэш (`meta["longread_body"]`), собранный прежними версиями генератора.
_MARKETING_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D\u20E3\u23F3]"
)


def _strip_marketing_emoji(text: str) -> str:
    """Убирает декоративные смайлики: остаётся строгая типографика."""
    return "\n".join(
        _MARKETING_EMOJI_RE.sub("", line).strip() for line in (text or "").splitlines()
    )


SERVICE_WORKER_JS = """// Science Pulse — офлайн-кэш статики (network-first, cache fallback).
const CACHE = 'science-pulse-v1';
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  let url;
  try { url = new URL(request.url); } catch (error) { return; }
  if (url.origin !== self.location.origin) return;
  event.respondWith(
    caches.open(CACHE).then((cache) =>
      fetch(request).then((response) => {
        if (response && response.ok) cache.put(request, response.clone());
        return response;
      }).catch(() => cache.match(request))
    )
  );
});
"""


DEPTH_JS = """
(function () {
  const buttons = Array.from(document.querySelectorAll('.depth-btn'));
  const sections = Array.from(document.querySelectorAll('.depth'));
  if (!buttons.length || !sections.length) return;
  function show(depth) {
    buttons.forEach((b) => b.classList.toggle('active', b.dataset.depth === depth));
    sections.forEach((s) => s.classList.toggle('visible', depth === 'all' || s.dataset.depth === depth));
  }
  buttons.forEach((b) => b.addEventListener('click', () => show(b.dataset.depth)));
  show('0');
})();
"""


BRANCH_JS = """
(function () {
  const dataEl = document.getElementById('branch-data');
  const panel = document.getElementById('branch-panel');
  if (!dataEl || !panel) return;
  const data = JSON.parse(dataEl.textContent || '{}');
  const posts = data.posts || [];
  const current = data.current || '';
  const key = 'scm_branch_v1';
  function load() { try { return JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch (e) { return {}; } }
  function save(v) { try { localStorage.setItem(key, JSON.stringify(v)); } catch (e) {} }
  function render() {
    const done = load();
    const domains = {math: 'Математика', cs: 'Информатика', physics: 'Физика'};
    const labels = {math: '📐', cs: '💻', physics: '⚛️'};
    let html = '<h2>🌿 Моя ветка освоения науки</h2>';
    Object.keys(domains).forEach(function (domain) {
      const all = posts.filter(function (p) { return p.domain === domain; });
      const got = all.filter(function (p) { return done[p.id]; }).length;
      const pct = all.length ? Math.round(100 * got / Math.max(1, all.length)) : 0;
      html += '<div class="branch-row"><span>' + labels[domain] + ' ' + domains[domain] + '</span>' +
        '<div class="branch-bar ' + domain + '"><span style="width:' + pct + '%"></span></div>' +
        '<span>' + got + ' / ' + all.length + '</span></div>';
    });
    const next = posts.filter(function (p) { return !done[p.id]; }).slice(0, 3);
    if (next.length) {
      html += '<div class="branch-next"><b>Следующие шаги:</b> ' + next.map(function (p) {
        return '<a href="' + (data.prefix || '') + 'post/' + p.id + '.html">§ ' + (p.section || '—') + ' · ' + p.title + '</a>';
      }).join('') + '</div>';
    } else {
      html += '<div class="branch-next">Все доступные параграфы отмечены. Открывайте новые ветки в канале.</div>';
    }
    panel.innerHTML = html;
    const btn = document.getElementById('master-btn');
    if (btn && current) {
      const on = !!done[current];
      btn.classList.toggle('mastered', on);
      btn.textContent = on ? '✓ Параграф освоен' : '✓ Отметить параграф освоенным';
    }
  }
  const btn = document.getElementById('master-btn');
  if (btn && current) {
    btn.addEventListener('click', function () {
      const done = load();
      if (done[current]) delete done[current]; else done[current] = true;
      save(done); render();
    });
  }
  render();
})();
"""

POINCARE_JS = """
(function () {
  const canvas = document.getElementById('poincare');
  if (!canvas || !canvas.getContext) return;
  const ctx = canvas.getContext('2d');
  const out = document.getElementById('poincare-path');
  const W = canvas.width, H = canvas.height;
  const cx = W / 2, cy = H / 2, S = Math.min(W, H) * 0.45;
  const R0 = 9;
  const COLORS = { math: '#1E3A8A', physics: '#9F1239', cs: '#065F46' };
  let data = null, selected = null;
  let centre = { x: 0, y: 0 }, target = { x: 0, y: 0 };
  let dragging = false, dragStart = null;

  const toScreen = (p) => ({ x: cx + p.x * S, y: cy - p.y * S });

  // Автоморфизм Мёбиуса: Φ(z) = (z − z0) / (1 − conj(z0)·z)
  function mobius(z, z0) {
    const nx = z.x - z0.x, ny = z.y - z0.y;
    const dx = 1 - (z0.x * z.x + z0.y * z.y);
    const dy = -(z0.x * z.y - z0.y * z.x);
    const den = dx * dx + dy * dy || 1e-12;
    return { x: (nx * dx + ny * dy) / den, y: (ny * dx - nx * dy) / den };
  }

  function project(point) { return mobius(point, centre); }

  // Геодезическая дуга, ортогональная границе |z| = 1.
  function geodesic(u, v) {
    const D = 2 * (u.x * v.y - u.y * v.x);
    if (Math.abs(D) < 1e-6) {
      const a = toScreen(u), b = toScreen(v);
      ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
      return;
    }
    const U = (1 + u.x * u.x + u.y * u.y) / 2;
    const V = (1 + v.x * v.x + v.y * v.y) / 2;
    const gx = (U * v.y - V * u.y) / D;
    const gy = (u.x * V - v.x * U) / D;
    const radius = Math.sqrt(Math.max(0, gx * gx + gy * gy - 1));
    const cc = toScreen({ x: gx, y: gy });
    const a = toScreen(u), b = toScreen(v);
    const a1 = Math.atan2(a.y - cc.y, a.x - cc.x);
    const a2 = Math.atan2(b.y - cc.y, b.x - cc.x);
    let delta = a2 - a1;
    while (delta > Math.PI) delta -= 2 * Math.PI;
    while (delta < -Math.PI) delta += 2 * Math.PI;
    ctx.arc(cc.x, cc.y, radius * S, a1, a1 + delta, delta < 0);
  }

  function drawSectors() {
    const centres = { math: Math.PI / 2, cs: 7 * Math.PI / 6, physics: 11 * Math.PI / 6 };
    for (const [domain, angle] of Object.entries(centres)) {
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + Math.cos(angle) * S, cy - Math.sin(angle) * S);
      ctx.strokeStyle = COLORS[domain];
      ctx.globalAlpha = 0.18;
      ctx.setLineDash([4, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    }
  }

  function draw() {
    if (!data) return;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#F3F0EA'; ctx.fillRect(0, 0, W, H);
    ctx.strokeStyle = '#D6D1C7'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(cx, cy, S, 0, Math.PI * 2); ctx.stroke();
    drawSectors();

    const projected = {};
    for (const node of data.nodes) projected[node.id] = project(node);
    const pathPairs = new Set();
    const chain = selected ? (data.paths[selected] || []) : [];
    for (let i = 0; i + 1 < chain.length; i++) pathPairs.add(chain[i] + '|' + chain[i + 1]);

    for (const edge of data.edges) {
      const a = edge[0], b = edge[1];
      if (!projected[a] || !projected[b]) continue;
      const onPath = pathPairs.has(a + '|' + b) || pathPairs.has(b + '|' + a);
      ctx.beginPath();
      ctx.strokeStyle = onPath ? '#B45309' : '#C9C3B8';
      ctx.lineWidth = onPath ? 2.4 : 0.8;
      geodesic(projected[a], projected[b]);
      ctx.stroke();
    }

    for (const node of data.nodes) {
      const w = projected[node.id];
      const p = toScreen(w);
      const radius = Math.max(2, R0 * (1 - (w.x * w.x + w.y * w.y)));
      const colour = COLORS[node.domain] || '#111827';
      ctx.beginPath(); ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
      if (node.status === 'published') {
        ctx.fillStyle = colour; ctx.fill();
      } else if (node.status === 'staged') {
        ctx.fillStyle = '#FFFFFF'; ctx.fill();
        ctx.strokeStyle = colour; ctx.lineWidth = 2; ctx.stroke();
      } else {
        ctx.fillStyle = '#FFFFFF'; ctx.fill();
        ctx.strokeStyle = '#C9C3B8'; ctx.lineWidth = 1; ctx.stroke();
      }
      if (node.id === selected) {
        ctx.beginPath(); ctx.arc(p.x, p.y, radius + 4, 0, Math.PI * 2);
        ctx.strokeStyle = '#B45309'; ctx.lineWidth = 2; ctx.stroke();
      }
    }
  }

  function animate() {
    centre.x += (target.x - centre.x) * 0.18;
    centre.y += (target.y - centre.y) * 0.18;
    if (Math.abs(target.x - centre.x) < 1e-4 && Math.abs(target.y - centre.y) < 1e-4) {
      centre = { x: target.x, y: target.y };
    }
    draw();
    requestAnimationFrame(animate);
  }

  function pick(event) {
    const rect = canvas.getBoundingClientRect();
    const mx = (event.clientX - rect.left) * (W / rect.width);
    const my = (event.clientY - rect.top) * (H / rect.height);
    let best = null, bestDistance = 16;
    for (const node of data.nodes) {
      const p = toScreen(project(node));
      const distance = Math.hypot(p.x - mx, p.y - my);
      if (distance < bestDistance) { bestDistance = distance; best = node; }
    }
    return best;
  }

  canvas.addEventListener('click', (event) => {
    const node = pick(event);
    if (!node) return;
    selected = node.id;
    target = { x: node.x, y: node.y };
    const chain = data.paths[node.id] || [];
    const sections = chain
      .map((id) => (data.nodes.find((item) => item.id === id) || {}).section)
      .filter(Boolean);
    if (out) out.textContent = 'Маршрут наименьшего когнитивного сопротивления: § ' + sections.join(' → § ');
  });

  canvas.addEventListener('mousedown', (event) => {
    dragging = true;
    const rect = canvas.getBoundingClientRect();
    dragStart = { x: event.clientX, y: event.clientY, cx: centre.x, cy: centre.y, w: rect.width };
  });
  window.addEventListener('mousemove', (event) => {
    if (!dragging || !dragStart) return;
    const dx = (event.clientX - dragStart.x) / dragStart.w;
    const dy = -(event.clientY - dragStart.y) / dragStart.w;
    target = {
      x: Math.max(-0.95, Math.min(0.95, dragStart.cx + dx * 2.0)),
      y: Math.max(-0.95, Math.min(0.95, dragStart.cy + dy * 2.0)),
    };
  });
  window.addEventListener('mouseup', () => { dragging = false; dragStart = null; });

  fetch('poincare.json').then((response) => response.json()).then((payload) => {
    data = payload;
    animate();
  }).catch(() => {});
})();
"""


SANDBOX_JS = """
(function () {
  const box = document.querySelector('.sandbox');
  if (!box) return;
  const canvas = document.getElementById('sandbox-canvas');
  if (!canvas || !canvas.getContext) return;
  const ctx = canvas.getContext('2d');
  const out = document.getElementById('sandbox-y');
  const domain = box.dataset.sandbox || 'math';
  const userFn = __USER_FN__;
  const aEl = document.getElementById('param-a');
  const bEl = document.getElementById('param-b');
  const xEl = document.getElementById('sandbox-x');
  const va = document.getElementById('val-a');
  const vb = document.getElementById('val-b');
  const W = canvas.width, H = canvas.height, XMIN = -3.2, XMAX = 3.2, YMAX = 1.7;
  const toPx = x => (x - XMIN) / (XMAX - XMIN) * W;
  const toPy = y => H / 2 - (y / YMAX) * (H / 2);
  function f(x, A, k) {
    if (userFn) { try { const v = userFn(x, A, k); if (isFinite(v)) return v; } catch (e) {} }
    if (domain === 'physics') return A * Math.exp(-x * x / 4) * Math.cos(k * x);
    if (domain === 'cs') return A * Math.max(2, x) * Math.log2(Math.max(2, x)) / 12;
    return A * Math.sin(k * x);
  }
  function axes() {
    ctx.fillStyle = '#F3F0EA'; ctx.fillRect(0, 0, W, H);
    ctx.strokeStyle = '#D6D1C7'; ctx.lineWidth = 1;
    for (let gx = -3; gx <= 3; gx++) { ctx.beginPath(); ctx.moveTo(toPx(gx), 0); ctx.lineTo(toPx(gx), H); ctx.stroke(); }
    for (let gy = -1.5; gy <= 1.5; gy += 0.5) { ctx.beginPath(); ctx.moveTo(0, toPy(gy)); ctx.lineTo(W, toPy(gy)); ctx.stroke(); }
    ctx.strokeStyle = '#111827'; ctx.lineWidth = 1.4;
    ctx.beginPath(); ctx.moveTo(0, toPy(0)); ctx.lineTo(W, toPy(0)); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(toPx(0), 0); ctx.lineTo(toPx(0), H); ctx.stroke();
  }
  function curve(fn, color, width) {
    ctx.strokeStyle = color; ctx.lineWidth = width; ctx.beginPath();
    let first = true;
    for (let i = 0; i <= 340; i++) {
      const xv = XMIN + (i / 340) * (XMAX - XMIN);
      const yv = fn(xv);
      if (!isFinite(yv)) { first = true; continue; }
      const px = toPx(xv), py = toPy(yv);
      first ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
      first = false;
    }
    ctx.stroke();
  }
  function draw() {
    const A = parseFloat(aEl.value) || 1, k = parseFloat(bEl.value) || 1;
    const x = parseFloat(xEl.value) || 0;
    axes();
    if (domain === 'cs') curve(n => k * n * n / 40, '#9F1239', 2);
    curve(xv => f(xv, A, k), '#1E3A8A', 2.6);
    const yx = f(x, A, k);
    ctx.fillStyle = '#065F46';
    ctx.beginPath(); ctx.arc(toPx(x), toPy(yx), 5, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = '#9F1239'; ctx.setLineDash([4, 3]); ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.moveTo(toPx(x), toPy(0)); ctx.lineTo(toPx(x), toPy(yx)); ctx.stroke();
    ctx.setLineDash([]);
    if (out) out.textContent = (Math.round(yx * 1000) / 1000).toString();
    if (va) va.textContent = A.toFixed(1);
    if (vb) vb.textContent = k.toFixed(1);
  }
  [aEl, bEl, xEl].forEach(el => { if (el) el.addEventListener('input', draw); });
  draw();

  // Клиентский синтезатор (WebAudio API): озвучивает текущую кривую f(x)
  // прямо в браузере, без скачивания файлов.
  const audioBtn = document.getElementById('sandbox-audio');
  let audioCtx = null, tone = null;
  function stopTone() {
    if (tone) { try { tone.stop(); } catch (error) {} tone = null; }
  }
  function playTone() {
    const Ctor = window.AudioContext || window.webkitAudioContext;
    if (!Ctor) return;
    audioCtx = audioCtx || new Ctor();
    if (audioCtx.state === 'suspended') audioCtx.resume();
    const A = parseFloat(aEl.value) || 1, k = parseFloat(bEl.value) || 1;
    stopTone();
    tone = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    tone.type = domain === 'physics' ? 'sine' : (domain === 'cs' ? 'square' : 'triangle');
    tone.frequency.value = Math.max(60, Math.min(1400, 220 * A * k));
    gain.gain.value = 0.07;
    tone.connect(gain); gain.connect(audioCtx.destination);
    tone.start();
    setTimeout(stopTone, 1200);
  }
  if (audioBtn) audioBtn.addEventListener('click', playTone);

  // Экспорт векторного графика: чистый SVG (для сайта и печати).
  const svgBtn = document.getElementById('sandbox-svg');
  function downloadSvg() {
    const A = parseFloat(aEl.value) || 1, k = parseFloat(bEl.value) || 1;
    const pts = [];
    for (let i = 0; i <= 340; i++) {
      const xv = XMIN + (i / 340) * (XMAX - XMIN);
      const yv = f(xv, A, k);
      if (!isFinite(yv)) continue;
      pts.push([toPx(xv), toPy(yv)]);
    }
    const path = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(2) + ' ' + p[1].toFixed(2)).join(' ');
    const grid = [];
    for (let gx = -3; gx <= 3; gx++) {
      grid.push('<line x1="' + toPx(gx) + '" y1="0" x2="' + toPx(gx) + '" y2="' + H + '" stroke="#D6D1C7"/>');
    }
    for (let gy = -1.5; gy <= 1.5; gy += 0.5) {
      grid.push('<line x1="0" y1="' + toPy(gy) + '" x2="' + W + '" y2="' + toPy(gy) + '" stroke="#D6D1C7"/>');
    }
    const svg = '<?xml version="1.0" encoding="UTF-8"?>'
      + '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + W + ' ' + H + '" width="' + W + '" height="' + H + '">'
      + '<rect width="' + W + '" height="' + H + '" fill="#F3F0EA"/>'
      + grid.join('')
      + '<line x1="0" y1="' + toPy(0) + '" x2="' + W + '" y2="' + toPy(0) + '" stroke="#111827" stroke-width="1.4"/>'
      + '<line x1="' + toPx(0) + '" y1="0" x2="' + toPx(0) + '" y2="' + H + '" stroke="#111827" stroke-width="1.4"/>'
      + '<path d="' + path + '" fill="none" stroke="#1E3A8A" stroke-width="2.6"/>'
      + '</svg>';
    const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'science-pulse-graph.svg';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
  }
  if (svgBtn) svgBtn.addEventListener('click', downloadSvg);

  // Пользовательский форк эксперимента: #fork=a_b_x
  function applyFork() {
    const match = (location.hash || '').match(/^#fork=([0-9.]+)_([0-9.]+)_([0-9.]+)/);
    if (!match) return;
    if (aEl) aEl.value = match[1];
    if (bEl) bEl.value = match[2];
    if (xEl) xEl.value = match[3];
    draw();
  }
  const forkBtn = document.getElementById('sandbox-fork');
  if (forkBtn) forkBtn.addEventListener('click', function () {
    const A = parseFloat(aEl.value) || 1;
    const k = parseFloat(bEl.value) || 1;
    const x = parseFloat(xEl.value) || 0;
    const hash = '#fork=' + A.toFixed(1) + '_' + k.toFixed(1) + '_' + x.toFixed(1);
    history.replaceState(null, '', hash);
    const link = location.href;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(link);
    }
    forkBtn.textContent = '🌿 Ссылка скопирована';
    setTimeout(function () { forkBtn.textContent = '🌿 Скопировать ссылку на мою ветку'; }, 1800);
  });
  applyFork();
})();
"""


class SiteBuilder:
    def __init__(self, config: Config, storage: Storage):
        self.config = config
        self.storage = storage

    def build(self) -> Path:
        dist = self.config.dist_dir
        posts_dir = dist / "post"
        cards_dir = dist / "cards"
        audio_dir = dist / "audio"
        audiogram_dir = dist / "audiogram"
        assets_dir = dist / "assets"
        for directory in (dist, posts_dir, cards_dir, audio_dir, audiogram_dir, assets_dir):
            directory.mkdir(parents=True, exist_ok=True)

        (assets_dir / "style.css").write_text(CSS, encoding="utf-8")
        posts = self.storage.list_posts(status="published", limit=1000, order="published_at DESC")
        # Атлас разворачивает СРАЗУ весь фундаментальный курс: открытые (published)
        # и подготовленные (ready) узлы канона получают полноценные главы.
        programme = [
            post for post in self.storage.list_posts(limit=2000)
            if post.status == "ready" and (post.meta or {}).get("foundation_id")
        ]
        programme.sort(key=lambda item: str((item.meta or {}).get("section_num") or "99"))
        for post in posts:
            self._ensure_card(post)
            self._copy_card(post, cards_dir)
            self._copy_audio(post, audio_dir)
            self._copy_audiogram(post, audiogram_dir)
        for post in programme:
            self._ensure_card(post)
            self._copy_card(post, cards_dir)

        self._write_index(posts, dist)
        for post in posts:
            self._write_post(post, posts, posts_dir)
        for post in programme:
            self._write_post(post, posts + programme, posts_dir)
        # Чистим устаревшие страницы постов (посты, ушедшие из published).
        keep = {f"{post.id}.html" for post in posts} | {f"{post.id}.html" for post in programme}
        for stale in posts_dir.glob("*.html"):
            if stale.name not in keep:
                stale.unlink()
        self._write_search(posts + programme, dist)
        self._write_graph(posts, dist)
        self._write_scientists(posts, dist)
        self._write_constants(posts, dist)
        self._write_topics(posts, dist)
        self._write_syllabus(posts + programme, dist)
        self._write_flashcards(posts, dist)
        if self.config.miniapp_public:
            self._write_miniapp(dist)
        else:
            # Убираем устаревший pult.html от прошлых сборок (приватность).
            stale_pult = dist / "pult.html"
            if stale_pult.exists():
                stale_pult.unlink()
        self._write_sitemap(posts + programme, dist)
        self._write_llms(posts + programme, dist)
        self._write_poincare(posts, dist)
        self._write_bibtex(posts, dist)
        self._write_og_images(posts, dist)
        self._write_legal(dist)
        self._write_radio(posts + programme, dist)
        self._write_pwa(dist)
        (dist / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
        # GitHub Pages из ветки gh-pages: отключаем обработку Jekyll, чтобы
        # отдавались все файлы как есть (важно для статического сайта).
        (dist / ".nojekyll").write_text("", encoding="utf-8")
        return dist

    def _ensure_card(self, post: Post) -> None:
        """Дорисовывает отсутствующую карточку (бессерверная живучесть).

        На чистой виртуальной машине (GitHub Actions) `data/cards/` пуст, и без
        этого шага сайт уезжал бы без картинок: 30 глав канона теряли оформление.
        """
        if not bool((self.config.raw.get("site") or {}).get("render_missing_cards", True)):
            return
        source = self.config.cards_dir / f"{post.id}.png"
        if source.is_file():
            return
        try:
            from .cards import render_card

            render_card(post, out_path=source, engine="auto")
        except Exception as exc:  # pragma: no cover - защита сборки
            LOGGER.warning("Карточка %s не дорисована: %s", post.id, exc)

    def _copy_card(self, post: Post, cards_dir: Path) -> None:
        if (post.meta or {}).get("card_url"):
            return
        raw = post.card_path or post.meta.get("card_path") or ""
        source = Path(raw) if raw else self.config.cards_dir / f"{post.id}.png"
        if not source.exists() and raw:
            source = self.config.cards_dir / f"{post.id}.png"
        if source.is_file():
            destination = cards_dir / f"{post.id}.png"
            if source.resolve() != destination.resolve():
                shutil.copyfile(source, destination)

    def _copy_film(self, post: Post, films_dir: Path) -> str:
        """Копирует 5-актовый фильм Moku3D в `dist/films/` (если он собран)."""
        source = Path(self.config.data_dir) / "films" / f"{post.id}.mp4"
        if not source.is_file():
            return ""
        films_dir.mkdir(parents=True, exist_ok=True)
        destination = films_dir / f"{post.id}.mp4"
        if source.resolve() != destination.resolve():
            shutil.copyfile(source, destination)
        return f"films/{post.id}.mp4"

    def _film_html(self, post: Post, rel: str) -> str:
        """Блок «Фильм Moku3D» на странице параграфа (одно уравнение — один фильм)."""
        if not rel:
            return ""
        return (
            '<section class="depth" data-depth="all">'
            "<h2>Фильм Moku3D</h2>"
            '<video controls preload="metadata" playsinline '
            'style="width:100%;max-width:720px;border:1px solid var(--rule);border-radius:4px" '
            f'src="../{_e(rel)}"></video>'
            '<p class="mono">5 актов · одна строка смысла на акт · геометрия считается уравнением</p>'
            "</section>"
        )

    def _copy_audio(self, post: Post, audio_dir: Path) -> None:
        """Копирует озвучку поста (mp3 + субтитры vtt/srt) в dist/audio/."""
        external = bool((post.meta or {}).get("audio_url"))
        for suffix in (".mp3", ".vtt", ".srt"):
            if external and suffix == ".mp3":
                continue
            source = self.config.data_dir / "audio" / f"{post.id}{suffix}"
            if source.is_file():
                destination = audio_dir / f"{post.id}{suffix}"
                if source.resolve() != destination.resolve():
                    shutil.copyfile(source, destination)

    def _copy_audiogram(self, post: Post, audiogram_dir: Path) -> None:
        """Копирует видео-аудиограмму (data/audiogram/<id>.mp4) в dist/audiogram/."""
        if (post.meta or {}).get("audiogram_url"):
            return
        source = self.config.data_dir / "audiogram" / f"{post.id}.mp4"
        if source.is_file():
            destination = audiogram_dir / f"{post.id}.mp4"
            if source.resolve() != destination.resolve():
                shutil.copyfile(source, destination)

    def _write_pwa(self, dist: Path) -> None:
        """PWA: манифест, service worker и иконки (офлайн-режим сайта)."""
        manifest = {
            "name": self.config.site_title,
            "short_name": "Science Pulse",
            "description": "Детерминированная научная лента: математика, физика, информатика.",
            "lang": "ru",
            "start_url": "./index.html",
            "scope": "./",
            "display": "standalone",
            "background_color": "#07090f",
            "theme_color": "#07090f",
            "icons": [
                {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            ],
        }
        (dist / "manifest.webmanifest").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (dist / "sw.js").write_text(SERVICE_WORKER_JS, encoding="utf-8")
        self._write_icons(dist)

    def _write_icons(self, dist: Path) -> None:
        """Иконки PWA рисуются кодом; без Pillow — молча пропускаем."""
        try:
            from PIL import Image, ImageDraw, ImageFont
        except Exception:
            return
        for size in (192, 512):
            image = Image.new("RGB", (size, size), "#07090f")
            draw = ImageDraw.Draw(image)
            margin = max(8, size // 10)
            draw.rounded_rectangle(
                [margin, margin, size - margin, size - margin],
                radius=size // 6, outline="#00f5d4", width=max(2, size // 40),
            )
            font = None
            for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
                try:
                    font = ImageFont.truetype(name, size // 3)
                    break
                except Exception:
                    continue
            if font is None:
                try:
                    font = ImageFont.load_default(size // 3)
                except Exception:
                    font = ImageFont.load_default()
            try:
                box = draw.textbbox((0, 0), "SP", font=font)
                width, height = box[2] - box[0], box[3] - box[1]
                draw.text(
                    ((size - width) / 2 - box[0], (size - height) / 2 - box[1]),
                    "SP", fill="#00f5d4", font=font,
                )
            except Exception:
                pass
            image.save(dist / f"icon-{size}.png")

    def _write_og_images(self, posts: List[Post], dist: Path) -> None:
        """OG-превью 1200×630: карточка слева, заголовок справа."""
        try:
            from PIL import Image, ImageDraw, ImageFont
        except Exception:
            return
        og_dir = dist / "og"
        og_dir.mkdir(parents=True, exist_ok=True)
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
        try:
            font = ImageFont.truetype(font_path, 52)
            small = ImageFont.truetype(font_path, 26)
        except OSError:
            font = ImageFont.load_default()
            small = font

        probe_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))

        def wrap(value: str, width: int) -> List[str]:
            words, lines, current = value.split(), [], ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if current and probe_draw.textlength(candidate, font=font) > width:
                    lines.append(current)
                    current = word
                else:
                    current = candidate
            if current:
                lines.append(current)
            return lines[:3]

        def compose(card: Path | None, title: str, target: Path) -> None:
            image = Image.new("RGB", (1200, 630), "#FAF8F4")
            draw = ImageDraw.Draw(image)
            draw.rectangle((28, 28, 1172, 602), outline="#111827", width=3)
            if card and card.is_file():
                thumb = Image.open(card).convert("RGB").resize((560, 560), Image.LANCZOS)
                image.paste(thumb, (38, 38))
                text_x = 630
            else:
                text_x = 90
            draw.rectangle((text_x, 70, text_x + 8, 560), fill="#9F1239")
            y = 82
            for line in wrap(title, 500):
                draw.text((text_x + 34, y), line, fill="#111827", font=font)
                y += 64
            draw.text((text_x + 34, 560), "Science Pulse · без LLM", fill="#9F1239", font=small)
            image.save(target, format="JPEG", quality=88, optimize=True)

        for post in posts:
            card = Path(post.card_path) if post.card_path else self.config.cards_dir / f"{post.id}.png"
            if not card.is_file():
                card = self.config.cards_dir / f"{post.id}.png"
            compose(card if card.is_file() else None, post.title, og_dir / f"{post.id}.jpg")
        first = posts[0] if posts else None
        card = None
        if first is not None:
            candidate = Path(first.card_path) if first.card_path else self.config.cards_dir / f"{first.id}.png"
            card = candidate if candidate.is_file() else None
        compose(card, self.config.site_title, og_dir / "index.jpg")

    def _write_bibtex(self, posts: List[Post], dist: Path) -> None:
        """BibTeX-экспорт постов: ``dist/bibtex.bib``."""
        entries: List[str] = []
        for post in posts:
            fields = [
                f"  title = {{{self._bib_escape(post.title)}}}",
                f"  author = {{{self._bib_escape(post.source_name or self.config.site_title)}}}",
            ]
            if post.formula_latex or post.formula_plain:
                fields.append(f"  note = {{{self._bib_escape(post.formula_plain or post.formula_latex)}}}")
            if post.source_url:
                fields.append(f"  howpublished = {{\\url{{{post.source_url}}}}}")
            if post.published_at[:4].isdigit():
                fields.append(f"  year = {{{post.published_at[:4]}}}")
            link = (
                f"{self.config.site_base_url}/post/{post.id}.html"
                if self.config.site_base_url
                else f"post/{post.id}.html"
            )
            fields.append(f"  url = {{{link}}}")
            entries.append("@misc{sciencepulse_%s,\n%s\n}" % (post.id, ",\n".join(fields)))
        header = "% Science Pulse — BibTeX-экспорт\n% Детерминированная научная лента (без LLM)\n\n"
        (dist / "bibtex.bib").write_text(header + "\n\n".join(entries) + "\n", encoding="utf-8")

    @staticmethod
    def _bib_escape(text: str) -> str:
        """Экранирует спецсимволы BibTeX (иначе .bib не соберётся)."""
        return (
            str(text or "")
            .replace("\\", "")
            .replace("{", "(")
            .replace("}", ")")
            .replace("&", "\\&")
            .replace("%", "\\%")
            .replace("_", "\\_")
            .replace("#", "\\#")
            .replace("$", "\\$")
        )

    def _page(self, title: str, content: str, depth: int = 0, extra_head: str = "", og_image: str = "") -> str:
        prefix = "../" * depth
        site_title = _e(self.config.site_title)
        og_tags = ""
        if og_image:
            og_tags = (
                f'<meta property="og:title" content="{_e(title)}">\n'
                f'<meta property="og:description" content="Детерминированная научная лента: математика, физика, информатика.">\n'
                f'<meta property="og:image" content="{_e(og_image)}">\n'
                '<meta name="twitter:card" content="summary_large_image">\n'
            )
        return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)} · {site_title}</title>
<meta name="description" content="Детерминированная научная лента: математика, физика, информатика.">
<meta name="theme-color" content="#FAF8F4">
{og_tags}
<link rel="manifest" href="{prefix}manifest.webmanifest">
<link rel="icon" type="image/png" href="{prefix}icon-192.png">
<link rel="apple-touch-icon" href="{prefix}icon-192.png">
<link rel="alternate" type="application/x-bibtex" href="{prefix}bibtex.bib" title="BibTeX">
<link rel="stylesheet" href="{prefix}assets/style.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"
  onload="renderMathInElement(document.body, {{delimiters: [{{left: '$$', right: '$$', display: true}}, {{left: '\\\\[', right: '\\\\]', display: true}}, {{left: '$', right: '$', display: false}}, {{left: '\\\\(', right: '\\\\)', display: false}}]}});"></script>
{extra_head}
</head>
<body>
<div class="wrap">
<header>
  <div class="brand"><h1><a href="{prefix}index.html" style="color:inherit">{site_title}</a></h1><span>системный атлас точных наук</span></div>
  <div class="stats">{self._stats_html(posts_count=self.storage.count("published"))}</div>
</header>
{content}
<footer>Science Pulse · источники: Stack Exchange, OEIS, Wikipedia, arXiv, Rosetta Code, GitHub raw, Numbers API, SymPy/CODATA. Без LLM в контенте. · <a href="{prefix}privacy.html">Политика конфиденциальности</a> · <a href="{prefix}data-deletion.html">Удаление данных</a></footer>
</div>
<script>if ('serviceWorker' in navigator) {{ window.addEventListener('load', () => navigator.serviceWorker.register('{prefix}sw.js').catch(() => {{}})); }}</script>
<script>{BRANCH_JS}</script>
</body>
</html>"""

    def _stats_html(self, posts_count: int) -> str:
        per_day = len(self.config.schedule) or 3
        return (
            f"<span>постов: {posts_count}</span>"
            f"<span>{len(self.config.domains)} дисциплины</span>"
            f"<span>{per_day} публикации в сутки</span>"
            "<span>0 LLM</span>"
        )

    def _node_card(self, item: Dict[str, Any], post: Optional[Post], staged: str, dist: Path) -> str:
        """Карточка узла канона в матрице ступеней: §, учёный, эпоха, формула, статус."""
        from .sources.foundation import section_of

        section = section_of(item["id"])
        domain = item["domain"]
        is_published = post is not None and post.status == "published"
        if is_published:
            state, stamp = "published", '<span class="stamp ok">Открыто</span>'
        elif item["id"] == staged:
            state, stamp = "staged", '<span class="stamp next">Следующий выпуск</span>'
        else:
            state, stamp = "locked", '<span class="stamp lock">В программе курса</span>'
        image = ""
        if post is not None:
            rel = str((post.meta or {}).get("card_url") or f"cards/{post.id}.png")
            if rel.startswith("http") or (dist / rel).exists():
                image = f'<img src="{_e(rel)}" alt="{_e(item["title"])}" loading="lazy">'
        formula = item.get("formula_latex") or item.get("formula_plain") or ""
        fx = f'<div class="fx">${_e(formula)}$</div>' if formula else ""
        haystack = " ".join(
            [str(item.get("title", "")), str(item.get("hook", "")), str(item.get("scientist", "")),
             str(item.get("body", "")), str(formula), str(DOMAIN_LABELS.get(domain, domain))]
        )
        tag = "a" if is_published else "div"
        href = f' href="post/{post.id}.html"' if is_published else ""
        return (
            f'<{tag} class="node {state}" data-domain="{_e(domain)}" data-search="{_e(haystack)}"{href}>'
            f"{image}"
            '<div class="nbody">'
            f'<span class="sec">§ {section} · {_e(DOMAIN_LABELS.get(domain, domain))}</span>'
            f"{stamp}"
            f'<h3>{_e(item["title"])}</h3>'
            f'<span class="sci">{_e(item.get("scientist", ""))}</span>'
            f'<span class="era">{_e(item.get("era", ""))}</span>'
            f"{fx}"
            "</div>"
            f"</{tag}>"
        )

    def _write_legal(self, dist: Path) -> None:
        """Публичные страницы для Meta Go Live: privacy и data deletion."""
        email = "newmathphys@gmail.com"
        privacy = f"""
<article>
  <div class="badge">PRIVACY</div>
  <h1>Политика конфиденциальности</h1>
  <p class="lead">Science Pulse — статический научный сайт. Мы не создаём аккаунты и не собираем персональные данные на сервере.</p>
  <h2>Что хранится</h2>
  <ul>
    <li>Прогресс чтения («Моя ветка») хранится только в вашем браузере: <code>localStorage["scm_branch_v1"]</code>.</li>
    <li>Сайт размещён на GitHub Pages; GitHub может вести технические журналы по своей политике.</li>
    <li>Публикация в Telegram/Threads выполняется через официальные API этих платформ; их политики применяются отдельно.</li>
  </ul>
  <h2>Чего мы не делаем</h2>
  <ul>
    <li>Не продаём данные.</li>
    <li>Не используем рекламные трекеры.</li>
    <li>Не генерируем контент LLM.</li>
  </ul>
  <h2>Контакты</h2>
  <p>Вопросы: <a href="mailto:{email}">{email}</a> · Telegram: <a href="https://t.me/newmathphys">@newmathphys</a></p>
</article>
"""
        deletion = f"""
<article>
  <div class="badge">DATA DELETION</div>
  <h1>Удаление данных</h1>
  <p class="lead">У Science Pulse нет серверных аккаунтов. Удалить локальный прогресс можно самостоятельно.</p>
  <h2>Локальный прогресс на сайте</h2>
  <ol>
    <li>Откройте сайт Science Pulse.</li>
    <li>Откройте консоль браузера (F12 → Console).</li>
    <li>Выполните: <code>localStorage.removeItem("scm_branch_v1")</code>.</li>
    <li>Обновите страницу.</li>
  </ol>
  <h2>Данные в Telegram/Threads</h2>
  <p>Сообщения и реакции хранятся на стороне платформ. Их можно удалить средствами Telegram или Threads. Для запроса по публикациям Science Pulse напишите на
  <a href="mailto:{email}">{email}</a> или в <a href="https://t.me/newmathphys">@newmathphys</a>; ответ — в течение 30 дней.</p>
  <h2>Что удаляется</h2>
  <ul>
    <li>локальный прогресс веток — сразу, в браузере;</li>
    <li>переписка и запросы — по обращению;</li>
    <li>публичные посты — через инструменты платформы.</li>
  </ul>
</article>
"""
        (dist / "privacy.html").write_text(self._page("Политика конфиденциальности", privacy), encoding="utf-8")
        (dist / "data-deletion.html").write_text(self._page("Удаление данных", deletion), encoding="utf-8")

    def _branch_html(self, posts: List[Post], current: str = "", prefix: str = "") -> str:
        payload = {
            "current": current,
            "prefix": prefix,
            "posts": [
                {
                    "id": post.id,
                    "domain": post.domain,
                    "section": str((post.meta or {}).get("section_num") or ""),
                    "title": post.title,
                }
                for post in posts
            ],
        }
        return (
            '<div id="branch-panel" class="branch-panel"></div>'
            '<script id="branch-data" type="application/json">'
            + _json_for_script(payload)
            + "</script>"
        )

    def _bibtex_entry(self, post: Post) -> str:
        fields = [
            f"  title = {{{self._bib_escape(post.title)}}}",
            f"  author = {{{self._bib_escape(post.source_name or self.config.site_title)}}}",
        ]
        if post.formula_latex or post.formula_plain:
            fields.append(f"  note = {{{self._bib_escape(post.formula_plain or post.formula_latex)}}}")
        if post.source_url:
            fields.append(f"  howpublished = {{\\url{{{post.source_url}}}}}")
        if post.published_at[:4].isdigit():
            fields.append(f"  year = {{{post.published_at[:4]}}}")
        link = f"{self.config.site_base_url}/post/{post.id}.html" if self.config.site_base_url else f"post/{post.id}.html"
        fields.append(f"  url = {{{link}}}")
        return "@misc{sciencepulse_%s,\n%s\n}" % (post.id, ",\n".join(fields))

    def _badges_html(self, post: Post) -> str:
        formula = (post.formula_latex or post.formula_plain or "").strip()
        code = (post.code or "").strip() or "Код для этого параграфа не задан."
        annotation = (post.hook or post.body or "")[:600]
        task = self._challenge_html(post)
        blocks = [
            ("АННОТАЦИЯ", f"<p>{_e(annotation)}</p>"),
            ("LATEX", f"<pre><code>{_e(formula or 'Формула не задана.')}</code></pre>"),
            ("PYTHON", f"<pre><code>{_e(code)}</code></pre>"),
            ("BIBTEX", f"<pre><code>{_e(self._bibtex_entry(post))}</code></pre>"),
            ("ЗАДАЧА", task or "<p>Задача для этого параграфа не задана.</p>"),
        ]
        return '<div class="badges">' + "".join(
            f'<details><summary>[{label}]</summary>{body}</details>' for label, body in blocks
        ) + "</div>"

    def _write_index(self, posts: List[Post], dist: Path) -> None:
        from .sources.foundation import STEP_TITLES, section_of, step_of
        from .sources.history_canon import CANON

        all_posts = self.storage.list_posts(limit=1000)
        by_canon: Dict[str, Post] = {}
        for post in all_posts:
            canon_id = (post.meta or {}).get("foundation_id")
            if canon_id:
                by_canon[canon_id] = post
        published = [cid for cid, post in by_canon.items() if post.status == "published"]
        staged = ""
        for item in sorted(by_canon.values(), key=lambda p: (p.meta or {}).get("section_num", "")):
            if item.status == "ready":
                staged = (item.meta or {}).get("foundation_id", "")
                break

        roman = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X"}
        steps = sorted({step_of(item["id"]) for item in CANON})
        rows: List[str] = []
        for step in steps:
            nodes = sorted([item for item in CANON if step_of(item["id"]) == step], key=section_of)
            cards = "".join(self._node_card(item, by_canon.get(item["id"]), staged, dist) for item in nodes)
            rows.append(
                '<section class="step">'
                f'<div class="step-head"><span class="roman">СТУПЕНЬ {roman.get(step, step)}</span>'
                f'<h2>{_e(STEP_TITLES.get(step, "Дополнительно"))}</h2></div>'
                f'<div class="step-row">{cards}</div></section>'
            )

        filters = ['<button class="filter active" data-domain="all">Все</button>']
        for domain, label in DOMAIN_LABELS.items():
            filters.append(f'<button class="filter" data-domain="{domain}">{label}</button>')

        extra = [post for post in posts if not (post.meta or {}).get("foundation_id")]
        extra_html = ""
        if extra:
            extra_cards = "".join(
                f'<a class="card" data-domain="{_e(post.domain)}" data-search="{_e(" ".join([post.title, post.hook, post.body[:400], post.formula_plain, post.formula_latex, post.source_name]))}" '
                f'href="post/{post.id}.html"><div class="body">'
                f'<span class="badge {_e(post.domain)}">{_e(DOMAIN_LABELS.get(post.domain, post.domain))}</span>'
                f"<h2>{_e(post.title)}</h2><span class=\"meta\">{_e(post.source_name)}</span></div></a>"
                for post in extra[:12]
            )
            extra_html = f'<section class="step"><div class="step-head"><span class="roman">ПРОЧЕЕ</span><h2>Дополнительные разборы</h2></div><div class="step-row">{extra_cards}</div></section>'

        passport = (
            '<div class="passport">'
            f'<span>Открыто фундаментальных узлов: <b>{len(published)} / {len(CANON)}</b></span>'
            f'<span>Ступеней: <b>{len(steps)}</b></span>'
            f'<span>Следующий выпуск: <b>§ {section_of(staged) or "—"}</b></span>'
            f'<span>В очереди: <b>{self.storage.count("ready")}</b></span>'
            "</div>"
        )
        content = f"""
{passport}
{self._branch_html(all_posts)}
<nav class="tabs">
  <a class="active" href="index.html">I. Дерево Фундамента</a>
  <a href="scientists.html">II. Учёные и эпохи</a>
  <a href="constants.html">III. Эталоны СИ (CODATA)</a>
  <a href="syllabus.html">IV. Программа курса</a>
  <a href="flashcards.html">V. Тренажёр памяти</a>
  <a href="radio.html">Радио 24/7</a>
  <a href="llms.txt">V. Машиночитаемый слой</a>
</nav>
{self._poincare_html()}
<div class="toolbar">
  <input id="search" type="search" placeholder="Поиск по формулам, теоремам, учёным…">
  {''.join(filters)}
</div>
{''.join(rows)}
{extra_html}
<p class="meta">Канон: {len(CANON)} узлов · {len(steps)} ступеней · обновляется при каждой публикации.
· <a href="sitemap.xml">sitemap.xml</a> · <a href="search.json">search.json</a> · <a href="bibtex.bib">bibtex.bib</a></p>
<script>{INDEX_JS}</script>
"""
        base = self.config.site_base_url.rstrip("/")
        og_image = f"{base}/og/index.jpg" if base else "og/index.jpg"
        (dist / "index.html").write_text(
            self._page(self.config.site_title, content, depth=0, og_image=og_image), encoding="utf-8"
        )

    def _longread_text(self, post: Post) -> str:
        """Пятичастный лонгрид (`enricher.py`); офлайн-сборка без сети."""
        meta = post.meta or {}
        text = str(meta.get("longread_body") or "")
        if len(text) < 1200:
            try:
                from .enricher import enrich_post_longread

                text = enrich_post_longread(post)
            except Exception:
                text = ""
        return _strip_marketing_emoji(text)

    @staticmethod
    def _split_longread(text: str) -> Dict[str, str]:
        """Делит лонгрид на части по римским заголовкам ``I..V``."""
        parts: Dict[str, str] = {}
        matches = list(re.finditer(r"^(I|II|III|IV|V)\.\s", text or "", re.MULTILINE))
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            parts[match.group(1)] = text[start:end].strip()
        return parts

    def _depth_sections(self, post: Post, blocks: Dict[str, str]) -> List[tuple]:
        """Пять голографических слоёв глубины z = 0…4 (AdS/CFT-развёртка)."""
        parts = self._split_longread(self._longread_text(post))
        return [
            ("0", "z = 0 · Граница / Импульс",
             blocks.get("image", "") + blocks.get("audio", "") + blocks.get("audiogram", "")),
            ("1", "z = 1 · Интуиция и генезис",
             self._paragraphs(parts.get("I", "")) + self._paragraphs(post.body)
             + self._paragraphs(parts.get("V", ""))),
            ("2", "z = 2 · Формализм",
             blocks.get("formula", "") + self._paragraphs(parts.get("II", ""))),
            ("3", "z = 3 · Симуляция",
             self._sparkline_html(post) + blocks.get("sandbox", "") + self._challenge_html(post)
             + blocks.get("code", "") + self._paragraphs(parts.get("III", ""))),
            ("4", "z = 4 · Сертификат истины",
             blocks.get("proof", "") + self._paragraphs(parts.get("IV", ""))),
        ]

    def _sparkline_html(self, post: Post) -> str:
        """Текстовая мини-осциллограмма профиля (Брайль): f(x), иначе сонификация."""
        from .text import braille_sparkline

        expression = (post.formula_plain or post.formula_latex or "").strip()
        label = "Профиль f(x)"
        values: List[float] = []
        if expression:
            try:
                from .plotting import evaluate_curve

                curve = evaluate_curve(expression, x_min=-3.1, x_max=3.1, points=200, include_derivative=False)
                values = [float(value) for value in curve["re_y"]]
            except Exception:
                values = []
        if not values:
            try:
                from .sound import _notes_from_post

                values = [float(note) for note in _notes_from_post(post)]
                label = "Профиль сонификации"
            except Exception:
                return ""
        spark = braille_sparkline(values, width=24)
        return f'<p class="mono">{label}: {spark}</p>' if spark else ""

    def _proof_html(self, post: Post) -> str:
        """Блок «Вычислительный паспорт»: CODATA-расчёт, проверка кода, merkle-печать."""
        proof = (post.meta or {}).get("proof")
        if not isinstance(proof, dict):
            try:
                from .post_proof import build_post_proof

                proof = build_post_proof(post)
            except Exception:
                proof = {}
        if not proof:
            return ""
        rows: List[str] = []
        if proof.get("computed_example"):
            rows.append(f'<li><b>Точный расчёт:</b> <code>{_e(str(proof["computed_example"]))}</code></li>')
        code_proof = proof.get("code_proof") or {}
        if code_proof:
            mark = "верно" if code_proof.get("ok") else "не сходится"
            rows.append(f'<li><b>Код:</b> {mark} {_e(str(code_proof.get("summary", "")))}</li>')
        if proof.get("merkle_hash"):
            rows.append(f'<li><b>Печать (merkle v1):</b> <code>{_e(str(proof["merkle_hash"])[:32])}…</code></li>')
        return "<h2>Вычислительный паспорт</h2><ul>" + "".join(rows) + "</ul>" if rows else ""

    def _write_poincare(self, posts: List[Post], dist: Path) -> None:
        """Данные гиперболического атласа: узлы, рёбра DAG и геодезические маршруты."""
        from .graph import canon_coordinates, canon_edges, find_geodesic_path
        from .sources.foundation import CANON, default_prereqs, section_of, step_of

        nodes = [
            dict(item, tier=step_of(item["id"]), section=section_of(item["id"]),
                 prereq_ids=default_prereqs(item["id"]))
            for item in CANON
        ]
        coords = canon_coordinates(nodes)
        edges = canon_edges(nodes)
        roots = [node["id"] for node in nodes if int(node["tier"]) == 1]

        status: Dict[str, str] = {}
        for post in self.storage.list_posts(limit=1000):
            canon_id = (post.meta or {}).get("foundation_id")
            if canon_id:
                status[canon_id] = post.status
        staged = ""
        for post in sorted(self.storage.list_posts(limit=1000), key=lambda item: (item.meta or {}).get("section_num", "")):
            if post.status == "ready" and (post.meta or {}).get("foundation_id"):
                staged = (post.meta or {})["foundation_id"]
                break

        payload = {
            "nodes": [
                {
                    "id": node["id"],
                    "x": round(coords[node["id"]][0], 6),
                    "y": round(coords[node["id"]][1], 6),
                    "title": node["title"],
                    "section": node["section"],
                    "domain": node["domain"],
                    "tier": node["tier"],
                    "status": (
                        "published" if status.get(node["id"]) == "published"
                        else ("staged" if node["id"] == staged else "locked")
                    ),
                }
                for node in nodes
            ],
            "edges": [[source, target] for source, target in edges],
            "paths": {node["id"]: find_geodesic_path(edges, coords, roots, node["id"]) for node in nodes},
        }
        (dist / "poincare.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _poincare_html(self) -> str:
        """Секция «Гиперболический атлас»: интерактивный диск Пуанкаре на Canvas."""
        return (
            '<section class="atlas">'
            "<h2>Гиперболический атлас (диск Пуанкаре)</h2>"
            '<p class="lead">Каждый узел — точка пространства Лобачевского: радиус задаёт ступень '
            '<span class="mono">r(k) = tanh((k − 0.82)/2.8)</span>, угол — дисциплину '
            '(математика 90°, информатика 210°, физика 330°). '
            "Клик по узлу центрирует диск преобразованием Мёбиуса и подсвечивает геодезический "
            "маршрут от Ступени I; диск можно перетаскивать.</p>"
            '<canvas id="poincare" width="900" height="560"></canvas>'
            '<p class="mono" id="poincare-path">Кликните по узлу, чтобы увидеть маршрут '
            "наименьшего когнитивного сопротивления.</p>"
            f"<script>{POINCARE_JS}</script>"
            "</section>"
        )

    def _sandbox_html(self, post: Post) -> str:
        """Интерактивная лаборатория на Canvas: ползунки A/k и расчёт y(x).

        Использует JS-функцию из безопасного SymPy-парсера (`plotting._js_function`);
        если формула не парсится — безопасный fallback по дисциплине.
        """
        from .plotting import _js_function, parse_expression

        js_fn = "null"
        try:
            expression = (post.formula_plain or post.formula_latex or "").strip()
            if expression:
                js_fn = _js_function(parse_expression(expression))
        except Exception:
            js_fn = "null"
        script = SANDBOX_JS.replace("__USER_FN__", js_fn)
        return (
            f'<section class="sandbox" data-sandbox="{_e(post.domain)}">'
            "<h2>Интерактивная лаборатория</h2>"
            '<canvas id="sandbox-canvas" width="680" height="280"></canvas>'
            '<div class="ctl">'
            '<label>A (масштаб) <input id="param-a" type="range" min="0.2" max="3.0" step="0.1" value="1.0"> <span id="val-a">1.0</span></label>'
            '<label>k (частота) <input id="param-b" type="range" min="0.5" max="4.0" step="0.1" value="1.0"> <span id="val-b">1.0</span></label>'
            '<label>x <input id="sandbox-x" type="number" value="1.0" step="0.1"></label>'
            '<span>y(x) = <output id="sandbox-y">—</output></span>'
            '<button id="sandbox-audio" class="mini-action" type="button">Услышать частоту формулы</button>'
            '<button id="sandbox-svg" class="mini-action" type="button">Экспорт графика в SVG</button>'
            '<button id="sandbox-fork" class="mini-action fork-copy" type="button">🌿 Скопировать ссылку на мою ветку</button>'
            "</div>"
            f"<script>{script}</script>"
            "</section>"
        )

    def _challenge_html(self, post: Post) -> str:
        """Просветительская задача для самопроверки (с раскрытием ответа)."""
        from .challenge import build_challenge, challenge_reveal

        challenge = (post.meta or {}).get("challenge")
        if not isinstance(challenge, dict) or not challenge.get("question"):
            try:
                challenge = build_challenge(post)
            except Exception:
                return ""
        question = str(challenge.get("question") or "").strip()
        if not question:
            return ""
        hint = str(challenge.get("hint") or "").strip()
        hint_html = f"<p><i>Подсказка: {_e(hint)}</i></p>" if hint else ""
        return (
            '<details class="flash"><summary>Просветительская задача для самопроверки</summary>'
            f"<p><b>{_e(question)}</b></p>{hint_html}"
            f"<p>{_e(challenge_reveal(challenge))}</p></details>"
        )

    def _lineage_html(self, post: Post) -> str:
        """Родословная первоисточников: первоисточник → свод → цифровой узел."""
        from .enricher import build_source_lineage

        lineage = (post.meta or {}).get("source_lineage")
        if not isinstance(lineage, dict):
            try:
                lineage = build_source_lineage(post)
            except Exception:
                lineage = {}
        if not lineage:
            return ""
        digital = lineage.get("digital_source") or {}
        rows = [
            f'<li><b>Первоисточник:</b> {_e(str(lineage.get("primary_work") or ""))}</li>',
            f'<li><b>Академический свод:</b> {_e(str(lineage.get("canonical_archive") or ""))}</li>',
        ]
        url = str(digital.get("url") or "")
        name = str(digital.get("name") or "")
        if name or url:
            link = f'<a href="{_e(url)}" rel="noopener">{_e(name or url)}</a>' if url else _e(name)
            rows.append(f"<li><b>Цифровой узел:</b> {link}</li>")
        refs = lineage.get("references") or []
        if refs:
            rows.append(
                "<li><b>Библиография:</b> "
                + "; ".join(_e(str(item)) for item in refs[:3])
                + "</li>"
            )
        return "<h2>Родословная первоисточников</h2><ul>" + "".join(rows) + "</ul>"

    @staticmethod
    def _formula_legend(post: Post) -> str:
        """Детерминированная расшифровка букв формулы без LLM."""
        meta = post.meta or {}
        explicit = str(meta.get("formula_vars") or "").strip()
        if explicit:
            return _e(explicit)
        common = {
            "n": "размер входа (число элементов)",
            "N": "размер входа (число элементов)",
            "T": "время / число операций",
            "O": "асимптотическая оценка роста",
            "x": "координата / переменная",
            "t": "время",
            "k": "коэффициент / волновое число",
        }
        by_domain = {
            "cs": {
                "A": "первое логическое высказывание (0 или 1)",
                "B": "второе логическое высказывание (0 или 1)",
                "h": "хеш-функция",
                "d": "расстояние / глубина",
            },
            "physics": {
                "G": "гравитационная постоянная",
                "m": "масса тела",
                "r": "расстояние между центрами",
                "F": "сила",
                "E": "энергия",
                "p": "давление",
                "ρ": "плотность",
                "c": "скорость света",
                "h": "постоянная Планка",
                "ℏ": "постоянная Дирака",
                "B": "магнитная индукция",
                "S": "энтропия / действие",
            },
            "math": {
                "A": "логическое или матричное выражение",
                "B": "логическое или матричное выражение",
                "S": "сумма / энтропия",
            },
        }
        known = dict(common)
        known.update(by_domain.get(str(post.domain or ""), {}))
        formula = str(post.formula_plain or post.formula_latex or "")
        formula = re.sub(r"\\[a-zA-Z]+", " ", formula)
        formula = re.sub(r"\b(?:sin|cos|tan|log|ln|exp|lim|max|min|mod|det|sup|inf)\b",
                         " ", formula, flags=re.IGNORECASE)
        seen: List[str] = []
        for token in re.findall(r"[A-Za-zА-Яа-яЁёℏρ]", formula):
            if token in known and token not in seen:
                seen.append(token)
        if not seen:
            return "Формула разобрана в тексте параграфа."
        return "; ".join(f"<b>{_e(token)}</b> — {_e(known[token])}" for token in seen[:8])

    def _anatomy_html(self, post: Post) -> str:
        """«Как читать закон»: суть, буквы, практика, чертёж."""
        meta = post.meta or {}
        formula = str(post.formula_plain or post.formula_latex or "").strip()
        if not formula and not meta.get("formula_vars"):
            return ""
        body = re.sub(r"\s+", " ", str(post.body or "")).strip()
        first = body.split(". ")[0][:220] + ("." if body else "")
        application = str(meta.get("modern_application") or "").strip()
        visual = {
            "standard_plot": "плавная кривая и точка на ней",
            "code_booktabs": "листинг алгоритма и шаги исполнения",
            "diptych_insar": "2D-поле слева и 1D-разрез справа",
            "cheatsheet_table": "таблица инвариантов и формул",
            "timeline_evolution": "шкала времени и вехи идеи",
        }.get(str(meta.get("visual_type") or ""), "книжный чертёж с подписями")
        rows = [
            ("Суть в одном предложении", _e(first) if first else "Смотрите формулу и численный пример ниже."),
            ("Что означает каждая буква", f'<span class="legend">{self._formula_legend(post)}</span>'),
            ("Зачем это нужно", _e(application) if application else "Применение разобрано в тексте и паспорте."),
            ("Как читать чертёж", _e(visual)),
        ]
        items = "".join(f"<li><b>{label}.</b> {value}</li>" for label, value in rows)
        return f'<section class="anatomy"><h2>Как это работает · путеводитель по главе</h2><ol>{items}</ol></section>'

    def _write_post(self, post: Post, all_posts: List[Post], posts_dir: Path) -> None:
        related = self._related(post, all_posts)
        related_html = "".join(
            f'<li><a href="{item.id}.html">{_e(item.title)}</a></li>' for item in related
        )
        image_path = str((post.meta or {}).get("card_url") or f"../cards/{post.id}.png")
        image_html = (
            f'<img class="article-card" src="{_e(image_path)}" alt="{_e(post.title)}">'
            if image_path.startswith("http") or (self.config.dist_dir / "cards" / f"{post.id}.png").exists()
            else ""
        )
        formula = post.formula_latex or post.formula_plain
        formula_html = f'<div class="formula">\\[ {_e(formula)} \\]</div>' if formula else ""
        code_html = f"<h2>Код</h2><pre><code>{_e(post.code)}</code></pre>" if post.code else ""
        audio_url = str((post.meta or {}).get("audio_url") or "")
        audio_file = self.config.dist_dir / "audio" / f"{post.id}.mp3"
        if not audio_url and audio_file.exists():
            audio_url = f"../audio/{post.id}.mp3"
        subtitle_track = (
            f'<track kind="subtitles" srclang="ru" label="Русский" '
            f'src="../audio/{post.id}.vtt" default>'
            if (self.config.dist_dir / "audio" / f"{post.id}.vtt").exists()
            else ""
        )
        audio_html = (
            f'<h2>Слушать</h2><audio controls preload="none" src="{_e(audio_url)}" '
            f'style="width:100%">{subtitle_track}</audio>'
            if audio_url
            else ""
        )
        audiogram_url = str((post.meta or {}).get("audiogram_url") or "")
        audiogram_file = self.config.dist_dir / "audiogram" / f"{post.id}.mp4"
        if not audiogram_url and audiogram_file.exists():
            audiogram_url = f"../audiogram/{post.id}.mp4"
        audiogram_html = (
            f'<h2>Видео-разбор</h2><video controls preload="none" playsinline '
            f'poster="{_e(image_path)}" src="{_e(audiogram_url)}" '
            'style="width:100%;max-width:520px"></video>'
            if audiogram_url
            else ""
        )
        source_html = (
            f'<p>Первоисточник: <a href="{_e(post.source_url)}" rel="noopener">{_e(post.source_url)}</a></p>'
            if post.source_url
            else ""
        )
        tags = "".join(f"<span>{_e(word)}</span>" for word in keywords(post.title + " " + post.body, 8))
        used_posts = []
        canon_id = (post.meta or {}).get("canon_id")
        if canon_id:
            for other in all_posts:
                if other.id != post.id and canon_id in ((other.meta or {}).get("prereq_ids") or []):
                    used_posts.append(other)
        used_in_html = "".join(
            f'<li><a href="{item.id}.html">{_e(item.title)}</a></li>' for item in used_posts
        )
        prereq_html = ""
        links = (post.meta or {}).get("prereq_links") or []
        if links:
            prereq_html = "<h2>Опирается на фундамент</h2><ul>" + "".join(
                f'<li><a href="{_e(str(url))}" rel="noopener">{_e(str(name))}</a></li>' for name, url in links
            ) + "</ul>"
        sandbox_html = self._sandbox_html(post)
        proof_html = self._proof_html(post)
        lineage_html = self._lineage_html(post)
        status_html = (
            ""
            if post.status == "published"
            else '<p class="stamp next">Параграф развёрнут полностью и выйдет в ближайшем '
                 "слоте эфира (09:00 · 13:00 · 17:00 · 21:00 MSK).</p>"
        )
        depth_nav = ""
        depth_html = ""
        depth_sections = self._depth_sections(post, {
            "image": image_html, "audio": audio_html, "audiogram": audiogram_html,
            "formula": formula_html, "sandbox": sandbox_html, "code": code_html, "proof": proof_html,
        })
        depth_nav = '<div class="depth-nav">' + "".join(
            f'<button class="depth-btn" data-depth="{key}">{label}</button>' for key, label, _ in depth_sections
        ) + '<button class="depth-btn" data-depth="all">Все слои</button></div>'
        depth_html = "".join(
            f'<section class="depth" data-depth="{key}"><h2>{label}</h2>{body}</section>'
            for key, label, body in depth_sections
        )
        sandbox_html = self._sandbox_html(post)
        film_html = self._film_html(post, self._copy_film(post, posts_dir.parent / "films"))
        meta_pass = post.meta or {}
        section = str(meta_pass.get("section_num") or "").strip()
        step = meta_pass.get("step")
        step_title = str(meta_pass.get("step_title") or "").strip()
        spec_rows: List[str] = []

        def _spec(label: str, value: str) -> None:
            if value:
                spec_rows.append(f"<li><b>{label}</b><span>{value}</span></li>")

        paragraph = " · ".join(part for part in (
            f"§ {_e(section)}" if section else "",
            f"Ступень {_e(str(step))}" if step else "",
            _e(step_title),
        ) if part)
        _spec("ПАРАГРАФ", paragraph)
        _spec("ДИСЦИПЛИНА", _e(DOMAIN_LABELS.get(post.domain, post.domain)))
        author = " · ".join(part for part in (
            _e(str(meta_pass.get("scientist") or "")),
            _e(str(meta_pass.get("era") or "")),
        ) if part)
        _spec("АВТОР / ЭПОХА", author)
        _spec("ПЕРВОИСТОЧНИК", _e(str(post.source_name or meta_pass.get("source_name") or "")))
        formula_value = str(meta_pass.get("formula_plain") or post.formula_plain or post.formula_latex or "")
        _spec("ИНВАРИАНТ", f"<code>{_e(formula_value)}</code>" if formula_value else "")
        proof = meta_pass.get("proof") if isinstance(meta_pass.get("proof"), dict) else {}
        _spec("ВЕРИФИКАЦИЯ", _e(str((proof or {}).get("computed_example") or "")))
        links = " · ".join(
            f'<a href="{_e(str(url))}">{_e(str(name))}</a>'
            for name, url in (meta_pass.get("prereq_links") or [])[:3]
        )
        _spec("СВЯЗИ", ("← " + links) if links else "")
        passport_html = (
            '<h2>Паспорт параграфа</h2><ul class="spec">' + "".join(spec_rows) + "</ul>" + prereq_html
        )
        content = f"""
<article>
  <a href="../index.html">← ко всем разборам</a>
  <p class="meta"><a href="../radio.html">Слушать этот параграф в эфире Science Pulse FM</a>
  · <a href="../podcast.xml">подкаст (RSS)</a></p>
  <div class="journal">
    <aside class="side">{passport_html}</aside>
    <div class="main">
      <div class="badge {_e(post.domain)}">{_e(DOMAIN_LABELS.get(post.domain, post.domain))}</div>
      <h1>{_e(post.title)}</h1>
      <p class="lead">{_e(post.hook)}</p>
      <button id="master-btn" class="mini-action" data-post-id="{_e(post.id)}" type="button">✓ Отметить параграф освоенным</button>
      {self._badges_html(post)}
      {status_html}
      {depth_nav}
      {self._anatomy_html(post)}
      {film_html}
      {depth_html}
    </div>
    <aside class="side">
      {self._branch_html(self.storage.list_posts(limit=1000), current=post.id, prefix="../")}
      {proof_html}
      {lineage_html}
      <div class="tags">{tags}</div>
      {source_html}
      <p style="color:var(--ink-2)">Источник: {_e(post.source_name)} · {_e(post.tier)} · качество {post.quality:.2f}</p>
      {f'<h2>Используется в новых темах</h2><ul>{used_in_html}</ul>' if used_in_html else ''}
      {f'<h2>Связанные разборы</h2><ul>{related_html}</ul>' if related_html else ''}
    </aside>
  </div>
</article>
<script>{DEPTH_JS}</script>
"""
        base = self.config.site_base_url.rstrip("/")
        og_image = f"{base}/og/{post.id}.jpg" if base else f"../og/{post.id}.jpg"
        (posts_dir / f"{post.id}.html").write_text(
            self._page(post.title, content, depth=1, og_image=og_image), encoding="utf-8"
        )

    @staticmethod
    def _paragraphs(text: str) -> str:
        blocks = [block.strip() for block in re.split(r"\n\s*\n", text or "") if block.strip()]
        if not blocks:
            return "<p></p>"
        return "".join(f"<p>{_e(block).replace(chr(10), '<br>')}</p>" for block in blocks)

    @staticmethod
    def _related(post: Post, all_posts: List[Post]) -> List[Post]:
        post_words = set(keywords(post.title + " " + post.body, 12))
        scored: List[tuple[int, Post]] = []
        for other in all_posts:
            if other.id == post.id:
                continue
            other_words = set(keywords(other.title + " " + other.body, 12))
            score = len(post_words & other_words)
            if score:
                scored.append((score, other))
        scored.sort(key=lambda item: (-item[0], item[1].title))
        return [item for _, item in scored[:5]]

    def _write_radio(self, posts: List[Post], dist: Path) -> None:
        """Веб-радиостанция 24/7 и подкаст-фид (`radio.py`)."""
        try:
            from .radio import write_radio

            write_radio(dist, posts, self.config)
        except Exception as exc:  # pragma: no cover - радио не должно ронять сборку
            LOGGER.warning("Радио не собрано: %s", exc)

    def _write_search(self, posts: List[Post], dist: Path) -> None:
        data = [
            {
                "id": post.id,
                "title": post.title,
                "domain": post.domain,
                "hook": post.hook,
                "body": truncate(post.body, 600),
                "formula": post.formula_latex or post.formula_plain,
                "url": f"post/{post.id}.html",
            }
            for post in posts
        ]
        (dist / "search.json").write_text(_json_for_script(data), encoding="utf-8")

    @staticmethod
    def _graph_data(
        posts: List[Post],
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, float], Dict[str, tuple[float, float]]]:
        """Единый расчёт графа: узлы с PageRank и координатами Пуанкаре, рёбра, ранги."""
        ids = [post.id for post in posts]
        links = build_links(posts)
        rank = pagerank(ids, links)
        layout = poincare_layout(ids, {post.id: post.domain for post in posts}, rank)
        nodes: List[Dict[str, Any]] = []
        for post in posts:
            x, y = layout.get(post.id, (0.0, 0.0))
            nodes.append(
                {
                    "id": post.id,
                    "title": truncate(post.title, 80),
                    "domain": post.domain,
                    "value": 1 + len(post.body) // 300,
                    "pagerank": round(rank.get(post.id, 0.0), 9),
                    "x": x,
                    "y": y,
                }
            )
        return nodes, links, rank, layout

    def _write_graph(self, posts: List[Post], dist: Path) -> None:
        nodes, links, _rank, _layout = self._graph_data(posts)
        (dist / "graph.json").write_text(
            _json_for_script({"nodes": nodes, "links": links}),
            encoding="utf-8",
        )

    def _write_miniapp(self, dist: Path) -> None:
        """Статический «Пульт» (Mini App): снимок состояния + кнопки команд.

        Кнопки шлют POST {command} на `CF_WORKER_URL/telegram-webhook`, если
        Worker настроен; секреты живут в Worker'е и в страницу не попадают.
        """
        worker = self.config.cf_worker_url
        endpoint = f"{worker}/telegram-webhook" if worker else ""
        counts = self.storage.queue_counts()
        queue_line = " · ".join(f"{key}={value}" for key, value in counts.items()) or "пусто"
        platforms = " ".join(
            f"{name}={'готово' if self.config.platform_enabled(name) else 'нет'}"
            for name in ("telegram", "threads", "bluesky", "discord", "mastodon", "vk")
        )
        sources_line = " · ".join(
            f"{row['name']}{' (OPEN)' if self.storage.source_is_open(str(row['name'])) else ''}"
            for row in self.storage.source_states()
        ) or "нет данных"
        actions = [
            ("run", "Опубликовать сейчас"),
            ("harvest", "Добрать материалы"),
            ("site", "Пересобрать сайт"),
            ("status", "Статус"),
        ]
        buttons = "".join(
            f'<button class="mini-action" data-command="{cmd}"{" disabled" if not endpoint else ""}>{_e(label)}</button>'
            for cmd, label in actions
        )
        hint = (
            f'<p class="mini-log">Endpoint: {_e(endpoint)}</p>'
            if endpoint
            else '<p class="mini-log">CF_WORKER_URL не задан — кнопки отключены. '
            "Настройте Cloudflare Worker (см. docs/PLATFORMS.md) и пересоберите сайт.</p>"
        )
        from .platforms_info import LABELS, PLATFORMS

        platforms_payload = [
            {"emoji": data["emoji"], "env": data["env"], "ru": data["ru"], "en": data["en"]}
            for data in PLATFORMS.values()
        ]
        about_ru = [
            "Пульт читает команды из getUpdates (long polling) — кнопки не нужны, команды не протухают.",
            "Mini App — эта страница (pult.html); кнопки шлют POST на Cloudflare Worker.",
            "Состояние: data/science.db (SQLite, WAL); карточки: data/cards/*.png; сайт: dist/.",
            "Секреты — только в .env / GitHub Secrets / Cloudflare Secrets.",
            "Edge-реплика (опционально): Cloudflare D1 через cli state --push/--sync.",
        ]
        about_en = [
            "The pult reads commands via getUpdates (long polling) — no buttons, commands do not expire.",
            "Mini App — this page (pult.html); buttons POST to the Cloudflare Worker.",
            "State: data/science.db (SQLite, WAL); cards: data/cards/*.png; site: dist/.",
            "Secrets live only in .env / GitHub Secrets / Cloudflare Secrets.",
            "Edge replica (optional): Cloudflare D1 via cli state --push/--sync.",
        ]
        about_html = (
            '<div class="panel-box" data-about="ru">'
            + "".join(f"<p>{_e(line)}</p>" for line in about_ru)
            + "</div>"
            '<div class="panel-box" data-about="en" style="display:none">'
            + "".join(f"<p>{_e(line)}</p>" for line in about_en)
            + "</div>"
        )
        content = f"""
<article>
  <div class="badge">ПУЛЬТ · MINI APP</div>
  <h1>Пульт Science Pulse</h1>
  <p class="lead">Публичный снимок состояния и кнопки команд. Токены остаются в Cloudflare Worker.</p>
  <div class="panel-box">
    <p>Очередь: {_e(queue_line)}</p>
    <p>Опубликовано: {self.storage.count('published')} · Ошибок: {self.storage.count('failed')}</p>
    <p>Площадки: {_e(platforms)}</p>
    <p>Источники: {_e(sources_line)}</p>
  </div>
  <div class="mini-actions">{buttons}</div>
  {hint}
  <pre class="mini-log" id="mini-out">Готов.</pre>
  <h2>Площадки / Platforms</h2>
  <div class="mini-actions">
    <button class="mini-action" data-lang="ru">Русский</button>
    <button class="mini-action" data-lang="en">English</button>
  </div>
  <div id="platforms"></div>
  <h2>Как это работает / How it works</h2>
  {about_html}
</article>
<script>
const endpoint = {_json_for_script(endpoint)};
const platforms = {_json_for_script(platforms_payload)};
const labels = {_json_for_script(LABELS)};
let lang = 'ru';
function esc(value) {{
  return String(value == null ? '' : value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}}
function renderPlatforms() {{
  const box = document.getElementById('platforms');
  if (!box) return;
  const L = labels[lang] || labels.ru;
  box.innerHTML = platforms.map(platform => {{
    const t = platform[lang] || platform.ru;
    return '<div class="panel-box"><b>' + platform.emoji + ' ' + esc(t.title) + '</b>'
      + '<p class="mini-log"><b>' + esc(L.what) + ':</b> ' + esc(t.what) + '</p>'
      + '<p class="mini-log"><b>' + esc(L.limits) + ':</b> ' + esc(t.limits) + '</p>'
      + '<p class="mini-log"><b>' + esc(L.image) + ':</b> ' + esc(t.image) + '</p>'
      + '<p class="mini-log"><b>' + esc(L.metrics) + ':</b> ' + esc(t.metrics) + '</p>'
      + '<p class="mini-log"><b>' + esc(L.notes) + ':</b> ' + esc(t.notes) + '</p>'
      + '<p class="mini-log"><b>' + esc(L.env) + ':</b> ' + esc(platform.env.join(', ')) + '</p></div>';
  }}).join('');
  document.querySelectorAll('[data-about]').forEach(el => {{ el.style.display = el.dataset.about === lang ? '' : 'none'; }});
}}
document.querySelectorAll('.mini-action[data-lang]').forEach(button => {{
  button.addEventListener('click', () => {{ lang = button.dataset.lang; renderPlatforms(); }});
}});
document.querySelectorAll('.mini-action[data-command]').forEach(button => {{
  button.addEventListener('click', async () => {{
    const out = document.getElementById('mini-out');
    if (!endpoint) {{ out.textContent = 'Endpoint не задан.'; return; }}
    const command = button.dataset.command;
    out.textContent = 'Отправляю: ' + command + '…';
    try {{
      const response = await fetch(endpoint, {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ command }})
      }});
      out.textContent = command + ': HTTP ' + response.status;
    }} catch (error) {{
      out.textContent = command + ': ' + error;
    }}
  }});
}});
renderPlatforms();
</script>
"""
        (dist / "pult.html").write_text(self._page("Пульт", content, depth=0), encoding="utf-8")

    @staticmethod
    def _slug(text: str) -> str:
        slug = re.sub(r"[^0-9a-zа-яё]+", "-", str(text or "").lower()).strip("-")
        return slug[:60] or "x"

    def _write_scientists(self, posts: List[Post], dist: Path) -> None:
        """Досье учёных: эпоха, «применение сегодня» и все связанные посты."""
        dossiers: Dict[str, Dict[str, Any]] = {}
        for post in posts:
            meta = post.meta or {}
            scientist = str(meta.get("scientist") or "").strip()
            if not scientist:
                continue
            entry = dossiers.setdefault(
                scientist, {"era": str(meta.get("era") or ""), "posts": [], "applications": []}
            )
            entry["posts"].append(post)
            application = str(meta.get("modern_application") or "").strip()
            if application and application not in entry["applications"]:
                entry["applications"].append(application)
        items: List[str] = []
        for scientist in sorted(dossiers):
            entry = dossiers[scientist]
            links = "".join(
                f'<li><a href="post/{post.id}.html">{_e(post.title)}</a></li>' for post in entry["posts"]
            )
            apps = " · ".join(_e(app) for app in entry["applications"])
            items.append(
                '<div class="card" style="display:block"><div class="body">'
                f'<span class="badge">{_e(entry["era"] or "эпоха")}</span>'
                f"<h2>{_e(scientist)}</h2>"
                + (f"<p>Применение сегодня: {apps}</p>" if apps else "")
                + f"<ul>{links}</ul></div></div>"
            )
        content = (
            '<article><a href="index.html">← ко всем разборам</a>'
            "<h1>Досье учёных</h1>"
            '<p class="lead">Каждый узел канона привязан к учёному и эпохе: кто открыл, '
            "какая формула осталась и где это работает сегодня.</p>"
            f'<div class="grid">{"".join(items) or "<p>Пока нет постов с учёными.</p>"}</div></article>'
        )
        (dist / "scientists.html").write_text(self._page("Досье учёных", content), encoding="utf-8")

    def _write_constants(self, posts: List[Post], dist: Path) -> None:
        """Словарь-указатель фундаментальных констант (CODATA) со ссылками на посты."""
        from .constants import CONSTANTS, constants_used_by, format_value

        usage = constants_used_by(posts)
        rows: List[str] = []
        for item in CONSTANTS:
            used = usage.get(item["symbol"], [])
            links = " ".join(
                f'<a href="post/{post.id}.html">{_e(post.title[:42])}</a>' for post in used[:6]
            )
            rows.append(
                f"<tr><td><b>{_e(item['tex'])}</b></td><td>{_e(item['name'])}</td>"
                f"<td><code>{_e(format_value(item['value']))}</code></td><td>{_e(item['unit'])}</td>"
                f"<td>{links or '—'}</td></tr>"
            )
        content = (
            '<article><a href="index.html">← ко всем разборам</a>'
            "<h1>Словарь физических величин</h1>"
            '<p class="lead">Реестр фундаментальных констант (CODATA, СИ) из <code>scipy.constants</code>: '
            "точные значения и все посты, где константа применяется.</p>"
            '<div class="formula" style="overflow-x:auto"><table style="width:100%;border-collapse:collapse">'
            '<tr style="text-align:left"><th>Символ</th><th>Величина</th><th>Значение</th><th>Единица</th><th>Где встречается</th></tr>'
            f"{''.join(rows)}</table></div></article>"
        )
        (dist / "constants.html").write_text(self._page("Словарь констант", content), encoding="utf-8")

    def _write_topics(self, posts: List[Post], dist: Path) -> None:
        """Авто-хабы тем и «маршруты изучения»: концепции канона + общие ключевые слова."""
        from .text import keywords

        hubs: Dict[str, List[Post]] = {}
        for post in posts:
            concept = str((post.meta or {}).get("concept") or "").strip()
            if concept:
                hubs.setdefault(concept, []).append(post)
        counts: Dict[str, List[Post]] = {}
        for post in posts:
            for word in keywords(f"{post.title} {post.hook}", 6):
                key = word.lower()
                members = counts.setdefault(key, [])
                if post not in members:
                    members.append(post)
        for word, members in sorted(counts.items()):
            if len(members) >= 2 and word not in hubs and len(hubs) < 14:
                hubs[word] = members
        blocks: List[str] = []
        for topic in sorted(hubs):
            members = sorted(hubs[topic], key=lambda post: post.created_at)
            route = "".join(
                f'<li><a href="post/{post.id}.html">{_e(post.title)}</a></li>' for post in members[:8]
            )
            blocks.append(
                f'<div class="card" style="display:block"><div class="body">'
                f'<h2>{_e(topic)}</h2><p class="meta">маршрут изучения · {len(members)} постов</p>'
                f"<ol>{route}</ol></div></div>"
            )
        content = (
            '<article><a href="index.html">← ко всем разборам</a>'
            "<h1>Темы и маршруты изучения</h1>"
            '<p class="lead">Если два и более постов объединены общей концепцией или тегом, '
            "сайт автоматически собирает тематический маршрут: читайте по порядку от основ к применениям.</p>"
            f'<div class="grid">{"".join(blocks) or "<p>Темы появятся после публикаций.</p>"}</div></article>'
        )
        (dist / "topics.html").write_text(self._page("Темы и маршруты", content), encoding="utf-8")

    def _write_syllabus(self, posts: List[Post], dist: Path) -> None:
        """Бесконечная программа: 45 ветвей и 135 тем университетского курса."""
        from .syllabus_tree import BRANCHES, syllabus_summary, syllabus_topics

        summary = syllabus_summary()
        topics = syllabus_topics()
        by_section = {str((p.meta or {}).get("section_num") or ""): p for p in posts}
        domains = {"math": "📐 Математика", "physics": "⚛️ Физика", "cs": "💻 Информатика"}
        blocks: List[str] = []
        for domain, label in domains.items():
            branches = [b for b in BRANCHES if b["domain"] == domain]
            rows: List[str] = []
            for branch in branches:
                items = [t for t in topics if t["branch_id"] == branch["id"]]
                done = sum(1 for t in items if by_section.get(t["section_num"]))
                links = "".join(
                    f'<li>§ {_e(t["section_num"])} · {_e(t["title"])}'
                    + (f' · <a href="post/{by_section[t["section_num"]].id}.html">открыть</a>' if by_section.get(t["section_num"]) else ' · <span class="meta">в программе</span>')
                    + "</li>"
                    for t in items
                )
                rows.append(
                    f'<details class="flash"><summary>{_e(branch["title"])} · {done}/{len(items)}</summary><ul>{links}</ul></details>'
                )
            blocks.append(
                f'<section class="step"><div class="step-head"><span class="roman">{label}</span>'
                f'<h2>{len(branches)} ветвей · {sum(len(b["topics"]) for b in branches)} тем</h2></div>'
                + "".join(rows) + "</section>"
            )
        content = f"""
<article>
  <div class="badge">ПРОГРАММА КУРСА</div>
  <h1>Бесконечный поток науки</h1>
  <p class="lead">30 узлов канона — семя. Дальше — {summary['branches']} ветвей и {summary['topics']} тем:
  § {summary['first_section']} … § {summary['last_section']}. Очередь пополняется автоматически.</p>
  <div class="passport">
    <span>Ветвей: <b>{summary['branches']}</b></span>
    <span>Тем: <b>{summary['topics']}</b></span>
    <span>В очереди: <b>{self.storage.count('ready')}</b></span>
    <span>Опубликовано: <b>{self.storage.count('published')}</b></span>
  </div>
  {''.join(blocks)}
</article>
"""
        (dist / "syllabus.html").write_text(self._page("Программа курса", content), encoding="utf-8")

    def _write_flashcards(self, posts: List[Post], dist: Path) -> None:
        """Страница карточек-повторений (flashcards): вопрос → ответ."""
        cards: List[str] = []
        for post in posts:
            question = post.hook or f"Что описывает формула {post.formula_plain}?"
            formula = post.formula_latex or post.formula_plain
            formula_html = f"<p><code>{_e(formula)}</code></p>" if formula else ""
            cards.append(
                f"""<details class="flash">
  <summary>{_e(question)}</summary>
  <p><b>{_e(post.title)}</b> <span class="meta">{_e(DOMAIN_LABELS.get(post.domain, post.domain))}</span></p>
  {formula_html}
  <p>{_e(truncate(post.body, 320))}</p>
  <p><a href="post/{post.id}.html">Полный разбор →</a></p>
</details>"""
            )
        content = (
            '<article><div class="badge">ФЛЕШКАРТЫ</div>'
            "<h1>Карточки для повторения</h1>"
            f'<p class="lead">Вопрос → ответ по {len(posts)} разборам. '
            "Нажмите на карточку, чтобы увидеть ответ.</p>"
            + ("".join(cards) if cards else '<p class="empty">Пока нет опубликованных постов.</p>')
            + '<p><a href="index.html">← ко всем разборам</a></p></article>'
        )
        (dist / "flashcards.html").write_text(self._page("Флешкарты", content), encoding="utf-8")

    def _write_sitemap(self, posts: List[Post], dist: Path) -> None:
        base = self.config.site_base_url or "https://science-pulse.local"
        urls = [f"{base}/", f"{base}/index.html", f"{base}/scientists.html",
                f"{base}/constants.html", f"{base}/topics.html", f"{base}/syllabus.html",
                f"{base}/radio.html", f"{base}/podcast.xml"]
        for post in posts:
            urls.append(f"{base}/post/{post.id}.html")
        body = "".join(f"<url><loc>{_e(url)}</loc></url>" for url in urls)
        (dist / "sitemap.xml").write_text(
            f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
            encoding="utf-8",
        )

    def _write_llms(self, posts: List[Post], dist: Path) -> None:
        base = self.config.site_base_url or "https://science-pulse.local"
        lines = [
            f"# {self.config.site_title}",
            "",
            "Детерминированная научная лента: математика, физика, информатика.",
            "Источники: Stack Exchange, OEIS, Wikipedia, arXiv, Rosetta Code, GitHub raw, Numbers API, SymPy/CODATA.",
            "",
            "## Posts",
        ]
        for post in posts:
            lines.append(f"- [{post.title}]({base}/post/{post.id}.html) — {post.domain}")
        (dist / "llms.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

        full = [f"# {self.config.site_title}", ""]
        for post in posts:
            full.extend(
                [
                    f"## {post.title}",
                    f"URL: {base}/post/{post.id}.html",
                    f"Domain: {post.domain}",
                    f"Formula: {post.formula_latex or post.formula_plain}",
                    "",
                    post.body,
                    "",
                ]
            )
        (dist / "llms-full.txt").write_text("\n".join(full), encoding="utf-8")
