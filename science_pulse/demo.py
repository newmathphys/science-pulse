"""Экскурсия по системе: как один и тот же пост выглядит в каждой соцсети.

`cli demo` отправляет в админ-чат подробный тур: по одному посту на каждый
архетип карточки + тексты для всех 6 площадок, озвучку, видео, служебные
таблицы и PDF-книгу.

Тексты берутся ТЕМИ ЖЕ функциями, что и публикация (билдеры адаптеров),
поэтому тур честно показывает, что реально уйдёт в сеть.
"""
from __future__ import annotations

import html
import logging
from typing import Any, Dict, List

from .models import Post

LOGGER = logging.getLogger(__name__)

# По одному посту на каждый визуальный архетип.
TOUR_ARCHETYPES: tuple = (
    ("pythagoras", "standard_plot", "график f(x) и производной"),
    ("euclid_gcd", "code_booktabs", "книжный листинг «Алгоритм 1.»"),
    ("insar_ndvi", "diptych_insar", "двухпанельный диптих: 2D-поле + разрез"),
    ("schwarzschild_light", "cheatsheet_table", "шпаргалка-таблица"),
    ("schrodinger", "timeline_evolution", "таймлайн «Эволюция идеи»"),
)


def network_variants(post: Post, config: Any, site_url: str = "") -> Dict[str, str]:
    """Тексты поста для каждой площадки — теми же билдерами, что и публикация."""
    from .platforms_info import PlatformRules
    from .publishers.base import PublishContext, build_caption, build_short_text
    from .publishers.bluesky import BlueskyPublisher
    from .publishers.discord import build_embed
    from .publishers.mastodon import build_status
    from .publishers.vk import build_message
    from .text import split_text

    rules = PlatformRules.load(None, config)
    context = PublishContext(site_url=site_url,
                             public_card_url=f"{site_url}/cards/{post.id}.png" if site_url else "")
    threads_limit = rules.limit("threads", "max_caption_chars", 500)
    threads_chunks = split_text(
        build_short_text(post, limit=threads_limit, site_url=site_url, include_link=False),
        max(80, threads_limit - 10),
    )
    embed = build_embed(post, context, rules)
    return {
        "telegram": build_caption(post, limit=rules.limit("telegram", "max_caption_chars", 1024) - 4,
                                  html=True, site_url=site_url),
        "threads": "\n— — —\n".join(threads_chunks[: rules.limit("threads", "max_chain_parts", 2)]),
        "bluesky": BlueskyPublisher(config)._text(post, context, rules),
        "discord": f"{embed['title']}\n{embed['description']}",
        "mastodon": build_status(post, context, rules),
        "vk": build_message(post, context, rules),
    }


def format_variants(post: Post, variants: Dict[str, str]) -> List[str]:
    """Оформляет варианты по сетям: по одному короткому сообщению на площадку.

    Разбивка на отдельные сообщения — чтобы длинные тексты не разрезались на
    границе HTML-тегов (Telegram лимит 4096).
    """
    notes = {
        "telegram": "фото + подпись, звук голосовым",
        "threads": "цепочка ответов, картинка по URL",
        "bluesky": "текст ≤300 + картинка/видео из RAM",
        "discord": "embed с картинкой + mp3-вложение",
        "mastodon": "статус с медиа (аудио играет нативно)",
        "vk": "запись на стене с фото/видео",
    }
    messages = [f"🧪 <b>{html.escape(post.title)}</b> [{post.domain}] — как этот пост уйдёт в каждую сеть:"]
    for name, text in variants.items():
        body = html.escape(text)
        if len(body) > 2600:
            body = body[:2600] + "…"
        messages.append(
            f"<b>— {name.upper()}</b> <i>({notes.get(name, '')}; {len(text)} симв.)</i>\n<blockquote>{body}</blockquote>"
        )
    return messages


def _archetype_posts(config: Any) -> List[Any]:
    """Посты тура: по одному на архетип, в порядке ступеней фундамента."""
    from .sources.foundation import FoundationSource, ordered_nodes

    source = FoundationSource(config)
    nodes = ordered_nodes()
    posts: List[Any] = []
    for canon_id, _archetype, _note in TOUR_ARCHETYPES:
        for index, node in enumerate(nodes):
            if node["id"] == canon_id:
                posts.append(source.fetch(limit=1, cycle=index)[0])
                break
    return posts


