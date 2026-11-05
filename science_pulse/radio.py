"""Научное радио «Science Pulse FM» — детерминированный эфир без сервера.

Четыре контура (все — бесплатно и без LLM):

1. **`dist/radio.html`** — бессерверная веб-радиостанция: генеративный
   математический эмбиент на `WebAudio API` (пифагорейский строй), ротация
   лекций диктора с музыкальными паузами, `navigator.mediaSession` (эфир
   продолжается на заблокированном экране смартфона), анализатор спектра
   (`AnalyserNode`) на Canvas.
2. **`dist/podcast.xml`** — валидный RSS 2.0 подкаст-фид (`itunes:*`,
   `enclosure`) для подписки в Apple Podcasts / Яндекс.Музыке.
3. **`dist/radio_mix.mp4` + `dist/radio_chapters.txt`** — сквозной
   радио-микс из видео-аудиограмм опубликованных параграфов (ffmpeg) с
   гармоническими интерлюдиями и оглавлением таймкодов.
4. **`rtmp_argv()`** — команда круглосуточного вещания в Telegram Live /
   YouTube Live (`ffmpeg -re -stream_loop -1 … -f flv`).

Синхронизация эфира идёт по «часам Вселенной»: `epoch_slot_index()`
(`(now − epoch) // 6 ч`), поэтому плеер на любом устройстве мгновенно
попадает на тот же такт расписания, что и остальные слушатели.
"""
from __future__ import annotations

import html
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .config import Config
from .models import DOMAIN_LABELS, Post
from .sota import EPOCH_START_UTC, SLOT_SECONDS, epoch_slot_index

LOGGER = logging.getLogger(__name__)

RADIO_TITLE = "Science Pulse FM"
RADIO_TAGLINE = "Академическое радио · 24/7 · без LLM"
PAUSE_SECONDS = 5.0
AMBIENT_CHORD_HZ = (220.0, 330.0, 440.0)
DEFAULT_MIX_SECONDS = 5.0

# ---------------------------------------------------------------------------
# Эфирная сетка: порядок и метаданные выпусков
# ---------------------------------------------------------------------------


def section_key(post: Post) -> tuple:
    """Ключ сортировки эфира: ``§ X.Y`` (по возрастанию), затем дата выхода."""
    section = str((post.meta or {}).get("section_num") or "")
    head, _, tail = section.partition(".")
    try:
        return (int(head), int(tail or 0))
    except ValueError:
        return (99, 99)


def _entry_notes(post: Post) -> List[float]:
    """Частоты аккорда выпуска: гармонический спектр формулы (детерминированно)."""
    try:
        from .sound import _notes_from_post

        notes = [float(value) for value in _notes_from_post(post)]
    except Exception:
        notes = []
    return notes[:4] or list(AMBIENT_CHORD_HZ)


def _lecture_script(post: Post, max_chars: int = 900) -> str:
    """5-блочный лекционный сценарий диктора (см. `voice.build_lecture_script`)."""
    try:
        from .voice import build_lecture_script

        return build_lecture_script(post, max_chars)
    except Exception:
        return " ".join(part for part in (post.title, post.hook, post.body) if part).strip()


def episode_entry(post: Post, base_url: str, audio_dir: Path, status: str = "published") -> Dict[str, Any]:
    """Метаданные одного выпуска эфира (используются и сайтом, и подкастом)."""
    meta = post.meta or {}
    section = str(meta.get("section_num") or "").strip()
    audio = f"audio/{post.id}.mp3"
    has_audio = (Path(audio_dir) / f"{post.id}.mp3").is_file()
    return {
        "id": post.id,
        "section": section,
        "title": post.title,
        "label": f"§ {section} • {post.title}" if section else post.title,
        "domain": post.domain,
        "domain_label": DOMAIN_LABELS.get(post.domain, post.domain),
        "scientist": str(meta.get("scientist") or ""),
        "era": str(meta.get("era") or ""),
        "formula": post.formula_latex or post.formula_plain or "",
        "formula_plain": post.formula_plain or "",
        "hook": post.hook,
        "script": _lecture_script(post),
        "notes": _entry_notes(post),
        "audio": audio if has_audio else "",
        "card": f"cards/{post.id}.png",
        "page": f"post/{post.id}.html",
        "url": f"{base_url}/post/{post.id}.html" if base_url else f"post/{post.id}.html",
        "status": status,
    }


