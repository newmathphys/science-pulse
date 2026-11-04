from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional

from ..models import Post, make_id
from ..text import clean_text, smart_sentence_truncate, truncate
from .base import Source, SourceError

CATEGORY_MAP = {
    "math": "Математика",
    "physics": "Физика",
    "cs": "Информатика",
}

API_URL = "https://ru.wikipedia.org/w/api.php"
SUMMARY_URL = "https://ru.wikipedia.org/api/rest_v1/page/summary/{title}"


class WikipediaSource(Source):
    name = "wikipedia"
    domains = ("math", "physics", "cs")
    tier = "online"

    def fetch(self, limit: int = 2, cycle: int = 0) -> List[Post]:
        domains = list(self.config.domains)
        if not domains:
            return []
        posts: List[Post] = []
        for offset in range(max(limit, 1)):
            domain = domains[(cycle + offset) % len(domains)]
            try:
                post = self.fetch_random(domain)
            except SourceError:
                if not posts and offset == max(limit, 1) - 1:
                    raise
                continue
            if post:
                posts.append(post)
            if len(posts) >= limit:
                break
        return posts

    def fetch_random(self, domain: str) -> Optional[Post]:
        category = CATEGORY_MAP.get(domain, "Наука")
        members = self.http.get_json(
            API_URL,
            params={
                "action": "query",
                "list": "categorymembers",
                "cmtitle": f"Категория:{category}",
                "cmtype": "page",
                "cmlimit": "50",
                "format": "json",
            },
        )
        pages = (members.get("query") or {}).get("categorymembers") or []
        titles = [
            page.get("title", "")
            for page in pages
            if page.get("title")
            and "(значения)" not in page.get("title", "")
            and not page.get("title", "").startswith("Служебная:")
        ]
        if not titles:
            return None

        random.shuffle(titles)
        for title in titles[:8]:
            try:
                summary = self.http.get_json(SUMMARY_URL.format(title=title.replace(" ", "_")))
            except SourceError:
                continue
            if summary.get("type") == "disambiguation":
                continue
            extract = clean_text(summary.get("extract") or "", max_len=900)
            if len(extract) < 140:
                continue
            description = clean_text(summary.get("description") or "", max_len=160)
            page_title = clean_text(summary.get("title") or title, max_len=180)
            content_urls = summary.get("content_urls") or {}
            page_url = ((content_urls.get("desktop") or {}).get("page")) or ""
            if not page_url:
                page_url = f"https://ru.wikipedia.org/wiki/{title.replace(' ', '_')}"

            formulas = self._extract_math(extract)
            post = Post(
                id=make_id(self.name, page_title),
                domain=domain,
                title=self._translate(page_title),
                hook=self._translate(description or smart_sentence_truncate(extract, 80, 180)),
                body=self._translate(extract),
                formula_latex=formulas[0] if formulas else "",
                formula_plain=formulas[0] if formulas else "",
                source_name="Wikipedia (ru)",
                source_url=page_url,
                tier=self.tier,
                meta={"page_id": summary.get("pageid"), "category": category},
            )
            post.quality = post.quality_score()
            return post
        return None

    @staticmethod
    def _extract_math(text: str) -> List[str]:
        found = re.findall(r"\$\$(.+?)\$\$|\$(.+?)\$", text or "", re.DOTALL)
        formulas = [next((g for g in pair if g), "").strip() for pair in found]
        return [f for f in formulas if 5 <= len(f) <= 160]
