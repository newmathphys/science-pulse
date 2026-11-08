"""SCM Knowledge Base — единая документальная память проекта.

SCM = Scientific Content Machine: источники → проверяемое знание → публикация →
сайт → метрики → коммерческая ветка. База хранит документы проекта, утверждения
со статусом доказанности, решения, заметки и метрики.

Принцип: **слово агента не доказательство**. Заметка или утверждение остаются
`unproven`, пока владелец не подписал их (`owner_signed=1`).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

LOGGER = logging.getLogger(__name__)

STATUSES = ("PROVEN", "EMPIRIC", "HYPOTHESIS", "REFUTED", "UNPROVEN")

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'doc',
    content TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    title, content, path UNINDEXED, tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'UNPROVEN',
    source TEXT NOT NULL DEFAULT '',
    owner_signed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'UNPROVEN',
    source TEXT NOT NULL DEFAULT '',
    owner_signed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'accepted',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS concepts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    domain TEXT NOT NULL DEFAULT 'scm',
    description TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    value REAL NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    collected_at TEXT NOT NULL
);
"""


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _title_of(path: Path, text: str) -> str:
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+)$", line.strip())
        if match:
            return match.group(1).strip()
    return path.stem.replace("_", " ").replace("-", " ").title()


@dataclass
class KnowledgeStats:
    documents: int
    claims: int
    notes: int
    decisions: int
    concepts: int
    links: int
    metrics: int
    fts_rows: int

    def as_dict(self) -> Dict[str, int]:
        return {
            "documents": self.documents,
            "claims": self.claims,
            "notes": self.notes,
            "decisions": self.decisions,
            "concepts": self.concepts,
            "links": self.links,
            "metrics": self.metrics,
            "fts_rows": self.fts_rows,
        }