def radio_playlist(posts: Sequence[Post], config: Config) -> List[Dict[str, Any]]:
    """Эфирная сетка: опубликованные параграфы, затем подготовленные (N+1)."""
    base_url = (config.site_base_url or "").rstrip("/")
    audio_dir = config.data_dir / "audio"
    published = sorted(
        [post for post in posts if post.status == "published"],
        key=lambda post: (section_key(post), post.published_at or ""),
    )
    prepared = sorted(
        [
            post for post in posts
            if post.status == "ready" and (post.meta or {}).get("foundation_id")
        ],
        key=section_key,
    )
    return [
        episode_entry(post, base_url, audio_dir, status=post.status)
        for post in list(published) + list(prepared)
    ]


def current_slot(now: Optional[float] = None) -> int:
    """Текущий такт эфира по «часам Вселенной» (номер слота от начала эпохи)."""
    return epoch_slot_index(now)


def slot_entry(playlist: Sequence[Dict[str, Any]], now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Какой выпуск идёт в эфире прямо сейчас (по глобальному такту)."""
    if not playlist:
        return None
    return playlist[current_slot(now) % len(playlist)]


# ---------------------------------------------------------------------------
# Контур 2: подкаст-фид RSS 2.0
# ---------------------------------------------------------------------------


def _rfc822(stamp: str) -> str:
    """ISO-8601 → RFC-822 (формат `pubDate` в RSS)."""
    from datetime import datetime, timezone
    from email.utils import format_datetime

    try:
        moment = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        moment = datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return format_datetime(moment)


def build_podcast_xml(entries: Sequence[Dict[str, Any]], config: Config) -> str:
    """RSS 2.0 подкаст-фид с тегами `itunes` и `enclosure` (audio/mpeg)."""
    base = (config.site_base_url or "").rstrip("/") or "https://science-pulse.local"
    items: List[str] = []
    for entry in entries:
        if not entry.get("audio"):
            continue
        hook = html.escape(str(entry.get("hook") or ""))
        items.append(
            "<item>"
            f"<title>{html.escape(str(entry['label']))}</title>"
            f"<link>{html.escape(str(entry['url']))}</link>"
            f'<guid isPermaLink="false">science-pulse:{html.escape(str(entry["id"]))}</guid>'
            f"<description>{hook}</description>"
            f"<itunes:author>{html.escape(str(entry.get('scientist') or RADIO_TITLE))}</itunes:author>"
            f"<itunes:summary>{hook}</itunes:summary>"
            f'<enclosure url="{html.escape(base + "/" + str(entry["audio"]))}" '
            'type="audio/mpeg" length="0"/>'
            "</item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" '
        'xmlns:atom="http://www.w3.org/2005/Atom">'
        "<channel>"
        f"<title>{html.escape(RADIO_TITLE)}</title>"
        f"<link>{html.escape(base)}/radio.html</link>"
        f"<description>{html.escape(RADIO_TAGLINE)}</description>"
        "<language>ru</language>"
        f'<atom:link href="{html.escape(base)}/podcast.xml" rel="self" type="application/rss+xml"/>'
        "<itunes:author>Science Pulse</itunes:author>"
        '<itunes:category text="Science"/>'
        "<itunes:explicit>false</itunes:explicit>"
        f'<itunes:image href="{html.escape(base)}/icon-512.png"/>'
        f"{''.join(items)}"
        "</channel></rss>"
    )


# ---------------------------------------------------------------------------
# Контур 3: сквозной радио-микс и RTMP-вещание
# ---------------------------------------------------------------------------


def _duration_seconds(path: Path) -> float:
    """Длительность медиафайла через ffprobe (0.0, если определить не удалось)."""
    probe = shutil.which("ffprobe")
    if not probe or not Path(path).is_file():
        return 0.0
    try:
        out = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        return float((out.stdout or "0").strip() or 0.0)
    except Exception:
        return 0.0


def mix_plan(posts: Sequence[Post], data_dir: Path, pause: float = PAUSE_SECONDS) -> Dict[str, Any]:
    """План эфирного микса: выпуски с аудиограммой + интерлюдии + таймкоды."""
    audiogram_dir = Path(data_dir) / "audiogram"
    chapters: List[Dict[str, Any]] = []
    cursor = 0.0
    for post in sorted([item for item in posts if item.status == "published"], key=section_key):
        media = audiogram_dir / f"{post.id}.mp4"
        if not media.is_file():
            continue
        seconds = _duration_seconds(media)
        chapters.append({
            "id": post.id,
            "label": f"§ {str((post.meta or {}).get('section_num') or '')} {post.title}".strip(),
            "path": str(media),
            "start": cursor,
            "seconds": seconds,
        })
        cursor += seconds + pause
    return {"chapters": chapters, "total_seconds": cursor, "pause": pause}


def write_chapters(plan: Dict[str, Any], out_path: Path) -> Optional[Path]:
    """Файл оглавления для YouTube: ``00:00 § 1.1 Пифагор``."""
    chapters = plan.get("chapters") or []
    if not chapters:
        return None
    lines = []
    for chapter in chapters:
        total = int(chapter["start"])
        lines.append(f"{total // 60:02d}:{total % 60:02d} {chapter['label']}")
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return Path(out_path)


def _interlude_argv(path: Path, seconds: float, frequency: float) -> List[str]:
    """Гармоническая интерлюдия: книжный фон + чистая синусоида (пифагорейский строй)."""
    return [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"color=c=0xFAF8F4:s=1080x1080:d={seconds:.2f}",
        "-f", "lavfi", "-i", f"sine=frequency={frequency:.2f}:duration={seconds:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(path),
    ]


def build_radio_mix(posts: Sequence[Post], data_dir: Path, out_path: Path,
                    chapters_path: Optional[Path] = None) -> Optional[Path]:
    """Склеивает выпуски и интерлюдии в единый радио-микс (нужен ffmpeg)."""
    if not shutil.which("ffmpeg"):
        LOGGER.warning("Радио-микс пропущен: ffmpeg не найден")
        return None
    plan = mix_plan(posts, data_dir)
    chapters = plan["chapters"]
    if not chapters:
        LOGGER.info("Радио-микс пропущен: нет видео-аудиограмм")
        return None
    out_path = Path(out_path)
    parts_dir = Path(data_dir) / "radio_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    pieces: List[Path] = []
    for index, chapter in enumerate(chapters):
        pieces.append(Path(str(chapter["path"])))
        interlude = parts_dir / f"interlude_{index:03d}.mp4"
        result = subprocess.run(
            _interlude_argv(interlude, float(plan["pause"]), AMBIENT_CHORD_HZ[index % len(AMBIENT_CHORD_HZ)]),
            capture_output=True, text=True, timeout=300, check=False,
        )
        if result.returncode == 0 and interlude.is_file():
            pieces.append(interlude)
    listing = parts_dir / "concat.txt"
    listing.write_text(
        "\n".join(f"file '{piece.as_posix()}'" for piece in pieces) + "\n", encoding="utf-8"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-movflags", "+faststart", str(out_path)],
        capture_output=True, text=True, timeout=3600, check=False,
    )
    if result.returncode != 0 or not out_path.is_file():
        LOGGER.warning("Радио-микс не собран: %s", (result.stderr or "")[-400:])
        return None
    if chapters_path is not None:
        write_chapters(plan, Path(chapters_path))
    return out_path


def rtmp_argv(url: str, source: Path, loop: bool = True) -> List[str]:
    """Команда круглосуточного вещания в Telegram Live / YouTube Live."""
    argv = ["ffmpeg", "-re"]
    if loop:
        argv += ["-stream_loop", "-1"]
    argv += [
        "-i", str(source),
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-b:v", "2500k", "-maxrate", "2500k", "-bufsize", "5000k",
        "-pix_fmt", "yuv420p", "-g", "50",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-f", "flv", url,
    ]
    return argv


# ---------------------------------------------------------------------------
# Контур 1: бессерверная веб-радиостанция dist/radio.html
# ---------------------------------------------------------------------------

RADIO_JS = r"""
(function () {
  var SP = window.SP_RADIO || { playlist: [], epoch: 0, slot: 21600, pause: 5 };
  var PL = SP.playlist || [];
  var PAUSE = SP.pause || 5;
  var $ = function (id) { return document.getElementById(id); };
  var index = 0, ctx = null, master = null, analyser = null, drone = null;
  var timer = null, current = null, raf = 0;

  function fmt(sec) {
    sec = Math.max(0, Math.round(sec || 0));
    return String(Math.floor(sec / 60)).padStart(2, '0') + ':' + String(sec % 60).padStart(2, '0');
  }

  function initAudio() {
    if (ctx) return;
    var Ctor = window.AudioContext || window.webkitAudioContext;
    if (!Ctor) return;
    ctx = new Ctor();
    master = ctx.createGain();
    master.gain.value = 0.0;
    var filter = ctx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.value = 760;
    filter.Q.value = 0.7;
    var base = [220, 330, 440];
    drone = { filter: filter, oscs: [] };
    base.forEach(function (hz, i) {
      var osc = ctx.createOscillator();
      osc.type = i === 1 ? 'triangle' : 'sine';
      osc.frequency.value = hz;
      var g = ctx.createGain();
      g.gain.value = 0.34 / (i + 1);
      osc.connect(g); g.connect(filter); osc.start();
      drone.oscs.push(osc);
    });
    var lfo = ctx.createOscillator();
    lfo.frequency.value = 0.07;
    var lfoGain = ctx.createGain();
    lfoGain.gain.value = 260;
    lfo.connect(lfoGain); lfoGain.connect(filter.frequency); lfo.start();
    filter.connect(master);
    // Анализатор спектра: AnalyserNode + Canvas (живая осциллограмма эфира).
    analyser = ctx.createAnalyser();
    analyser.fftSize = 2048;
    master.connect(analyser);
    analyser.connect(ctx.destination);
  }

  function chord(notes) {
    if (!drone || !ctx) return;
    var freqs = (notes && notes.length) ? notes : [220, 330, 440];
    drone.oscs.forEach(function (osc, i) {
      var hz = freqs[i % freqs.length];
      osc.frequency.linearRampToValueAtTime(hz, ctx.currentTime + 1.4);
    });
  }

  function ambient(level) {
    if (!master || !ctx) return;
    master.gain.linearRampToValueAtTime(level, ctx.currentTime + 1.0);
  }

  function draw() {
    var canvas = $('radio-scope');
    if (canvas && analyser) {
      var g = canvas.getContext('2d');
      var data = new Uint8Array(analyser.fftSize);
      analyser.getByteTimeDomainData(data);
      g.fillStyle = '#F3F0EA';
      g.fillRect(0, 0, canvas.width, canvas.height);
      g.lineWidth = 2;
      g.strokeStyle = '#1E3A8A';
      g.beginPath();
      for (var i = 0; i < data.length; i++) {
        var x = (i / data.length) * canvas.width;
        var y = (data[i] / 255) * canvas.height;
        if (i === 0) g.moveTo(x, y); else g.lineTo(x, y);
      }
      g.stroke();
    }
    raf = requestAnimationFrame(draw);
  }

  function render(entry) {
    if (!entry) return;
    var set = function (id, value) { var el = $(id); if (el) el.textContent = value || ''; };
    set('radio-section', entry.section ? '\u00A7 ' + entry.section : '');
    set('radio-title', entry.title);
    set('radio-scientist', [entry.scientist, entry.era].filter(Boolean).join(' \u00B7 '));
    set('radio-domain', entry.domain_label);
    set('radio-hook', entry.hook);
    set('radio-status', entry.status === 'published' ? 'В эфире канала' : 'Готовится к эфиру');
    set('radio-transcript', entry.script);
    set('radio-formula', entry.formula_plain || entry.formula || '');
    var card = $('radio-card');
    if (card) { card.src = entry.card; card.style.display = ''; }
    var link = $('radio-post');
    if (link) link.href = entry.page;
    var items = document.querySelectorAll('#radio-list li');
    for (var i = 0; i < items.length; i++) items[i].className = i === index ? 'playing' : '';
    if (window.renderMathInElement) {
      try { window.renderMathInElement($('radio-formula')); } catch (e) {}
    }
  }

  function speak(entry, done) {
    if (!('speechSynthesis' in window)) { setTimeout(done, 4000); return; }
    var u = new SpeechSynthesisUtterance(entry.script || entry.title || '');
    u.lang = 'ru-RU'; u.rate = 1.0; u.pitch = 1.0;
    u.onend = done; u.onerror = done;
    try { window.speechSynthesis.cancel(); window.speechSynthesis.speak(u); }
    catch (e) { done(); }
  }

  function mediaSession(entry) {
    if (!('mediaSession' in navigator)) return;
    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: entry.label,
        artist: entry.scientist || 'Science Pulse FM',
        album: entry.domain_label,
        artwork: [{ src: entry.card, sizes: '512x512', type: 'image/png' }]
      });
      navigator.mediaSession.setActionHandler('previoustrack', function () { play(index - 1); });
      navigator.mediaSession.setActionHandler('nexttrack', function () { play(index + 1); });
    } catch (e) {}
  }

  function gap() {
    ambient(0.11);
    clearTimeout(timer);
    timer = setTimeout(function () { play(index + 1); }, PAUSE * 1000);
  }

  function play(i) {
    if (!PL.length) return;
    index = ((i % PL.length) + PL.length) % PL.length;
    var entry = PL[index];
    render(entry); chord(entry.notes || []); ambient(0.055);
    if (current) { try { current.pause(); } catch (e) {} current = null; }
    if ('speechSynthesis' in window) { try { window.speechSynthesis.cancel(); } catch (e) {} }
    mediaSession(entry);
    if (entry.audio) {
      current = new Audio(entry.audio);
      current.onended = gap;
      current.onerror = function () { speak(entry, gap); };
      var p = current.play();
      if (p && p.catch) p.catch(function () { speak(entry, gap); });
    } else {
      speak(entry, gap);
    }
  }

  function on() {
    initAudio();
    if (ctx && ctx.state === 'suspended') ctx.resume();
    ambient(0.055);
    if (!raf) draw();
    var btn = $('radio-toggle');
    if (btn) btn.textContent = 'Пауза эфира';
  }

  function off() {
    ambient(0.0);
    clearTimeout(timer);
    if (current) { try { current.pause(); } catch (e) {} current = null; }
    if ('speechSynthesis' in window) { try { window.speechSynthesis.cancel(); } catch (e) {} }
    var btn = $('radio-toggle');
    if (btn) btn.textContent = 'Включить эфир';
  }

  window.SP_RADIO_CTL = { play: play, on: on, off: off };

  var toggle = $('radio-toggle');
  if (toggle) toggle.addEventListener('click', function () {
    if (toggle.dataset.on === '1') { toggle.dataset.on = '0'; off(); }
    else { toggle.dataset.on = '1'; on(); play(index); }
  });
  var prev = $('radio-prev'), next = $('radio-next'), rnd = $('radio-random');
  if (prev) prev.addEventListener('click', function () { on(); play(index - 1); });
  if (next) next.addEventListener('click', function () { on(); play(index + 1); });
  if (rnd) rnd.addEventListener('click', function () { on(); play(Math.floor(Math.random() * PL.length)); });
  var rows = document.querySelectorAll('#radio-list li');
  for (var r = 0; r < rows.length; r++) {
    (function (i) { rows[i].addEventListener('click', function () { on(); play(i); }); })(r);
  }

  if (PL.length) {
    var slot = Math.floor((Date.now() / 1000 - SP.epoch) / SP.slot);
    index = ((slot % PL.length) + PL.length) % PL.length;
    render(PL[index]);
    var now = $('radio-now');
    if (now) now.textContent = 'Эфирный такт № ' + slot + ' · сейчас в эфире: ' + PL[index].label;
  }
})();
"""





RADIO_CSS = """
.radio-live { display: grid; grid-template-columns: 320px minmax(0, 1fr); gap: 26px; align-items: start; margin: 22px 0; }
@media (max-width: 860px) { .radio-live { grid-template-columns: 1fr; } }
.radio-card { width: 100%; border: 1px solid var(--rule); border-radius: 4px; }
.onair { display: inline-flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 12px; letter-spacing: .12em; text-transform: uppercase; color: var(--physics); border: 1px solid var(--physics); border-radius: 999px; padding: 4px 12px; }
.onair i { width: 8px; height: 8px; border-radius: 50%; background: var(--physics); animation: pulse 1.6s infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .25; } }
.radio-ctl { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin: 18px 0; }
.radio-ctl button { background: var(--paper-2); border: 1px solid var(--rule); color: var(--ink); border-radius: 4px; padding: 10px 16px; cursor: pointer; font-family: var(--serif); font-size: 15px; }
.radio-ctl button:hover { border-color: var(--ink); }
#radio-toggle { background: var(--ink); color: var(--paper); border-color: var(--ink); font-weight: 700; }
#radio-scope { width: 100%; background: var(--paper-3); border: 1px solid var(--rule); border-radius: 4px; }
#radio-list { list-style: none; padding: 0; margin: 12px 0 0; max-height: 340px; overflow-y: auto; }
#radio-list li { padding: 8px 10px; border-bottom: 1px solid var(--rule); cursor: pointer; font-size: 14px; color: var(--ink-2); }
#radio-list li:hover { color: var(--ink); }
#radio-list li.playing { background: var(--paper-3); color: var(--ink); font-weight: 700; border-left: 3px solid var(--math); }
#radio-list li span { font-family: var(--mono); font-size: 12px; color: var(--ink-2); }
.transcript { background: var(--paper-2); border: 1px solid var(--rule); border-left: 4px solid var(--math); border-radius: 4px; padding: 14px 16px; font-size: 15px; color: var(--ink-2); margin: 16px 0; }
"""


def _json_script(value: Any) -> str:
    """JSON, безопасный для вставки внутрь ``<script>``."""
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


RADIO_PAGE_HEAD = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__RADIO__ \u00B7 __SITE__</title>
<meta name="description" content="__TAGLINE__: генеративный математический эмбиент и лекции о законах природы.">
<meta name="theme-color" content="#FAF8F4">
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" type="image/png" href="icon-192.png">
<link rel="alternate" type="application/rss+xml" href="podcast.xml" title="__RADIO__">
<link rel="stylesheet" href="assets/style.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"
  onload="renderMathInElement(document.body, {delimiters: [{left: '$$', right: '$$', display: true}, {left: '$', right: '$', display: false}]});"></script>
<style>__CSS__</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="brand"><h1><a href="index.html" style="color:inherit">__SITE__</a></h1><span>радио 24/7</span></div>
  <div class="stats"><span>выпусков в сетке: __COUNT__</span><span>с озвучкой: __LIVE__</span><span>0 LLM</span></div>
</header>
<nav class="tabs">
  <a href="index.html">I. Дерево Фундамента</a>
  <a href="scientists.html">II. Учёные и эпохи</a>
  <a href="constants.html">III. Эталоны СИ (CODATA)</a>
  <a href="flashcards.html">IV. Тренажёр памяти</a>
  <a class="active" href="radio.html">Радио 24/7</a>
</nav>
<p class="meta" id="radio-now">Эфир синхронизирован по «часам Вселенной»: (сейчас \u2212 эпоха) // 6 ч.</p>
<div class="radio-live">
  <div>
    <img class="radio-card" id="radio-card" src="icon-512.png" alt="Карточка параграфа">
    <p class="meta">__TAGLINE__<br>
    <a href="podcast.xml">podcast.xml</a> \u00B7 __MIX_LINK__</p>
  </div>
  <div>
    <span class="onair"><i></i> <span id="radio-status">в эфире</span></span>
    <h1 style="font-size:clamp(20px,3vw,30px);margin:10px 0 4px"><span id="radio-section"></span> <span id="radio-title"></span></h1>
    <p class="meta" id="radio-scientist"></p>
    <p class="meta" id="radio-domain"></p>
    <p class="lead" id="radio-hook"></p>
    <div class="formula" id="radio-formula"></div>
    <div class="radio-ctl">
      <button id="radio-toggle" type="button">Включить эфир</button>
      <button id="radio-prev" type="button">Предыдущий</button>
      <button id="radio-next" type="button">Следующий</button>
      <button id="radio-random" type="button">Случайная волна знаний</button>
      <a href="podcast.xml" style="border:0">Подписаться (RSS)</a>
    </div>
    <canvas id="radio-scope" width="680" height="160"></canvas>
    <div class="transcript" id="radio-transcript"></div>
    <p><a id="radio-post" href="index.html">\u2192 открыть главу целиком</a></p>
    <h2 style="font-family:var(--mono);font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-2)">Эфирная сетка</h2>
    <ul id="radio-list">__ROWS__</ul>
  </div>
</div>
<footer>Science Pulse FM \u00B7 звук синтезируется в браузере (WebAudio API) \u00B7 без внешних серверов и без LLM в контенте.</footer>
</div>
"""


