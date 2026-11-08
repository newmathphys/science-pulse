from __future__ import annotations

import difflib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .models import Post, PublishResult, utc_now
from .text import hamming, simhash64

def _parse_simhash(value: Any) -> int:
    """Читает SimHash и из hex-строки, и из старого десятичного формата."""
    text = str(value or "0").strip().lower()
    if text.startswith("0x"):
        return int(text, 16)
    if len(text) == 16 and any(ch in "abcdef" for ch in text):
        return int(text, 16)
    return int(text)


# ----------------------------------------------------------------------
# CRDT-слияние состояния (Join-Semilattice): монотонные правила
# ----------------------------------------------------------------------

# Порядок статусов поста: старший статус «сильнее» и не откатывается.
STATUS_RANK = {"ready": 1, "publishing": 2, "failed": 3, "published": 4}
# Порядок статусов публикации: 'ok' всегда побеждает 'failed'/'skipped'/'error'.
PUBLICATION_RANK = {"error": 1, "skipped": 1, "failed": 2, "ok": 3}
# Ключи kv: управляющее состояние реплики не реплицируется.
KV_LOCAL_ONLY = {"paused", "tg_offset"}
# Ключи kv: монотонные счётчики — сливаются по максимуму.
KV_COUNTERS = {"harvest_cursor"}
KV_COUNTER_PREFIXES = ("cycle:",)
# Поля поста, сливаемые по правилу «непустое побеждает пустое».
POST_MERGE_TEXT = (
    "hook",
    "body",
    "formula_latex",
    "formula_plain",
    "code",
    "source_name",
    "source_url",
    "tier",
    "created_at",
    "scheduled_for",
    "published_at",
    "card_path",
    "card_file_id",
    "meta_json",
)


def _is_empty(value: Any) -> bool:
    return value is None or value == ""


def _join_text(a: Any, b: Any) -> Any:
    """Join строк: непустое побеждает пустое; при обоих непустых — max (детерминизм)."""
    if _is_empty(a):
        return b
    if _is_empty(b):
        return a
    return a if str(a) >= str(b) else b


def _join_num(a: Any, b: Any) -> Any:
    """Join чисел: максимум (None = отсутствие значения)."""
    if a is None:
        return b
    if b is None:
        return a
    try:
        return a if float(a) >= float(b) else b
    except (TypeError, ValueError):
        return _join_text(a, b)


def _upsert(connection: sqlite3.Connection, table: str, row: Dict[str, Any]) -> None:
    columns = list(row.keys())
    placeholders = ",".join("?" for _ in columns)
    connection.execute(
        f"INSERT OR REPLACE INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
        [row[column] for column in columns],
    )


def _join_post(local: Dict[str, Any] | None, remote: Dict[str, Any]) -> Dict[str, Any]:
    if not local:
        return dict(remote)
    merged = dict(local)
    if STATUS_RANK.get(str(remote.get("status")), 0) > STATUS_RANK.get(str(local.get("status")), 0):
        merged["status"] = remote["status"]
    for field in POST_MERGE_TEXT:
        merged[field] = _join_text(local.get(field), remote.get(field))
    merged["quality"] = _join_num(local.get("quality"), remote.get("quality"))
    return merged


def _join_publication(local: Dict[str, Any] | None, remote: Dict[str, Any]) -> Dict[str, Any]:
    if not local:
        return dict(remote)
    merged = dict(local)
    if PUBLICATION_RANK.get(str(remote.get("status")), 0) > PUBLICATION_RANK.get(str(local.get("status")), 0):
        merged["status"] = remote["status"]
    for field in ("external_id", "url", "error"):
        merged[field] = _join_text(local.get(field), remote.get(field))
    return merged


def _join_source(local: Dict[str, Any] | None, remote: Dict[str, Any]) -> Dict[str, Any]:
    if not local:
        return dict(remote)
    merged = dict(local)
    local_ok = str(local.get("last_ok") or "")
    remote_ok = str(remote.get("last_ok") or "")
    newer = remote if remote_ok > local_ok else local
    merged["last_ok"] = max(local_ok, remote_ok) or None
    merged["open_until"] = _join_num(local.get("open_until") or 0, remote.get("open_until") or 0)
    merged["last_error"] = newer.get("last_error")
    merged["failures"] = newer.get("failures")
    return merged



SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    hook TEXT,
    body TEXT,
    formula_latex TEXT,
    formula_plain TEXT,
    code TEXT,
    source_name TEXT,
    source_url TEXT,
    tier TEXT,
    quality REAL,
    status TEXT NOT NULL DEFAULT 'ready',
    created_at TEXT NOT NULL,
    scheduled_for TEXT,
    published_at TEXT,
    card_path TEXT,
    card_file_id TEXT,
    meta_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_posts_status_domain
    ON posts(status, domain, created_at);

CREATE TABLE IF NOT EXISTS publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    external_id TEXT,
    url TEXT,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(post_id, platform)
);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    platform TEXT NOT NULL,
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    replies INTEGER DEFAULT 0,
    collected_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_metrics_post_platform
    ON metrics(post_id, platform);

CREATE TABLE IF NOT EXISTS sources (
    name TEXT PRIMARY KEY,
    enabled INTEGER DEFAULT 1,
    last_ok TEXT,
    last_error TEXT,
    failures INTEGER DEFAULT 0,
    open_until REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS seen (
    hash TEXT PRIMARY KEY,
    post_id TEXT,
    simhash TEXT,
    title_norm TEXT,
    body_norm TEXT,
    created_at TEXT NOT NULL
);
"""


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def cursor(self):
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self.cursor() as connection:
            connection.executescript(SCHEMA)
            for column in ("simhash TEXT", "title_norm TEXT", "body_norm TEXT"):
                try:
                    connection.execute(f"ALTER TABLE seen ADD COLUMN {column}")
                except sqlite3.OperationalError:
                    pass

    # ------------------------------------------------------------------
    # Посты
    # ------------------------------------------------------------------
    def is_seen(self, fingerprint: str) -> bool:
        with self.cursor() as connection:
            row = connection.execute("SELECT 1 FROM seen WHERE hash = ?", (fingerprint,)).fetchone()
        return row is not None

    def add_post(self, post: Post, fingerprint: str | None = None) -> bool:
        fingerprint = fingerprint or post.fingerprint()
        row = post.to_row()
        row["quality"] = post.quality or post.quality_score()
        with self.cursor() as connection:
            existing = connection.execute("SELECT 1 FROM posts WHERE id = ?", (post.id,)).fetchone()
            if existing:
                return False
            if connection.execute("SELECT 1 FROM seen WHERE hash = ?", (fingerprint,)).fetchone():
                return False
            simhash = simhash64(f"{post.title} {post.body}")
            simhash_hex = f"0x{simhash:016x}"
            title_norm = post.title.lower().strip()
            body_norm = post.body[:400].lower().strip()
            recent = connection.execute(
                "SELECT simhash, title_norm, body_norm FROM seen ORDER BY created_at DESC LIMIT 200"
            ).fetchall()
            for seen_row in recent:
                if seen_row["simhash"] and hamming(simhash, _parse_simhash(seen_row["simhash"])) <= 3:
                    return False
                if seen_row["title_norm"] and seen_row["body_norm"]:
                    title_ratio = difflib.SequenceMatcher(None, title_norm, seen_row["title_norm"]).ratio()
                    body_ratio = difflib.SequenceMatcher(None, body_norm, seen_row["body_norm"]).ratio()
                    if title_ratio >= 0.55 and body_ratio >= 0.85:
                        return False
            connection.execute(
                """
                INSERT INTO posts
                (id, domain, title, hook, body, formula_latex, formula_plain, code,
                 source_name, source_url, tier, quality, status, created_at, meta_json)
                VALUES (:id, :domain, :title, :hook, :body, :formula_latex, :formula_plain,
                        :code, :source_name, :source_url, :tier, :quality, 'ready',
                        :created_at, :meta_json)
                """,
                row,
            )
            connection.execute(
                "INSERT OR IGNORE INTO seen(hash, post_id, simhash, title_norm, body_norm, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (fingerprint, post.id, simhash_hex, title_norm, body_norm, utc_now()),
            )
        return True

    def get_post(self, post_id: str) -> Optional[Post]:
        with self.cursor() as connection:
            row = connection.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        return Post.from_row(row) if row else None

    def list_posts(
        self,
        status: str | None = None,
        domain: str | None = None,
        limit: int = 50,
        order: str = "created_at DESC",
    ) -> List[Post]:
        clauses: List[str] = []
        params: List[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if domain:
            clauses.append("domain = ?")
            params.append(domain)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        allowed_order = {
            "created_at DESC",
            "created_at ASC",
            "published_at DESC",
            "quality DESC",
        }
        if order not in allowed_order:
            order = "created_at DESC"
        with self.cursor() as connection:
            rows = connection.execute(
                f"SELECT * FROM posts {where} ORDER BY {order} LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [Post.from_row(row) for row in rows]

    def next_ready(self, domain: str | None = None) -> Optional[Post]:
        sql = "SELECT * FROM posts WHERE status = 'ready'"
        params: List[Any] = []
        if domain:
            sql += " AND domain = ?"
            params.append(domain)
        sql += " ORDER BY quality DESC, created_at ASC LIMIT 1"
        with self.cursor() as connection:
            row = connection.execute(sql, params).fetchone()
        return Post.from_row(row) if row else None

    def queue_counts(self) -> Dict[str, int]:
        with self.cursor() as connection:
            rows = connection.execute(
                "SELECT domain, COUNT(*) AS count FROM posts WHERE status = 'ready' GROUP BY domain"
            ).fetchall()
        return {row["domain"]: int(row["count"]) for row in rows}

    def count(self, status: str | None = None) -> int:
        with self.cursor() as connection:
            if status:
                row = connection.execute("SELECT COUNT(*) AS c FROM posts WHERE status = ?", (status,)).fetchone()
            else:
                row = connection.execute("SELECT COUNT(*) AS c FROM posts").fetchone()
        return int(row["c"] if row else 0)

    def mark_publishing(self, post_id: str) -> None:
        with self.cursor() as connection:
            connection.execute(
                "UPDATE posts SET status = 'publishing' WHERE id = ? AND status = 'ready'",
                (post_id,),
            )

    def mark_published(self, post_id: str, card_path: str = "", card_file_id: str = "") -> None:
        with self.cursor() as connection:
            connection.execute(
                """
                UPDATE posts
                SET status = 'published', published_at = ?, card_path = ?,
                    card_file_id = COALESCE(NULLIF(?, ''), card_file_id)
                WHERE id = ?
                """,
                (utc_now(), card_path, card_file_id, post_id),
            )

    def requeue_failed(self, post_id: str, max_attempts: int = 3) -> bool:
        """РОС: вернуть failed-пост в очередь, если попыток меньше лимита."""
        with self.cursor() as connection:
            row = connection.execute("SELECT meta_json FROM posts WHERE id = ?", (post_id,)).fetchone()
            if not row:
                return False
            try:
                meta = json.loads(row["meta_json"] or "{}")
            except (TypeError, ValueError):
                meta = {}
            attempts = int(meta.get("requeue_attempts") or 0)
            if attempts >= max_attempts:
                return False
            meta["requeue_attempts"] = attempts + 1
            connection.execute(
                "UPDATE posts SET status = 'ready', published_at = NULL, meta_json = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), post_id),
            )
        return True

    def set_card_file_id(self, post_id: str, file_id: str) -> None:
        with self.cursor() as connection:
            connection.execute(
                "UPDATE posts SET card_file_id = ? WHERE id = ?",
                (file_id, post_id),
            )

    def mark_failed(self, post_id: str, error: str = "") -> None:
        with self.cursor() as connection:
            row = connection.execute("SELECT meta_json FROM posts WHERE id = ?", (post_id,)).fetchone()
            try:
                meta = json.loads(row["meta_json"] or "{}") if row else {}
            except (TypeError, ValueError):
                meta = {}
            meta["last_error"] = error[:500]
            connection.execute(
                "UPDATE posts SET status = 'failed', meta_json = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), post_id),
            )

    def delete_post(self, post_id: str) -> bool:
        """Удаляет пост и связанные записи (публикации, метрики, seen)."""
        with self.cursor() as connection:
            row = connection.execute("SELECT id FROM posts WHERE id = ?", (post_id,)).fetchone()
            if not row:
                return False
            connection.execute("DELETE FROM publications WHERE post_id = ?", (post_id,))
            connection.execute("DELETE FROM metrics WHERE post_id = ?", (post_id,))
            connection.execute("DELETE FROM seen WHERE post_id = ?", (post_id,))
            connection.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        return True

    def update_post_fields(self, post_id: str, fields: Dict[str, Any]) -> bool:
        """Обновляет перечисленные поля поста (title/hook/body/…)."""
        allowed = {
            "title",
            "hook",
            "body",
            "formula_latex",
            "formula_plain",
            "code",
            "source_name",
            "source_url",
            "tier",
            "quality",
            "status",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return False
        columns = ", ".join(f"{key} = ?" for key in updates)
        with self.cursor() as connection:
            connection.execute(
                f"UPDATE posts SET {columns} WHERE id = ?", [*updates.values(), post_id]
            )
        return True

    def set_post_meta(self, post_id: str, key: str, value: Any) -> None:
        """Точечно обновляет ключ в meta_json поста (например, style_variant)."""
        with self.cursor() as connection:
            row = connection.execute("SELECT meta_json FROM posts WHERE id = ?", (post_id,)).fetchone()
            try:
                meta = json.loads(row["meta_json"] or "{}") if row else {}
            except (TypeError, ValueError):
                meta = {}
            meta[str(key)] = value
            connection.execute(
                "UPDATE posts SET meta_json = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), post_id),
            )

    def last_published(self) -> Optional[Post]:
        with self.cursor() as connection:
            row = connection.execute(
                "SELECT * FROM posts WHERE status = 'published' ORDER BY published_at DESC LIMIT 1"
            ).fetchone()
        return Post.from_row(row) if row else None

    # ------------------------------------------------------------------
    # Публикации
    # ------------------------------------------------------------------
    def record_publication(self, post_id: str, result: PublishResult) -> None:
        with self.cursor() as connection:
            connection.execute(
                """
                INSERT INTO publications
                (post_id, platform, external_id, url, status, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(post_id, platform) DO UPDATE SET
                    external_id = excluded.external_id,
                    url = excluded.url,
                    status = excluded.status,
                    error = excluded.error,
                    created_at = excluded.created_at
                """,
                (
                    post_id,
                    result.platform,
                    result.external_id,
                    result.url,
                    "ok" if result.ok else ("skipped" if result.skipped else "error"),
                    result.error,
                    utc_now(),
                ),
            )

    def publication_exists(self, post_id: str, platform: str) -> bool:
        with self.cursor() as connection:
            row = connection.execute(
                "SELECT 1 FROM publications WHERE post_id = ? AND platform = ? AND status = 'ok'",
                (post_id, platform),
            ).fetchone()
        return row is not None

    def publications_for(self, post_id: str) -> List[Dict[str, Any]]:
        with self.cursor() as connection:
            rows = connection.execute(
                "SELECT * FROM publications WHERE post_id = ? ORDER BY platform",
                (post_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def forget_publication(self, post_id: str, platform: str) -> bool:
        """Забыть публикацию (например, сообщение удалено в канале вручную).

        Нужно, чтобы пост можно было снова поставить в очередь и опубликовать.
        """
        with self.cursor() as connection:
            cursor = connection.execute(
                "DELETE FROM publications WHERE post_id = ? AND platform = ?",
                (post_id, platform),
            )
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Метрики
    # ------------------------------------------------------------------
    def add_metrics(
        self,
        post_id: str,
        platform: str,
        views: int = 0,
        likes: int = 0,
        replies: int = 0,
    ) -> None:
        with self.cursor() as connection:
            connection.execute(
                "INSERT INTO metrics(post_id, platform, views, likes, replies, collected_at) VALUES (?, ?, ?, ?, ?, ?)",
                (post_id, platform, int(views), int(likes), int(replies), utc_now()),
            )

    def metrics_targets(
        self,
        limit: int = 50,
        platforms: Optional[Iterable[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Успешные публикации с внешним id — цели для сбора метрик."""
        sql = """
            SELECT pub.post_id AS post_id, pub.platform AS platform,
                   pub.external_id AS external_id, pub.url AS url,
                   posts.domain AS domain, posts.title AS title
            FROM publications pub
            JOIN posts ON posts.id = pub.post_id
            WHERE pub.status = 'ok' AND pub.external_id IS NOT NULL
        """
        params: List[Any] = []
        names = [str(name) for name in platforms] if platforms else []
        if names:
            sql += " AND pub.platform IN (%s)" % ",".join("?" for _ in names)
            params.extend(names)
        sql += " ORDER BY pub.created_at DESC, pub.id DESC LIMIT ?"
        params.append(int(limit))
        with self.cursor() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def metrics_for(self, post_id: str) -> List[Dict[str, Any]]:
        """Последний замер по каждой площадке для поста."""
        with self.cursor() as connection:
            rows = connection.execute(
                """
                SELECT m.* FROM metrics m
                WHERE m.post_id = ? AND m.id = (
                    SELECT MAX(id) FROM metrics
                    WHERE post_id = m.post_id AND platform = m.platform
                )
                ORDER BY m.platform
                """,
                (post_id,),
            ).fetchall()
        return [self._metrics_row(row) for row in rows]

    def metrics_summary(self) -> Dict[str, Any]:
        """Агрегат замеров по площадкам, дисциплинам и общий итог."""
        with self.cursor() as connection:
            by_platform = connection.execute(
                """
                SELECT platform,
                       SUM(views) AS views, SUM(likes) AS likes, SUM(replies) AS replies,
                       COUNT(DISTINCT post_id) AS posts, MAX(collected_at) AS last_collected
                FROM metrics GROUP BY platform ORDER BY platform
                """
            ).fetchall()
            by_domain = connection.execute(
                """
                SELECT posts.domain AS domain,
                       SUM(metrics.views) AS views, SUM(metrics.likes) AS likes,
                       SUM(metrics.replies) AS replies, COUNT(DISTINCT metrics.post_id) AS posts
                FROM metrics JOIN posts ON posts.id = metrics.post_id
                GROUP BY posts.domain ORDER BY posts.domain
                """
            ).fetchall()
            totals = connection.execute(
                "SELECT COUNT(*) AS samples, SUM(views) AS views, SUM(likes) AS likes, SUM(replies) AS replies FROM metrics"
            ).fetchone()
        return {
            "by_platform": [self._metrics_row(row) for row in by_platform],
            "by_domain": [self._metrics_row(row) for row in by_domain],
            "by_style": self.metrics_by_style(),
            "totals": {
                "samples": int(totals["samples"] or 0),
                "views": int(totals["views"] or 0),
                "likes": int(totals["likes"] or 0),
                "replies": int(totals["replies"] or 0),
            },
        }

    def metrics_by_style(self) -> List[Dict[str, Any]]:
        """A/B по стилю карточки: агрегат метрик, сгруппированный по style_variant."""
        variants: Dict[str, str] = {}
        for post in self.list_posts(limit=2000):
            variants[post.id] = str(post.meta.get("style_variant") or "default")
        buckets: Dict[str, Dict[str, Any]] = {}
        members: Dict[str, set[str]] = {}
        with self.cursor() as connection:
            rows = connection.execute("SELECT post_id, views, likes, replies FROM metrics").fetchall()
        for row in rows:
            variant = variants.get(row["post_id"], "default")
            bucket = buckets.setdefault(
                variant, {"variant": variant, "views": 0, "likes": 0, "replies": 0, "posts": 0}
            )
            bucket["views"] += int(row["views"] or 0)
            bucket["likes"] += int(row["likes"] or 0)
            bucket["replies"] += int(row["replies"] or 0)
            members.setdefault(variant, set()).add(row["post_id"])
        result: List[Dict[str, Any]] = []
        for variant, bucket in sorted(buckets.items()):
            bucket["posts"] = len(members.get(variant, ()))
            result.append(bucket)
        return result

    @staticmethod
    def _metrics_row(row: Any) -> Dict[str, Any]:
        data = dict(row)
        for key in ("views", "likes", "replies", "posts"):
            if key in data:
                data[key] = int(data[key] or 0)
        return data

    # ------------------------------------------------------------------
    # KV
    # ------------------------------------------------------------------
    def kv_get(self, key: str, default: str = "") -> str:
        with self.cursor() as connection:
            row = connection.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def kv_set(self, key: str, value: Any) -> None:
        with self.cursor() as connection:
            connection.execute(
                "INSERT INTO kv(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    def kv_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.kv_get(key, str(default)))
        except ValueError:
            return default

    def bump_counter(self, key: str) -> int:
        value = self.kv_int(key, 0) + 1
        self.kv_set(key, value)
        return value

    # ------------------------------------------------------------------
    # Источники / circuit breaker
    # ------------------------------------------------------------------
    def source_state(self, name: str) -> Dict[str, Any]:
        with self.cursor() as connection:
            row = connection.execute("SELECT * FROM sources WHERE name = ?", (name,)).fetchone()
            if not row:
                connection.execute("INSERT OR IGNORE INTO sources(name) VALUES (?)", (name,))
                row = connection.execute("SELECT * FROM sources WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else {}

    def source_is_open(self, name: str) -> bool:
        state = self.source_state(name)
        return float(state.get("open_until") or 0) > time.time()

    def record_source_ok(self, name: str) -> None:
        with self.cursor() as connection:
            connection.execute(
                "UPDATE sources SET last_ok = ?, last_error = NULL, failures = 0, open_until = 0 WHERE name = ?",
                (utc_now(), name),
            )

    def record_source_failure(self, name: str, error: str, failures_limit: int = 3, open_minutes: int = 45) -> None:
        with self.cursor() as connection:
            connection.execute("INSERT OR IGNORE INTO sources(name) VALUES (?)", (name,))
            row = connection.execute("SELECT failures FROM sources WHERE name = ?", (name,)).fetchone()
            failures = int(row["failures"] or 0) + 1 if row else 1
            open_until = time.time() + open_minutes * 60 if failures >= failures_limit else 0
            connection.execute(
                "UPDATE sources SET last_error = ?, failures = ?, open_until = ? WHERE name = ?",
                (error[:500], failures, open_until, name),
            )

    def source_states(self) -> List[Dict[str, Any]]:
        with self.cursor() as connection:
            rows = connection.execute("SELECT * FROM sources ORDER BY name").fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Снимок состояния (репликация в D1 / резервная копия)
    # ------------------------------------------------------------------
    TABLES = ("posts", "publications", "metrics", "sources", "kv", "seen")

    def snapshot(self) -> Dict[str, List[Dict[str, Any]]]:
        """Снимок всех таблиц состояния (для репликации в D1)."""
        data: Dict[str, List[Dict[str, Any]]] = {}
        with self.cursor() as connection:
            for table in self.TABLES:
                rows = connection.execute(f"SELECT * FROM {table}").fetchall()
                data[table] = [dict(row) for row in rows]
        return data

    def import_rows(self, data: Dict[str, List[Dict[str, Any]]]) -> int:
        """Восстанавливает состояние из снимка (INSERT OR REPLACE). Возвращает число строк."""
        imported = 0
        with self.cursor() as connection:
            for table in self.TABLES:
                for row in data.get(table) or []:
                    if not row:
                        continue
                    columns = list(row.keys())
                    placeholders = ",".join("?" for _ in columns)
                    connection.execute(
                        f"INSERT OR REPLACE INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
                        [row[column] for column in columns],
                    )
                    imported += 1
        return imported

    # ------------------------------------------------------------------
    # CRDT-слияние снимков (Join-Semilattice)
    # ------------------------------------------------------------------
    def merge_snapshot(self, snapshot: Dict[str, List[Dict[str, Any]]]) -> Dict[str, int]:
        """Монотонное слияние внешнего снимка с локальным состоянием.

        Идемпотентно, коммутативно и ассоциативно: параллельные писатели
        (GitHub Actions + Edge) не могут «затереть» более сильное состояние —
        `published` не откатывается в `ready`, непустые поля не теряются.
        Возвращает число записанных строк по таблицам.
        """
        result: Dict[str, int] = {}
        with self.cursor() as connection:
            result["posts"] = self._merge_posts(connection, snapshot.get("posts") or [])
            result["publications"] = self._merge_publications(connection, snapshot.get("publications") or [])
            result["sources"] = self._merge_sources(connection, snapshot.get("sources") or [])
            result["seen"] = self._merge_seen(connection, snapshot.get("seen") or [])
            result["metrics"] = self._merge_metrics(connection, snapshot.get("metrics") or [])
            result["kv"] = self._merge_kv(connection, snapshot.get("kv") or [])
        return result

    def _merge_posts(self, connection: sqlite3.Connection, rows: List[Dict[str, Any]]) -> int:
        written = 0
        local = {row["id"]: dict(row) for row in connection.execute("SELECT * FROM posts").fetchall()}
        for remote in rows:
            rid = remote.get("id")
            if not rid:
                continue
            current = local.get(rid)
            merged = _join_post(current, remote)
            if current is not None and merged == current:
                continue
            _upsert(connection, "posts", merged)
            written += 1
        return written

    def _merge_publications(self, connection: sqlite3.Connection, rows: List[Dict[str, Any]]) -> int:
        written = 0
        local = {
            (row["post_id"], row["platform"]): dict(row)
            for row in connection.execute("SELECT * FROM publications").fetchall()
        }
        for remote in rows:
            key = (remote.get("post_id"), remote.get("platform"))
            if not key[0] or not key[1]:
                continue
            current = local.get(key)
            merged = _join_publication(current, remote)
            if current is not None and merged == current:
                continue
            _upsert(connection, "publications", merged)
            written += 1
        return written

    def _merge_sources(self, connection: sqlite3.Connection, rows: List[Dict[str, Any]]) -> int:
        written = 0
        local = {row["name"]: dict(row) for row in connection.execute("SELECT * FROM sources").fetchall()}
        for remote in rows:
            name = remote.get("name")
            if not name:
                continue
            current = local.get(name)
            merged = _join_source(current, remote)
            if current is not None and merged == current:
                continue
            _upsert(connection, "sources", merged)
            written += 1
        return written

    def _merge_seen(self, connection: sqlite3.Connection, rows: List[Dict[str, Any]]) -> int:
        written = 0
        for remote in rows:
            if not remote.get("hash"):
                continue
            cursor = connection.execute(
                "INSERT OR IGNORE INTO seen (hash, post_id, simhash, title_norm, body_norm, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    remote.get("hash"),
                    remote.get("post_id"),
                    remote.get("simhash"),
                    remote.get("title_norm"),
                    remote.get("body_norm"),
                    remote.get("created_at") or utc_now(),
                ),
            )
            if cursor.rowcount and cursor.rowcount > 0:
                written += cursor.rowcount
        return written

    def _merge_metrics(self, connection: sqlite3.Connection, rows: List[Dict[str, Any]]) -> int:
        written = 0
        existing = {
            (row["post_id"], row["platform"], row["collected_at"])
            for row in connection.execute("SELECT post_id, platform, collected_at FROM metrics").fetchall()
        }
        for remote in rows:
            key = (remote.get("post_id"), remote.get("platform"), remote.get("collected_at"))
            if not key[0] or not key[2] or key in existing:
                continue
            connection.execute(
                "INSERT INTO metrics (post_id, platform, views, likes, replies, collected_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    remote.get("post_id"),
                    remote.get("platform"),
                    int(remote.get("views") or 0),
                    int(remote.get("likes") or 0),
                    int(remote.get("replies") or 0),
                    remote.get("collected_at"),
                ),
            )
            existing.add(key)
            written += 1
        return written

    def _merge_kv(self, connection: sqlite3.Connection, rows: List[Dict[str, Any]]) -> int:
        written = 0
        local = {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM kv").fetchall()}
        for remote in rows:
            key = remote.get("key")
            if key is None or key in KV_LOCAL_ONLY:
                continue  # управляющее состояние реплики (paused, tg_offset) не сливается
            value = remote.get("value")
            if key in local:
                current = str(local[key])
                candidate = str(value)
                is_counter = key in KV_COUNTERS or key.startswith(KV_COUNTER_PREFIXES)
                if is_counter and current.isdigit() and candidate.isdigit():
                    merged_value = str(max(int(current), int(candidate)))
                else:
                    merged_value = current  # локальное значение сохраняется
                if merged_value == current:
                    continue
            else:
                merged_value = value
            connection.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, merged_value))
            written += 1
        return written

    # ------------------------------------------------------------------
    # WAL checkpoint (обязательно перед git commit в Actions)
    # ------------------------------------------------------------------
    def checkpoint(self) -> None:
        """Сбрасывает WAL в основной файл, чтобы git не потерял записи."""
        with self.cursor() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE);")

    def vacuum(self) -> None:
        """Сжимает файл БД (``VACUUM``) — уменьшает размер после удалений."""
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            connection.execute("VACUUM;")
        finally:
            connection.close()

    # ------------------------------------------------------------------
    # Сброс (только для CLI с подтверждением)
    # ------------------------------------------------------------------
    def reset(self) -> None:
        with self.cursor() as connection:
            for table in ("publications", "metrics", "posts", "seen", "sources", "kv"):
                connection.execute(f"DELETE FROM {table}")
