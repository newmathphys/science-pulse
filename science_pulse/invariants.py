from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

from .storage import Storage

# Формат SimHash в БД: hex «0x…» (16 знаков) или legacy десятичное число.
SIMHASH_RE = re.compile(r"^(0x[0-9a-f]{16}|\d+)$")
KNOWN_STATUSES = {"ready", "publishing", "published", "failed"}


@dataclass
class Violation:
    code: str
    message: str
    detail: List[Any] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "detail": self.detail}


@dataclass
class InvariantReport:
    checked: int
    violations: List[Violation]

    @property
    def ok(self) -> bool:
        return not self.violations

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "checked": self.checked,
            "violations": [item.as_dict() for item in self.violations],
        }


class InvariantChecker:
    """Исполняемые инварианты состояния (Lean-спецификация — docs/INVARIANTS.md).

    Проверяет safety-свойства поверх SQLite: идемпотентность публикаций,
    целостность статусов, формат SimHash и отсутствие «сирот».
    """

    def __init__(self, storage: Storage):
        self.storage = storage

    def check(self) -> InvariantReport:
        checks: List[Callable[[], List[Violation]]] = [
            self._inv1_idempotent_publications,
            self._inv2_published_has_publication,
            self._inv3_no_orphan_file_id,
            self._inv4_known_statuses,
            self._inv5_simhash_format,
            self._inv6_no_orphans,
        ]
        violations: List[Violation] = []
        for check in checks:
            violations.extend(check())
        return InvariantReport(checked=len(checks), violations=violations)

    def _query(self, sql: str, params: tuple = ()) -> List[Any]:
        with self.storage.cursor() as connection:
            return connection.execute(sql, params).fetchall()

    def _inv1_idempotent_publications(self) -> List[Violation]:
        rows = self._query(
            "SELECT post_id, platform, COUNT(*) AS c FROM publications "
            "WHERE status = 'ok' GROUP BY post_id, platform HAVING c > 1"
        )
        return [
            Violation("INV-1", "дубликат успешной публикации", [row["post_id"], row["platform"], row["c"]])
            for row in rows
        ]

    def _inv2_published_has_publication(self) -> List[Violation]:
        rows = self._query(
            "SELECT p.id FROM posts p WHERE p.status = 'published' AND NOT EXISTS "
            "(SELECT 1 FROM publications pub WHERE pub.post_id = p.id AND pub.status = 'ok')"
        )
        return [Violation("INV-2", "published-пост без успешной публикации", [row["id"]]) for row in rows]

    def _inv3_no_orphan_file_id(self) -> List[Violation]:
        """`card_file_id` не может «висеть» без успешной telegram-публикации.

        Обратное неверно: Telegram может отдать `ok` без фото (текстовый
        fallback), поэтому отсутствие `file_id` — не нарушение.
        """
        rows = self._query(
            "SELECT p.id, p.card_file_id FROM posts p WHERE COALESCE(p.card_file_id, '') != '' "
            "AND NOT EXISTS (SELECT 1 FROM publications pub WHERE pub.post_id = p.id "
            "AND pub.platform = 'telegram' AND pub.status = 'ok')"
        )
        return [
            Violation("INV-3", "card_file_id без успешной telegram-публикации", [row["id"], row["card_file_id"]])
            for row in rows
        ]

    def _inv4_known_statuses(self) -> List[Violation]:
        rows = self._query("SELECT DISTINCT status FROM posts")
        return [
            Violation("INV-4", "неизвестный статус поста", [row["status"]])
            for row in rows
            if row["status"] not in KNOWN_STATUSES
        ]

    def _inv5_simhash_format(self) -> List[Violation]:
        rows = self._query("SELECT hash, simhash FROM seen WHERE COALESCE(simhash, '') != ''")
        return [
            Violation("INV-5", "некорректный формат SimHash", [row["hash"], row["simhash"]])
            for row in rows
            if not SIMHASH_RE.match(str(row["simhash"]))
        ]

    def _inv6_no_orphans(self) -> List[Violation]:
        metrics = self._query(
            "SELECT m.id FROM metrics m WHERE NOT EXISTS (SELECT 1 FROM posts p WHERE p.id = m.post_id)"
        )
        publications = self._query(
            "SELECT pub.id FROM publications pub WHERE NOT EXISTS (SELECT 1 FROM posts p WHERE p.id = pub.post_id)"
        )
        return [Violation("INV-6", "метрика без поста", [row["id"]]) for row in metrics] + [
            Violation("INV-6", "публикация без поста", [row["id"]]) for row in publications
        ]
