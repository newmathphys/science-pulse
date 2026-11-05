from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Iterable, List, Optional
from zoneinfo import ZoneInfo

from .config import Config
from .pipeline import Pipeline

LOGGER = logging.getLogger(__name__)


def parse_schedule(values: Iterable[str]) -> List[tuple[int, int]]:
    result: List[tuple[int, int]] = []
    for value in values:
        try:
            hours, minutes = str(value).strip().split(":", 1)
            hour, minute = int(hours), int(minutes)
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                result.append((hour, minute))
        except (ValueError, AttributeError):
            LOGGER.warning("Некорректное время расписания: %s", value)
    return sorted(set(result))


def next_run(now: datetime, schedule: List[tuple[int, int]]) -> datetime:
    if not schedule:
        schedule = [(9, 0), (18, 0)]
    candidates: List[datetime] = []
    for hour, minute in schedule:
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        candidates.append(candidate)
    return min(candidates)


def run_daemon(
    pipeline: Pipeline,
    config: Config,
    once: bool = False,
    max_runs: Optional[int] = None,
    dry_run: bool = False,
) -> int:
    timezone = ZoneInfo(config.timezone)
    schedule = parse_schedule(config.schedule)
    runs = 0

    if once:
        pipeline.run(dry_run=dry_run)
        return 1

    while max_runs is None or runs < max_runs:
        now = datetime.now(timezone)
        target = next_run(now, schedule)
        wait_seconds = max(1.0, (target - now).total_seconds())
        LOGGER.info("Следующий запуск: %s (%s сек.)", target.isoformat(), int(wait_seconds))
        time.sleep(wait_seconds)
        moment = datetime.now(timezone)
        try:
            from .rituals import SATELLITE_DOMAIN, daily_domain, evening_kind, publishes_post

            if publishes_post(moment, config):
                slot = daily_domain(moment, config)
                domain = SATELLITE_DOMAIN if slot == "satellite_lab" else slot
                LOGGER.info("Слот суток: %s → дисциплина %s", slot, domain)
                result = pipeline.run(dry_run=dry_run, domain=domain)
                LOGGER.info("Публикация: %s", result.get("ok"))
            else:
                # Вечер Пт/Сб/Вс занят ритуалом: второго сообщения в ту же минуту нет.
                LOGGER.info("Вечерний слот отдан ритуалу: %s", evening_kind(moment))
        except Exception:
            LOGGER.exception("Ошибка планировщика")
        try:
            from .rituals import run_rituals

            report = run_rituals(pipeline, now=moment, dry_run=dry_run)
            if report.get("due"):
                LOGGER.info("Ритуалы: %s", report["due"])
        except Exception:
            LOGGER.exception("Ошибка ритуалов")
        runs += 1
    return runs
