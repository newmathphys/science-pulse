from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List

from .config import Config
from .graph import build_links, pagerank, poincare_layout, top_by_pagerank
from .models import DOMAIN_LABELS, Post
from .storage import Storage
from .text import keywords, truncate

CSS = """
:root {
  --bg: #07090f;
  --panel: #101622;
  --panel-2: #161d2b;
  --text: #ecf2ff;
  --muted: #8a94a6;
  --accent: #00f5d4;
  --pink: #ff007f;
  --yellow: #fee440;
  --border: #222834;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: radial-gradient(circle at 20% 0%, #101a2c 0%, var(--bg) 45%);
  color: var(--text); font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  line-height: 1.55;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.wrap { width: min(1180px, calc(100% - 32px)); margin: 0 auto; }
header { padding: 28px 0 18px; border-bottom: 1px solid var(--border); }
.brand { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.brand h1 { margin: 0; font-size: clamp(24px, 4vw, 40px); letter-spacing: -0.02em; }
.brand span { color: var(--accent); font-family: ui-monospace, monospace; font-size: 12px; }
.stats { display: flex; gap: 18px; flex-wrap: wrap; color: var(--muted); font-size: 14px; margin-top: 10px; }
.toolbar { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin: 20px 0; }
input[type=search] {
  flex: 1 1 260px; background: var(--panel); border: 1px solid var(--border);
  color: var(--text); border-radius: 12px; padding: 12px 14px; font-size: 15px;
}
button.filter {
  background: var(--panel); border: 1px solid var(--border); color: var(--muted);
  padding: 10px 14px; border-radius: 999px; cursor: pointer; font-size: 14px;
}
button.filter.active { color: #071018; background: var(--accent); border-color: var(--accent); font-weight: 700; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; padding-bottom: 40px; }
.card {
  background: linear-gradient(160deg, var(--panel), #0b1019); border: 1px solid var(--border);
  border-radius: 18px; overflow: hidden; display: flex; flex-direction: column;
  transition: transform .18s ease, border-color .18s ease;
}
.card:hover { transform: translateY(-3px); border-color: #34405a; }
.card img { width: 100%; aspect-ratio: 1/1; object-fit: cover; background: #0b1019; }
.card .body { padding: 14px 16px 18px; display: flex; flex-direction: column; gap: 8px; flex: 1; }
.card h2 { font-size: 18px; line-height: 1.3; margin: 0; }
.card p { margin: 0; color: var(--muted); font-size: 14px; }
.badge { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--accent); }
.badge.physics { color: var(--pink); }
.badge.cs { color: var(--yellow); }
.meta { color: var(--muted); font-size: 12px; margin-top: auto; }
article { padding: 32px 0 60px; }
article h1 { font-size: clamp(26px, 5vw, 46px); line-height: 1.15; margin: 8px 0 14px; }
.lead { color: var(--muted); font-size: 18px; }
.formula {
  background: var(--panel); border: 1px solid var(--accent); border-radius: 14px;
  padding: 18px; margin: 22px 0; overflow-x: auto;
}
pre {
  background: #0b1019; border: 1px solid var(--border); border-radius: 14px;
  padding: 16px; overflow-x: auto; color: #d7e2ff; font-size: 13px;
}
.article-card { width: min(560px, 100%); border-radius: 18px; border: 1px solid var(--border); }
.article-body { font-size: 17px; max-width: 820px; }
.article-body p { margin: 0 0 14px; }
.tags { display: flex; gap: 8px; flex-wrap: wrap; margin: 14px 0 24px; }
.tags span { border: 1px solid var(--border); color: var(--muted); border-radius: 999px; padding: 4px 10px; font-size: 12px; }
footer { border-top: 1px solid var(--border); color: var(--muted); padding: 22px 0 40px; font-size: 13px; }
#graph { width: 100%; height: 460px; border: 1px solid var(--border); border-radius: 18px; background: #0b1019; }
.two { display: grid; grid-template-columns: 1.1fr .9fr; gap: 20px; align-items: start; }
@media (max-width: 820px) { .two { grid-template-columns: 1fr; } }
.empty { color: var(--muted); padding: 40px 0; }
.mini-actions { display: flex; gap: 10px; flex-wrap: wrap; margin: 18px 0; }
.mini-action {
  background: var(--panel); border: 1px solid var(--accent); color: var(--accent);
  border-radius: 12px; padding: 12px 16px; cursor: pointer; font-size: 15px; font-weight: 600;
}
.mini-action:disabled { opacity: .5; cursor: not-allowed; border-color: var(--border); color: var(--muted); }
.mini-log { font-family: ui-monospace, monospace; color: var(--muted); font-size: 13px; white-space: pre-wrap; }
.panel-box { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 16px 18px; margin: 14px 0; }
"""

