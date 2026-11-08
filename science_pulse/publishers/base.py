from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from ..models import CardArtifact, Post, PublishResult
from ..text import clean_latex_for_telegram, escape_html, formula_to_unicode, lead_sentence, smart_sentence_truncate, truncate

# Ширина подписи поля в блоке «Field: Detail» (стиль mokujiro.com).
SPEC_PAD = 15


@dataclass
class PublishContext:
    site_url: str = ""
    public_card_url: str = ""
    thread_id: str = ""
    video: bool = False
    rules: Any = None  # PlatformRules: единый реестр лимитов и режима звука


def context_rules(context: "PublishContext", config: Any) -> Any:
    """Правила площадок из контекста (или загрузка из config как fallback)."""
    if getattr(context, "rules", None) is not None:
        return context.rules
    from ..platforms_info import PlatformRules

    return PlatformRules.load(None, config)


def audio_link(post: Post, site_url: str) -> str:
    """Ссылка на аудио-разбор для площадок без поддержки аудио."""
    return f"{site_url}/post/{post.id}.html" if site_url else ""


def audiogram_url(post: Post, site_url: str) -> str:
    """Публичный URL видео-аудиограммы (карточка + голос) на сайте."""
    return f"{site_url}/audiogram/{post.id}.mp4" if site_url else ""


class Publisher(ABC):
    name: str = "base"

    @abstractmethod
    def available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def publish(self, post: Post, card: CardArtifact, context: PublishContext) -> PublishResult:
        raise NotImplementedError


DOMAIN_CONTEXT = {
    "math": (
        "Аналитическое соотношение лежит в основе теории аппроксимации, спектрального анализа и численных методов.",
        "Такие конструкции применяются в криптографии, обработке сигналов и оптимизации.",
        "#математика #анализ #наука",
    ),
    "physics": (
        "Закономерность определяет динамику полей, сохранение энергии и поведение квантовых систем.",
        "Физические модели используются в материаловедении, астрофизике и инженерии.",
        "#физика #законыприроды #наука",
    ),
    "cs": (
        "Алгоритмическая конструкция помогает оценивать сложность и проектировать быстрые системы.",
        "Подход применяется в базах данных, компиляторах и распределённых вычислениях.",
        "#информатика #алгоритмы #код",
    ),
}