class KnowledgeBase:
    def __init__(self, path: str | Path, root: str | Path | None = None):
        self.path = Path(path)
        self.root = Path(root) if root else Path.cwd()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _init_schema(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    # ------------------------------------------------------------------
    # Документы
    # ------------------------------------------------------------------
    def index_documents(self, root: str | Path, patterns: Optional[Iterable[str]] = None) -> Dict[str, int]:
        root = Path(root)
        self.root = root
        patterns = list(patterns or ("README.md", "AGENTS.md", "SCM.md", "docs/**/*.md", "config.yaml"))
        paths: List[Path] = []
        for pattern in patterns:
            paths.extend(root.glob(pattern))
        seen: set[Path] = set()
        indexed = 0
        skipped = 0
        with self.connect() as connection:
            for path in sorted(set(paths)):
                if not path.is_file() or path in seen:
                    continue
                seen.add(path)
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    skipped += 1
                    continue
                relative = str(path.relative_to(root))
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                title = _title_of(path, text)
                kind = "config" if path.suffix in (".yaml", ".yml") else "doc"
                row = connection.execute("SELECT id, sha256 FROM documents WHERE path = ?", (relative,)).fetchone()
                if row and row["sha256"] == digest:
                    skipped += 1
                    continue
                if row:
                    connection.execute(
                        "UPDATE documents SET title=?, kind=?, content=?, sha256=?, updated_at=? WHERE path=?",
                        (title, kind, text, digest, _utc_now(), relative),
                    )
                    connection.execute("DELETE FROM documents_fts WHERE path = ?", (relative,))
                else:
                    connection.execute(
                        "INSERT INTO documents(path, title, kind, content, sha256, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (relative, title, kind, text, digest, _utc_now()),
                    )
                connection.execute(
                    "INSERT INTO documents_fts(title, content, path) VALUES (?, ?, ?)",
                    (title, text, relative),
                )
                indexed += 1
        return {"indexed": indexed, "skipped": skipped, "total": len(seen)}

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []
        with self.connect() as connection:
            try:
                rows = connection.execute(
                    """
                    SELECT d.path, d.title, d.kind, snippet(documents_fts, 1, '…', '…', '…', 18) AS snippet,
                           bm25(documents_fts) AS rank
                    FROM documents_fts
                    JOIN documents d ON d.path = documents_fts.path
                    WHERE documents_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (query, max(1, int(limit))),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = connection.execute(
                    "SELECT path, title, kind, substr(content, 1, 220) AS snippet, 0 AS rank "
                    "FROM documents WHERE title LIKE ? OR content LIKE ? LIMIT ?",
                    (f"%{query}%", f"%{query}%", max(1, int(limit))),
                ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> KnowledgeStats:
        with self.connect() as connection:
            def count(table: str) -> int:
                return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

            return KnowledgeStats(
                documents=count("documents"),
                claims=count("claims"),
                notes=count("notes"),
                decisions=count("decisions"),
                concepts=count("concepts"),
                links=count("links"),
                metrics=count("metrics"),
                fts_rows=count("documents_fts"),
            )

    # ------------------------------------------------------------------
    # Утверждения и заметки
    # ------------------------------------------------------------------
    def add_claim(self, text: str, status: str = "UNPROVEN", source: str = "", owner_signed: bool = False) -> int:
        status = status.upper() if status.upper() in STATUSES else "UNPROVEN"
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO claims(text, status, source, owner_signed, created_at) VALUES (?, ?, ?, ?, ?)",
                (text.strip(), status, source, 1 if owner_signed else 0, _utc_now()),
            )
            return int(cursor.lastrowid)

    def add_note(self, text: str, source: str = "", status: str = "UNPROVEN", owner_signed: bool = False) -> int:
        status = status.upper() if status.upper() in STATUSES else "UNPROVEN"
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO notes(text, status, source, owner_signed, created_at) VALUES (?, ?, ?, ?, ?)",
                (text.strip(), status, source, 1 if owner_signed else 0, _utc_now()),
            )
            return int(cursor.lastrowid)

    def list_claims(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, text, status, source, owner_signed, created_at FROM claims ORDER BY id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_notes(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, text, status, source, owner_signed, created_at FROM notes ORDER BY id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Решения и метрики
    # ------------------------------------------------------------------
    def add_decision(self, title: str, decision: str, reason: str = "", status: str = "accepted") -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO decisions(title, decision, reason, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (title.strip(), decision.strip(), reason.strip(), status, _utc_now()),
            )
            return int(cursor.lastrowid)

    def list_decisions(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, title, decision, reason, status, created_at FROM decisions ORDER BY id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_metric(self, key: str, value: float, source: str = "") -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO metrics(key, value, source, collected_at) VALUES (?, ?, ?, ?)",
                (key, float(value), source, _utc_now()),
            )
            return int(cursor.lastrowid)

    # ------------------------------------------------------------------
    # Целостность
    # ------------------------------------------------------------------
    def integrity(self) -> Dict[str, Any]:
        stats = self.stats()
        issues: List[str] = []
        if stats.documents != stats.fts_rows:
            issues.append(f"documents={stats.documents} != fts_rows={stats.fts_rows}")
        with self.connect() as connection:
            missing = []
            for row in connection.execute("SELECT path FROM documents").fetchall():
                if not (self.root / row["path"]).exists():
                    missing.append(row["path"])
            if missing:
                issues.append(f"missing files: {len(missing)}")
            unsigned = connection.execute(
                "SELECT COUNT(*) FROM claims WHERE status IN ('PROVEN','EMPIRIC') AND owner_signed=0"
            ).fetchone()[0]
            if unsigned:
                issues.append(f"unsigned proven/empiric claims: {unsigned}")
        return {"ok": not issues, "issues": issues, "stats": stats.as_dict()}

    def export_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "stats": self.stats().as_dict(),
            "claims": self.list_claims(limit=1000),
            "notes": self.list_notes(limit=1000),
            "decisions": self.list_decisions(limit=1000),
            "integrity": self.integrity(),
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target


def format_stats(stats: KnowledgeStats) -> str:
    return "\n".join([
        "SCM Knowledge Base",
        f"  документы: {stats.documents}",
        f"  FTS-строки: {stats.fts_rows}",
        f"  утверждения: {stats.claims}",
        f"  заметки: {stats.notes}",
        f"  решения: {stats.decisions}",
        f"  концепты: {stats.concepts}",
        f"  связи: {stats.links}",
        f"  метрики: {stats.metrics}",
    ])


def format_search(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "Ничего не найдено."
    lines: List[str] = []
    for row in rows:
        lines.append(f"• {row['title']}  [{row['path']}]")
        snippet = str(row.get("snippet") or "").replace("\n", " ")
        if snippet:
            lines.append(f"  {snippet[:240]}")
    return "\n".join(lines)