def radio_page_html(entries: Sequence[Dict[str, Any]], config: Config, has_mix: bool = False) -> str:
    """Полная страница бессерверной радиостанции (WebAudio + лекции + mediaSession)."""
    from datetime import datetime

    site_title = html.escape(config.site_title or "Science Pulse")
    payload = {
        "playlist": list(entries),
        "epoch": int(datetime.fromisoformat(EPOCH_START_UTC).timestamp()),
        "slot": int(SLOT_SECONDS),
        "pause": PAUSE_SECONDS,
    }
    rows = "".join(
        f'<li><span>{"§ " + html.escape(str(item["section"])) if item.get("section") else "—"}</span> '
        f'{html.escape(str(item["title"]))}</li>'
        for item in entries
    )
    mix_link = (
        '<a href="radio_mix.mp4">радио-микс</a> · <a href="radio_chapters.txt">таймкоды</a>'
        if has_mix
        else "<span>радио-микс собирается локально (<code>cli radio --mix</code>)</span>"
    )
    head = (
        RADIO_PAGE_HEAD
        .replace("__RADIO__", html.escape(RADIO_TITLE))
        .replace("__SITE__", site_title)
        .replace("__TAGLINE__", html.escape(RADIO_TAGLINE))
        .replace("__CSS__", RADIO_CSS)
        .replace("__COUNT__", str(len(entries)))
        .replace("__LIVE__", str(sum(1 for item in entries if item.get("audio"))))
        .replace("__ROWS__", rows)
        .replace("__MIX_LINK__", mix_link)
    )
    tail = (
        f"<script>window.SP_RADIO = {_json_script(payload)};</script>\n"
        f"<script>{RADIO_JS}</script>\n</body>\n</html>"
    )
    return head + tail