INDEX_JS = """
const cards = Array.from(document.querySelectorAll('.card'));
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
}
search.addEventListener('input', apply);
filters.forEach(button => button.addEventListener('click', () => {
  filters.forEach(item => item.classList.remove('active'));
  button.classList.add('active');
  active = button.dataset.domain;
  apply();
}));
async function drawGraph() {
  const container = document.getElementById('graph');
  if (!container || !window.vis) return;
  try {
    const response = await fetch('graph.json');
    const data = await response.json();
    const SCALE = 320;
    const ranks = data.nodes.map(node => node.pagerank || 0);
    const maxRank = Math.max(...ranks, 1e-9);
    const nodes = new vis.DataSet(data.nodes.map(node => ({
      id: node.id, label: node.title, group: node.domain, title: node.title,
      value: node.value || 1,
      x: (node.x || 0) * SCALE, y: (node.y || 0) * SCALE,
      size: 8 + 26 * Math.sqrt((node.pagerank || 0) / maxRank)
    })));
    const edges = new vis.DataSet(data.links.map(link => ({ from: link.source, to: link.target, value: link.weight || 1 })));
    new vis.Network(container, { nodes, edges }, {
      nodes: { shape: 'dot', font: { color: '#ecf2ff', size: 11 } },
      edges: { color: { color: '#2b3650', highlight: '#00f5d4' }, smooth: true },
      groups: { math: { color: '#00f5d4' }, physics: { color: '#ff007f' }, cs: { color: '#fee440' } },
      physics: false,
      interaction: { hover: true, dragNodes: false, zoomView: true }
    });
  } catch (error) { console.warn('graph', error); }
}
drawGraph();
"""


def _e(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _json_for_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


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
        for post in posts:
            self._copy_card(post, cards_dir)
            self._copy_audio(post, audio_dir)
            self._copy_audiogram(post, audiogram_dir)

        self._write_index(posts, dist)
        for post in posts:
            self._write_post(post, posts, posts_dir)
        self._write_search(posts, dist)
        self._write_graph(posts, dist)
        self._write_scientists(posts, dist)
        self._write_constants(posts, dist)
        self._write_topics(posts, dist)
        self._write_miniapp(dist)
        self._write_sitemap(posts, dist)
        self._write_llms(posts, dist)
        (dist / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
        # GitHub Pages из ветки gh-pages: отключаем обработку Jekyll, чтобы
        # отдавались все файлы как есть (важно для статического сайта).
        (dist / ".nojekyll").write_text("", encoding="utf-8")
        return dist

    def _copy_card(self, post: Post, cards_dir: Path) -> None:
        raw = post.card_path or post.meta.get("card_path") or ""
        source = Path(raw) if raw else self.config.cards_dir / f"{post.id}.png"
        if not source.exists() and raw:
            source = self.config.cards_dir / f"{post.id}.png"
        if source.is_file():
            destination = cards_dir / f"{post.id}.png"
            if source.resolve() != destination.resolve():
                shutil.copyfile(source, destination)

    def _copy_audio(self, post: Post, audio_dir: Path) -> None:
        """Копирует озвучку поста (mp3 + субтитры vtt/srt) в dist/audio/."""
        for suffix in (".mp3", ".vtt", ".srt"):
            source = self.config.data_dir / "audio" / f"{post.id}{suffix}"
            if source.is_file():
                destination = audio_dir / f"{post.id}{suffix}"
                if source.resolve() != destination.resolve():
                    shutil.copyfile(source, destination)

    def _copy_audiogram(self, post: Post, audiogram_dir: Path) -> None:
        """Копирует видео-аудиограмму (data/audiogram/<id>.mp4) в dist/audiogram/."""
        source = self.config.data_dir / "audiogram" / f"{post.id}.mp4"
        if source.is_file():
            destination = audiogram_dir / f"{post.id}.mp4"
            if source.resolve() != destination.resolve():
                shutil.copyfile(source, destination)

    def _page(self, title: str, content: str, depth: int = 0, extra_head: str = "") -> str:
        prefix = "../" * depth
        site_title = _e(self.config.site_title)
        return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)} · {site_title}</title>