def run_demo(pipeline: Any, admin: Any, limit_posts: int = 5, with_media: bool = True) -> Dict[str, Any]:
    """Отправляет экскурсию в админ-чат. Возвращает счётчики."""
    from .cards import render_card
    from .evolve import EvolutionEngine
    from .publishers.base import build_full_description

    config = pipeline.config
    site_url = config.site_base_url
    sent = 0

    def send(text: str) -> None:
        nonlocal sent
        admin.send(text)
        sent += 1

    send("🎓 <b>ЭКСКУРСИЯ ПО SCIENCE PULSE</b>\n\n"
         "Покажу по шагам: карточки (5 архетипов) → как один пост выглядит в каждой из 6 соцсетей → "
         "звук (голос Светланы + фонетика формул) → видео → служебные таблицы → PDF-книга.\n\n"
         "Тексты берутся теми же функциями, что и реальная публикация.")

    posts = _archetype_posts(config)[:limit_posts]
    engine = EvolutionEngine(pipeline)
    for index, post in enumerate(posts):
        canon_id, archetype, note = TOUR_ARCHETYPES[index]
        try:
            card = render_card(post, out_path=config.cards_dir / f"{post.id}.png")
        except Exception as exc:
            send(f"⚠️ Карточка {canon_id} не собралась: {html.escape(str(exc))[:150]}")
            continue
        try:
            engine.prepare(post)  # ссылки на уже опубликованный фундамент
        except Exception as exc:
            LOGGER.warning("demo prepare: %s", exc)
        variants = network_variants(post, config, site_url)
        caption = (f"📐 <b>Архетип {index + 1}/5: {archetype}</b> — {note}\n"
                   f"<b>{html.escape(post.title)}</b>\n"
                   f"Домен: {post.domain} · источник: {html.escape(post.source_name)}\n\n"
                   f"Так карточка выходит в Telegram (фото + подпись). "
                   f"📖 Детальное описание — следующим сообщением.")
        try:
            admin.send_photo(card.path, caption)
            sent += 1
        except Exception as exc:
            LOGGER.warning("demo photo: %s", exc)
        # Детальное описание поста (второе сообщение после карточки).
        send("📖 <b>ДЕТАЛЬНОЕ ОПИСАНИЕ ПОСТА</b> (вторым сообщением после карточки):\n\n"
             + build_full_description(post, limit=4000, site_url=site_url))
        for message in format_variants(post, variants):
            send(message)

    if with_media and posts:
        _send_media(admin, posts[0], config)

    _send_service(pipeline, admin, send)
    send("🎓 <b>Конец экскурсии.</b>\n\n"
         "Дальше: <code>cli publish --video</code> (пост с видео), "
         "<code>/limits set threads max_caption_chars 600</code> (правила на ходу), "
         "<code>cli book</code> (книга), <code>/voice</code> (озвучить пост), "
         "<code>cli verify</code> (полная верификация).")
    return {"sent": sent, "posts": len(posts)}


def _send_media(admin: Any, post: Post, config: Any) -> None:
    """Озвучка, видео-аудиограмма и оживший чертёж."""
    from .video import video_for_post
    from .voice import audiogram_for_post, voice_for_post

    try:
        artifact = voice_for_post(post, config)
        if artifact and artifact.ogg_path:
            admin.send_voice(artifact.ogg_path,
                             f"🔊 Озвучка (голос {artifact.voice}, {artifact.duration_s:.0f} с). "
                             "Формулы произносятся словами: «о большое от эн логарифм эн».")
    except Exception as exc:
        LOGGER.warning("demo voice: %s", exc)
    try:
        audiogram = audiogram_for_post(post, config)
        if audiogram:
            admin.send_video(audiogram, "🎬 <b>Видео-аудиограмма</b>: книжная страница + голос + "
                                        "живая осциллограмма (для Threads/Bluesky/VK, где нет .mp3).")
    except Exception as exc:
        LOGGER.warning("demo audiogram: %s", exc)
    try:
        animation = video_for_post(post, config)
        if animation:
            admin.send_video(animation, "🎞 <b>Оживший чертёж</b>: 30 кадров анимации формулы + сонификация. "
                                        "Выходит каждый 3-й пост автоматически.")
    except Exception as exc:
        LOGGER.warning("demo video: %s", exc)


def _send_service(pipeline: Any, admin: Any, send: Any) -> None:
    """Служебные таблицы: правила, фундамент, preflight, verify, doctor, книга."""
    from .platforms_info import PlatformRules, format_limits
    from .preflight import format_preflight, preflight
    from .verify import format_verify, run_verify

    config = pipeline.config
    try:
        rules = PlatformRules.load(pipeline.storage, config)
        availability = {item["name"]: bool(item.get("available")) for item in pipeline.status().get("platforms", [])}
        send(format_limits(rules, availability or None))
    except Exception as exc:
        LOGGER.warning("demo limits: %s", exc)
    for name, builder in (
        ("foundation", lambda: admin._foundation_text([])),
        ("preflight", lambda: format_preflight(preflight(pipeline, with_media=True))),
        ("verify", lambda: format_verify(run_verify(pipeline, include_media=False))),
        ("doctor", lambda: admin._doctor_text()),
    ):
        try:
            send(builder())
        except Exception as exc:
            LOGGER.warning("demo %s: %s", name, exc)
    try:
        from .book import BookBuilder

        book = BookBuilder(config, pipeline.storage).build()
        admin.send_document(book, "📕 <b>PDF-книга проекта</b>: титул, оглавление, главы по дисциплинам, "
                                  "формулы Computer Modern, предметный указатель учёных.")
    except Exception as exc:
        LOGGER.warning("demo book: %s", exc)