"""Радар мировых научных новостей (Trending Radar).

Опрашивает открытые JSON-источники без ключей и считает «индекс горячести»:

* Hacker News Top Stories API — ``score`` (лайки) + ``descendants`` (комментарии);
* Reddit Hot JSON (r/math, r/physics, r/compsci) — ``ups`` + ``num_comments``.

Формула виральности (гравитационная):

    heat = (likes + 2 * comments) / (hours + 2) ** 1.4

HTTP-слой инъектируется, поэтому тесты идут без сети.
"""

from __future__ import annotations

import json
import logging
import math
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .config import Config
from .models import Post, make_id, utc_now
from .storage import Storage
from .text import translate_preserving_latex, truncate

LOGGER = logging.getLogger(__name__)

HN_TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
REDDIT_HOT = "https://www.reddit.com/r/{sub}/hot.json?limit={limit}"
USER_AGENT = "SciencePulse/1.0 (trending radar)"

TRENDING_KEY = "trending_candidates"

REDDIT_SUBS: Dict[str, str] = {"math": "math", "physics": "physics", "cs": "compsci"}

KEYWORDS: Dict[str, tuple] = {
    "math": (
        "theorem", "proof", "prime", "conjecture", "topology", "geometry", "algebra",
        "calculus", "integral", "derivative", "matrix", "eigenvalue", "fibonacci",
        "number theory", "combinatorics", "graph theory", "equation", "mathematic", "math",
    ),
    "physics": (
        "quantum", "particle", "relativity", "entropy", "thermodynamic", "photon",
        "electron", "gravity", "cosmolog", "black hole", "wave", "laser", "superconduct",
        "plasma", "neutrino", "higgs", "spacetime", "mechanics", "cern", "physics",
    ),
    "cs": (
        "algorithm", "complexity", "compiler", "neural", "machine learning", "database",
        "cryptograph", "protocol", "kernel", "sorting", "hash", "programming",
        "distributed", "turing", "quantum comput", "formal verification", "type theory",
    ),
}


def heat_score(likes: int, comments: int, hours: float) -> float:
    """Гравитационный индекс виральности: свежее и залайканное — выше."""
    return (float(likes) + 2.0 * float(comments)) / ((max(0.0, float(hours)) + 2.0) ** 1.4)


def keyword_hits(text: str) -> int:
    """Сколько научных ключевых слов встретилось (мера релевантности)."""
    lowered = (text or "").lower()
    return sum(1 for words in KEYWORDS.values() for word in words if word in lowered)


def classify_domain(text: str, strict: bool = False) -> Optional[str]:
    """Относит заголовок к дисциплине по ключевым словам.

    ``strict=True`` возвращает ``None``, если научных ключевых слов нет вовсе
    (так радар отсеивает ненаучные новости вроде «WTF Ubuntu?»).
    """
    lowered = (text or "").lower()
    best: Optional[str] = None
    best_hits = 0
    for domain, words in KEYWORDS.items():
        hits = sum(1 for word in words if word in lowered)
        if hits > best_hits:
            best, best_hits = domain, hits
    if best is None and not strict:
        return "cs"
    return best


@dataclass
class TrendItem:
    title: str
    url: str
    source: str
    domain: str = "cs"
    likes: int = 0
    comments: int = 0
    created: float = 0.0
    summary: str = ""
    heat: float = 0.0
    relevance: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrendItem":
        allowed = {key: data.get(key) for key in cls.__dataclass_fields__ if key in data}
        return cls(**allowed)


