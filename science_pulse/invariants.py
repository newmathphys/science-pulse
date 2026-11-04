from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

from .storage import Storage

# Формат SimHash в БД: hex «0x…» (16 знаков) или legacy десятичное число.
SIMHASH_RE = re.compile(r"^(0x[0-9a-f]{16}|\d+)$")
# `rejected` — законный статус карантина (canon_gate / standards / пульт).
KNOWN_STATUSES = {"ready", "publishing", "published", "failed", "rejected"}


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
            self._inv8_causal_completeness,
        ]
        violations: List[Violation] = []
        for check in checks:
            violations.extend(check())
        return InvariantReport(checked=len(checks), violations=violations)

    def _query(self, sql: str, params: tuple = ()) -> List[Any]:
        with self.storage.cursor() as connection:
            return connection.execute(sql, params).fetchall()

    def _inv8_causal_completeness(self) -> List[Violation]:
        """INV-8: причинно-геодезическая полнота DAG канона.

        Каждый узел ступени > 1 обязан иметь пререквизит строго меньшей ступени
        и конечный гиперболический скачок ``d_ℍ ≤ R_max(ступень)``: в графе нет
        изолированных сирот вне корней Ступени I.
        """
        import math

        from .graph import canon_coordinates, hyperbolic_distance, max_hyperbolic_jump
        from .sources.foundation import CANON, default_prereqs, step_of

        nodes = [
            {"id": item["id"], "domain": item["domain"], "tier": step_of(item["id"])}
            for item in CANON
        ]
        coords = canon_coordinates(nodes)
        by_id = {node["id"]: node for node in nodes}
        violations: List[Violation] = []
        for node in nodes:
            tier = int(node["tier"])
            if tier <= 1:
                continue
            parents = default_prereqs(node["id"])
            if not parents:
                violations.append(Violation("INV-8", "узел ступени > 1 без пререквизитов", [node["id"]]))
                continue
            limit = max_hyperbolic_jump(tier)
            for parent in parents:
                parent_node = by_id.get(parent)
                if parent_node is None or int(parent_node["tier"]) >= tier:
                    violations.append(Violation("INV-8", "пререквизит не младше узла", [node["id"], parent]))
                    continue
                distance = hyperbolic_distance(coords[node["id"]], coords[parent])
                if not math.isfinite(distance) or distance > limit + 1e-9:
                    violations.append(
                        Violation("INV-8", f"скачок d_ℍ {distance:.2f} > R_max {limit:.2f}", [node["id"], parent])
                    )
        return violations

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
