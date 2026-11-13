"""Синхронизация CANON → неопубликованные записи posts."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from .models import make_id
from .sources.history_canon import CANON
from .storage import Storage

LOGGER = logging.getLogger(__name__)

FIELDS = ("formula_latex", "formula_plain", "visual_type", "scene_type", "prereq_ids", "symbols")


def sync_canon(storage: Storage, dry_run: bool = False) -> Dict[str, Any]:
    """Обновляет meta/formula только у status != published. Идемпотентно."""
    changed = 0
    skipped_published = 0
    missing = 0
    for node in CANON:
        post_id = make_id("history_canon", node["id"])
        post = storage.get_post(post_id)
        if post is None:
            missing += 1
            continue
        if post.status == "published":
            skipped_published += 1
            continue
        meta = dict(post.meta or {})
        updates: Dict[str, Any] = {}
        for field in FIELDS:
            if field in node and node[field] not in (None, "", [], {}):
                updates[field] = node[field]
        if "formula_latex" in updates and updates["formula_latex"] != post.formula_latex:
            storage.update_post_fields(post_id, {"formula_latex": updates["formula_latex"]})
        if "formula_plain" in updates and updates["formula_plain"] != post.formula_plain:
            storage.update_post_fields(post_id, {"formula_plain": updates["formula_plain"]})
        for key in ("visual_type", "scene_type", "prereq_ids", "symbols"):
            if key in updates and meta.get(key) != updates[key]:
                meta[key] = updates[key]
                if not dry_run:
                    storage.set_post_meta(post_id, key, updates[key])
                changed += 1
    return {
        "ok": True,
        "changed": changed,
        "skipped_published": skipped_published,
        "missing": missing,
        "dry_run": dry_run,
    }