class TrendingRadar:
    """Сканер мировых хитов: Hacker News + Reddit."""

    def __init__(
        self,
        config: Config,
        storage: Optional[Storage] = None,
        http_get: Optional[Callable[[str], Any]] = None,
        now: Optional[Callable[[], float]] = None,
    ):
        self.config = config
        self.storage = storage
        self._http_get = http_get or self._default_get
        self._now = now or time.time

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    def _default_get(self, url: str) -> Any:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))

    def _get(self, url: str) -> Any:
        try:
            return self._http_get(url)
        except Exception as exc:  # сеть не должна ронять радар
            LOGGER.warning("Trending HTTP %s: %s", url, exc)
            return None

    # ------------------------------------------------------------------
    # Источники
    # ------------------------------------------------------------------
    def hackernews(self, limit: int = 30, domain: Optional[str] = None) -> List[TrendItem]:
        ids = self._get(HN_TOP)
        if not isinstance(ids, list):
            return []
        selected = ids[:limit]
        from concurrent.futures import ThreadPoolExecutor

        def fetch(story_id: Any) -> Any:
            return self._get(HN_ITEM.format(id=story_id))

        with ThreadPoolExecutor(max_workers=8) as pool:
            payloads = list(pool.map(fetch, selected))

        items: List[TrendItem] = []
        for story_id, data in zip(selected, payloads):
            if not isinstance(data, dict) or data.get("type") != "story":
                continue
            title = str(data.get("title") or "")
            item_domain = classify_domain(title)
            if domain and item_domain != domain:
                continue
            created = float(data.get("time") or 0)
            hours = max(0.0, (self._now() - created) / 3600.0)
            likes = int(data.get("score") or 0)
            comments = int(data.get("descendants") or 0)
            items.append(
                TrendItem(
                    title=title,
                    url=str(data.get("url") or f"https://news.ycombinator.com/item?id={story_id}"),
                    source="Hacker News",
                    domain=item_domain,
                    likes=likes,
                    comments=comments,
                    created=created,
                    heat=heat_score(likes, comments, hours),
                    relevance=keyword_hits(title),
                )
            )
        return items

    def reddit(self, subreddit: str, domain: str, limit: int = 10) -> List[TrendItem]:
        payload = self._get(REDDIT_HOT.format(sub=subreddit, limit=limit))
        children = ((payload or {}).get("data") or {}).get("children") or []
        items: List[TrendItem] = []
        for child in children:
            data = child.get("data") or {}
            title = str(data.get("title") or "")
            if not title:
                continue
            created = float(data.get("created_utc") or 0)
            hours = max(0.0, (self._now() - created) / 3600.0)
            likes = int(data.get("ups") or 0)
            comments = int(data.get("num_comments") or 0)
            items.append(
                TrendItem(
                    title=title,
                    url="https://www.reddit.com" + str(data.get("permalink") or ""),
                    source=f"r/{subreddit}",
                    domain=domain,
                    likes=likes,
                    comments=comments,
                    created=created,
                    summary=str(data.get("selftext") or "")[:280],
                    heat=heat_score(likes, comments, hours),
                )
            )
        return items

    def github(self, limit: int = 10, domain: Optional[str] = None, days: int = 7) -> List[TrendItem]:
        """Свежие репозитории GitHub, набирающие звёзды (звёзды ≈ лайки)."""
        since = datetime.fromtimestamp(self._now() - days * 86400, tz=timezone.utc).strftime("%Y-%m-%d")
        url = (
            "https://api.github.com/search/repositories"
            f"?q=created:>{since}+stars:>30&sort=stars&order=desc&per_page={max(1, limit)}"
        )
        payload = self._get(url)
        items: List[TrendItem] = []
        for repo in (payload or {}).get("items") or []:
            text = f"{repo.get('full_name', '')} {repo.get('description') or ''}"
            item_domain = classify_domain(text)
            if domain and item_domain != domain:
                continue
            try:
                created = datetime.strptime(
                    str(repo.get("created_at") or ""), "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc).timestamp()
            except (ValueError, TypeError):
                created = self._now()
            hours = max(0.0, (self._now() - created) / 3600.0)
            stars = int(repo.get("stargazers_count") or 0)
            forks = int(repo.get("forks_count") or 0)
            items.append(
                TrendItem(
                    title=str(repo.get("full_name") or ""),
                    url=str(repo.get("html_url") or ""),
                    source="GitHub",
                    domain=item_domain,
                    likes=stars,
                    comments=forks,
                    created=created,
                    summary=str(repo.get("description") or "")[:280],
                    heat=heat_score(stars, forks, hours),
                    relevance=keyword_hits(text),
                )
            )
        return items

    # ------------------------------------------------------------------
    # Сканирование и кэш
    # ------------------------------------------------------------------
    def scan(self, domain: Optional[str] = None, top: int = 5, translate: bool = True) -> List[TrendItem]:
        collected: List[TrendItem] = []
        collected.extend(self.hackernews(limit=40, domain=domain))
        collected.extend(self.github(limit=15, domain=domain))
        for item_domain, subreddit in REDDIT_SUBS.items():
            if domain and item_domain != domain:
                continue
            collected.extend(self.reddit(subreddit, item_domain, limit=10))

        seen: set = set()
        unique: List[TrendItem] = []
        ordered = sorted(
            collected,
            key=lambda entry: (1 if entry.relevance > 0 else 0, entry.heat),
            reverse=True,
        )
        for item in ordered:
            key = item.title.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(item)

        signal_cfg = dict((getattr(self.config, "raw", {}) or {}).get("signal_engine") or {})
        if signal_cfg.get("trending_filter"):
            try:
                from .signal_engine import NeymanPearsonDetector

                detector = NeymanPearsonDetector(float(signal_cfg.get("p_fa", 0.05)))
                filtered, report = detector.filter_items(
                    unique,
                    lambda item: 10.0 * item.relevance + math.log1p(max(0.0, item.heat)),
                )
                if filtered:
                    unique = filtered
                self._last_filter = report
            except Exception as exc:  # pragma: no cover - радар не должен падать
                LOGGER.warning("Нейман—Пирсон: %s", exc)

        picked = unique[:top]
        if translate:
            for item in picked:
                translated = translate_preserving_latex(item.title)
                if translated:
                    item.title = translated
                if item.summary:
                    item.summary = translate_preserving_latex(truncate(item.summary, 400)) or item.summary

        self.save(picked)
        return picked

    def save(self, items: List[TrendItem]) -> None:
        if self.storage is None:
            return
        try:
            self.storage.kv_set(TRENDING_KEY, json.dumps([item.as_dict() for item in items], ensure_ascii=False))
        except Exception as exc:
            LOGGER.warning("Не удалось сохранить trending_candidates: %s", exc)

    def load(self) -> List[TrendItem]:
        if self.storage is None:
            return []
        raw = self.storage.kv_get(TRENDING_KEY, "")
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except ValueError:
            return []
        return [TrendItem.from_dict(item) for item in data if isinstance(item, dict)]

    def to_post(self, item: TrendItem) -> Post:
        metrics = (
            f"Источник: {item.source}. Метрики: 👍 {item.likes} лайков, "
            f"💬 {item.comments} комментариев, индекс горячести 🔥 {item.heat:.0f}."
        )
        summary = (item.summary or "").strip()
        body = f"{summary}\n\n{metrics}" if summary else f"{item.title}.\n\n{metrics}"
        if item.url:
            body += f"\nСсылка: {item.url}"
        return Post(
            id=make_id("trend", f"{item.title}:{utc_now()}"),
            domain=item.domain,
            title=item.title,
            hook=truncate(body, 160),
            body=body,
            source_name=f"trending:{item.source}",
            source_url=item.url,
            tier="trending",
        )


def format_trending(items: List[TrendItem], lang: str = "ru") -> str:
    """Отчёт оператору: Топ-5 мировых хитов с метриками и индексом 🔥."""
    if not items:
        return "Радар ничего не нашёл (нет сети или источники молчат)."
    header = "🔥 <b>ТОП МИРОВЫХ НОВОСТЕЙ НАУКИ СЕЙЧАС:</b>" if lang == "ru" else "🔥 <b>TOP WORLD SCIENCE NEWS:</b>"
    labels = {
        "ru": {"likes": "лайков", "comm": "комм.", "queue": "В очередь", "now": "Опубликовать сейчас"},
        "en": {"likes": "likes", "comm": "comments", "queue": "Queue", "now": "Publish now"},
    }[lang if lang in ("ru", "en") else "ru"]
    lines = [header]
    for index, item in enumerate(items, start=1):
        lines.append("")
        lines.append(
            f"<b>#{index}. [🔥 {item.heat:.0f} | 👍 {item.likes} {labels['likes']} | "
            f"💬 {item.comments} {labels['comm']}] • {item.domain.upper()}</b>"
        )
        lines.append(item.title)
        if item.summary:
            lines.append(f"<i>{truncate(item.summary, 220)}</i>")
        lines.append(
            f"👉 {labels['queue']}: <code>/pick {index}</code> | "
            f"{labels['now']}: <code>/pick {index} now</code>"
        )
    return "\n".join(lines)