<meta name="description" content="Детерминированная научная лента: математика, физика, информатика.">
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
  <div class="brand"><h1><a href="{prefix}index.html" style="color:inherit">{site_title}</a></h1><span>deterministic science feed</span></div>
  <div class="stats">{self._stats_html(posts_count=self.storage.count("published"))}</div>
</header>
{content}
<footer>Science Pulse · источники: Stack Exchange, OEIS, Wikipedia, arXiv, Rosetta Code, GitHub raw, Numbers API, SymPy/CODATA. Без LLM в контенте.</footer>
</div>
</body>
</html>"""

    @staticmethod
    def _stats_html(posts_count: int) -> str:
        return (
            f"<span>постов: {posts_count}</span>"
            "<span>3 дисциплины</span>"
            "<span>3 публикации в сутки</span>"
            "<span>0 LLM</span>"
        )

    def _write_index(self, posts: List[Post], dist: Path) -> None:
        cards: List[str] = []
        for post in posts:
            image = f"cards/{post.id}.png"
            image_html = f'<img src="{image}" alt="{_e(post.title)}" loading="lazy">' if (dist / image).exists() else ""
            haystack = " ".join([post.title, post.hook, post.body, post.formula_plain, post.source_name])
            cards.append(
                f"""<a class="card" data-domain="{_e(post.domain)}" data-search="{_e(haystack)}" href="post/{post.id}.html">
{image_html}
<div class="body">
  <span class="badge {_e(post.domain)}">{post.emoji} {_e(DOMAIN_LABELS.get(post.domain, post.domain))}</span>
  <h2>{_e(post.title)}</h2>
  <p>{_e(truncate(post.hook or post.body, 150))}</p>
  <span class="meta">{_e(post.source_name)}</span>
</div>
</a>"""
            )
        filters = ['<button class="filter active" data-domain="all">Все</button>']
        for domain, label in DOMAIN_LABELS.items():
            filters.append(f'<button class="filter" data-domain="{domain}">{label}</button>')
        _nodes, _links, rank, _layout = self._graph_data(posts)
        by_id = {post.id: post for post in posts}
        top_ids = top_by_pagerank([post.id for post in posts], rank, 5)
        top_items = "".join(
            f'<li><a href="post/{pid}.html">{_e(by_id[pid].title)}</a> '
            f'<span style="color:var(--muted)">· {rank.get(pid, 0.0) * 1000:.1f}‰</span></li>'
            for pid in top_ids
            if pid in by_id
        )
        graph_html = (
            '<div class="two"><div id="graph"></div><div>'
            '<h2 style="margin-top:0">Граф знаний</h2>'
            '<p style="color:var(--muted)">Каждый пост — узел. Связи строятся по общим научным понятиям; '
            'чем выше PageRank, тем крупнее узел и ближе к центру диска Пуанкаре. Граф обновляется при каждой публикации.</p>'
            + (
                f'<h3 style="margin:0 0 6px">Топ по PageRank</h3>'
                f'<ol style="margin:0 0 12px;padding-left:20px">{top_items}</ol>'
                if top_items
                else ""
            )
            + '<p><a href="scientists.html">Досье учёных</a> · <a href="constants.html">Словарь констант</a> · '
            '<a href="topics.html">Темы и маршруты</a> · <a href="llms.txt">llms.txt</a> · '
            '<a href="sitemap.xml">sitemap.xml</a> · <a href="search.json">search.json</a> · <a href="pult.html">Пульт</a></p>'
            '</div></div>'
        )
        content = f"""
<div class="toolbar">
  <input id="search" type="search" placeholder="Поиск по формулам, теоремам, авторам…">
  {''.join(filters)}
