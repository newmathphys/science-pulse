"""Центральное детерминированное ядро Science Pulse (`SciencePulseKernel`).

Ядро сводит все подсистемы проекта в **один предсказуемый 6-фазный цикл**
(`run_cycle`) и выдаёт полный паспорт состояния (`status_report`). Никаких
«болтливых ИИ-агентов» в рантайме: конечный автомат, детерминированные
источники и проверяемые инварианты.

| Фаза | Что делает | Подсистемы |
|:--|:--|:--|
| 1 `canon` | гарантирует 30 узлов канона и добирает темы курса `§ 11.1 … § 55.3` | `sources/foundation`, `sources/curriculum_crawler`, `syllabus_tree` |
| 2 `selection` | выбирает следующий узел по блоку Каданова и часам эпохи, строит лонгрид и вычислительный паспорт | `sota`, `enricher`, `post_proof` |
| 3 `script` | собирает 5-блочный лекционный сценарий и двухслойный звук | `voice`, `sound` |
| 4 `gate` | приёмочная комиссия `CanonGate` (Pass 1/2) и пред-подготовка `N+1` | `canon_gate` |
| 5 `atlas` | пересобирает атлас сайта: все главы канона, Диск Пуанкаре, Вечное Радио, подкаст | `site`, `radio`, `graph` |
| 6 `telemetry` | метрики, инварианты `INV-1…INV-8`, формальная печать | `metrics`, `invariants`, `formal` |
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from .config import Config
from .invariants import InvariantChecker
from .models import Post
from .radio import radio_status
from .signal_engine import signal_status
from .sota import epoch_slot_index, kadanov_block, preferred_domain
from .storage import Storage
from .syllabus_tree import syllabus_summary

LOGGER = logging.getLogger(__name__)

PHASES = ("canon", "selection", "script", "gate", "atlas", "telemetry")


class SciencePulseKernel:
    """Детерминированное ядро: 6 фаз, один паспорт состояния."""

    def __init__(self, config: Config, storage: Storage, pipeline: Any = None):
        self.config = config
        self.storage = storage
        self._pipeline = pipeline

    # ------------------------------------------------------------------
    # Служебное
    # ------------------------------------------------------------------
    @property
    def pipeline(self) -> Any:
        if self._pipeline is None:
            from .pipeline import Pipeline

            try:
                self._pipeline = Pipeline(self.config, storage=self.storage)
            except TypeError:  # pragma: no cover - совместимость сигнатур
                self._pipeline = Pipeline(self.config)
        return self._pipeline

    def schedule(self) -> List[str]:
        raw = self.config.raw.get("schedule") or ["09:00", "13:00", "17:00", "21:00"]
        return [str(item) for item in raw] or ["09:00"]

    def current_slot(self) -> Dict[str, Any]:
        """Текущий слот расписания по «часам Вселенной» + блок Каданова."""
        slots = self.schedule()
        index = epoch_slot_index() % len(slots)
        slot = slots[index]
        block = kadanov_block(slot)
        return {
            "slot": slot,
            "index": index,
            "epoch_slot": epoch_slot_index(),
            "layer": block.get("layer"),
            "domain": preferred_domain(slot) or block.get("domain") or "",
        }

    def _safe(self, func: Any, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """Фаза не должна ронять цикл: ошибка фиксируется в отчёте."""
        started = time.perf_counter()
        try:
            result = func(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - защита цикла
            LOGGER.warning("Фаза %s: %s", getattr(func, "__name__", func), exc)
            return {"ok": False, "error": str(exc), "seconds": round(time.perf_counter() - started, 3)}
        payload = dict(result or {})
        payload.setdefault("ok", True)
        payload["seconds"] = round(time.perf_counter() - started, 3)
        return payload

    # ------------------------------------------------------------------
    # Фаза 1: канон и фрактальное ветвление
    # ------------------------------------------------------------------
    def canon_coverage(self) -> Dict[str, Any]:
        """Покрытие канона: сколько узлов уже есть в базе и сколько открыто."""
        from .sources.foundation import ordered_nodes, section_of

        nodes = ordered_nodes()
        by_id: Dict[str, Any] = {}
        for post in self.storage.list_posts(limit=2000):
            canon_id = str((post.meta or {}).get("foundation_id") or "")
            if canon_id:
                by_id[canon_id] = post
        present = [str(node["id"]) for node in nodes if str(node["id"]) in by_id]
        published = [
            str(node["id"]) for node in nodes
            if str(node["id"]) in by_id and by_id[str(node["id"])].status == "published"
        ]
        missing = [str(node["id"]) for node in nodes if str(node["id"]) not in by_id]
        next_section = ""
        for node in nodes:
            post = by_id.get(str(node["id"]))
            if post is not None and post.status != "published":
                next_section = section_of(str(node["id"]))
                break
        return {
            "canon_total": len(nodes),
            "present": len(present),
            "published": len(published),
            "missing": missing,
            "next_section": next_section,
        }

    def phase_canon(self, expand: bool = True, expand_count: Optional[int] = None,
                    deep: bool = False, deep_depth: int = 1) -> Dict[str, Any]:
        """Гарантирует канон в базе и добирает темы университетского курса."""
        from .sources.foundation import FoundationSource, ordered_nodes

        coverage = self.canon_coverage()
        ensured = 0
        if coverage["missing"]:
            source = FoundationSource(self.config)
            for index, node in enumerate(ordered_nodes()):
                if str(node["id"]) not in coverage["missing"]:
                    continue
                try:
                    posts = source.fetch(limit=1, cycle=index)
                except Exception as exc:  # pragma: no cover - данные/сеть
                    LOGGER.info("Канон: узел %s не добавлен (%s)", node["id"], exc)
                    continue
                for post in posts:
                    if self.storage.add_post(post):
                        ensured += 1
        expansion: Dict[str, Any] = {"syllabus_added": 0}
        if expand:
            expansion = self.expand_syllabus(count=expand_count)
        deep_report: Dict[str, Any] = {"deep_added": 0}
        if deep:
            deep_report = self.expand_deep(count=expand_count or 10, depth=deep_depth)
        return {**self.canon_coverage(), "ensured": ensured, **expansion, **deep_report}

    def expand_syllabus(self, count: Optional[int] = None) -> Dict[str, Any]:
        """Бесконечный насос: добавляет следующие темы `§ 11.1 … § 55.3` в очередь."""
        from .sources.curriculum_crawler import CurriculumCrawlerSource

        ready = self.storage.count("ready")
        low_water = int(self.config.raw.get("low_water", 9))
        limit = int(count) if count is not None else max(0, low_water * 2 - ready)
        if limit <= 0:
            return {
                "syllabus_added": 0,
                "ready": ready,
                "cursor": self.storage.kv_int("curriculum_cursor", 0),
            }
        cursor = self.storage.kv_int("curriculum_cursor", 0)
        source = CurriculumCrawlerSource(self.config)
        added = 0
        posts = source.fetch(limit=limit, cycle=cursor)
        for post in posts:
            if self.storage.add_post(post):
                added += 1
        self.storage.kv_set("curriculum_cursor", cursor + len(posts))
        return {
            "syllabus_added": added,
            "ready": self.storage.count("ready"),
            "cursor": cursor + len(posts),
        }

    def expand_deep(self, count: int = 10, depth: int = 1) -> Dict[str, Any]:
        """Рекурсивный обход «источников источников» (подкатегории Википедии).

        Работает только при наличии сети: без HTTP-клиента честно возвращает
        `reason="нет сети"` и ничего не выдумывает. Найденные темы становятся
        обычными постами очереди — их достраивает наш контур (лонгрид, паспорт,
        задача, карточка).
        """
        getter = self.http_getter()
        if getter is None:
            return {"deep_added": 0, "reason": "нет HTTP-клиента (офлайн-режим)"}
        from .sources.curriculum_crawler import RecursiveMetaCrawler

        try:
            crawler = RecursiveMetaCrawler(http_get=getter)
            candidates = crawler.discover(depth=depth)
        except Exception as exc:  # pragma: no cover - сеть
            return {"deep_added": 0, "reason": f"обход не удался: {exc}"}
        if not candidates:
            return {"deep_added": 0, "reason": "категории не вернули новых тем"}
        cursor = self.storage.kv_int("deep_cursor", 0)
        window = candidates[cursor: cursor + max(1, int(count))]
        added = 0
        for offset, item in enumerate(window):
            try:
                post = self._deep_post(item, cursor + offset)
            except Exception as exc:  # pragma: no cover - защита
                LOGGER.info("Глубокая тема пропущена: %s", exc)
                continue
            if self.storage.add_post(post):
                added += 1
        self.storage.kv_set("deep_cursor", cursor + len(window))
        return {
            "deep_added": added,
            "deep_cursor": cursor + len(window),
            "deep_seen": len(candidates),
            "depth": depth,
        }

    def _deep_post(self, item: Dict[str, Any], index: int) -> Post:
        """Пост из темы, найденной рекурсивным обходом категорий."""
        from urllib.parse import quote

        from .curriculum import annotate
        from .models import make_id

        title = str(item.get("title") or "").strip() or f"Тема {index}"
        domain = str(item.get("domain") or "math")
        post = Post(
            id=make_id("deep", f"{title}#{index}"),
            domain=domain if domain in ("math", "physics", "cs") else "math",
            title=title,
            hook=f"Что такое «{title}» и где это работает в XXI веке?",
            body=(
                "Тема найдена рекурсивным обходом научных категорий (мета-каталоги "
                "Википедии). Выпуск собирает наше ядро: формулировка, разбор величин, "
                "численная проверка и задача для читателя."
            ),
            source_name="Рекурсивный обход категорий",
            source_url=f"https://ru.wikipedia.org/wiki/{quote(title)}",
            tier="online",
            quality=0.55,
        )
        post.meta.update({
            "deep_origin": str(item.get("origin") or "wiki-category"),
            "deep_depth": item.get("depth"),
        })
        try:
            annotate(post)
        except Exception:  # pragma: no cover - защита
            pass
        return post

    # ------------------------------------------------------------------
    # Фаза 2: кинетика выбора и вычислительное доказательство
    # ------------------------------------------------------------------
    def http_getter(self) -> Optional[Any]:
        """Сетевой геттер конвейера (для обогащения глав полным текстом Википедии).

        Возвращает `None`, если у конвейера нет HTTP-клиента: тогда лонгрид
        собирается офлайн из канона, и сборка остаётся детерминированной.
        """
        http = getattr(getattr(self.pipeline, "sources", None), "http", None)
        if http is None:
            return None
        for name in ("get_json", "get"):
            getter = getattr(http, name, None)
            if callable(getter):
                return getter
        return None

    def phase_selection(self, domain: Optional[str] = None) -> Dict[str, Any]:
        """Выбор следующего узла + лонгрид + вычислительный паспорт."""
        from .enricher import enrich_post_longread
        from .post_proof import build_post_proof

        slot = self.current_slot()
        target = domain or slot.get("domain") or None
        post = self.pipeline.choose_next(target)
        if post is None:
            post = self.storage.next_ready(target)
        if post is None:
            return {"chosen": None, "slot": slot}
        longread = enrich_post_longread(post, http_get=self.http_getter())
        proof = build_post_proof(post)
        self.storage.set_post_meta(post.id, "longread_body", longread)
        self.storage.set_post_meta(post.id, "proof", proof)
        try:
            from .platforms_info import PlatformRules
            from .signal_engine import SignalVolumeMatcher

            rules = PlatformRules.load(self.storage, self.config)
            volume = SignalVolumeMatcher(self.config).match_volume(post, "telegram", rules)
            self.storage.set_post_meta(post.id, "signal_volume", volume)
        except Exception as exc:  # pragma: no cover
            LOGGER.debug("Signal volume: %s", exc)
        return {
            "chosen": {
                "id": post.id,
                "title": post.title,
                "domain": post.domain,
                "section": str((post.meta or {}).get("section_num") or ""),
            },
            "longread_chars": len(longread),
            "merkle": str(proof.get("merkle_hash") or "")[:16],
            "slot": slot,
        }

    # ------------------------------------------------------------------
    # Фаза 3: 5-блочный сценарий и двухслойный звук
    # ------------------------------------------------------------------
    def phase_script(self, post: Any = None, voice: bool = False) -> Dict[str, Any]:
        """Собирает 5-блочный лекционный сценарий (и, при желании, озвучку)."""
        from .voice import build_lecture_script, voice_available, voice_for_post

        if post is None:
            post = self.pipeline.choose_next(self.current_slot().get("domain") or None)
        if post is None:
            return {"post": None, "script_chars": 0}
        max_chars = int((self.config.raw.get("voice") or {}).get("max_chars", 750))
        script = build_lecture_script(post, max_chars=max_chars)
        artifact: Dict[str, Any] = {}
        if voice and voice_available(self.config):
            try:
                result = voice_for_post(post, self.config)
                if result is not None:
                    artifact = result.as_dict() if hasattr(result, "as_dict") else {"path": str(result)}
            except Exception as exc:  # pragma: no cover - внешний TTS
                LOGGER.info("Озвучка фазы 3 не удалась: %s", exc)
        blocks = sum(
            1 for marker in ("Раздел", "Фундаментальный вопрос", "Применение сегодня", "Эфир продолжается")
            if marker in script
        )
        entropy = {}
        try:
            from .signal_engine import ShannonTextCompressor

            entropy = ShannonTextCompressor().entropy_report(script)
            self.storage.set_post_meta(post.id, "signal_entropy", entropy)
        except Exception as exc:  # pragma: no cover
            LOGGER.debug("Signal entropy: %s", exc)
        return {"post": post.id, "script_chars": len(script), "blocks": blocks, "voice": artifact, "entropy": entropy}

    # ------------------------------------------------------------------
    # Фаза 4: приёмочная комиссия и пред-подготовка N+1
    # ------------------------------------------------------------------
    def phase_gate(self, post: Any = None, publish: bool = False) -> Dict[str, Any]:
        """Приёмка `CanonGate` (Pass 1/2) и пред-подготовка `N+1`.

        В режиме `publish=False` фаза НЕ мутирует состояние: она лишь сообщает
        готовность карточки (приёмка запускается при реальной публикации).
        """
        from .canon_gate import CanonGate

        gate = CanonGate(self.storage, self.config)
        if post is None:
            post = self.pipeline.choose_next(self.current_slot().get("domain") or None)
        result: Dict[str, Any] = {"post": getattr(post, "id", None)}
        if post is None:
            result["gate"] = {"ok": False, "dry_run": True, "reasons": ["очередь пуста"]}
            result["staged_next"] = self.storage.kv_get("staged_next_post_id", "")
            return result
        card = self.config.cards_dir / f"{post.id}.png"
        result["card_ready"] = card.is_file()
        if publish:
            try:
                report = gate.verify_and_enforce(post, card_path=str(card) if card.is_file() else "")
                result["gate"] = report if isinstance(report, dict) else {"ok": bool(report)}
            except Exception as exc:  # pragma: no cover - защита цикла
                result["gate"] = {"ok": False, "error": str(exc)}
            try:
                staged = gate.stage_next(self.pipeline)
                result["staged"] = staged if isinstance(staged, dict) else {"ok": bool(staged)}
            except Exception as exc:  # pragma: no cover - защита цикла
                result["staged"] = {"ok": False, "error": str(exc)}
        else:
            reasons = [] if result["card_ready"] else [
                "карточка ещё не отрендерена — приёмка Pass 2 запустится при публикации"
            ]
            result["gate"] = {"ok": True, "dry_run": True, "reasons": reasons}
        result["staged_next"] = self.storage.kv_get("staged_next_post_id", "")
        return result

    # ------------------------------------------------------------------
    # Фаза 5: атлас сайта, Диск Пуанкаре, Вечное Радио и подкаст
    # ------------------------------------------------------------------
    def phase_atlas(self, rebuild: bool = True) -> Dict[str, Any]:
        """Пересобирает атлас: все главы канона, атлас, радио, подкаст."""
        if not rebuild:
            return {"rebuilt": False}
        path = self.pipeline.build_site()
        posts = self.storage.list_posts(limit=2000)
        return {"rebuilt": True, "dist": str(path), "radio": radio_status(posts, self.config)}

    # ------------------------------------------------------------------
    # Фаза 6: телеметрия, инварианты и формальная печать
    # ------------------------------------------------------------------
    def phase_telemetry(self, formal: bool = False) -> Dict[str, Any]:
        """Метрики площадок, инварианты `INV-1…INV-8`, при желании — Lean."""
        report = InvariantChecker(self.storage).check()
        payload: Dict[str, Any] = {
            "invariants": report.as_dict(),
            "metrics": self.storage.metrics_summary(),
            "epoch_slot": epoch_slot_index(),
            "slot": self.current_slot(),
        }
        try:
            from .signal_engine import signal_status

            payload["signal_engine"] = signal_status(self.storage, self.config)
        except Exception as exc:  # pragma: no cover
            payload["signal_engine"] = {"ok": False, "error": str(exc)}
        if formal:
            try:
                from .formal import check_lean

                payload["formal"] = check_lean(self.config.root).as_dict()
            except Exception as exc:  # pragma: no cover - внешний Lean
                payload["formal"] = {"ok": False, "error": str(exc)}
        return payload

    # ------------------------------------------------------------------
    # Полный цикл и паспорт
    # ------------------------------------------------------------------
    def run_cycle(
        self,
        expand: bool = True,
        expand_count: Optional[int] = None,
        publish: bool = False,
        voice: bool = False,
        rebuild_site: bool = True,
        formal: bool = False,
        deep: bool = False,
        deep_depth: int = 1,
    ) -> Dict[str, Any]:
        """Полный 6-фазный цикл ядра (каждая фаза изолирована от падения)."""
        report: Dict[str, Any] = {}
        report["canon"] = self._safe(
            self.phase_canon, expand=expand, expand_count=expand_count,
            deep=deep, deep_depth=deep_depth,
        )
        report["selection"] = self._safe(self.phase_selection)
        chosen = report["selection"].get("chosen")
        post = None
        if isinstance(chosen, dict) and chosen.get("id"):
            post = self.storage.get_post(str(chosen["id"]))
        report["script"] = self._safe(self.phase_script, post, voice)
        report["gate"] = self._safe(self.phase_gate, post, publish)
        report["atlas"] = self._safe(self.phase_atlas, rebuild_site)
        report["telemetry"] = self._safe(self.phase_telemetry, formal)
        return report

    def status_report(self) -> Dict[str, Any]:
        """Паспорт состояния ядра: канон, курс, очередь, радио, инварианты."""
        posts = self.storage.list_posts(limit=2000)
        report = InvariantChecker(self.storage).check()
        return {
            "phases": list(PHASES),
            "slot": self.current_slot(),
            "canon": self.canon_coverage(),
            "syllabus": syllabus_summary(),
            "queue": {
                "ready": self.storage.count("ready"),
                "published": self.storage.count("published"),
                "failed": self.storage.count("failed"),
                "staged_next": self.storage.kv_get("staged_next_post_id", ""),
                "curriculum_cursor": self.storage.kv_int("curriculum_cursor", 0),
            },
            "radio": radio_status(posts, self.config),
            "invariants": report.as_dict(),
            "signal_engine": signal_status(self.storage, self.config),
            "paused": self.storage.kv_get("paused", "0") == "1",
        }

    def format_status(self, report: Optional[Dict[str, Any]] = None) -> str:
        """Человекочитаемый паспорт ядра (для `cli kernel --status`)."""
        data = report or self.status_report()
        canon = data["canon"]
        syllabus = data["syllabus"]
        radio = data["radio"]
        return "\n".join([
            "🧠 ЯДРО SCIENCE PULSE",
            f"  Фаз цикла: {len(data['phases'])} ({', '.join(data['phases'])})",
            f"  Такт эпохи: № {data['slot']['epoch_slot']} · слот {data['slot']['slot']}"
            f" · дисциплина {data['slot']['domain'] or 'синтез'}",
            f"  Канон: {canon['present']}/{canon['canon_total']} в базе, открыто {canon['published']}",
            f"  Курс: {syllabus['branches']} ветвей, {syllabus['topics']} тем"
            f" (§ {syllabus['first_section']} … § {syllabus['last_section']})",
            f"  Очередь: ready {data['queue']['ready']} · published {data['queue']['published']}"
            f" · failed {data['queue']['failed']}",
            f"  Следующий выпуск: § {canon['next_section'] or '—'}"
            f" · подготовлен: {data['queue']['staged_next'] or '—'}",
            f"  Радио: {radio['episodes']} выпусков (с озвучкой {radio['with_audio']}),"
            f" в эфире: {radio['now'] or '—'}",
            f"  Инварианты: {'✅ OK' if data['invariants']['ok'] else '❌ нарушения'}"
            f" ({data['invariants']['checked']} проверок)",
            f"  Сигналы: {'✅' if data.get('signal_engine', {}).get('enabled', True) else 'off'}"
            f" · УОС {data.get('signal_engine', {}).get('feedback', {}).get('mode', 'normal')}"
            f" · интервалы {'OK' if data.get('signal_engine', {}).get('multiplexer', {}).get('ok') else '—'}",
        ])
