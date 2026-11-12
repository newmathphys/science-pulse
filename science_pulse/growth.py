"""Рост аудитории SCM: уникальные форматы Threads, UTM и реестр каналов.

SCM не конкурирует «новостной лентой»: он продаёт уникальность
**детерминированной науки** — источник, формула, карточка, проверяемое
следствие. Этот модуль собирает из поста Threads-формат и ведёт реестр
каналов/партнёров для сбора аудитории.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import Post
from .text import clean_latex_for_telegram, formula_to_unicode, lead_sentence, smart_sentence_truncate, truncate

LOGGER = logging.getLogger(__name__)

FORMAT_LABELS = {
    "math": "ТЕОРЕМА ДНЯ",
    "physics": "ЯВЛЕНИЕ ДНЯ",
    "cs": "АЛГОРИТМ ДНЯ",
}

# Threads показывает кликабельным только один Topic Tag; гирлянда тегов
# выглядит как спам для алгоритма Meta. Один точный тег на домен.
HASHTAGS = {
    "math": ["#математика"],
    "physics": ["#физика"],
    "cs": ["#информатика"],
}

CTA = {
    "math": "Разбор, формула и задача — в Telegram.",
    "physics": "Полный разбор явления — в Telegram.",
    "cs": "Код, сложность и разбор — в Telegram.",
}


def utm_url(url: str, source: str = "threads", medium: str = "social",
            campaign: str = "scm", content: str = "") -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({"utm_source": source, "utm_medium": medium, "utm_campaign": campaign})
    if content:
        query["utm_content"] = content
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def telegram_url(config: Any) -> str:
    channel = str(getattr(config, "telegram_channel", "") or "").strip()
    if not channel:
        return ""
    if channel.startswith("@"):
        return f"https://t.me/{channel.lstrip('@')}"
    if channel.startswith("https://t.me/"):
        return channel
    return ""


class ThreadsGrowthEngine:
    """Собирает уникальный Threads-пост из данных SCM-поста."""

    def __init__(self, config: Any = None):
        raw = dict((getattr(config, "raw", {}) or {}).get("growth") or {})
        threads = dict(raw.get("threads") or {})
        self.enabled = bool(threads.get("enabled", False))
        self.max_chars = int(threads.get("max_chars", 480))
        self.with_utm = bool(threads.get("utm", True))

    @staticmethod
    def label(post: Post) -> str:
        return FORMAT_LABELS.get(post.domain, "НАУКА ДНЯ")

    @staticmethod
    def hashtags(post: Post, limit: int = 1) -> str:
        return " ".join(HASHTAGS.get(post.domain, ["#наука"])[:max(1, limit)])

    @staticmethod
    def hook_variants(post: Post) -> List[str]:
        title = clean_latex_for_telegram(post.title)
        hook = clean_latex_for_telegram(post.hook or "")
        body = clean_latex_for_telegram(post.body or "")
        variants = []
        if hook:
            variants.append(hook)
        if title:
            variants.append(f"Почему это важно: {title}")
        lead = lead_sentence(body, 160)
        if lead:
            variants.append(lead)
        variants.append("Одна формула — один проверяемый факт.")
        return list(dict.fromkeys(variants))

    def first_post(self, post: Post, limit: Optional[int] = None) -> str:
        limit = int(limit or self.max_chars)
        title = clean_latex_for_telegram(post.title)
        hook = self.hook_variants(post)[0]
        body = re.sub(r"https?://\S+", "", post.body or "")
        body = smart_sentence_truncate(body, 120, 220)
        formula = formula_to_unicode(post.formula_latex or post.formula_plain, 90)
        parts = [f"{self.label(post)} · {title}", hook]
        if body:
            parts.append(body)
        if formula:
            parts.append(f"Формула: {formula}")
        parts.append(self.hashtags(post))
        return truncate("\n\n".join(part for part in parts if part), limit)

    @staticmethod
    def _post_url(site_url: str, post: Post) -> str:
        """База сайта → каноническая страница параграфа, без двойного /post/."""
        base = str(site_url or "").rstrip("/")
        if not base:
            return ""
        suffix = f"/post/{post.id}.html"
        if base.endswith(suffix) or base.endswith(f"/post/{post.id}"):
            return base
        return base + suffix

    @staticmethod
    def _source_citation(post: Post) -> str:
        """Сухая академическая ссылка без внешнего URL (Threads не любит гирлянды)."""
        meta = post.meta or {}
        scientist = str(meta.get("scientist") or post.source_name or "").strip()
        era = str(meta.get("era") or "").strip()
        year = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", era)
        parts = [part for part in (scientist, year.group(1) if year else "") if part]
        return "Первоисточник: " + ", ".join(parts) if parts else ""

    def reply(self, post: Post, site_url: str = "", tg_url: str = "",
              limit: Optional[int] = None) -> str:
        limit = int(limit or self.max_chars)
        site = utm_url(self._post_url(site_url, post), content=post.id) if self.with_utm else self._post_url(site_url, post)
        tg = utm_url(tg_url, medium="social", campaign="scm_telegram", content=post.id) if self.with_utm else tg_url
        parts = []
        if site:
            parts.append(f"Полный разбор: {site}")
        if tg:
            parts.append(f"{CTA.get(post.domain, 'Продолжение — в Telegram.')} {tg}")
        citation = self._source_citation(post)
        if citation:
            parts.append(citation)
        return truncate("\n\n".join(part for part in parts if part), limit)

    def chain(self, post: Post, site_url: str = "", tg_url: str = "",
              limit: Optional[int] = None) -> List[str]:
        """Первый пост без внешней ссылки, второй — ссылки/CTA (алгоритмы Threads)."""
        limit = int(limit or self.max_chars)
        first = self.first_post(post, limit)
        second = self.reply(post, site_url, tg_url, limit)
        return [first, second] if second else [first]

    def plan(self, post: Post, site_url: str = "", tg_url: str = "") -> Dict[str, Any]:
        return {
            "format": self.label(post),
            "hooks": self.hook_variants(post),
            "hashtags": self.hashtags(post),
            "chain": self.chain(post, site_url, tg_url),
            "utm": self.with_utm,
        }


@dataclass
class AudienceTarget:
    id: int
    platform: str
    name: str
    url: str
    topic: str
    audience_size: int
    status: str
    notes: str
    created_at: str


class AudienceRegistry:
    """Реестр каналов/партнёров для сбора аудитории (SQLite)."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL,
        name TEXT NOT NULL,
        url TEXT NOT NULL UNIQUE,
        topic TEXT NOT NULL DEFAULT 'science',
        audience_size INTEGER DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'new',
        notes TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        value REAL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY(target_id) REFERENCES targets(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS audience_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL,
        followers INTEGER DEFAULT 0,
        views INTEGER DEFAULT 0,
        likes INTEGER DEFAULT 0,
        replies INTEGER DEFAULT 0,
        collected_at TEXT NOT NULL,
        meta_json TEXT DEFAULT '{}'
    );
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(self.SCHEMA)

    def _now(self) -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    def add(self, platform: str, name: str, url: str, topic: str = "science",
            audience_size: int = 0, notes: str = "") -> int:
        with sqlite3.connect(self.path) as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO targets(platform,name,url,topic,audience_size,notes,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (platform, name, url, topic, int(audience_size), notes, self._now()),
            )
            if cursor.lastrowid:
                return int(cursor.lastrowid)
            row = connection.execute("SELECT id FROM targets WHERE url = ?", (url,)).fetchone()
            return int(row[0]) if row else 0

    def list(self, status: Optional[str] = None, platform: Optional[str] = None,
             limit: int = 100) -> List[AudienceTarget]:
        clauses = []
        params: List[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                f"SELECT * FROM targets {where} ORDER BY audience_size DESC, id DESC LIMIT ?",
                (*params, int(limit)),
            ).fetchall()
        return [AudienceTarget(**dict(row)) for row in rows]

    def set_status(self, target_id: int, status: str, notes: str = "") -> bool:
        with sqlite3.connect(self.path) as connection:
            cursor = connection.execute(
                "UPDATE targets SET status = ?, notes = ? WHERE id = ?",
                (status, notes, int(target_id)),
            )
            return cursor.rowcount > 0

    def event(self, target_id: int, kind: str, value: float = 0) -> int:
        with sqlite3.connect(self.path) as connection:
            cursor = connection.execute(
                "INSERT INTO events(target_id,kind,value,created_at) VALUES (?,?,?,?)",
                (int(target_id), kind, float(value), self._now()),
            )
            return int(cursor.lastrowid)

    def add_snapshot(self, platform: str, followers: int = 0, views: int = 0,
                     likes: int = 0, replies: int = 0, meta: Optional[Dict[str, Any]] = None) -> int:
        with sqlite3.connect(self.path) as connection:
            cursor = connection.execute(
                "INSERT INTO audience_snapshots(platform,followers,views,likes,replies,collected_at,meta_json) "
                "VALUES (?,?,?,?,?,?,?)",
                (platform, int(followers), int(views), int(likes), int(replies),
                 self._now(), json.dumps(meta or {}, ensure_ascii=False)),
            )
            return int(cursor.lastrowid)

    def latest_snapshots(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT s.* FROM audience_snapshots s
                WHERE s.id = (SELECT MAX(id) FROM audience_snapshots WHERE platform = s.platform)
                ORDER BY s.platform
                """
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["meta"] = json.loads(item.pop("meta_json") or "{}")
            except ValueError:
                item["meta"] = {}
            result.append(item)
        return result

    def report(self) -> Dict[str, Any]:
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            by_platform = connection.execute(
                "SELECT platform, COUNT(*) AS targets, SUM(audience_size) AS audience "
                "FROM targets GROUP BY platform ORDER BY audience DESC"
            ).fetchall()
            by_status = connection.execute(
                "SELECT status, COUNT(*) AS count FROM targets GROUP BY status"
            ).fetchall()
            events = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        return {
            "by_platform": [dict(row) for row in by_platform],
            "by_status": [dict(row) for row in by_status],
            "events": int(events),
            "audience": self.latest_snapshots(),
        }


def format_plan(plan: Dict[str, Any]) -> str:
    lines = [f"Формат: {plan['format']}", "", "Крючки:"]
    lines += [f"  - {hook}" for hook in plan["hooks"]]
    lines += ["", "Threads-цепочка:"]
    for index, text in enumerate(plan["chain"], start=1):
        lines.append(f"--- пост {index} ---")
        lines.append(text)
    return "\n".join(lines)


def format_targets(targets: List[AudienceTarget]) -> str:
    if not targets:
        return "Реестр пуст."
    lines = ["Каналы для сбора аудитории:"]
    for item in targets:
        lines.append(
            f"  #{item.id} [{item.platform}/{item.status}] {item.name} · "
            f"{item.topic} · {item.audience_size} · {item.url}"
        )
    return "\n".join(lines)


def format_report(report: Dict[str, Any]) -> str:
    lines = ["Аудиторный реестр SCM"]
    for row in report.get("audience") or []:
        lines.append(f"  {row['platform']}: подписчиков {row.get('followers', 0)} ({row.get('collected_at', '')})")
    for row in report["by_platform"]:
        lines.append(f"  {row['platform']}: каналов {row['targets']} · аудитория {row['audience'] or 0}")
    for row in report["by_status"]:
        lines.append(f"  {row['status']}: {row['count']}")
    lines.append(f"  событий: {report['events']}")
    return "\n".join(lines)
