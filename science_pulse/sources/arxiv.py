from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List

from ..models import Post, make_id
from ..text import clean_text, smart_sentence_truncate, truncate
from .base import Source, SourceError

ATOM = "{http://www.w3.org/2005/Atom}"
QUERY_URL = "https://export.arxiv.org/api/query"

CATEGORY_MAP = {
    "math": "cat:math.*",
    "physics": "cat:physics.*",
    "cs": "cat:cs.*",
}


class ArxivSource(Source):
    name = "arxiv"
    domains = ("math", "physics", "cs")
    tier = "online"

    def fetch(self, limit: int = 2, cycle: int = 0) -> List[Post]:
        domains = list(self.config.domains)
        if not domains:
            return []
        domain = domains[cycle % len(domains)]
        category = CATEGORY_MAP.get(domain, "cat:math.*")
        text = self.http.get_text(
            QUERY_URL,
            params={
                "search_query": category,
                "start": 0,
                "max_results": max(limit * 3, 5),
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            },
        )
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise SourceError(f"arXiv: invalid XML: {exc}") from exc

        posts: List[Post] = []
        for entry in root.findall(f"{ATOM}entry"):
            title = clean_text((entry.findtext(f"{ATOM}title") or "").replace("\n", " "), max_len=200)
            summary = clean_text((entry.findtext(f"{ATOM}summary") or "").replace("\n", " "), max_len=900)
            link = entry.findtext(f"{ATOM}id") or ""
            published = entry.findtext(f"{ATOM}published") or ""
            if len(title) < 8 or len(summary) < 100:
                continue
            authors = [
                clean_text(author.findtext(f"{ATOM}name") or "", max_len=80)
                for author in entry.findall(f"{ATOM}author")
            ]
            post = Post(
                id=make_id(self.name, link or title),
                domain=domain,
                title=self._translate(title),
                hook=self._translate(smart_sentence_truncate(summary, 80, 180)),
                body=self._translate(summary),
                source_name="arXiv",
                source_url=link,
                tier=self.tier,
                meta={"published": published, "authors": authors[:4]},
            )
            post.quality = post.quality_score()
            posts.append(post)
            if len(posts) >= limit:
                break
        return posts
