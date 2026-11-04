from __future__ import annotations

import re
from typing import List
from urllib.parse import quote

from ..models import Post, make_id
from ..text import clean_text, truncate
from .base import Source, SourceError

API_URL = "https://rosettacode.org/w/api.php"

TASKS = {
    "math": [
        "Fibonacci_sequence",
        "Greatest_common_divisor",
        "Prime_decomposition",
        "Sieve_of_Eratosthenes",
    ],
    "physics": [
        "N-body_problem",
        "Fast_Fourier_transform",
    ],
    "cs": [
        "Binary_search",
        "Quicksort",
        "Dijkstra's_algorithm",
        "Conway's_Game_of_Life",
    ],
}


class RosettaSource(Source):
    name = "rosetta"
    domains = ("math", "physics", "cs")
    tier = "online"

    def fetch(self, limit: int = 2, cycle: int = 0) -> List[Post]:
        domains = list(self.config.domains)
        if not domains:
            return []
        domain = domains[cycle % len(domains)]
        tasks = TASKS.get(domain) or TASKS["cs"]
        posts: List[Post] = []
        for offset in range(min(max(limit, 1), len(tasks))):
            task = tasks[(cycle + offset) % len(tasks)]
            try:
                post = self.fetch_task(task, domain)
            except SourceError:
                if not posts and offset == min(max(limit, 1), len(tasks)) - 1:
                    raise
                continue
            if post:
                posts.append(post)
            if len(posts) >= limit:
                break
        return posts

    def fetch_task(self, task: str, domain: str) -> Post | None:
        data = self.http.get_json(
            API_URL,
            params={"action": "parse", "page": task, "prop": "wikitext", "format": "json"},
        )
        wikitext = (((data.get("parse") or {}).get("wikitext") or {}).get("*")) or ""
        if not wikitext:
            return None

        intro_raw = re.split(r"==\s*\{\{header\|", wikitext, maxsplit=1)[0]
        intro = self._clean_wikitext(intro_raw)
        code = self._extract_python(wikitext)
        title_text = task.replace("_", " ").replace("%27", "'")
        title = self._translate(f"Эталонный алгоритм: {title_text}")
        body = self._translate(intro)
        if len(body) < 80 and not code:
            return None

        formula = ""
        for line in code.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and any(ch in line for ch in ("=", "return", "def ")):
                formula = truncate(line, 120)
                break

        post = Post(
            id=make_id(self.name, task),
            domain=domain,
            title=title,
            hook=self._translate(f"Как выглядит каноническая реализация «{title_text}»?"),
            body=body or f"Каноническая реализация задачи «{title_text}» на Python.",
            formula_latex=formula,
            formula_plain=formula,
            code=truncate(code, 700),
            source_name="Rosetta Code",
            source_url=f"https://rosettacode.org/wiki/{quote(task)}",
            tier=self.tier,
            meta={"task": task},
        )
        post.quality = post.quality_score()
        return post

    @staticmethod
    def _clean_wikitext(value: str) -> str:
        text = value or ""
        text = re.sub(r"\{\{.*?\}\}", " ", text, flags=re.DOTALL)
        text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = text.replace("'''", "").replace("''", "")
        text = re.sub(r"^=+\s*(.*?)\s*=+\s*$", r"\1", text, flags=re.MULTILINE)
        return clean_text(text, max_len=1000)

    @staticmethod
    def _extract_python(wikitext: str) -> str:
        match = re.search(
            r"==\s*\{\{header\|Python\}\}\s*==(.*?)(?===+\s*\{\{header\||$)",
            wikitext,
            re.DOTALL | re.IGNORECASE,
        )
        block = match.group(1) if match else ""
        for pattern in (
            r"<syntaxhighlight[^>]*lang=[\"']?python[^>]*>(.*?)</syntaxhighlight>",
            r"<syntaxhighlight[^>]*>(.*?)</syntaxhighlight>",
            r"<pre[^>]*>(.*?)</pre>",
        ):
            code_match = re.search(pattern, block, re.DOTALL | re.IGNORECASE)
            if code_match:
                return code_match.group(1).strip()
        return ""
