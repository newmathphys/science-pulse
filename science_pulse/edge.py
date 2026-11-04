from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

from .config import Config
from .graph import build_links, pagerank, poincare_layout
from .storage import Storage

LOGGER = logging.getLogger(__name__)


class EdgeSync:
    """Синхронизация карточек (R2) и узлов знаний (D1) через Cloudflare Worker.

    Шлёт `POST {CF_WORKER_URL}/api/ingest` с формой `meta` (JSON) + `png`.
    HTTP инъектируется, поэтому тесты идут без сети.
    """

    def __init__(
        self,
        config: Config,
        storage: Storage,
        http_post: Optional[Callable[..., Any]] = None,
    ):
        self.config = config
        self.storage = storage
        self._post = http_post or requests.post

    def available(self) -> bool:
        return bool(self.config.cf_worker_url and self.config.ingest_secret)

    def endpoint(self) -> str:
        return f"{self.config.cf_worker_url}/api/ingest"

    def _card_path(self, post) -> Path:
        raw = post.card_path or post.meta.get("card_path") or ""
        if raw and Path(raw).exists():
            return Path(raw)
        return self.config.cards_dir / f"{post.id}.png"

    def _node_meta(self, post, rank: Dict[str, float], layout: Dict[str, tuple[float, float]]) -> Dict[str, Any]:
        x, y = layout.get(post.id, (0.0, 0.0))
        return {
            "id": post.id,
            "domain": post.domain,
            "title": post.title,
            "hook": post.hook,
            "body": post.body,
            "formula": post.formula_latex or post.formula_plain,
            "js_fn": post.meta.get("js_fn", ""),
            "merkle_hash": post.meta.get("merkle_hash", ""),
            "pagerank": round(rank.get(post.id, 0.0), 9),
            "poincare_x": x,
            "poincare_y": y,
            "source_url": post.source_url,
        }

    def sync(self, limit: int = 20) -> Dict[str, Any]:
        if not self.available():
            return {
                "ok": False,
                "error": "CF_WORKER_URL/INGEST_SECRET не заданы",
                "pushed": 0,
                "failed": 0,
                "results": [],
            }

        posts = self.storage.list_posts(status="published", limit=limit)
        ids = [post.id for post in posts]
        rank = pagerank(ids, build_links(posts))
        layout = poincare_layout(ids, {post.id: post.domain for post in posts}, rank)
        headers = {"Authorization": f"Bearer {self.config.ingest_secret}"}
        endpoint = self.endpoint()

        pushed = 0
        failed = 0
        results: List[Dict[str, Any]] = []
        for post in posts:
            card = self._card_path(post)
            if not card.exists():
                results.append({"id": post.id, "ok": False, "error": "нет карточки"})
                failed += 1
                continue
            meta = self._node_meta(post, rank, layout)
            try:
                response = self._post(
                    endpoint,
                    headers=headers,
                    files={"png": ("card.png", card.read_bytes(), "image/png")},
                    data={"meta": json.dumps(meta, ensure_ascii=False)},
                    timeout=30,
                )
                status = getattr(response, "status_code", 0)
                ok = status in (200, 201, 204)
                results.append({"id": post.id, "ok": ok, "status": status})
                pushed += 1 if ok else 0
                failed += 0 if ok else 1
            except Exception as exc:
                LOGGER.warning("Edge ingest %s: %s", post.id, exc)
                results.append({"id": post.id, "ok": False, "error": str(exc)[:200]})
                failed += 1

        return {
            "ok": failed == 0,
            "pushed": pushed,
            "failed": failed,
            "endpoint": endpoint,
            "results": results,
        }
