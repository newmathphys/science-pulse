"""Движок эволюции: старт от фундамента, паспорт поста и обратные ссылки.

- `foundation_status()` — список первых постов (по ступеням) с их статусом;
- `evolve_step()` — следующий пост: неопубликованный узел фундамента по
  ступеням, иначе обычный выбор из очереди;
- `prepare(post)` — паспорт «Тройной связи времени»: эпоха/учёный (уже в meta),
  «Где работает сегодня» и кликабельные ссылки `🔗 Опирается на фундамент`
  на уже опубликованные родительские посты из `prereq_ids`;
- `used_in(post)` — обратные ссылки: кто из постов опирается на этот закон.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .models import Post
from .sources.foundation import FoundationSource, ordered_nodes, step_of, STEP_TITLES

LOGGER = logging.getLogger(__name__)


class EvolutionEngine:
    def __init__(self, pipeline: Any):
        self.pipeline = pipeline
        self.config = pipeline.config
        self.storage = pipeline.storage

    # ── ссылки ─────────────────────────────────────────────────────────────
    def telegram_url(self, post_id: str) -> str:
        """Публичная ссылка на сообщение канала (если пост опубликован)."""
        channel = str(self.config.telegram_channel or "").lstrip("@")
        if not channel:
            return ""
        for publication in self.storage.publications_for(post_id):
            if publication.get("platform") == "telegram" and publication.get("external_id"):
                return f"https://t.me/{channel}/{publication['external_id']}"
        return ""

    def prereq_links(self, post: Post) -> List[Tuple[str, str]]:
        """Кликабельные ссылки на уже опубликованные родительские посты."""
        links: List[Tuple[str, str]] = []
        for canon_id in (getattr(post, "meta", {}) or {}).get("prereq_ids") or []:
            parent_id = FoundationSource.post_id_for(str(canon_id))
            parent = self.storage.get_post(parent_id)
            if not parent or parent.status != "published":
                continue
            url = self.telegram_url(parent_id)
            if url:
                section = str((parent.meta or {}).get("section_num") or "").strip()
                short = parent.title.split(":")[0].strip() or parent.title
                name = f"§ {section} {short}".strip() if section else short
                links.append((name, url))
        return links

    def used_in(self, post: Post) -> List[Post]:
        """Обратные ссылки: посты, которые опираются на этот закон."""
        canon_id = (getattr(post, "meta", {}) or {}).get("canon_id")
        if not canon_id:
            return []
        result: List[Post] = []
        for other in self.storage.list_posts(limit=1000):
            if other.id == post.id:
                continue
            if canon_id in ((other.meta or {}).get("prereq_ids") or []):
                result.append(other)
        return result

    # ── паспорт поста ──────────────────────────────────────────────────────
    def prepare(self, post: Post) -> Post:
        """Заполняет паспорт: ссылки на фундамент для подписи и сайта."""
        links = self.prereq_links(post)
        if links:
            post.meta["prereq_links"] = links
            try:
                self.storage.set_post_meta(post.id, "prereq_links", links)
            except Exception as exc:
                LOGGER.warning("prereq_links не сохранены: %s", exc)
        return post

    # ── статус фундамента и шаг эволюции ───────────────────────────────────
    def foundation_status(self, limit: int = 9) -> List[Dict[str, Any]]:
        """Первые посты фундамента по ступеням с их статусом в базе."""
        source = FoundationSource(self.config)
        rows: List[Dict[str, Any]] = []
        for index, node in enumerate(ordered_nodes()[:limit]):
            post = source.fetch(limit=1, cycle=index)[0]
            db_post = self.storage.get_post(post.id)
            status = db_post.status if db_post else "нет в базе"
            rows.append({
                "step": step_of(node["id"]),
                "step_title": STEP_TITLES.get(step_of(node["id"]), ""),
                "id": post.id,
                "title": post.title,
                "domain": post.domain,
                "status": status,
            })
        return rows

    def evolve_step(self, domain: Optional[str] = None) -> Dict[str, Any]:
        """Один шаг: сначала неопубликованный фундамент по ступеням."""
        source = FoundationSource(self.config)
        for index, node in enumerate(ordered_nodes()):
            post = source.fetch(limit=1, cycle=index)[0]
            db_post = self.storage.get_post(post.id)
            if db_post is None:
                self.storage.add_post(post)
                return {"ok": True, "source": "foundation", "step": post.meta.get("step"),
                        "step_title": post.meta.get("step_title"), "post": post}
            if db_post.status == "ready":
                return {"ok": True, "source": "foundation", "step": db_post.meta.get("step"),
                        "step_title": db_post.meta.get("step_title"), "post": db_post}
        post = self.pipeline.choose_next(domain)
        if post is None:
            self.pipeline.harvest(domains=[domain] if domain else None)
            post = self.pipeline.choose_next(domain)
        return {"ok": post is not None, "source": "queue", "post": post}