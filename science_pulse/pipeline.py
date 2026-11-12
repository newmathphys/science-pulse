from __future__ import annotations

import functools
import logging
import os
import socket
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .abtest import ab_enabled, choose_variant, variants_from_config
from .cards import render_card
from .config import Config, load_config
from .models import CardArtifact, Post, PublishResult, make_id, utc_now
from .publishers.manager import PublisherManager
from .sota import SOTAKVExtensions
from .sources.manager import SourceManager
from .storage import Storage
from .text import smart_sentence_truncate

LOGGER = logging.getLogger(__name__)


def _state_locked(method):
    """Единый writer-lock D1 для всех мутирующих операций пайплайна."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if method.__name__ in ("run", "publish_next") and (
            kwargs.get("dry_run") or (args and args[0] is True)
        ):
            return method(self, *args, **kwargs)
        with self.state_guard() as lock:
            if not lock.get("ok"):
                return self._deferred(
                    "state_lock",
                    lock.get("error") or "D1 state lock занят",
                    lock=lock,
                )
            return method(self, *args, **kwargs)
    return wrapper


class Pipeline:
    def __init__(
        self,
        config: Config | None = None,
        storage: Storage | None = None,
        source_manager: SourceManager | None = None,
        publisher_manager: PublisherManager | None = None,
    ):
        self.config = config or load_config()
        self.storage = storage or Storage(self.config.db_path)
        self.sources = source_manager or SourceManager(self.config, self.storage)
        self.publishers = publisher_manager or PublisherManager(self.config, self.storage)
        self.sota = SOTAKVExtensions(self.storage)
        self._state_lock_owner = ""

    # ------------------------------------------------------------------
    # D1 как основной источник (D1-Primary + lease lock)
    # ------------------------------------------------------------------
    @contextmanager
    def state_guard(self, ttl_s: int = 900):
        """Lease-lock на запись. Вложенные вызовы используют один owner."""
        if not self.d1_primary_enabled():
            yield {"ok": True, "skipped": "D1 primary disabled"}
            return
        if self._state_lock_owner:
            yield {"ok": True, "shared": True, "owner": self._state_lock_owner}
            return

        from .state_export import StateSync

        sync = StateSync(self.config, self.storage)
        edge = dict(self.config.raw.get("edge") or {})
        ttl = int(edge.get("lock_ttl_seconds", ttl_s) or ttl_s)
        owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        acquired = sync.acquire_lock(owner, ttl_s=ttl)
        if not acquired.get("ok"):
            yield acquired
            return
        if acquired.get("degraded"):
            LOGGER.warning("D1 lease-lock: %s", acquired["degraded"])
        self._state_lock_owner = owner
        try:
            yield acquired
        finally:
            try:
                sync.release_lock(owner)
            except Exception as exc:  # pragma: no cover - защита finally
                LOGGER.warning("D1 unlock: %s", exc)
            self._state_lock_owner = ""

    def d1_primary_enabled(self) -> bool:
        edge = dict(self.config.raw.get("edge") or {})
        if not edge.get("d1_primary", False):
            return False
        from .state_export import StateSync

        return StateSync(self.config, self.storage).available()

    def pull_state(self) -> Dict[str, Any]:
        """Забирает снимок D1 и монотонно сливает его (мягкий fallback при сбое)."""
        from .state_export import StateSync

        try:
            result = StateSync(self.config, self.storage).pull()
        except Exception as exc:
            LOGGER.warning("D1 pull не удался: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}
        if not result.get("ok"):
            LOGGER.warning("D1 pull: %s", result.get("error"))
        return result

    def push_state(self, batch_size: int = 200) -> Dict[str, Any]:
        """Отправляет локальный снимок в D1 (мягкий fallback при сбое)."""
        from .state_export import StateSync

        try:
            result = StateSync(self.config, self.storage).push(batch_size=batch_size)
        except Exception as exc:
            LOGGER.warning("D1 push не удался: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}
        if not result.get("ok"):
            LOGGER.warning("D1 push: %s", result.get("error") or result.get("failed"))
        return result

    # ------------------------------------------------------------------
    # Добыча
    # ------------------------------------------------------------------
    @_state_locked
    def harvest(
        self,
        limit_per_source: int | None = None,
        domains: Optional[Iterable[str]] = None,
        include_offline: bool = False,
    ) -> int:
        if self.d1_primary_enabled():
            self.pull_state()
        if self.storage.count("ready") >= self.config.max_queue:
            LOGGER.info("Очередь заполнена (%s), добыча пропущена", self.config.max_queue)
            return 0

        limit = int(limit_per_source or self.config.raw.get("harvest_per_source", 2))
        posts = self.sources.fetch(limit_per_source=limit, domains=domains, include_offline=include_offline)
        added = 0
        for post in posts:
            errors = post.validate()
            if errors:
                LOGGER.info("Пост %s отклонён quality gate: %s", post.id, "; ".join(errors))
                continue
            post.quality = post.quality_score()
            if self.storage.add_post(post):
                added += 1

        if not posts and self.storage.count("ready") == 0:
            added += self._harvest_offline()

        LOGGER.info("Добыча: добавлено %s постов", added)
        if self.d1_primary_enabled():
            self.push_state()
        self.storage.checkpoint()
        return added

    def add_manual_post(
        self,
        domain: str,
        title: str,
        body: str,
        formula: str = "",
        code: str = "",
        source_name: str = "manual",
    ) -> tuple[Post | None, list[str]]:
        post = Post(
            id=make_id("manual", f"{title}:{utc_now()}"),
            domain=domain,
            title=title,
            hook=smart_sentence_truncate(body, 80, 180),
            body=body,
            formula_latex=formula,
            formula_plain=formula,
            code=code,
            source_name=source_name,
            tier="manual",
        )
        errors = post.validate()
        if errors:
            return None, errors
        post.quality = post.quality_score()
        if not self.storage.add_post(post):
            return None, ["такой пост уже есть"]
        self.storage.checkpoint()
        return post, []

    def _harvest_offline(self, domain: str | None = None) -> int:
        source = self.sources.sources.get("offline")
        if source is None:
            from .sources.offline import OfflineBunkerSource

            source = OfflineBunkerSource(self.config)
        cycle = self.storage.kv_int("cycle:offline", 0)
        posts = []
        for offset in range(6 if domain else 1):
            candidate = source.fetch(limit=1, cycle=cycle + offset)
            if candidate and (domain is None or candidate[0].domain == domain):
                posts = candidate
                cycle += offset
                break
        if not posts:
            posts = source.fetch(limit=1, cycle=cycle)
        self.storage.kv_set("cycle:offline", cycle + 1)
        added = 0
        for post in posts:
            post.quality = post.quality_score()
            if self.storage.add_post(post):
                added += 1
        return added

    # ------------------------------------------------------------------
    # Выбор и публикация
    # ------------------------------------------------------------------
    def domain_order(self) -> List[str]:
        domains = list(self.config.domains)
        if not domains:
            return ["math", "physics", "cs"]
        if self.config.raw.get("selection") == "thompson":
            selected = self.sota.select_domain_thompson(tuple(domains))
            return [selected] + [domain for domain in domains if domain != selected]
        last = self.storage.last_published()
        if last and last.domain in domains:
            index = domains.index(last.domain)
            return domains[index + 1 :] + domains[: index + 1]
        return domains

    def choose_next(self, domain: str | None = None) -> Optional[Post]:
        """Выбор поста: сначала фундамент по ступеням, затем маятник по сложности.

        Закон причинности: пост выходит, только если его родители (`prereq_ids`)
        уже опубликованы. Если так вышло, что вся очередь ждёт родителей,
        причинность уступает непрерывности эфира — с честным предупреждением.
        """
        from .curriculum import is_foundation, order_posts, open_posts, published_ids

        ready = self.storage.list_posts(status="ready", limit=300, order="created_at ASC")
        if domain:
            ready = [post for post in ready if post.domain == domain]
        if not ready:
            return self.storage.next_ready(domain)
        allowed = open_posts(ready, published_ids(self.storage))
        if allowed:
            ready = allowed
        else:
            LOGGER.warning("Все готовые посты ждут родителей — беру ближайший по ступеням")
        # 1) Узлы фундамента выходят строго по ступеням (Пифагор → Евклид → Архимед …).
        foundation = [post for post in ready if is_foundation(post)]
        if foundation:
            return order_posts(foundation)[0]
        # 2) Дальше — маятник дисциплин, внутри дисциплины от простого к сложному.
        for candidate_domain in self.domain_order():
            if domain and candidate_domain != domain:
                continue
            pool = [post for post in ready if post.domain == candidate_domain]
            if pool:
                return order_posts(pool)[0]
        return order_posts(ready)[0]

    def _video_mode(self, requested: Optional[bool]) -> bool:
        """Видео-режим: явный флаг, иначе каждый N-й пост по настройке video."""
        if requested is not None:
            return bool(requested)
        from .video import video_settings

        settings = video_settings(self.config)
        if not settings["enabled"]:
            return False
        counter = self.storage.kv_int("video_counter", 0) + 1
        self.storage.kv_set("video_counter", str(counter))
        every = max(1, settings["every_nth_post"])
        return counter % every == 0

    @staticmethod
    def _deferred(reason: str, detail: str, **extra: Any) -> Dict[str, Any]:
        """Отложенная публикация — это НЕ сбой.

        Гейт (Hawkes) может попросить подождать: планировщик просто вернётся
        позже. Возвращаем `ok=True` + `deferred=True`, чтобы шаг CI не падал и
        оператор не получал ложный алерт; причина остаётся в `error`/`reason`.
        """
        payload: Dict[str, Any] = {
            "ok": True,
            "deferred": True,
            "reason": reason,
            "error": detail,
            "post": None,
            "card": None,
            "results": [],
        }
        payload.update(extra)
        return payload

    @_state_locked
    def publish_next(
        self,
        dry_run: bool = False,
        domain: str | None = None,
        targets: Optional[Iterable[str]] = None,
        force: bool = False,
        build_site: bool = True,
        post_id: str | None = None,
        video: Optional[bool] = None,
    ) -> Dict[str, Any]:
        if self.storage.kv_get("paused", "0") == "1" and not force:
            return {"ok": False, "error": "публикация на паузе"}

        if self.d1_primary_enabled():
            self.pull_state()

        if not force and not dry_run:
            last = self.storage.last_published()
            min_value = self.config.raw.get("publish_min_interval_hours", 3)
            min_hours = 3.0 if min_value is None else float(min_value)
            if last and last.published_at:
                try:
                    last_at = datetime.fromisoformat(str(last.published_at))
                    if last_at.tzinfo is None:
                        last_at = last_at.replace(tzinfo=timezone.utc)
                    age_h = (datetime.now(timezone.utc) - last_at).total_seconds() / 3600
                    if 0 <= age_h < min_hours:
                        return self._deferred(
                            "slot",
                            f"слот уже закрыт: последняя публикация {age_h:.1f} ч назад",
                        )
                except ValueError:
                    pass

        hawkes = self.config.raw.get("hawkes") or {}
        if hawkes.get("enabled") and not force:
            hawkes_state = self.sota.check_hawkes_ready(
                beta_per_hour=float(hawkes.get("beta_per_hour", 0.38)),
                eps=float(hawkes.get("eps", 0.45)),
            )
            if not hawkes_state["ready"]:
                # Гейт Hawkes — это ОТЛОЖЕНИЕ, а не сбой: планировщик вернётся
                # позже (волна затухнет или пройдёт 6 часов). `--force` обходит.
                return self._deferred(
                    "hawkes",
                    f"Hawkes: остаточная волна {hawkes_state['residual_wave']}",
                    hours_since_last=hawkes_state.get("hours_since_last"),
                )

        if post_id:
            post = self.storage.get_post(post_id)
            if not post:
                return {"ok": False, "error": f"пост {post_id} не найден"}
            if post.status != "ready" and not force:
                return {"ok": False, "error": f"пост {post_id} в статусе {post.status}"}
        else:
            post = self.choose_next(domain)
        if not post:
            self.harvest(domains=[domain] if domain else None, include_offline=False)
            post = self.storage.get_post(post_id) if post_id else self.choose_next(domain)
        if not post:
            self._harvest_offline(domain)
            post = self.choose_next(domain) or self.choose_next()
        if not post:
            return {"ok": False, "error": "нет готовых постов"}

        variant = None
        if ab_enabled(self.config):
            variant = choose_variant(post.id, variants_from_config(self.config))
            post.meta["style_variant"] = variant
            try:
                self.storage.set_post_meta(post.id, "style_variant", variant)
            except Exception as exc:  # A/B не должен блокировать публикацию
                LOGGER.warning("Не удалось записать style_variant: %s", exc)

        # Математический движок сигналов: объём поста против ёмкости канала.
        signal_cfg = dict(self.config.raw.get("signal_engine") or {})
        auto_visual = bool(signal_cfg.get("auto_visual", False))
        auto_visual_ratio = float(signal_cfg.get("auto_visual_ratio", 1.8))
        try:
            from .platforms_info import PlatformRules
            from .signal_engine import SignalVolumeMatcher

            volume = SignalVolumeMatcher(self.config).match_volume(
                post, "telegram", PlatformRules.load(self.storage, self.config)
            )
            post.meta["signal_volume"] = volume
            if auto_visual and not volume["fits"] and float(volume.get("ratio", 0)) >= auto_visual_ratio:
                post.meta["signal_visual_mode"] = volume["recommended_mode"]
        except Exception as exc:  # pragma: no cover
            LOGGER.debug("Signal volume: %s", exc)

        # Дизайн выпуска: реестр тем (academic/3b1b/blueprint/moku3d/bookfilm).
        # В режиме `auto` стиль выбирает бандит Томпсона, иначе — фиксация оператора.
        from .themes import is_auto, record_reward, theme_for_post

        theme = theme_for_post(self.storage, self.config)
        if auto_visual and is_auto(self.config) and post.meta.get("signal_visual_mode") == "bookfilm":
            theme = "bookfilm"
        archetype = ""
        try:
            from .cards_academic import pick_visual_type

            archetype = pick_visual_type(post)
        except Exception:
            archetype = ""
        design = {
            "theme": theme,
            "archetype": archetype,
            "format": "film" if theme in ("moku3d", "explainer") else "card",
        }
        post.meta["design_variant"] = design
        # Режим подачи (психология ленты): задача выходит дозированно.
        from .post_modes import mode_for_post

        post.meta["post_mode"] = mode_for_post(self.storage, self.config, post, theme=theme)
        design["mode"] = post.meta["post_mode"]

        # Живые датчики Планеты и Космоса (без ключей) — по конфигу.
        from .live_sensors import enable as enable_sensors

        enable_sensors(bool((self.config.raw.get("live_sensors") or {}).get("enabled", True)))
        try:
            self.storage.set_post_meta(post.id, "design_variant", design)
        except Exception as exc:  # дизайн не должен блокировать публикацию
            LOGGER.warning("Не удалось записать design_variant: %s", exc)

        card_path = self.config.cards_dir / f"{post.id}.png"
        try:
            card = render_card(
                post,
                out_path=card_path,
                size=int(self.config.card.get("size", 1080)),
                ssaa=int(self.config.card.get("ssaa", 2)),
                variant=variant,
                engine=str(self.config.card.get("engine", "auto")),
                theme=theme,
            )
        except Exception as exc:
            LOGGER.exception("Не удалось отрисовать карточку %s", post.id)
            self.storage.mark_failed(post.id, f"render: {exc}")
            return {"ok": False, "error": f"render: {exc}", "post": post}

        # Паспорт «Тройной связи времени»: ссылки на уже опубликованный фундамент.
        from .evolve import EvolutionEngine

        EvolutionEngine(self).prepare(post)

        # Контур качества: 7-рубежный StandardsChecker перед публикацией.
        from .publishers.base import build_caption
        from .standards import StandardsChecker

        checker = StandardsChecker.load(self.storage, self.config)
        baseline = build_caption(post, limit=1020, html=True, site_url=self.config.site_base_url)
        if dry_run:
            report = checker.check(post, baseline, card)
            if not report.ok:
                post, healed, _notes = checker.heal(post, baseline)
                report = checker.check(post, healed, card)
                baseline = healed
        else:
            report, post, baseline = checker.enforce(post, baseline, card, self.storage)
            if not report.ok:
                reason = "; ".join(f"{item.code}: {item.detail}" for item in report.violations)[:300]
                return {"ok": False, "error": f"standards: {reason}", "post": post, "card": card,
                        "standards": report.as_dict()}
        if baseline and baseline != build_caption(post, limit=1020, html=True, site_url=self.config.site_base_url):
            post.meta["caption_override"] = baseline
            try:
                self.storage.set_post_meta(post.id, "caption_override", baseline)
            except Exception as exc:
                LOGGER.warning("Не удалось сохранить вылеченную подпись: %s", exc)

        if dry_run:
            if build_site:
                try:
                    self.build_site()
                except Exception as exc:
                    LOGGER.warning("Сайт не пересобран: %s", exc)
            return {"ok": True, "dry_run": True, "post": post, "card": card, "results": []}

        available = set(self.publishers.available_platforms())
        requested = {targets} if isinstance(targets, str) else set(targets or [])
        if requested:
            available = available & requested
        if not available:
            return {
                "ok": False,
                "error": "нет доступных площадок: заполните .env или запустите --dry-run",
                "post": post,
                "card": card,
                "results": [],
            }

        self.storage.mark_publishing(post.id)
        public_card_url = ""
        if self.config.site_base_url:
            public_card_url = f"{self.config.site_base_url}/cards/{post.id}.png"

        results = self.publishers.publish(
            post,
            card,
            site_url=self.config.site_base_url,
            public_card_url=public_card_url,
            targets=targets,
            video=self._video_mode(video),
        )
        any_ok = any(result.ok for result in results)
        telegram_file_id = ""
        for result in results:
            if result.platform == "telegram" and result.ok:
                telegram_file_id = str((result.meta or {}).get("file_id") or "")
        telegram_file_id = telegram_file_id or post.card_file_id
        error = ""

        if any_ok:
            self.storage.mark_published(post.id, card_path=str(card.path), card_file_id=telegram_file_id)
            if hawkes.get("enabled"):
                self.sota.record_hawkes_fire(beta_per_hour=float(hawkes.get("beta_per_hour", 0.38)))
            bandit = self.config.raw.get("bandit") or {}
            if bandit.get("enabled"):
                self.sota.reward_domain(post.domain, success=True)
            record_reward(self.storage, theme, success=True)
        else:
            error = "; ".join(f"{r.platform}: {r.error}" for r in results if r.error)[:500]
            self.storage.mark_failed(post.id, error or "все площадки недоступны")
            bandit = self.config.raw.get("bandit") or {}
            if bandit.get("enabled"):
                self.sota.reward_domain(post.domain, success=False)
            record_reward(self.storage, theme, success=False)

        # Контур РОС/УОС: сбой возвращается в накопитель, успех сбрасывает счётчик.
        try:
            from .signal_engine import FeedbackControllerUOS

            feedback = FeedbackControllerUOS(self.storage, self.config).on_publish(post, any_ok, error)
            if not any_ok and feedback.get("action") == "requeue":
                requeued = self.storage.requeue_failed(post.id)
                feedback["requeued"] = bool(requeued)
                LOGGER.info("РОС: пост %s возвращён в очередь: %s", post.id, requeued)
            self.storage.set_post_meta(post.id, "signal_feedback", feedback)
        except Exception as exc:  # pragma: no cover - движок не должен ломать публикацию
            LOGGER.warning("Signal feedback: %s", exc)

        # N+1 warm staging: сразу после успешной публикации готовим следующий
        # пост (лонгрид + паспорт + карточка + приёмка), чтобы он вышел «тёплым».
        if any_ok and bool((self.config.raw.get("staging") or {}).get("auto", False)):
            try:
                from .canon_gate import CanonGate

                staged = CanonGate(self.storage, self.config).stage_next(
                    self, enforce=False, render_card=False
                )
                LOGGER.info("N+1 staged: %s (ok=%s)", staged.get("post_id"), staged.get("ok"))
            except Exception as exc:  # pragma: no cover - защита публикации
                LOGGER.warning("N+1 staging не удался: %s", exc)

        # Нативная викторина канала: задача выпуска уходит опросом в реплай.
        if any_ok and bool((self.config.raw.get("telegram") or {}).get("quiz_poll", False)):
            try:
                quiz_result = self.send_quiz_poll(post, results)
                if quiz_result:
                    LOGGER.info("Викторина отправлена: %s", quiz_result.get("message_id"))
            except Exception as exc:  # pragma: no cover - защита публикации
                LOGGER.warning("Викторина не отправлена: %s", exc)

        if build_site:
            try:
                self.build_site()
            except Exception as exc:
                LOGGER.warning("Сайт не пересобран: %s", exc)

        if self.d1_primary_enabled():
            self.push_state()
        self.storage.checkpoint()
        return {
            "ok": any_ok,
            "post": post,
            "card": card,
            "results": [result.as_dict() for result in results],
        }

    def send_quiz_poll(
        self, post: Post, results: Optional[List[Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Отправляет нативную викторину (`sendPoll`) по задаче выпуска.

        Возвращает результат Telegram или `None`, если викторина недоступна
        (нет токена, нет числа в ответе, площадка отклонила запрос).
        """
        publisher = getattr(self.publishers, "publishers", {}).get("telegram")
        if publisher is None or not publisher.available():
            return None
        reply_to: Optional[Any] = None
        for result in results or []:
            if getattr(result, "platform", "") == "telegram":
                reply_to = (getattr(result, "meta", None) or {}).get("message_id")
                if reply_to:
                    break
        return publisher.send_poll(post, reply_to=reply_to)

    @_state_locked
    def run(
        self,
        dry_run: bool = False,
        harvest_if_low: bool = True,
        build_site: bool = True,
        domain: str | None = None,
    ) -> Dict[str, Any]:
        if harvest_if_low and self.storage.count("ready") < int(self.config.raw.get("low_water", 9)):
            self.harvest()
        result = self.publish_next(dry_run=dry_run, domain=domain, build_site=False)
        if build_site:
            try:
                self.build_site()
            except Exception as exc:
                LOGGER.warning("Сайт не пересобран: %s", exc)
        return result

    # ------------------------------------------------------------------
    # Сайт и статус
    # ------------------------------------------------------------------
    def build_site(self) -> Path:
        from .site import SiteBuilder

        builder = SiteBuilder(self.config, self.storage)
        return builder.build()

    def status(self) -> Dict[str, Any]:
        counts = self.storage.queue_counts()
        last = self.storage.last_published()
        return {
            "ready": self.storage.count("ready"),
            "published": self.storage.count("published"),
            "failed": self.storage.count("failed"),
            "by_domain": counts,
            "last": {
                "id": last.id,
                "title": last.title,
                "domain": last.domain,
                "published_at": last.published_at or None,
            }
            if last
            else None,
            "paused": self.storage.kv_get("paused", "0") == "1",
            "platforms": self.publishers.status(),
            "sources": self.sources.status(),
            "site_url": self.config.site_base_url,
        }
