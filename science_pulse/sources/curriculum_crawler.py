"""Бесконечный экспедитор дерева наук — Эшелон 2 и 3 (без потолка в 30 статей).

Два механизма:

1. **`CurriculumCrawlerSource`** — источник очереди: берёт следующие темы из
   матрицы университетского курса (`syllabus_tree.py`, `§ 11.1 … § 55.3`),
   присваивает сквозные §-номера, связывает через `prereq_ids` с предыдущим
   параграфом и ставит в очередь по возрастанию `complexity_tier`.
2. **`RecursiveMetaCrawler`** — обход «источников источников» вглубь и вширь:
   подкатегории Википедии (`cmtype=subcat`) → статьи → внутренние ссылки
   (`prop=links`) → перекрёстные ссылки OEIS. Сеть подключается только через
   инъектируемый `http_get`, поэтому модуль полностью герметичен в тестах.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence
from urllib.parse import quote

from ..models import Post, make_id
from ..syllabus_tree import next_syllabus_topics, syllabus_summary
from .base import Source

LOGGER = logging.getLogger(__name__)

WIKI_API = "https://ru.wikipedia.org/w/api.php"
OEIS_API = "https://oeis.org/search"

# Ступенчатый список научных категорий: от базы к фронтиру (Эшелон 2–3).
CATEGORY_TIERS: Dict[str, List[str]] = {
    "A": [
        "Элементарная математика",
        "Геометрия",
        "Механика",
        "Физические законы и уравнения",
        "Алгоритмы",
        "Логические операции",
    ],
    "B": [
        "Математический анализ",
        "Линейная алгебра",
        "Теория чисел",
        "Термодинамика",
        "Электродинамика",
        "Оптика",
        "Структуры данных",
        "Алгоритмы сортировки",
        "Алгоритмы на графах",
    ],
    "C": [
        "Дифференциальные уравнения",
        "Теория вероятностей",
        "Квантовая механика",
        "Теория относительности",
        "Астрофизика",
        "Криптография",
        "Теория вычислимости",
    ],
}

CATEGORY_DOMAIN: Dict[str, str] = {
    "A": "math",
    "B": "math",
    "C": "physics",
}


def _get_json(http_get: Optional[Callable[..., Any]], url: str, timeout: float) -> Any:
    """Сетевой вызов через инъектируемый `http_get`; при отсутствии — None."""
    if http_get is None:
        return None
    try:
        try:
            payload = http_get(url, timeout=timeout)
        except TypeError:
            payload = http_get(url)
    except Exception as exc:  # pragma: no cover - сеть в тестах не используется
        LOGGER.info("Краулер: запрос не выполнен (%s)", exc)
        return None
    if payload is None:
        return None
    if hasattr(payload, "json"):
        try:
            return payload.json()
        except Exception:
            return None
    return payload if isinstance(payload, (dict, list)) else None


class RecursiveMetaCrawler:
    """«Источники источников»: подкатегории → статьи → ссылки → OEIS xref."""

    def __init__(self, http_get: Optional[Callable[..., Any]] = None, timeout: float = 3.0):
        self.http_get = http_get
        self.timeout = float(timeout)

    def category_members(self, category: str, kind: str = "page", limit: int = 50) -> List[str]:
        """Элементы категории: статьи (`page`) или подкатегории (`subcat`)."""
        url = (
            f"{WIKI_API}?action=query&list=categorymembers&cmtype={kind}"
            f"&cmlimit={int(limit)}&format=json&cmtitle={quote('Категория:' + category)}"
        )
        payload = _get_json(self.http_get, url, self.timeout)
        if not isinstance(payload, dict):
            return []
        members = ((payload.get("query") or {}).get("categorymembers") or [])
        prefix = "Категория:"
        out: List[str] = []
        for member in members:
            title = str((member or {}).get("title") or "")
            if title.startswith(prefix):
                title = title[len(prefix):]
            if title:
                out.append(title)
        return out

    def subcategories(self, category: str, depth: int = 1, limit: int = 20) -> List[str]:
        """Рекурсивно собирает подкатегории (категория → подкатегории → …)."""
        found: List[str] = []
        frontier = [category]
        for _level in range(max(1, int(depth))):
            next_frontier: List[str] = []
            for item in frontier:
                for sub in self.category_members(item, kind="subcat", limit=limit):
                    if sub not in found and sub != category:
                        found.append(sub)
                        next_frontier.append(sub)
            if not next_frontier:
                break
            frontier = next_frontier
        return found

    def article_links(self, title: str, limit: int = 50) -> List[str]:
        """Внутренние ссылки статьи (разделы «См. также» и тело статьи)."""
        url = (
            f"{WIKI_API}?action=query&prop=links&plnamespace=0&pllimit={int(limit)}"
            f"&format=json&titles={quote(title)}"
        )
        payload = _get_json(self.http_get, url, self.timeout)
        if not isinstance(payload, dict):
            return []
        pages = ((payload.get("query") or {}).get("pages") or {})
        out: List[str] = []
        for page in pages.values():
            for link in (page or {}).get("links") or []:
                name = str((link or {}).get("title") or "").strip()
                if name and name not in out:
                    out.append(name)
        return out

    def oeis_xref(self, series: str, limit: int = 20) -> List[str]:
        """Перекрёстные ссылки последовательности OEIS (`xref` → соседние A-номера)."""
        payload = _get_json(
            self.http_get, f"{OEIS_API}?q=id:{quote(series)}&fmt=json", self.timeout
        )
        text = str(payload or "")
        found = re.findall(r"A\d{6}", text)
        return [item for item in dict.fromkeys(found) if item != series][: int(limit)]

    def discover(self, categories: Optional[Sequence[str]] = None, depth: int = 1) -> List[Dict[str, Any]]:
        """Кандидаты новых тем: подкатегории и статьи выбранных категорий."""
        pool: List[str] = []
        for level, items in CATEGORY_TIERS.items():
            if categories is not None and level not in categories:
                continue
            for category in items:
                pool.extend(self.subcategories(category, depth=depth, limit=20))
                pool.extend(self.category_members(category, kind="page", limit=30))
        ordered = list(dict.fromkeys(pool))
        return [
            {"title": name, "domain": "math", "origin": "wiki-category", "depth": depth}
            for name in ordered
        ]


def topic_body(topic: Dict[str, Any]) -> str:
    """Детерминированный учебный текст параграфа (без LLM)."""
    return (
        f"Ветвь университетского курса «{topic['branch_title']}». {topic['hook']} "
        f"Параграф «{topic['title']}» вводит рабочий аппарат темы и связывает его с уже "
        f"пройденным фундаментом: сначала формулировка, затем разбор величин и численная "
        f"проверка. Дальше на этот параграф опираются следующие темы ветви — курс идёт "
        f"от простого к сложному, без пропусков и повторов."
    )


class CurriculumCrawlerSource(Source):
    """Источник бесконечной очереди: матрица курса + рекурсивный обход категорий."""

    name = "curriculum"
    domains = ("math", "physics", "cs")
    tier = "curriculum"

    def __init__(self, config: Any = None, http: Any = None):
        super().__init__(config, http)
        self.crawler = RecursiveMetaCrawler(
            http_get=getattr(http, "get_json", None) or getattr(http, "get", None)
        )

    def fetch(self, limit: int = 2, cycle: int = 0) -> List[Post]:
        """Следующие темы силлабуса → посты очереди (детерминированно)."""
        topics = next_syllabus_topics(max(1, int(limit)), cycle=cycle)
        posts: List[Post] = []
        for topic in topics:
            post = Post(
                id=make_id("curriculum", topic["id"]),
                domain=topic["domain"],
                title=f"§ {topic['section_num']} {topic['title']}",
                hook=topic["hook"],
                body=topic_body(topic),
                formula_latex=topic["formula_latex"],
                formula_plain=topic["formula_latex"],
                source_name=str(topic["source_name"]),
                source_url=str(topic["source_url"]),
                tier=self.tier,
                quality=0.7,
            )
            post.meta.update({
                "section_num": topic["section_num"],
                "step": topic["step"],
                "step_title": topic["branch_title"],
                "complexity_tier": topic["complexity_tier"],
                "prereq_ids": list(topic["prereq_ids"]),
                "syllabus_id": topic["id"],
                "syllabus_branch": topic["branch_id"],
                "scientist": topic["scientist"],
                "era": topic["era"],
                "unlocks_concepts": [],
            })
            posts.append(post)
        return posts

    def discover(self, depth: int = 1, categories: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """Кандидаты из «источников источников» (подкатегории Википедии)."""
        return self.crawler.discover(categories=categories, depth=depth)

    def available(self) -> bool:
        return True

    def summary(self) -> Dict[str, Any]:
        return syllabus_summary()