def build_rich_telegram_caption(post: Post, limit: int = 1024, site_url: str = "") -> str:
    """Полный Telegram-пост в строгом стиле mokujiro.com (без смайликов).

    Типографика вместо эмодзи: паспортная строка `§ X.Y · ДИСЦИПЛИНА · ЭПОХА`,
    заголовок, вопрос-постановка, разбор, выровненный блок `Field: Detail`
    (Инвариант / Верификация / Первоисточник / Применение), задача выпуска и
    строка связей `← …`.
    """
    title = clean_latex_for_telegram(post.title)
    hook = clean_latex_for_telegram(post.hook or "")
    raw_body = clean_latex_for_telegram(post.body or "")
    context_note, application_note, tags = DOMAIN_CONTEXT.get(post.domain, DOMAIN_CONTEXT["math"])
    meta = getattr(post, "meta", {}) or {}
    modern = clean_latex_for_telegram(str(meta.get("modern_application") or ""))

    formula = formula_to_unicode(clean_latex_for_telegram(post.formula_plain or post.formula_latex or ""), 140)
    code = (post.code or "").strip()
    source = clean_latex_for_telegram(post.source_name or "Science Pulse")

    section = str(meta.get("section_num") or "").strip()
    era_short = str(meta.get("era") or "").split("•")[0].strip()
    # Паспортная строка в стиле mokujiro: «§ X.Y · ДИСЦИПЛИНА · ЭПОХА».
    passport = " · ".join(
        part for part in (f"§ {section}" if section else "", post.label, era_short) if part
    )
    header_parts = [f"<b>{escape_html(passport)}</b>", f"<b>{escape_html(title)}</b>"]
    if not hook or hook.lower() == title.lower() or raw_body.startswith(hook):
        hook = lead_sentence(raw_body, 200)
    if hook and hook.lower() != title.lower() and hook not in raw_body[: len(hook) + 40]:
        header_parts.append(f"<i>{escape_html(smart_sentence_truncate(hook, 80, 220))}</i>")

    footer_parts = []
    if formula:
        footer_parts.append(f"{'Инвариант:':<{SPEC_PAD}} <code>{escape_html(truncate(formula, 140))}</code>")
    elif code:
        first_lines = "\n".join(code.splitlines()[:5])
        footer_parts.append(f"<b>Реализация.</b>\n<pre>{escape_html(truncate(first_lines, 240))}</pre>")
    # Вычислительный паспорт: точный расчёт (CODATA / значения формулы).
    proof = meta.get("proof") if isinstance(meta.get("proof"), dict) else None
    if not proof or not proof.get("computed_example"):
        try:
            from ..post_proof import build_post_proof

            proof = build_post_proof(post)
        except Exception:
            proof = proof or {}
    example = str((proof or {}).get("computed_example") or "").strip()
    if example:
        footer_parts.append(f"{'Верификация:':<{SPEC_PAD}} {escape_html(truncate(example, 220))}")

    # Живой датчик Планеты и Космоса: реальное сегодняшнее число в формулу поста.
    try:
        from ..live_sensors import live_line

        live = live_line(post)
    except Exception:  # pragma: no cover - датчик не должен ломать публикацию
        live = ""
    if live:
        footer_parts.append(f"{'Живой датчик:':<{SPEC_PAD}} {escape_html(truncate(live, 220))}")
    challenge = (proof or {}).get("challenge") if isinstance(proof, dict) else None
    if not isinstance(challenge, dict):
        try:
            from ..challenge import build_challenge

            challenge = build_challenge(post)
        except Exception:
            challenge = None

    # Первоисточник: убираем служебный префикс источника фундамента.
    primary = source.replace("Фундамент Науки · ", "").replace("Фундамент Науки", "").strip() or source
    if post.source_url:
        footer_parts.append(
            f"{'Первоисточник:':<{SPEC_PAD}} "
            f"<a href=\"{escape_html(post.source_url)}\">{escape_html(truncate(primary, 60))}</a>"
        )
    elif primary:
        footer_parts.append(f"{'Первоисточник:':<{SPEC_PAD}} {escape_html(truncate(primary, 60))}")

    # Тройная связь времени: конкретное применение из узла канона важнее шаблона.
    if modern:
        footer_parts.append(f"{'Применение:':<{SPEC_PAD}} {escape_html(truncate(modern, 200))}")
    elif application_note:
        footer_parts.append(f"{'Применение:':<{SPEC_PAD}} {escape_html(application_note)}")

    # Задача выпуска: только в режиме `interactive_challenge` (дозированно).
    from ..post_modes import shows_challenge

    mode = str(meta.get("post_mode") or "pure_knowledge")
    question = str((challenge or {}).get("question") or "").strip() if isinstance(challenge, dict) else ""
    if question and shows_challenge(mode):
        footer_parts.append(f"<b>Задача.</b> <i>{escape_html(truncate(question, 220))}</i>")
        answer = str((challenge or {}).get("answer") or "").strip() if isinstance(challenge, dict) else ""
        if answer:
            # Мгновенная самопроверка: ответ спрятан под нативный спойлер Telegram.
            footer_parts.append(
                f"<b>Ответ:</b> <tg-spoiler>{escape_html(truncate(answer, 220))}</tg-spoiler>"
            )

    chain: List[str] = []
    for name, url in (meta.get("prereq_links") or [])[:2]:
        chain.append(f'<a href="{escape_html(str(url))}">{escape_html(truncate(str(name), 46))}</a>')
    trainer_href = (
        f'{escape_html(site_url)}/post/{escape_html(post.id)}.html' if site_url else ""
    )
    if chain and trainer_href:
        chain.append(f'<a href="{trainer_href}">Тренажёр</a>')
        footer_parts.append("← " + " · ".join(chain))
    elif chain:
        footer_parts.append("← " + " · ".join(chain))
    elif trainer_href:
        footer_parts.append(
            f'Тренажёр: <a href="{trainer_href}">покрутить формулу и проверить себя</a>'
        )
    footer_parts.append(post.hashtags or tags)

    header = "\n\n".join(header_parts)
    footer = "\n\n".join(footer_parts)
    overhead = len(header) + len(footer) + 8
    # Полное описание: до ~620 символов вместо прежних ~380.
    body_limit = max(320, min(620, limit - overhead))
    if len(raw_body) > body_limit * 2:
        try:
            from ..signal_engine import ShannonTextCompressor

            compressed = ShannonTextCompressor().compress(raw_body, body_limit * 2)
            if len(compressed) >= 200:
                raw_body = compressed
        except Exception:
            pass
    body = smart_sentence_truncate(raw_body, min_chars=min(480, body_limit), max_chars=body_limit)

    if len(body) < 300:
        body = f"{body}\n\n{context_note}"

    caption = "\n\n".join(part for part in [header, escape_html(body), footer] if part)
    target = min(limit, 1000)
    if len(caption) > target:
        overflow = len(caption) - target
        shorter_limit = max(220, body_limit - overflow - 20)
        body = smart_sentence_truncate(raw_body, min_chars=min(360, shorter_limit), max_chars=shorter_limit)
        caption = "\n\n".join(part for part in [header, escape_html(body), footer] if part)
    return caption[:limit]


