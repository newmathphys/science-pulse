"""Синхронизация CANON → posts + аудит причинности и очереди."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from .models import make_id
from .sources.foundation import (
    STEP_TITLES,
    FoundationSource,
    default_prereqs,
    section_of,
    step_of,
    year_of,
)
from .sources.history_canon import CANON
from .storage import Storage

LOGGER = logging.getLogger(__name__)

META_FIELDS = (
    "visual_type",
    "scene_type",
    "prereq_ids",
    "symbols",
    "era",
    "scientist",
    "modern_application",
    "concept",
    "constants_used",
    "step",
    "step_title",
    "section_num",
    "foundation_id",
    "canon_id",
)


def canonical_prereqs(node: Dict[str, Any]) -> List[str]:
    explicit = [str(value) for value in (node.get("prereq_ids") or []) if str(value).strip()]
    return explicit or default_prereqs(str(node["id"]))


def _scene_type(node: Dict[str, Any]) -> str:
    declared = str(node.get("scene_type") or node.get("visual_type") or "").strip()
    if declared:
        return declared
    if node.get("simulation"):
        return "diptych_insar"
    if node.get("timeline"):
        return "timeline_evolution"
    if node.get("table"):
        return "cheatsheet_table"
    if node.get("code"):
        return "code_booktabs"
    formula = f"{node.get('formula_latex', '')} {node.get('formula_plain', '')}"
    if any(symbol in formula for symbol in ("∀", "∃", "¬", "∧", "∨", "⇒", "\\forall", "\\exists")):
        return "logic_proof"
    return "standard_plot"


def canonical_meta(node: Dict[str, Any]) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "canon_id": node["id"],
        "step": step_of(node["id"]),
        "step_title": STEP_TITLES.get(step_of(node["id"]), "Дополнительно"),
        "section_num": section_of(node["id"]),
        "foundation_id": node["id"],
        "prereq_ids": canonical_prereqs(node),
        "scene_type": _scene_type(node),
    }
    for key in META_FIELDS:
        if key in ("prereq_ids", "step", "step_title", "section_num", "foundation_id", "canon_id"):
            continue
        if key in node and node[key] not in (None, "", [], {}):
            meta[key] = node[key]
    return meta


def _create_missing(storage: Storage, node: Dict[str, Any], dry_run: bool) -> bool:
    if dry_run:
        return False
    source = FoundationSource()
    post = source._history._build(node, CANON.index(node))
    post.tier = "foundation"
    post.source_name = f"Фундамент Науки · {node['scientist']}"
    post.meta.update(canonical_meta(node))
    post.quality = post.quality_score()
    return bool(storage.add_post(post))


def audit_canon(storage: Storage) -> Dict[str, Any]:
    """Сухой аудит: missing, анахронизмы, stale prereq, зависшие publishing."""
    missing: List[str] = []
    stale_prereqs: List[Dict[str, Any]] = []
    inversions: List[Dict[str, Any]] = []
    canon = {str(node["id"]): node for node in CANON}
    for node in CANON:
        post_id = make_id("history_canon", node["id"])
        post = storage.get_post(post_id)
        if post is None:
            missing.append(str(node["id"]))
            continue
        expected = canonical_prereqs(node)
        actual = [str(value) for value in ((post.meta or {}).get("prereq_ids") or [])]
        scene_actual = str((post.meta or {}).get("scene_type") or "")
        scene_expected = _scene_type(node)
        if post.status != "published" and (actual != expected or scene_actual != scene_expected):
            stale_prereqs.append({
                "canon_id": node["id"],
                "post_id": post_id,
                "actual": actual,
                "expected": expected,
                "scene_actual": scene_actual,
                "scene_expected": scene_expected,
            })
        node_year = year_of(node.get("era"))
        for parent_id in expected:
            parent = canon.get(parent_id)
            if not parent:
                continue
            parent_year = year_of(parent.get("era"))
            if node_year is not None and parent_year is not None and parent_year > node_year:
                inversions.append({
                    "canon_id": node["id"],
                    "year": node_year,
                    "parent_id": parent_id,
                    "parent_year": parent_year,
                })
    stuck = [
        {"id": post.id, "title": post.title, "created_at": post.created_at}
        for post in storage.list_posts(status="publishing", limit=100)
    ]
    return {
        "missing": missing,
        "stale_prereqs": stale_prereqs,
        "inversions": inversions,
        "stuck_publishing": stuck,
        "canon_total": len(CANON),
    }


def sync_canon(
    storage: Storage,
    dry_run: bool = False,
    create_missing: bool = False,
) -> Dict[str, Any]:
    """Обновляет meta/formula у status != published. Идемпотентно.

    ``create_missing`` добавляет в очередь узлы канона, которых нет в БД.
    """
    changed = 0
    skipped_published = 0
    missing = 0
    created = 0
    for node in CANON:
        post_id = make_id("history_canon", node["id"])
        post = storage.get_post(post_id)
        if post is None:
            missing += 1
            if create_missing and _create_missing(storage, node, dry_run):
                created += 1
                changed += 1
            continue
        if post.status == "published":
            skipped_published += 1
            continue

        meta = dict(post.meta or {})
        updates = canonical_meta(node)
        formula = node.get("formula_latex")
        if formula and formula != post.formula_latex:
            if not dry_run:
                storage.update_post_fields(post_id, {"formula_latex": formula})
            changed += 1
        formula_plain = node.get("formula_plain")
        if formula_plain and formula_plain != post.formula_plain:
            if not dry_run:
                storage.update_post_fields(post_id, {"formula_plain": formula_plain})
            changed += 1
        for key, value in updates.items():
            if meta.get(key) != value:
                meta[key] = value
                if not dry_run:
                    storage.set_post_meta(post_id, key, value)
                changed += 1

    report = {
        "ok": True,
        "changed": changed,
        "created": created,
        "skipped_published": skipped_published,
        "missing": missing,
        "dry_run": dry_run,
    }
    report["audit"] = audit_canon(storage)
    return report