</div>
{graph_html}
<h2>Последние разборы</h2>
<div class="grid">{''.join(cards) if cards else '<p class="empty">Пока нет опубликованных постов. Запустите <code>python -m science_pulse.cli publish --dry-run</code>.</p>'}</div>
<script src="https://cdn.jsdelivr.net/npm/vis-network@9.1.9/dist/vis-network.min.js"></script>
<script>{INDEX_JS}</script>
"""
        (dist / "index.html").write_text(self._page(self.config.site_title, content, depth=0), encoding="utf-8")

    def _write_post(self, post: Post, all_posts: List[Post], posts_dir: Path) -> None:
        related = self._related(post, all_posts)
        related_html = "".join(
            f'<li><a href="{item.id}.html">{_e(item.title)}</a></li>' for item in related
        )
        image_path = f"../cards/{post.id}.png"
        image_html = (
            f'<img class="article-card" src="{image_path}" alt="{_e(post.title)}">'
            if (self.config.dist_dir / "cards" / f"{post.id}.png").exists()
            else ""
        )
        formula = post.formula_latex or post.formula_plain
        formula_html = f'<div class="formula">\\[ {_e(formula)} \\]</div>' if formula else ""
        code_html = f"<h2>Код</h2><pre><code>{_e(post.code)}</code></pre>" if post.code else ""
        audio_file = self.config.dist_dir / "audio" / f"{post.id}.mp3"
        subtitle_track = (
            f'<track kind="subtitles" srclang="ru" label="Русский" '
            f'src="../audio/{post.id}.vtt" default>'
            if (self.config.dist_dir / "audio" / f"{post.id}.vtt").exists()
            else ""
        )
        audio_html = (
            f'<h2>Слушать</h2><audio controls preload="none" src="../audio/{post.id}.mp3" '
            f'style="width:100%">{subtitle_track}</audio>'
            if audio_file.exists()
            else ""
        )
        audiogram_file = self.config.dist_dir / "audiogram" / f"{post.id}.mp4"
        audiogram_html = (
            f'<h2>Видео-разбор</h2><video controls preload="none" playsinline '
            f'poster="../cards/{post.id}.png" src="../audiogram/{post.id}.mp4" '
            'style="width:100%;max-width:520px"></video>'
            if audiogram_file.exists()
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
        content = f"""
<article>
  <a href="../index.html">← ко всем разборам</a>
  <div class="badge {_e(post.domain)}">{post.emoji} {_e(DOMAIN_LABELS.get(post.domain, post.domain))}</div>
  <h1>{_e(post.title)}</h1>
  <p class="lead">{_e(post.hook)}</p>
  {image_html}
  {formula_html}
  {audio_html}
  {audiogram_html}
  <div class="article-body">{self._paragraphs(post.body)}</div>
  {code_html}
  <div class="tags">{tags}</div>
  {source_html}
  <p style="color:var(--muted)">Источник: {_e(post.source_name)} · {_e(post.tier)} · качество {post.quality:.2f}</p>
  {prereq_html}
  {f'<h2>Используется в новых темах</h2><ul>{used_in_html}</ul>' if used_in_html else ''}
  {f'<h2>Связанные разборы</h2><ul>{related_html}</ul>' if related_html else ''}
</article>
"""
        (posts_dir / f"{post.id}.html").write_text(self._page(post.title, content, depth=1), encoding="utf-8")

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
            f"{name}={'✓' if self.config.platform_enabled(name) else '—'}"
            for name in ("telegram", "threads", "bluesky", "discord", "mastodon", "vk")
        )
        sources_line = " · ".join(
            f"{row['name']}{' (OPEN)' if self.storage.source_is_open(str(row['name'])) else ''}"
            for row in self.storage.source_states()
        ) or "нет данных"
        actions = [
            ("run", "▶️ Опубликовать сейчас"),
            ("harvest", "🛰 Добрать материалы"),
            ("site", "🪐 Пересобрать сайт"),
            ("status", "📊 Статус"),
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
  <div class="badge">🎛 ПУЛЬТ · MINI APP</div>
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
    <button class="mini-action" data-lang="ru">🇷🇺 Русский</button>
    <button class="mini-action" data-lang="en">🇬🇧 English</button>
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

    def _write_sitemap(self, posts: List[Post], dist: Path) -> None:
        base = self.config.site_base_url or "https://science-pulse.local"
        urls = [f"{base}/", f"{base}/index.html", f"{base}/scientists.html",
                f"{base}/constants.html", f"{base}/topics.html"]
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