def build_caption(post: Post, limit: int = 1024, html: bool = True, site_url: str = "") -> str:
    # Вылеченная подписью стандартов (StandardsChecker) имеет приоритет.
    override = (getattr(post, "meta", {}) or {}).get("caption_override")
    if override:
        return truncate(str(override), limit)
    if html:
        return build_rich_telegram_caption(post, limit=limit, site_url=site_url)
    title = clean_latex_for_telegram(post.title)
    hook = clean_latex_for_telegram(post.hook or "")
    body = smart_sentence_truncate(post.body or "", 300, max(300, limit - 200))
    formula = formula_to_unicode(clean_latex_for_telegram(post.formula_plain or post.formula_latex or ""), 140)
    parts = [post.label, title]
    if hook:
        parts.append(hook)
    if body:
        parts.append(body)
    if formula:
        parts.append(f"Формула: {formula}")
    if site_url:
        parts.append(f"Разбор: {site_url}")
    parts.append(post.hashtags)
    return truncate("\n\n".join(parts), limit)


def formula_frame(post: Any, width: int = 30) -> str:
    """ASCII-рамка «мобильная формула» для площадок без поддержки LaTeX.

    В режиме `TEXT` (Threads, Bluesky, VK) формула должна читаться на телефоне
    без рендера — оборачиваем её в моноширинную рамку:

    ```
    ┌─── ФОРМУЛА ───
    │ a² + b² = c²
    └──────────────────
    ```
    """
    formula = clean_latex_for_telegram(
        getattr(post, "formula_plain", "") or getattr(post, "formula_latex", "") or ""
    ).strip()
    if not formula:
        return ""
    body = " ".join(formula.split())
    if len(body) > width:
        body = truncate(body, width)
    top = "┌─── ФОРМУЛА " + "─" * max(0, width - 15)
    bottom = "└" + "─" * max(0, width - 1)
    return "\n".join((top, f"│ {body}", bottom))


def challenge_answer_line(post: Post) -> str:
    """Строка ответа для площадок без спойлеров (Threads/Bluesky/Mastodon).

    В Telegram ответ прячется под `<tg-spoiler>`, а здесь он уходит отдельным
    сообщением цепочки или хвостом поста — чтобы читатель мог проверить себя.
    """
    from ..post_modes import shows_challenge

    meta = getattr(post, "meta", {}) or {}
    if not shows_challenge(str(meta.get("post_mode") or "")):
        return ""
    try:
        from ..challenge import build_challenge

        data = build_challenge(post) or {}
    except Exception:  # pragma: no cover - защитный контур
        return ""
    answer = str(data.get("answer") or "").strip()
    return f"Ответ: {answer}" if answer else ""


def build_short_text(post: Post, limit: int = 500, site_url: str = "", include_link: bool = True) -> str:
    formula = clean_latex_for_telegram(post.formula_latex or post.formula_plain)
    parts = [clean_latex_for_telegram(post.title)]
    hook = clean_latex_for_telegram(post.hook or "")
    if hook:
        parts.append(hook)
    if post.body:
        parts.append(smart_sentence_truncate(post.body, 120, max(80, limit - 180)))
    if formula:
        parts.append(f"Формула: {formula}")
    answer_line = challenge_answer_line(post)
    if answer_line:
        parts.append(answer_line)
    if site_url and include_link:
        parts.append(site_url)
    parts.append(post.hashtags)
    return truncate("\n\n".join(parts), limit)