def write_radio(dist: Path, posts: Sequence[Post], config: Config) -> Dict[str, Any]:
    """Собирает веб-радиостанцию и подкаст-фид; возвращает карту артефактов."""
    dist = Path(dist)
    entries = radio_playlist(posts, config)
    has_mix = (dist / "radio_mix.mp4").is_file()
    (dist / "radio.html").write_text(
        radio_page_html(entries, config, has_mix=has_mix), encoding="utf-8"
    )
    (dist / "radio.json").write_text(
        json.dumps(
            {"playlist": entries, "epoch": EPOCH_START_UTC, "slot": SLOT_SECONDS},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    (dist / "podcast.xml").write_text(build_podcast_xml(entries, config), encoding="utf-8")
    return {
        "radio": str(dist / "radio.html"),
        "podcast": str(dist / "podcast.xml"),
        "playlist": str(dist / "radio.json"),
        "episodes": len(entries),
        "with_audio": sum(1 for item in entries if item.get("audio")),
        "slot": current_slot(),
    }


def radio_status(posts: Sequence[Post], config: Config) -> Dict[str, Any]:
    """Краткая сводка эфира (для `cli radio --json` и пульта)."""
    entries = radio_playlist(posts, config)
    now_playing = slot_entry(entries)
    return {
        "episodes": len(entries),
        "with_audio": sum(1 for item in entries if item.get("audio")),
        "slot": current_slot(),
        "now": now_playing["label"] if now_playing else "",
        "epoch": EPOCH_START_UTC,
        "slot_seconds": SLOT_SECONDS,
        "pause_seconds": PAUSE_SECONDS,
    }

