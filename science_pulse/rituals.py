"""4-уровневый календарь: суточные слоты, недельные ритуалы, месячная профилактика.

| Уровень | Что происходит |
|:--|:--|
| **сутки** | 4 слота: `math` 09:00 · `cs` 13:00 · `physics` 17:00 · `satellite_lab` 21:00 (МСК) |
| **событие** | «Молния науки» из радара трендов при превышении порога лайков |
| **неделя** | Пт — квиз-опрос, Сб — шпаргалка + радио-микс, Вс — PDF-книга + бэкап + `/ab` |
| **месяц** | 1-е число: продление токена Threads, `VACUUM` + очистка медиа, паспорт Атласа |

Недельные и месячные задачи идемпотентны: факт выполнения хранится в `kv`
(`last_friday_quiz`, `last_saturday_cheatsheet`, `last_sunday_book`,
`last_monthly_maint`), поэтому повторный запуск в тот же день/месяц ничего не
дублирует.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

LOGGER = logging.getLogger(__name__)

# Слот суток → дисциплина. Ключ — час по местному времени (МСК по умолчанию).
DEFAULT_SLOTS: Dict[int, str] = {9: "math", 13: "cs", 17: "physics", 21: "satellite_lab"}

# Прикладной слот идёт по физике (лаборатории — физические), но с приоритетом
# постов-стендов (`meta["simulation"]`).
SATELLITE_DOMAIN = "physics"

KV_FRIDAY = "last_friday_quiz"
KV_SATURDAY = "last_saturday_cheatsheet"
KV_SUNDAY = "last_sunday_book"
KV_MONTHLY = "last_monthly_maint"
KV_WEEKLY_AB = "last_weekly_ab"

MEDIA_DIRS = ("cards", "audio", "audiogram", "video", "films", "canon")


def slots(config: Any = None) -> Dict[int, str]:
    """Расписание слотов из конфига (`schedule_slots`) или значение по умолчанию."""
    raw = dict((getattr(config, "raw", {}) or {}).get("schedule_slots") or {}) if config else {}
    mapping: Dict[int, str] = {}
    for key, value in raw.items():
        try:
            mapping[int(str(key).split(":")[0])] = str(value)
        except (TypeError, ValueError):
            continue
    return mapping or dict(DEFAULT_SLOTS)


def daily_domain(now: datetime, config: Any = None) -> str:
    """Дисциплина текущего слота суток (ближайший слот не позже текущего часа)."""
    table = slots(config)
    hour = now.hour
    candidates = [h for h in sorted(table) if h <= hour]
    if not candidates:
        candidates = sorted(table)
    return table[candidates[-1]]


def week_key(now: datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def month_key(now: datetime) -> str:
    return f"{now.year}-{now.month:02d}"


def due_rituals(storage: Any, config: Any, now: datetime) -> List[str]:
    """Какие ритуалы пора выполнить (с учётом `kv`-метки о прошлом запуске)."""
    due: List[str] = []
    weekday = now.weekday()          # 0 = понедельник … 4 = пятница … 6 = воскресенье
    if weekday == 4 and storage.kv_get(KV_FRIDAY, "") != week_key(now):
        due.append("friday_quiz")
    if weekday == 5 and storage.kv_get(KV_SATURDAY, "") != week_key(now):
        due.append("saturday_cheatsheet")
    if weekday == 6 and storage.kv_get(KV_SUNDAY, "") != week_key(now):
        due.append("sunday_book")
    if weekday == 6 and storage.kv_get(KV_WEEKLY_AB, "") != week_key(now):
        due.append("weekly_ab")
    if now.day == 1 and storage.kv_get(KV_MONTHLY, "") != month_key(now):
        due.append("monthly_maintenance")
    return due


def news_threshold(config: Any) -> int:
    """Порог лайков для внеочередной «Молнии науки» (0 = выключено)."""
    raw = dict((getattr(config, "raw", {}) or {}).get("trending") or {})
    return max(0, int(raw.get("auto_publish_min_likes", 0) or 0))


def evening_hour(config: Any = None) -> int:
    """Час вечернего слота (последний в расписании, по умолчанию 21)."""
    table = slots(config)
    return max(table) if table else 21


def evening_kind(now: datetime) -> str:
    """Формат вечернего слота: Пн–Чт — лаборатория/фильм, Пт — квиз, Сб — шпаргалка, Вс — книга.

    Так вечерний выпуск НИКОГДА не накладывается на ритуал: в пятницу, субботу
    и воскресенье вечерний слот занят ровно одним событием.
    """
    return {4: "quiz", 5: "cheatsheet", 6: "book"}.get(now.weekday(), "lab")


def publishes_post(now: datetime, config: Any = None) -> bool:
    """Публикуем ли обычный пост сейчас (в Пт/Сб/Вс вечер отдан ритуалу)."""
    if now.hour != evening_hour(config):
        return True
    return evening_kind(now) == "lab"


def refresh_threads_token(config: Any, http: Optional[Callable[..., Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Продление 60-дневного токена Meta Threads (`refresh_access_token`)."""
    import os

    token = str(os.getenv("TH_ACCESS_TOKEN", "") or "").strip()
    if not token:
        return {"ok": False, "skipped": True, "detail": "TH_ACCESS_TOKEN не задан"}
    client = http
    if client is None:
        import requests

        def client(url: str, **kwargs: Any) -> Dict[str, Any]:  # type: ignore[misc]
            response = requests.get(url, timeout=20)
            return {"status": response.status_code, "data": response.json()}

    payload = client(
        "https://graph.threads.com/refresh_access_token",
        params={"grant_type": "th_refresh_token", "access_token": token},
    )
    data = payload.get("data") or {}
    if not data.get("access_token"):
        return {"ok": False, "detail": str(data.get("error") or payload.get("status"))[:160]}
    return {"ok": True, "expires_in_days": int(data.get("expires_in", 0)) // 86400}


def cleanup_old_media(config: Any, keep_last: int = 30) -> int:
    """Оставляет в медиа-каталогах только `keep_last` самых свежих файлов."""
    data_dir = Path(getattr(config, "data_dir", "data"))
    removed = 0
    for name in MEDIA_DIRS:
        directory = data_dir / name
        if not directory.is_dir():
            continue
        files = sorted(
            (item for item in directory.iterdir() if item.is_file()),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for stale in files[max(0, int(keep_last)):]:
            try:
                stale.unlink()
                removed += 1
            except OSError as exc:  # pragma: no cover - файловая система
                LOGGER.warning("не удалось удалить %s: %s", stale, exc)
    return removed


def atlas_passport(storage: Any) -> Dict[str, Any]:
    """Паспорт роста Атласа: параграфы, учёные, константы, дисциплины."""
    posts = storage.list_posts(limit=5000)
    published = [post for post in posts if post.status == "published"]
    sections = {(post.meta or {}).get("section_num") for post in published}
    scientists = {(post.meta or {}).get("scientist") for post in published}
    constants: set = set()
    for post in published:
        constants.update(str(item) for item in ((post.meta or {}).get("constants_used") or []))
    domains: Dict[str, int] = {}
    for post in published:
        domains[post.domain] = domains.get(post.domain, 0) + 1
    return {
        "published": len(published),
        "ready": sum(1 for post in posts if post.status == "ready"),
        "sections": len({item for item in sections if item}),
        "scientists": len({item for item in scientists if item}),
        "constants": len(constants),
        "domains": domains,
    }


def friday_quiz(pipeline: Any, dry_run: bool = False) -> Dict[str, Any]:
    """Пятничная викторина: нативный `sendPoll` по одному из законов недели."""
    from .challenge import build_challenge, quiz_options

    posts = pipeline.storage.list_posts(status="published", limit=12, order="published_at DESC")
    for post in posts:
        challenge = build_challenge(post)
        if not quiz_options(challenge):
            continue
        section = (post.meta or {}).get("section_num")
        if dry_run:
            return {"ok": True, "dry_run": True, "post": post.id, "section": section}
        publisher = pipeline.publishers.publishers.get("telegram")
        if publisher is None or not publisher.available():
            return {"ok": False, "error": "telegram недоступен"}
        response = publisher.send_poll(post, challenge=challenge)
        return {"ok": bool(response), "post": post.id, "section": section,
                "message_id": ((response or {}).get("result") or {}).get("message_id")}
    return {"ok": False, "error": "нет постов с проверяемой викториной"}


def saturday_cheatsheet(pipeline: Any, dry_run: bool = False) -> Dict[str, Any]:
    """Суббота: сводная карточка-шпаргалка недели + обновление радио-микса."""
    config, storage = pipeline.config, pipeline.storage
    posts = storage.list_posts(status="published", limit=8, order="published_at DESC")
    if not posts:
        return {"ok": False, "error": "нет опубликованных постов"}
    if dry_run:
        return {"ok": True, "dry_run": True, "posts": len(posts)}
    mixed = ""
    try:
        from .radio import build_radio_mix

        result = build_radio_mix(posts, Path(config.data_dir), Path(config.dist_dir) / "radio_mix.mp4")
        mixed = str(result) if result else ""
    except Exception as exc:  # pragma: no cover - радио не должно ломать ритуал
        LOGGER.warning("радио-микс не собран: %s", exc)
    return {"ok": True, "posts": len(posts), "mix": mixed}


def sunday_book(pipeline: Any, dry_run: bool = False) -> Dict[str, Any]:
    """Воскресенье: PDF-книга проекта + бэкап базы + сводка дизайнов оператору."""
    from .themes import format_design_table

    config, storage = pipeline.config, pipeline.storage
    if dry_run:
        return {"ok": True, "dry_run": True}
    book_path = ""
    try:
        from .book import BookBuilder

        book_path = str(BookBuilder(config, storage).build())
    except Exception as exc:  # pragma: no cover - typst может отсутствовать
        LOGGER.warning("книга не собрана: %s", exc)
    delivered = False
    try:
        from .admin import TelegramAdmin

        admin = TelegramAdmin(config, pipeline)
        if book_path and Path(book_path).is_file():
            delivered = bool(admin.send_document(book_path, "PDF-книга недели"))
        admin.api_call("sendMessage", {
            "chat_id": admin.chat_id,
            "text": format_design_table(storage, config, html=False)[:3900],
        })
    except Exception as exc:  # pragma: no cover - доставка не должна ломать ритуал
        LOGGER.warning("воскресный пакет не отправлен: %s", exc)
    return {"ok": True, "book": book_path, "delivered": delivered}


def monthly_maintenance(pipeline: Any, dry_run: bool = False) -> Dict[str, Any]:
    """1-е число: продление токена Threads, VACUUM + очистка медиа, паспорт Атласа."""
    config, storage = pipeline.config, pipeline.storage
    passport = atlas_passport(storage)
    if dry_run:
        return {"ok": True, "dry_run": True, "passport": passport}
    token = refresh_threads_token(config)
    storage.vacuum()
    keep = int((config.raw.get("media") or {}).get("keep_last", 30))
    removed = cleanup_old_media(config, keep_last=keep)
    token_note = (f"продлён на {token.get('expires_in_days')} дн." if token.get("ok")
                  else str(token.get("detail", "не задан")))
    lines = [
        "Ежемесячный паспорт Атласа",
        f"опубликовано: {passport['published']} · в очереди: {passport['ready']}",
        f"параграфов: {passport['sections']} · учёных: {passport['scientists']} · констант: {passport['constants']}",
        f"дисциплины: {passport['domains']}",
        f"профилактика: VACUUM выполнен, удалено медиафайлов: {removed}",
        f"токен Threads: {token_note}",
    ]
    try:
        from .admin import TelegramAdmin

        admin = TelegramAdmin(config, pipeline)
        admin.api_call("sendMessage", {"chat_id": admin.chat_id, "text": "\n".join(lines)[:3900]})
    except Exception as exc:  # pragma: no cover
        LOGGER.warning("месячный отчёт не отправлен: %s", exc)
    return {"ok": True, "token": token, "removed_media": removed, "passport": passport}


def weekly_ab_report(pipeline: Any, dry_run: bool = False) -> Dict[str, Any]:
    """Воскресный отчёт: какой видео-дизайн побеждает по бандиту."""
    from .themes import THEMES, effective_theme, record_reward, win_rates

    rates = win_rates(pipeline.storage)
    winner = max(THEMES, key=lambda name: rates.get(name, 0.0)) if THEMES else "academic"
    current = effective_theme(pipeline.storage, pipeline.config)
    if not dry_run:
        record_reward(pipeline.storage, winner, success=True)
    lines = [
        "🎛 Еженедельный отчёт /ab",
        f"Победитель недели: {winner} ({rates.get(winner, 0):.1f}%)",
        f"Текущий режим: {current}",
        "Рейтинг:",
    ]
    for name in THEMES:
        lines.append(f"  {name}: {rates.get(name, 0):.1f}%")
    lines.append("Следующая неделя: победитель получает дополнительный вес.")
    if not dry_run:
        try:
            from .admin import TelegramAdmin

            admin = TelegramAdmin(pipeline.config, pipeline)
            admin.api_call("sendMessage", {"chat_id": admin.chat_id, "text": "\n".join(lines)[:3900]})
        except Exception as exc:
            LOGGER.warning("weekly /ab не отправлен: %s", exc)
    return {"ok": True, "winner": winner, "rates": rates, "current": current}


TASKS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "friday_quiz": friday_quiz,
    "saturday_cheatsheet": saturday_cheatsheet,
    "sunday_book": sunday_book,
    "monthly_maintenance": monthly_maintenance,
    "weekly_ab": weekly_ab_report,
}

KV_MARKS = {
    "friday_quiz": KV_FRIDAY,
    "saturday_cheatsheet": KV_SATURDAY,
    "sunday_book": KV_SUNDAY,
    "monthly_maintenance": KV_MONTHLY,
    "weekly_ab": KV_WEEKLY_AB,
}


def run_rituals(pipeline: Any, now: Optional[datetime] = None, dry_run: bool = False) -> Dict[str, Any]:
    """Выполняет все должные ритуалы и ставит `kv`-метки (идемпотентно)."""
    from zoneinfo import ZoneInfo

    config, storage = pipeline.config, pipeline.storage
    moment = now or datetime.now(ZoneInfo(getattr(config, "timezone", "Europe/Moscow")))
    due = due_rituals(storage, config, moment)
    results: Dict[str, Any] = {}
    for name in due:
        try:
            results[name] = TASKS[name](pipeline, dry_run=dry_run)
        except Exception as exc:  # pragma: no cover - ритуал не должен ронять цикл
            LOGGER.exception("ритуал %s упал", name)
            results[name] = {"ok": False, "error": str(exc)[:200]}
        if results[name].get("ok") and not dry_run:
            mark = month_key(moment) if name == "monthly_maintenance" else week_key(moment)
            storage.kv_set(KV_MARKS[name], mark)
    return {"moment": moment.isoformat(), "due": due, "results": results}