def build_full_description(post: Post, limit: int = 4096, site_url: str = "") -> str:
    """Детальный разбор поста — вторым сообщением после карточки (до 4096 знаков).

    Структура: рубрика → эпоха/учёный → вопрос → полный разбор → код → формула →
    где работает сегодня → константы → тема → фундамент → источник → сайт → теги.
    В отличие от подписи (1024), здесь текст поста НЕ обрезается до абзаца.
    """
    meta = getattr(post, "meta", {}) or {}
    title = clean_latex_for_telegram(post.title)
    hook = clean_latex_for_telegram(post.hook or "")
    body = clean_latex_for_telegram(post.body or "")
    formula = formula_to_unicode(clean_latex_for_telegram(post.formula_plain or post.formula_latex or ""), 140)
    source = clean_latex_for_telegram(post.source_name or "Science Pulse")

    section = str(meta.get("section_num") or "").strip()
    era_short = str(meta.get("era") or "").split("•")[0].strip()
    passport = " · ".join(
        part for part in (f"§ {section}" if section else "", post.label, era_short) if part
    )
    blocks: List[str] = [f"<b>{escape_html(passport)}</b>", f"<b>{escape_html(title)}</b>"]

    if hook:
        blocks.append(f"<i>{escape_html(hook)}</i>")
    if body:
        blocks.append(f"<b>Разбор.</b>\n{escape_html(body)}")
    if post.code:
        blocks.append(f"<b>Реализация.</b>\n<pre>{escape_html(truncate(post.code, 1200))}</pre>")
    if formula:
        blocks.append(f"{'Инвариант:':<{SPEC_PAD}} <code>{escape_html(truncate(formula, 300))}</code>")

    # Вычислительный паспорт: полный разбор обязан быть надмножеством подписи.
    proof = meta.get("proof") if isinstance(meta.get("proof"), dict) else None
    if not proof or not proof.get("computed_example"):
        try:
            from ..post_proof import build_post_proof

            proof = build_post_proof(post)
        except Exception:
            proof = proof or {}
    example = str((proof or {}).get("computed_example") or "").strip()
    if example:
        blocks.append(f"{'Верификация:':<{SPEC_PAD}} {escape_html(truncate(example, 300))}")

    application = clean_latex_for_telegram(str(meta.get("modern_application") or ""))
    if application:
        blocks.append(f"{'Применение:':<{SPEC_PAD}} {escape_html(application)}")

    constants = [str(item) for item in (meta.get("constants_used") or []) if str(item).strip()]
    if constants:
        blocks.append(f"{'Константы:':<{SPEC_PAD}} {escape_html(', '.join(constants))}")

    concept = str(meta.get("concept") or "").strip()
    if concept:
        blocks.append(f"{'Тема:':<{SPEC_PAD}} {escape_html(concept)}")

    rendered = " · ".join(
        f'<a href="{escape_html(str(url))}">{escape_html(truncate(str(name), 60))}</a>'
        for name, url in (meta.get("prereq_links") or [])[:4]
    )
    if rendered:
        blocks.append("← " + rendered)

    if post.source_url:
        blocks.append(
            f"{'Первоисточник:':<{SPEC_PAD}} "
            f"<a href=\"{escape_html(post.source_url)}\">{escape_html(truncate(source, 70))}</a>"
        )
    elif source:
        blocks.append(f"{'Первоисточник:':<{SPEC_PAD}} {escape_html(truncate(source, 70))}")
    if site_url:
        blocks.append(f"<a href=\"{escape_html(site_url)}\">Полная версия с карточкой и аудио — на сайте</a>")
    blocks.append(post.hashtags)

    return truncate("\n\n".join(blocks), limit)


def build_telegram_text(post: Post, limit: int = 4096, site_url: str = "") -> str:
    """Полный текст поста для Telegram: детальный разбор (не обрезанный абзац)."""
    return build_full_description(post, limit=limit, site_url=site_url)


def result_skipped(platform: str, reason: str) -> PublishResult:
    return PublishResult(platform=platform, ok=False, skipped=True, error=reason)
